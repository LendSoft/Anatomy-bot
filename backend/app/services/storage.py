"""Работа с файловым хранилищем.

Файлы лежат на диске (том Docker), в БД — только пути. Раскладка по
подпапкам с хешем: в одном каталоге не окажется тысяч файлов, и имя
не зависит от исходного (кириллица и пробелы в именах учебников —
норма).
"""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path
from typing import BinaryIO

from app.core.config import settings

DOCUMENTS_DIR = "documents"
IMAGES_DIR = "images"
THUMBNAILS_DIR = "thumbnails"

ALLOWED_DOCUMENT_SUFFIXES = {".pdf", ".docx", ".txt", ".md"}
ALLOWED_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".gif"}


def storage_root() -> Path:
    root = Path(settings.storage_dir)
    root.mkdir(parents=True, exist_ok=True)
    return root


def _target_dir(kind: str, content_hash: str) -> Path:
    directory = storage_root() / kind / content_hash[:2]
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def hash_file(source: BinaryIO) -> str:
    """sha256 потоком — учебники бывают по несколько сотен мегабайт."""
    digest = hashlib.sha256()
    source.seek(0)
    for block in iter(lambda: source.read(1024 * 1024), b""):
        digest.update(block)
    source.seek(0)
    return digest.hexdigest()


def save_upload(source: BinaryIO, original_filename: str, kind: str) -> tuple[Path, str, int]:
    """Сохраняет файл. Возвращает (путь, хеш, размер)."""
    suffix = Path(original_filename).suffix.lower()
    content_hash = hash_file(source)

    target = _target_dir(kind, content_hash) / f"{content_hash}{suffix}"
    if not target.exists():
        with target.open("wb") as out:
            shutil.copyfileobj(source, out, length=1024 * 1024)

    return target, content_hash, target.stat().st_size


def delete_file(path: str | Path) -> None:
    file_path = Path(path)
    try:
        # На всякий случай не даём удалить что-либо вне хранилища
        file_path.resolve().relative_to(storage_root().resolve())
    except ValueError:
        return
    file_path.unlink(missing_ok=True)


def make_thumbnail(image_path: Path, max_side: int = 512) -> Path | None:
    """Уменьшенная копия для списка изображений в админке."""
    from PIL import Image

    try:
        with Image.open(image_path) as img:
            img = img.convert("RGB")
            img.thumbnail((max_side, max_side))
            target = (
                storage_root() / THUMBNAILS_DIR / image_path.parent.name
            )
            target.mkdir(parents=True, exist_ok=True)
            thumb_path = target / f"{image_path.stem}.jpg"
            img.save(thumb_path, "JPEG", quality=85)
            return thumb_path
    except Exception:  # noqa: BLE001 — без превью работать можно
        return None


def image_size(image_path: Path) -> tuple[int, int] | None:
    from PIL import Image

    try:
        with Image.open(image_path) as img:
            return img.size
    except Exception:  # noqa: BLE001
        return None
