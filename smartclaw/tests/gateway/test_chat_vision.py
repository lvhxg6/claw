"""Gateway tests for vision-capable attachment routing."""

from __future__ import annotations

from unittest.mock import AsyncMock

from langchain_core.messages import HumanMessage

from smartclaw.providers.capabilities import ModelCapabilities
from tests.gateway.conftest import make_test_client


def test_chat_vision_preferred_uses_multimodal_when_model_supports_vision(tmp_path, monkeypatch) -> None:
    """POST /api/chat routes image attachments to invoke_multimodal when the model is vision-capable."""
    import smartclaw.agent.graph as graph_module

    original_invoke = graph_module.invoke
    original_invoke_multimodal = graph_module.invoke_multimodal
    image_path = tmp_path / "screen.png"
    image_path.write_bytes(b"\x89PNG\r\n\x1a\nfake-image")

    try:
        client, mock_invoke, mock_memory, _ = make_test_client()
        mock_invoke_multimodal = AsyncMock(
            return_value={
                "final_answer": "Vision response",
                "iteration": 1,
                "error": None,
                "session_key": "sess-vision",
                "messages": [],
                "token_stats": None,
            }
        )
        monkeypatch.setattr(graph_module, "invoke_multimodal", mock_invoke_multimodal)
        mock_memory.get_attachments = AsyncMock(
            return_value=[
                {
                    "asset_id": "att_img",
                    "session_key": "sess-vision",
                    "filename": "screen.png",
                    "media_type": "image/png",
                    "kind": "image",
                    "storage_path": str(image_path),
                    "size_bytes": image_path.stat().st_size,
                    "sha256": "abc",
                    "status": "uploaded",
                    "extract_status": "success",
                    "extract_text": "Firewall baseline passed",
                    "extract_summary": "OCR: Firewall baseline passed",
                    "error_message": "",
                    "created_at": None,
                    "updated_at": None,
                },
                {
                    "asset_id": "att_doc",
                    "session_key": "sess-vision",
                    "filename": "hosts.csv",
                    "media_type": "text/csv",
                    "kind": "table",
                    "storage_path": "/tmp/hosts.csv",
                    "size_bytes": 42,
                    "sha256": "def",
                    "status": "uploaded",
                    "extract_status": "success",
                    "extract_text": "host,ip\napp-01,10.0.0.1",
                    "extract_summary": "资产列表",
                    "error_message": "",
                    "created_at": None,
                    "updated_at": None,
                },
            ]
        )

        with client:
            client.app.state.settings.uploads.image_analysis_mode = "vision_preferred"
            client.app.state.runtime.resolve_model_capabilities.return_value = ModelCapabilities(
                supports_vision=True,
                source="test",
            )
            resp = client.post(
                "/api/chat",
                json={
                    "session_key": "sess-vision",
                    "message": "请分析图片和文档",
                    "attachment_ids": ["att_img", "att_doc"],
                },
            )

        assert resp.status_code == 200
        mock_invoke.assert_not_awaited()
        mock_invoke_multimodal.assert_awaited_once()
        message = mock_invoke_multimodal.call_args.args[0]
        assert isinstance(message, HumanMessage)
        text_blocks = [block["text"] for block in message.content if block.get("type") == "text"]
        assert text_blocks
        text_payload = text_blocks[0]
        assert "[Images]" in text_payload
        assert "screen.png" in text_payload
        assert "hosts.csv" in text_payload
        assert "资产列表" in text_payload
        assert "[User Request]" in text_payload
        assert "请分析图片和文档" in text_payload
        image_blocks = [block for block in message.content if block.get("type") == "image_url"]
        assert len(image_blocks) == 1
    finally:
        graph_module.invoke = original_invoke  # type: ignore[assignment]
        graph_module.invoke_multimodal = original_invoke_multimodal  # type: ignore[assignment]


def test_chat_vision_preferred_falls_back_to_ocr_context_when_model_lacks_vision(tmp_path, monkeypatch) -> None:
    """POST /api/chat keeps OCR text path when the model does not support vision."""
    import smartclaw.agent.graph as graph_module

    original_invoke = graph_module.invoke
    original_invoke_multimodal = graph_module.invoke_multimodal
    image_path = tmp_path / "screen.png"
    image_path.write_bytes(b"\x89PNG\r\n\x1a\nfake-image")

    try:
        client, mock_invoke, mock_memory, _ = make_test_client()
        monkeypatch.setattr(graph_module, "invoke_multimodal", AsyncMock())
        mock_memory.get_attachments = AsyncMock(
            return_value=[
                {
                    "asset_id": "att_img",
                    "session_key": "sess-ocr",
                    "filename": "screen.png",
                    "media_type": "image/png",
                    "kind": "image",
                    "storage_path": str(image_path),
                    "size_bytes": image_path.stat().st_size,
                    "sha256": "abc",
                    "status": "uploaded",
                    "extract_status": "success",
                    "extract_text": "Firewall baseline passed",
                    "extract_summary": "OCR: Firewall baseline passed",
                    "error_message": "",
                    "created_at": None,
                    "updated_at": None,
                }
            ]
        )

        with client:
            client.app.state.settings.uploads.image_analysis_mode = "vision_preferred"
            client.app.state.runtime.resolve_model_capabilities.return_value = ModelCapabilities(
                supports_vision=False,
                source="test",
            )
            resp = client.post(
                "/api/chat",
                json={
                    "session_key": "sess-ocr",
                    "message": "请分析截图",
                    "attachment_ids": ["att_img"],
                },
            )

        assert resp.status_code == 200
        mock_invoke.assert_awaited_once()
        effective_message = mock_invoke.call_args.args[1]
        assert "[Attachments]" in effective_message
        assert "screen.png" in effective_message
        assert "OCR: Firewall baseline passed" in effective_message
    finally:
        graph_module.invoke = original_invoke  # type: ignore[assignment]
        graph_module.invoke_multimodal = original_invoke_multimodal  # type: ignore[assignment]


