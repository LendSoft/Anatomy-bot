"""Общая настройка тестов.

Конфигурация читается из окружения при импорте, поэтому обязательные
переменные задаём до того, как что-либо из app будет импортировано.
"""

from __future__ import annotations

import os

os.environ.setdefault("SECRET_KEY", "test-secret-key-for-tests-only")
os.environ.setdefault("POSTGRES_PASSWORD", "test")
os.environ.setdefault("FIRST_ADMIN_PASSWORD", "test-admin-password")
os.environ.setdefault("ENVIRONMENT", "development")
