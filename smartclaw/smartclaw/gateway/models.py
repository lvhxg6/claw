"""Pydantic request/response models for the SmartClaw API Gateway."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1)
    session_key: str | None = None
    max_iterations: int | None = Field(default=None, ge=1)


class ChatResponse(BaseModel):
    session_key: str
    response: str
    iterations: int
    error: str | None = None


class SSEEvent(BaseModel):
    event: str  # "tool_call" | "tool_result" | "thinking" | "done" | "error"
    data: dict  # type: ignore[type-arg]


class ToolInfo(BaseModel):
    name: str
    description: str


class HealthResponse(BaseModel):
    status: str
    version: str
    tools_count: int
    model: str = ""


class SessionHistoryResponse(BaseModel):
    session_key: str
    messages: list[dict]  # type: ignore[type-arg]


class SessionSummaryResponse(BaseModel):
    session_key: str
    summary: str
