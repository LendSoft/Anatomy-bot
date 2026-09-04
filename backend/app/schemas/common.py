"""Общие схемы."""

from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    size: int

    @property
    def pages(self) -> int:
        return (self.total + self.size - 1) // self.size if self.size else 0


class PaginationParams(BaseModel):
    page: int = Field(1, ge=1)
    size: int = Field(20, ge=1, le=200)

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.size


class MessageResponse(BaseModel):
    detail: str


class IdResponse(BaseModel):
    id: int
