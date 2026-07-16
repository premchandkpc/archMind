# ---------- base ----------
FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# system deps for unstructured, paddleocr, opencv
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libgl1 \
    libglib2.0-0 \
    poppler-utils \
    tesseract-ocr \
    libreoffice-core \
    && rm -rf /var/lib/apt/lists/*

# ---------- deps ----------
FROM base AS deps

COPY pyproject.toml .
RUN pip install --no-cache-dir -e ".[dev]"

# ---------- runtime ----------
FROM deps AS runtime

COPY civilmind/ civilmind/
COPY alembic/ alembic/
COPY alembic.ini .

EXPOSE 8000

CMD ["uvicorn", "civilmind.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
