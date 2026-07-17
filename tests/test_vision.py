"""Tests for vision module — OCR, floor plan analyzer, table extractor."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from civilmind.vision.floorplan import DrawingAnalysis, FloorPlanAnalyzer
from civilmind.vision.ocr import OCREngine, OCRResult
from civilmind.vision.tables import ExtractedTable, TableExtractor, TableType


class TestOCRResult:
    def test_basic_creation(self) -> None:
        r = OCRResult(text="hello", confidence=0.95, bbox=[[0, 0], [100, 0]])
        assert r.text == "hello"
        assert r.confidence == 0.95
        assert len(r.bbox) == 2
        assert r.page is None

    def test_with_page(self) -> None:
        r = OCRResult(text="text", confidence=0.8, page=3)
        assert r.page == 3


class TestOCREngine:
    def test_init(self) -> None:
        engine = OCREngine()
        assert engine._lang == "en"

    def test_init_custom_lang(self) -> None:
        engine = OCREngine(lang="hi")
        assert engine._lang == "hi"

    def test_file_not_found(self) -> None:
        engine = OCREngine()
        with pytest.raises(FileNotFoundError, match="Image not found"):
            import asyncio

            asyncio.get_event_loop().run_until_complete(
                engine.extract_text("/nonexistent/file.png")
            )

    def test_file_too_large(self, tmp_path: Path) -> None:
        big_file = tmp_path / "big.png"
        big_file.write_bytes(b"x" * (11 * 1024 * 1024))  # 11MB

        engine = OCREngine()
        with pytest.raises(ValueError, match="too large"):
            import asyncio

            asyncio.get_event_loop().run_until_complete(engine.extract_text(str(big_file)))

    def test_unsupported_format(self, tmp_path: Path) -> None:
        bad_file = tmp_path / "file.xyz"
        bad_file.write_bytes(b"content")

        engine = OCREngine()
        with pytest.raises(ValueError, match="Unsupported format"):
            import asyncio

            asyncio.get_event_loop().run_until_complete(engine.extract_text(str(bad_file)))

    def test_supported_formats(self, tmp_path: Path) -> None:
        for ext in [".png", ".jpg", ".jpeg", ".tiff", ".bmp", ".pdf"]:
            f = tmp_path / f"test{ext}"
            f.write_bytes(b"content")
            assert f.exists()

    def test_extract_all_text(self, tmp_path: Path) -> None:
        img = tmp_path / "doc.png"
        img.write_bytes(b"fake image")

        engine = OCREngine()
        with patch.object(
            engine,
            "_extract_sync",
            return_value=[
                OCRResult(text="Line 1", confidence=0.9),
                OCRResult(text="Line 2", confidence=0.8),
            ],
        ):
            import asyncio

            result = asyncio.get_event_loop().run_until_complete(engine.extract_all_text(str(img)))
            assert "Line 1" in result
            assert "Line 2" in result


class TestDrawingAnalysis:
    def test_from_dict_full(self) -> None:
        data = {
            "drawing_type": "floor_plan",
            "rooms": [{"name": "Bedroom", "area_sqm": 14.5}],
            "walls": [{"type": "load_bearing", "thickness_mm": 230}],
            "doors": [{"id": "D1", "width_mm": 900}],
            "windows": [{"id": "W1", "width_mm": 1200}],
            "columns": [{"id": "C1", "size_mm": {"width": 300, "depth": 300}}],
            "beams": [{"id": "B1", "size_mm": {"width": 230, "depth": 450}, "span_m": 4.0}],
            "dimensions": {"total_area_sqm": 180.0},
            "notes": ["structural note"],
        }
        analysis = DrawingAnalysis.from_dict(data)

        assert analysis.drawing_type == "floor_plan"
        assert len(analysis.rooms) == 1
        assert analysis.rooms[0]["name"] == "Bedroom"
        assert len(analysis.walls) == 1
        assert analysis.walls[0]["type"] == "load_bearing"
        assert len(analysis.columns) == 1
        assert len(analysis.beams) == 1
        assert analysis.dimensions["total_area_sqm"] == 180.0

    def test_from_dict_empty(self) -> None:
        analysis = DrawingAnalysis.from_dict({})
        assert analysis.drawing_type == "unknown"
        assert analysis.rooms == []
        assert analysis.walls == []
        assert analysis.confidence == 0.0


class TestFloorPlanAnalyzer:
    def test_init(self) -> None:
        analyzer = FloorPlanAnalyzer()
        assert analyzer._model is not None

    def test_init_custom_model(self) -> None:
        analyzer = FloorPlanAnalyzer(model="custom-model")
        assert analyzer._model == "custom-model"

    def test_file_not_found(self) -> None:
        analyzer = FloorPlanAnalyzer()
        with pytest.raises(FileNotFoundError, match="Image not found"):
            import asyncio

            asyncio.get_event_loop().run_until_complete(
                analyzer.analyze("/nonexistent/drawing.png")
            )

    def test_analyze_batch(self, tmp_path: Path) -> None:
        img1 = tmp_path / "drawing1.png"
        img1.write_bytes(b"image1")
        img2 = tmp_path / "drawing2.png"
        img2.write_bytes(b"image2")

        analyzer = FloorPlanAnalyzer()
        mock_analysis = DrawingAnalysis(drawing_type="floor_plan", rooms=[{"name": "Room 1"}])

        with patch.object(analyzer, "analyze", new_callable=AsyncMock) as mock_analyze:
            mock_analyze.return_value = mock_analysis
            import asyncio

            results = asyncio.get_event_loop().run_until_complete(
                analyzer.analyze_batch([str(img1), str(img2)])
            )

            assert len(results) == 2
            assert mock_analyze.call_count == 2


class TestTableType:
    def test_enum_values(self) -> None:
        assert TableType.BOQ.value == "boq"
        assert TableType.SPEC.value == "spec"
        assert TableType.SCHEDULE.value == "schedule"
        assert TableType.COST.value == "cost"
        assert TableType.UNKNOWN.value == "unknown"


class TestExtractedTable:
    def test_default_creation(self) -> None:
        t = ExtractedTable()
        assert t.headers == []
        assert t.rows == []
        assert t.table_type == TableType.UNKNOWN
        assert t.confidence == 0.0

    def test_with_data(self) -> None:
        t = ExtractedTable(
            headers=["Item", "Qty", "Unit", "Rate", "Amount"],
            rows=[
                ["Concrete", "45", "cum", "4500", "202500"],
                ["Steel", "12", "mt", "85000", "1020000"],
            ],
            table_type=TableType.BOQ,
            page=1,
            confidence=0.95,
            source_path="boq.pdf",
        )
        assert t.table_type == TableType.BOQ
        assert len(t.rows) == 2
        assert t.page == 1


class TestTableExtractor:
    def test_init(self) -> None:
        ext = TableExtractor()
        assert ext._vision_model is not None

    def test_classify_boq(self) -> None:
        ext = TableExtractor()
        headers = ["Bill of Quantities", "Item", "Quantity", "Unit", "Rate", "Amount"]
        assert ext._classify_table(headers) == TableType.BOQ

    def test_classify_spec(self) -> None:
        ext = TableExtractor()
        headers = ["Material", "Property", "Value", "Grade", "Strength"]
        assert ext._classify_table(headers) == TableType.SPEC

    def test_classify_schedule(self) -> None:
        ext = TableExtractor()
        headers = ["Task", "Duration", "Start", "End", "Dependencies"]
        assert ext._classify_table(headers) == TableType.SCHEDULE

    def test_classify_unknown(self) -> None:
        ext = TableExtractor()
        headers = ["A", "B", "C"]
        assert ext._classify_table(headers) == TableType.UNKNOWN

    def test_file_not_found_pdf(self) -> None:
        ext = TableExtractor()
        with pytest.raises(FileNotFoundError, match="PDF not found"):
            import asyncio

            asyncio.get_event_loop().run_until_complete(ext.extract_from_pdf("/nonexistent.pdf"))

    def test_file_not_found_image(self) -> None:
        ext = TableExtractor()
        with pytest.raises(FileNotFoundError, match="Image not found"):
            import asyncio

            asyncio.get_event_loop().run_until_complete(ext.extract_from_image("/nonexistent.png"))

    def test_to_boq_json(self) -> None:
        ext = TableExtractor()
        table = ExtractedTable(
            headers=["Item", "Qty", "Unit", "Rate", "Amount"],
            rows=[
                ["Concrete M25", "45", "cum", "4500", "202500"],
                ["Steel Fe500", "12", "mt", "85000", "1020000"],
            ],
            table_type=TableType.BOQ,
        )

        result = ext.to_boq_json(table)

        assert result["currency"] == "INR"
        assert len(result["items"]) == 2
        assert result["items"][0]["item"] == "Concrete M25"
        assert result["items"][0]["qty"] == 45.0
        assert result["items"][0]["amount"] == 202500.0
        assert result["total"] == 1222500.0

    def test_to_boq_json_empty(self) -> None:
        ext = TableExtractor()
        table = ExtractedTable(headers=[], rows=[])
        result = ext.to_boq_json(table)
        assert result["total"] == 0.0
        assert result["items"] == []

    def test_extract_from_pdf_sync_no_pdfplumber(self, tmp_path: Path) -> None:
        pdf_file = tmp_path / "test.pdf"
        pdf_file.write_bytes(b"not a real pdf")

        ext = TableExtractor()
        with patch.dict("sys.modules", {"pdfplumber": None}):
            import asyncio

            results = asyncio.get_event_loop().run_until_complete(
                ext.extract_from_pdf(str(pdf_file))
            )
            assert results == []
