"""MinIO object storage wrapper — S3-compatible file operations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import structlog
from minio import Minio
from minio.error import S3Error

logger = structlog.get_logger()

# Content type mapping for supported formats
CONTENT_TYPES = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
}


@dataclass
class FileInfo:
    key: str
    size: int
    last_modified: datetime
    etag: str
    content_type: str


class MinIOStorage:
    """S3-compatible object storage for document files."""

    def __init__(
        self,
        endpoint: str,
        access_key: str,
        secret_key: str,
        bucket: str,
        secure: bool = False,
    ) -> None:
        self._client = Minio(
            endpoint,
            access_key=access_key,
            secret_key=secret_key,
            secure=secure,
        )
        self._bucket = bucket

    async def ensure_bucket(self) -> None:
        """Create bucket if it doesn't exist. Idempotent."""
        if not self._client.bucket_exists(self._bucket):
            self._client.make_bucket(self._bucket)
            logger.info("Created bucket", bucket=self._bucket)

    async def upload(
        self,
        file_bytes: bytes,
        key: str,
        content_type: str = "application/octet-stream",
    ) -> str:
        """Upload file to MinIO. Returns the key."""
        from io import BytesIO

        data_stream = BytesIO(file_bytes)
        self._client.put_object(
            self._bucket,
            key,
            data_stream,
            length=len(file_bytes),
            content_type=content_type,
        )
        logger.debug("Uploaded file", bucket=self._bucket, key=key, size=len(file_bytes))
        return key

    async def download(self, key: str) -> bytes:
        """Download file from MinIO. Raises S3Error if not found."""
        response = self._client.get_object(self._bucket, key)
        try:
            data = response.read()
        finally:
            response.close()
            response.release_conn()
        return data

    async def delete(self, key: str) -> None:
        """Delete file from MinIO."""
        self._client.remove_object(self._bucket, key)
        logger.debug("Deleted file", bucket=self._bucket, key=key)

    async def list_files(self, prefix: str = "") -> list[FileInfo]:
        """List all files with given prefix. Sorted by key."""
        objects = self._client.list_objects(self._bucket, prefix=prefix, recursive=True)
        result = []
        for obj in objects:
            result.append(
                FileInfo(
                    key=obj.object_name,
                    size=obj.size,
                    last_modified=obj.last_modified.replace(tzinfo=UTC)
                    if obj.last_modified
                    else datetime.now(UTC),
                    etag=obj.etag or "",
                    content_type=obj.content_type or "application/octet-stream",
                )
            )
        return sorted(result, key=lambda f: f.key)

    async def get_presigned_url(self, key: str, expires: int = 3600) -> str:
        """Generate temporary download URL (no auth needed)."""
        from datetime import timedelta

        url = self._client.presigned_get_object(
            self._bucket, key, expires=timedelta(seconds=expires)
        )
        return url

    async def file_exists(self, key: str) -> bool:
        """Check if file exists. Uses stat_object (efficient)."""
        try:
            self._client.stat_object(self._bucket, key)
            return True
        except S3Error:
            return False

    async def get_file_info(self, key: str) -> FileInfo | None:
        """Get file metadata. Returns None if not found."""
        try:
            stat = self._client.stat_object(self._bucket, key)
            return FileInfo(
                key=stat.object_name,
                size=stat.size,
                last_modified=stat.last_modified.replace(tzinfo=UTC)
                if stat.last_modified
                else datetime.now(UTC),
                etag=stat.etag or "",
                content_type=stat.content_type or "application/octet-stream",
            )
        except S3Error:
            return None

    async def copy_file(self, source_key: str, dest_key: str) -> None:
        """Copy file within the same bucket."""
        from minio.commonconfig import CopySource

        self._client.copy_object(
            self._bucket,
            dest_key,
            CopySource(self._bucket, source_key),
        )
        logger.debug("Copied file", source=source_key, dest=dest_key)

    async def get_file_bytes(self, key: str) -> tuple[bytes, str]:
        """Download file and return (bytes, content_type)."""
        info = await self.get_file_info(key)
        content_type = info.content_type if info else "application/octet-stream"
        data = await self.download(key)
        return data, content_type

    async def health_check(self) -> bool:
        """Check MinIO connectivity."""
        try:
            self._client.bucket_exists(self._bucket)
            return True
        except Exception:
            return False

    def close(self) -> None:
        """Close the underlying client (no-op for minio-py)."""
        pass
