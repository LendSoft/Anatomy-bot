"""Схемы организационной информации."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class GroupScheduleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    group_name: str
    original_filename: str
    mime_type: str
    size_bytes: int
    is_active: bool
    updated_at: datetime


class TeacherOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    full_name: str
    position: str
    area: str
    is_active: bool


class TeacherCreate(BaseModel):
    full_name: str = Field(..., min_length=1, max_length=255)
    position: str = Field(..., min_length=1, max_length=255)
    area: str = Field(..., min_length=1, max_length=512)


class TeacherUpdate(BaseModel):
    full_name: str | None = Field(None, min_length=1, max_length=255)
    position: str | None = Field(None, min_length=1, max_length=255)
    area: str | None = Field(None, min_length=1, max_length=512)