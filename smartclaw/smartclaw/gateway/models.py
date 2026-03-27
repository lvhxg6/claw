"""Pydantic request/response models for the SmartClaw API Gateway."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1)
    session_key: str | None = None
    max_iterations: int | None = Field(default=None, ge=1)
    model: str | None = Field(default=None, description="Optional model reference in 'provider/model' format")
    mode: Literal["auto", "classic", "orchestrator"] | None = Field(
        default=None,
        description="Optional execution mode override",
    )
    scenario_type: str | None = Field(
        default=None,
        description="Optional scenario hint such as chat/inspection/hardening",
    )
    task_profile: str | None = Field(
        default=None,
        description="Optional task profile hint such as simple/multi_stage",
    )
    capability_pack: str | None = Field(
        default=None,
        description="Optional capability pack name used for tool scoping and prompt guidance",
    )
    approved: bool | None = Field(
        default=None,
        description="Explicit approval flag for capability packs that require approval",
    )


class ClarificationData(BaseModel):
    question: str
    options: list[str] | None = None


class ChatResponse(BaseModel):
    session_key: str
    response: str
    iterations: int
    error: str | None = None
    token_stats: dict[str, int] | None = None
    clarification: ClarificationData | None = None


class SSEEvent(BaseModel):
    event: str  # "tool_call" | "tool_result" | "thinking" | "done" | "error"
    data: dict  # type: ignore[type-arg]


class ToolInfo(BaseModel):
    name: str
    description: str


class CapabilityPackInfoData(BaseModel):
    name: str
    description: str
    scenario_types: list[str] = Field(default_factory=list)
    preferred_mode: str | None = None
    task_profile: str | None = None
    approval_required: bool = False
    schema_enforced: bool = False


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


class SessionListItemData(BaseModel):
    session_key: str
    title: str
    preview: str = ""
    updated_at: str | None = None
    message_count: int = 0
    model_override: str | None = None


class SessionConfigRequest(BaseModel):
    """Request body for PUT /api/sessions/{key}/config."""

    model: str | None = Field(default=None, description="Model override in 'provider/model' format")