def test_chat_vision_only_returns_400_for_non_vision_model(tmp_path, monkeypatch) -> None:
    """POST /api/chat rejects image analysis when vision_only is configured but the model lacks vision."""
    import smartclaw.agent.graph as graph_module

    original_invoke = graph_module.invoke
    original_invoke_multimodal = graph_module.invoke_multimodal
    image_path = tmp_path / "screen.png"
    image_path.write_bytes(b"\x89PNG\r\n\x1a\nfake-image")

    try:
        client, mock_invoke, mock_memory, _ = make_test_client()
        mock_invoke_multimodal = AsyncMock()
        monkeypatch.setattr(graph_module, "invoke_multimodal", mock_invoke_multimodal)
        mock_memory.get_attachments = AsyncMock(
            return_value=[
                {
                    "asset_id": "att_img",
                    "session_key": "sess-vision-only",
                    "filename": "screen.png",
                    "media_type": "image/png",
                    "kind": "image",
                    "storage_path": str(image_path),
                    "size_bytes": image_path.stat().st_size,
                    "sha256": "abc",
                    "status": "uploaded",
                    "extract_status": "success",
                    "extract_text": "Firewall baseline passed",
                    "extract_summary": "OCR: Firewall baseline passed",
                    "error_message": "",
                    "created_at": None,
                    "updated_at": None,
                }
            ]
        )

        with client:
            client.app.state.settings.uploads.image_analysis_mode = "vision_only"
            client.app.state.runtime.resolve_model_capabilities.return_value = ModelCapabilities(
                supports_vision=False,
                source="test",
            )
            resp = client.post(
                "/api/chat",
                json={
                    "session_key": "sess-vision-only",
                    "message": "请分析截图",
                    "attachment_ids": ["att_img"],
                },
            )

        assert resp.status_code == 400
        assert "vision_only" in resp.text
        mock_invoke.assert_not_awaited()
        mock_invoke_multimodal.assert_not_awaited()
    finally:
        graph_module.invoke = original_invoke  # type: ignore[assignment]
        graph_module.invoke_multimodal = original_invoke_multimodal  # type: ignore[assignment]


def test_chat_stream_vision_preferred_uses_multimodal_path(tmp_path, monkeypatch) -> None:
    """POST /api/chat/stream emits done after invoke_multimodal on the vision path."""
    import smartclaw.agent.graph as graph_module

    original_invoke = graph_module.invoke
    original_invoke_multimodal = graph_module.invoke_multimodal
    image_path = tmp_path / "screen.png"
    image_path.write_bytes(b"\x89PNG\r\n\x1a\nfake-image")

    try:
        client, mock_invoke, mock_memory, _ = make_test_client()
        mock_invoke_multimodal = AsyncMock(
            return_value={
                "final_answer": "Vision stream response",
                "iteration": 1,
                "error": None,
                "session_key": "sess-stream",
                "messages": [],
                "token_stats": None,
            }
        )
        monkeypatch.setattr(graph_module, "invoke_multimodal", mock_invoke_multimodal)
        mock_memory.get_attachments = AsyncMock(
            return_value=[
                {
                    "asset_id": "att_img",
                    "session_key": "sess-stream",
                    "filename": "screen.png",
                    "media_type": "image/png",
                    "kind": "image",
                    "storage_path": str(image_path),
                    "size_bytes": image_path.stat().st_size,
                    "sha256": "abc",
                    "status": "uploaded",
                    "extract_status": "success",
                    "extract_text": "Firewall baseline passed",
                    "extract_summary": "OCR: Firewall baseline passed",
                    "error_message": "",
                    "created_at": None,
                    "updated_at": None,
                }
            ]
        )

        with client:
            client.app.state.settings.uploads.image_analysis_mode = "vision_preferred"
            client.app.state.runtime.resolve_model_capabilities.return_value = ModelCapabilities(
                supports_vision=True,
                source="test",
            )
            resp = client.post(
                "/api/chat/stream",
                json={
                    "session_key": "sess-stream",
                    "message": "请分析截图",
                    "attachment_ids": ["att_img"],
                },
            )

        assert resp.status_code == 200
        assert "event: done" in resp.text
        assert "Vision stream response" in resp.text
        mock_invoke.assert_not_awaited()
        mock_invoke_multimodal.assert_awaited_once()
    finally:
        graph_module.invoke = original_invoke  # type: ignore[assignment]
        graph_module.invoke_multimodal = original_invoke_multimodal  # type: ignore[assignment]
