"""Индексация изображений из атласов.

Эмбеддится текстовое описание: название, перечень структур на русском и
латыни, подпись. Само изображение моделью пока не обрабатывается — это
задел на потом, когда подключим мультимодальную модель; структура полей
для этого уже готова.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.image import AtlasImage
from app.rag import embeddings

log = get_logger(__name__)


def build_index_text(image: AtlasImage) -> str:
    parts = [image.title]
    if image.structures_ru:
        parts.append(", ".join(image.structures_ru))
    if image.structures_lat:
        parts.append(", ".join(image.structures_lat))
    if image.section:
        parts.append(image.section)
    if image.description:
        parts.append(image.description)
    return "\n".join(p for p in parts if p)


async def index_image(db: AsyncSession, image_id: int) -> None:
    image = (
        await db.execute(select(AtlasImage).where(AtlasImage.id == image_id))
    ).scalar_one_or_none()
    if image is None:
        return

    try:
        vector = await embeddings.embed_one(build_index_text(image), kind="document")
        image.embedding = vector
        await db.commit()
        log.info("image_indexed", image_id=image_id)
    except Exception as exc:  # noqa: BLE001
        log.exception("image_indexing_failed", image_id=image_id)
        await db.rollback()
        # Картинка остаётся в базе, просто не участвует в поиске,
        # пока её не переиндексируют
        raise RuntimeError(f"Не удалось проиндексировать изображение: {exc}") from exc


async def reindex_all(db: AsyncSession) -> int:
    ids = (await db.execute(select(AtlasImage.id))).scalars().all()
    for image_id in ids:
        try:
            await index_image(db, image_id)
        except RuntimeError:
            continue
    return len(ids)
