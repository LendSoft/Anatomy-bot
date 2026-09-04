"""Все модели импортируются здесь, чтобы Alembic их видел в метаданных."""

from app.db.base import Base
from app.models.chat import AnswerStatus, Channel, Conversation, Message, MessageRole
from app.models.document import Document, DocumentChunk, DocumentStatus
from app.models.evaluation import RunStatus, TestQuestion, TestResult, TestRun, TestSet
from app.models.glossary import AnatomyTerm
from app.models.image import AtlasImage
from app.models.prompt import Prompt, PromptKind
from app.models.setting import AppSetting
from app.models.user import AdminUser, VkUser

__all__ = [
    "AdminUser",
    "AnatomyTerm",
    "AnswerStatus",
    "AppSetting",
    "AtlasImage",
    "Base",
    "Channel",
    "Conversation",
    "Document",
    "DocumentChunk",
    "DocumentStatus",
    "Message",
    "MessageRole",
    "Prompt",
    "PromptKind",
    "RunStatus",
    "TestQuestion",
    "TestResult",
    "TestRun",
    "TestSet",
    "VkUser",
]
