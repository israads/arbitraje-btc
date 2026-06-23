"""Modelos de export de sesión auditable (PRD-002)."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class SessionMetadata(BaseModel):
    app: str
    env: str
    version: str
    exported_at: float


class SessionExport(BaseModel):
    metadata: SessionMetadata
    settings: dict[str, Any]
    quotes: list[dict[str, Any]] = Field(default_factory=list)
    opportunities: list[dict[str, Any]] = Field(default_factory=list)
    metrics: dict[str, Any] = Field(default_factory=dict)
    breakers: dict[str, Any] = Field(default_factory=dict)
    demo: dict[str, Any] = Field(default_factory=dict)
    calibration: dict[str, Any] = Field(default_factory=dict)
    validation: dict[str, Any] = Field(default_factory=dict)
    recording: dict[str, Any] = Field(default_factory=dict)
