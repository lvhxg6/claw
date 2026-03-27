"""Gateway tests for upload and attachment-aware chat flows."""

from __future__ import annotations

import sys
import types
from unittest.mock import AsyncMock

from tests.gateway.conftest import make_test_client


def test_upload_file_returns_metadata(tmp_path) -> None:
    """POST /api/uploads stores metadata for a text attachment."""
    import smartclaw.agent.graph as graph_module

    original = graph_module.invoke
    try:
        client, _, mock_memory, _ = make_test_client()
        mock_memory.list_attachments = AsyncMock(return_value=[])

        with client:
            client.app.state.settings.uploads.root_dir = str(tmp_path / "uploads")
            resp = client.post(
                "/api/uploads",
                data={"session_key": "sess-upload"},
                files={"file": ("hosts.csv", "host,ip\napp-01,10.0.0.1\n", "text/csv")},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["session_key"] == "sess-upload"
        assert data["filename"] == "hosts.csv"
        assert data["media_type"] == "text/csv"
        assert data["kind"] == "table"
        assert data["extract_status"] == "success"
        mock_memory.upsert_attachment.assert_awaited_once()
    finally:
        graph_module.invoke = original  # type: ignore[assignment]


def test_upload_image_returns_unsupported_extract_status(tmp_path) -> None:
    """POST /api/uploads falls back cleanly when OCR support is unavailable."""
    import smartclaw.agent.graph as graph_module

    original = graph_module.invoke
    try:
        client, _, mock_memory, _ = make_test_client()
        mock_memory.list_attachments = AsyncMock(return_value=[])

        with client:
            client.app.state.settings.uploads.root_dir = str(tmp_path / "uploads")
            client.app.state.settings.uploads.image_analysis_mode = "disabled"
            resp = client.post(
                "/api/uploads",
                data={"session_key": "sess-image"},
                files={"file": ("diagram.png", b"\x89PNG\r\n\x1a\n", "image/png")},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["kind"] == "image"
        assert data["extract_status"] == "unsupported"
        assert data["error_message"] is None
    finally:
        graph_module.invoke = original  # type: ignore[assignment]


def test_upload_image_returns_ocr_summary_when_available(tmp_path, monkeypatch) -> None:
    """POST /api/uploads extracts OCR text from images when OCR stack is available."""
    import smartclaw.agent.graph as graph_module

    class _FakeImage:
        size = (640, 480)

        def load(self) -> None:
            return None

    class _FakeImageModule:
        @staticmethod
        def open(_stream):
            return _FakeImage()

    class _FakePyTesseractInner:
        tesseract_cmd = ""

        @staticmethod
        def image_to_string(_image, lang="eng"):
            assert lang == "eng"
            return "Firewall baseline passed"

    class _FakeTesseractNotFoundError(Exception):
        pass

    fake_pytesseract = types.SimpleNamespace(
        pytesseract=_FakePyTesseractInner,
        TesseractNotFoundError=_FakeTesseractNotFoundError,
        image_to_string=_FakePyTesseractInner.image_to_string,
    )

    monkeypatch.setitem(sys.modules, "PIL", types.SimpleNamespace(Image=_FakeImageModule))
    monkeypatch.setitem(sys.modules, "PIL.Image", _FakeImageModule)
    monkeypatch.setitem(sys.modules, "pytesseract", fake_pytesseract)

    original = graph_module.invoke
    try:
        client, _, mock_memory, _ = make_test_client()
        mock_memory.list_attachments = AsyncMock(return_value=[])

        with client:
            client.app.state.settings.uploads.root_dir = str(tmp_path / "uploads")
            client.app.state.settings.uploads.image_analysis_mode = "ocr_only"
            resp = client.post(
                "/api/uploads",
                data={"session_key": "sess-image"},
                files={"file": ("diagram.png", b"\x89PNG\r\n\x1a\n", "image/png")},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["kind"] == "image"
        assert data["extract_status"] == "success"
        assert "OCR" in (data["extract_summary"] or "")
        assert "Firewall baseline passed" in (data["extract_summary"] or "")
    finally:
        graph_module.invoke = original  # type: ignore[assignment]


def test_upload_image_returns_unsupported_when_ocr_finds_no_text(tmp_path, monkeypatch) -> None:
    """POST /api/uploads returns unsupported when OCR runs but detects no text."""
    import smartclaw.agent.graph as graph_module

    class _FakeImage:
        size = (320, 200)

        def load(self) -> None:
            return None

    class _FakeImageModule:
        @staticmethod
        def open(_stream):
            return _FakeImage()

    class _FakePyTesseractInner:
        tesseract_cmd = ""

        @staticmethod
        def image_to_string(_image, lang="eng"):
            return ""

    class _FakeTesseractNotFoundError(Exception):
        pass

    fake_pytesseract = types.SimpleNamespace(
        pytesseract=_FakePyTesseractInner,
        TesseractNotFoundError=_FakeTesseractNotFoundError,
        image_to_string=_FakePyTesseractInner.image_to_string,
    )

    monkeypatch.setitem(sys.modules, "PIL", types.SimpleNamespace(Image=_FakeImageModule))
    monkeypatch.setitem(sys.modules, "PIL.Image", _FakeImageModule)
    monkeypatch.setitem(sys.modules, "pytesseract", fake_pytesseract)

    original = graph_module.invoke
    try:
        client, _, mock_memory, _ = make_test_client()
        mock_memory.list_attachments = AsyncMock(return_value=[])

        with client:
            client.app.state.settings.uploads.root_dir = str(tmp_path / "uploads")
            client.app.state.settings.uploads.image_analysis_mode = "ocr_only"
            resp = client.post(
                "/api/uploads",
                data={"session_key": "sess-image-empty"},
                files={"file": ("empty.png", b"\x89PNG\r\n\x1a\n", "image/png")},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["extract_status"] == "unsupported"
        assert "未识别到文字" in (data["extract_summary"] or "")
    finally:
        graph_module.invoke = original  # type: ignore[assignment]


def test_upload_image_returns_clear_error_when_ocr_language_missing(tmp_path, monkeypatch) -> None:
    """POST /api/uploads returns a clear message when the requested OCR language pack is missing."""
    import smartclaw.agent.graph as graph_module

    class _FakeImage:
        size = (320, 200)

        def load(self) -> None:
            return None

    class _FakeImageModule:
        @staticmethod
        def open(_stream):
            return _FakeImage()

    class _FakePyTesseractInner:
        tesseract_cmd = ""

        @staticmethod
        def image_to_string(_image, lang="eng+chi_sim"):
            raise RuntimeError(
                'Error opening data file chi_sim.traineddata Failed loading language '
                'chi_sim Tesseract couldn\'t load any languages!'
            )

    class _FakeTesseractNotFoundError(Exception):
        pass

    fake_pytesseract = types.SimpleNamespace(
        pytesseract=_FakePyTesseractInner,
        TesseractNotFoundError=_FakeTesseractNotFoundError,
        image_to_string=_FakePyTesseractInner.image_to_string,
    )

    monkeypatch.setitem(sys.modules, "PIL", types.SimpleNamespace(Image=_FakeImageModule))
    monkeypatch.setitem(sys.modules, "PIL.Image", _FakeImageModule)
    monkeypatch.setitem(sys.modules, "pytesseract", fake_pytesseract)

    original = graph_module.invoke
    try:
        client, _, mock_memory, _ = make_test_client()
        mock_memory.list_attachments = AsyncMock(return_value=[])

        with client:
            client.app.state.settings.uploads.root_dir = str(tmp_path / "uploads")
            client.app.state.settings.uploads.image_analysis_mode = "ocr_only"
            client.app.state.settings.uploads.ocr_languages = ["eng", "chi_sim"]
            resp = client.post(
                "/api/uploads",
                data={"session_key": "sess-image-lang-missing"},
                files={"file": ("missing-lang.png", b"\x89PNG\r\n\x1a\n", "image/png")},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["extract_status"] == "failed"
        assert "缺少所需语言包" in (data["extract_summary"] or "")
        assert "chi_sim" in (data["error_message"] or "")
    finally:
        graph_module.invoke = original  # type: ignore[assignment]


def test_upload_pdf_returns_extracted_summary(tmp_path, monkeypatch) -> None:
    """POST /api/uploads extracts text from PDF when parser dependency is available."""
    import smartclaw.agent.graph as graph_module

    class _FakePage:
        def __init__(self, text: str) -> None:
            self._text = text

        def extract_text(self) -> str:
            return self._text

    class _FakePdfReader:
        def __init__(self, _stream) -> None:
            self.pages = [_FakePage("第一页内容"), _FakePage("第二页内容")]

    monkeypatch.setitem(sys.modules, "pypdf", types.SimpleNamespace(PdfReader=_FakePdfReader))

    original = graph_module.invoke
    try:
        client, _, mock_memory, _ = make_test_client()
        mock_memory.list_attachments = AsyncMock(return_value=[])

        with client:
            client.app.state.settings.uploads.root_dir = str(tmp_path / "uploads")
            resp = client.post(
                "/api/uploads",
                data={"session_key": "sess-pdf"},
                files={"file": ("report.pdf", b"%PDF-1.4", "application/pdf")},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["media_type"] == "application/pdf"
        assert data["kind"] == "document"
        assert data["extract_status"] == "success"
        assert "第一页内容" in (data["extract_summary"] or "")
    finally:
        graph_module.invoke = original  # type: ignore[assignment]


def test_upload_docx_returns_extracted_summary(tmp_path, monkeypatch) -> None:
    """POST /api/uploads extracts text from DOCX when parser dependency is available."""
    import smartclaw.agent.graph as graph_module

    class _FakeParagraph:
        def __init__(self, text: str) -> None:
            self.text = text

    class _FakeDocument:
        def __init__(self, _stream) -> None:
            self.paragraphs = [_FakeParagraph("第一段"), _FakeParagraph("第二段")]

    monkeypatch.setitem(sys.modules, "docx", types.SimpleNamespace(Document=_FakeDocument))

    original = graph_module.invoke
    try:
        client, _, mock_memory, _ = make_test_client()
        mock_memory.list_attachments = AsyncMock(return_value=[])

        with client:
            client.app.state.settings.uploads.root_dir = str(tmp_path / "uploads")
            resp = client.post(
                "/api/uploads",
                data={"session_key": "sess-docx"},
                files={
                    "file": (
                        "report.docx",
                        b"PK\x03\x04",
                        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    )
                },
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["kind"] == "document"
        assert data["extract_status"] == "success"
        assert "第一段" in (data["extract_summary"] or "")
    finally:
        graph_module.invoke = original  # type: ignore[assignment]


def test_upload_xlsx_returns_extracted_summary(tmp_path, monkeypatch) -> None:
    """POST /api/uploads extracts text from XLSX when parser dependency is available."""
    import smartclaw.agent.graph as graph_module

    class _FakeSheet:
        title = "资产清单"

        def iter_rows(self, values_only=True):
            assert values_only is True
            return iter(
                [
                    ("host", "ip"),
                    ("app-01", "10.0.0.1"),
                    ("app-02", "10.0.0.2"),
                ]
            )

    class _FakeWorkbook:
        def __init__(self) -> None:
            self.worksheets = [_FakeSheet()]

    def _fake_load_workbook(_stream, read_only=True, data_only=True):
        assert read_only is True
        assert data_only is True
        return _FakeWorkbook()

    monkeypatch.setitem(sys.modules, "openpyxl", types.SimpleNamespace(load_workbook=_fake_load_workbook))

    original = graph_module.invoke
    try:
        client, _, mock_memory, _ = make_test_client()
        mock_memory.list_attachments = AsyncMock(return_value=[])

        with client:
            client.app.state.settings.uploads.root_dir = str(tmp_path / "uploads")
            resp = client.post(
                "/api/uploads",
                data={"session_key": "sess-xlsx"},
                files={
                    "file": (
                        "assets.xlsx",
                        b"PK\x03\x04",
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    )
                },
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["kind"] == "table"
        assert data["extract_status"] == "success"
        assert "资产清单" in (data["extract_summary"] or "")
    finally:
        graph_module.invoke = original  # type: ignore[assignment]


def test_list_session_attachments_returns_items() -> None:
    """GET /api/sessions/{key}/attachments returns attachment metadata."""
    import smartclaw.agent.graph as graph_module

    original = graph_module.invoke
    try:
        client, _, mock_memory, _ = make_test_client()
        mock_memory.list_attachments = AsyncMock(
            return_value=[
                {
                    "asset_id": "att_123",
                    "session_key": "sess-1",
                    "filename": "baseline.md",
                    "media_type": "text/markdown",
                    "kind": "text",
                    "size_bytes": 88,
                    "status": "uploaded",
                    "extract_status": "success",
                    "extract_summary": "基线要求摘要",
                    "error_message": "",
                    "created_at": "2026-03-27 12:00:00",
                    "updated_at": "2026-03-27 12:00:00",
                }
            ]
        )
        with client:
            resp = client.get("/api/sessions/sess-1/attachments")

        assert resp.status_code == 200
        assert resp.json() == [
            {
                "asset_id": "att_123",
                "session_key": "sess-1",
                "filename": "baseline.md",
                "media_type": "text/markdown",
                "kind": "text",
                "size_bytes": 88,
                "status": "uploaded",
                "extract_status": "success",
                "extract_summary": "基线要求摘要",
                "error_message": None,
                "created_at": "2026-03-27 12:00:00",
                "updated_at": "2026-03-27 12:00:00",
            }
        ]
    finally:
        graph_module.invoke = original  # type: ignore[assignment]


def test_chat_includes_attachment_context() -> None:
    """POST /api/chat injects attachment summaries into the effective message."""
    import smartclaw.agent.graph as graph_module

    original = graph_module.invoke
    try:
        client, mock_invoke, mock_memory, _ = make_test_client()
        mock_memory.get_attachments = AsyncMock(
            return_value=[
                {
                    "asset_id": "att_a",
                    "session_key": "sess-ctx",
                    "filename": "hosts.csv",
                    "media_type": "text/csv",
                    "kind": "table",
                    "storage_path": "/tmp/hosts.csv",
                    "size_bytes": 42,
                    "sha256": "abc",
                    "status": "uploaded",
                    "extract_status": "success",
                    "extract_text": "host,ip\napp-01,10.0.0.1",
                    "extract_summary": "资产列表",
                    "error_message": "",
                    "created_at": None,
                    "updated_at": None,
                }
            ]
        )

        with client:
            resp = client.post(
                "/api/chat",
                json={
                    "session_key": "sess-ctx",
                    "message": "请分析这些资产",
                    "attachment_ids": ["att_a"],
                },
            )

        assert resp.status_code == 200
        effective_message = mock_invoke.call_args.args[1]
        assert "[Attachments]" in effective_message
        assert "hosts.csv" in effective_message
        assert "资产列表" in effective_message
        assert "[User Request]" in effective_message
        assert "请分析这些资产" in effective_message
    finally:
        graph_module.invoke = original  # type: ignore[assignment]


def test_chat_returns_400_when_attachment_missing() -> None:
    """POST /api/chat returns 400 if an attachment id cannot be resolved."""
    import smartclaw.agent.graph as graph_module

    original = graph_module.invoke
    try:
        client, _, mock_memory, _ = make_test_client()
        mock_memory.get_attachments = AsyncMock(return_value=[])

        with client:
            resp = client.post(
                "/api/chat",
                json={
                    "session_key": "sess-ctx",
                    "message": "请分析",
                    "attachment_ids": ["att_missing"],
                },
            )

        assert resp.status_code == 400
        assert "attachments" in resp.text.lower()
    finally:
        graph_module.invoke = original  # type: ignore[assignment]
