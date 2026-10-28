"""Иллюстрации извлекаются из документов вместо ручной загрузки картинок

Было: таблица atlas_images, куда администратор вручную заливал картинки
из атласов и расписывал каждой перечень структур. Подбор к ответу шёл по
вектору этого описания.

Стало: таблица document_figures, которая заполняется сама при индексации
учебника. От иллюстрации хранятся источник (документ и страница),
подпись из книги, текст выносок и координаты на странице. Файл картинки
не хранится — изображение вырезается из исходного PDF по запросу.

Ручные описания переносить не из чего: в atlas_images нет ссылки на
документ и страницу в базе знаний, а именно они и нужны, чтобы указать
студенту, где смотреть рисунок. Поэтому таблица удаляется целиком.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-28
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EMBEDDING_DIM = 1024  # BAAI/bge-m3

FIGURE_KINDS = ("figure", "plate", "table", "page")

figure_kind = postgresql.ENUM(name="figure_kind", create_type=False)


def upgrade() -> None:
    # --------------------------------------------- убираем ручные картинки
    op.execute("DROP TRIGGER IF EXISTS atlas_images_tsv_update ON atlas_images")
    op.execute("DROP FUNCTION IF EXISTS atlas_images_tsv_trigger()")
    op.drop_table("atlas_images")

    # Журнал ответов: картинок больше нет, вместо них иллюстрации.
    # Старое содержимое поля ссылается на удалённые atlas_images, так что
    # колонка пересоздаётся пустой, а не переименовывается.
    op.drop_column("messages", "attached_images")
    op.add_column("messages", sa.Column("attached_figures", postgresql.JSONB()))

    # -------------------------------------------------- document_figures
    literals = ", ".join(f"'{value}'" for value in FIGURE_KINDS)
    op.execute(
        f"""
        DO $$ BEGIN
            CREATE TYPE figure_kind AS ENUM ({literals});
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
        """
    )

    op.add_column(
        "documents",
        sa.Column("figures_count", sa.Integer(), nullable=False, server_default="0"),
    )

    op.create_table(
        "document_figures",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("document_id", sa.Integer(), nullable=False),
        # 0 — иллюстрация из DOCX, где нумерации страниц нет
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("index_on_page", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("kind", figure_kind, nullable=False, server_default="figure"),
        sa.Column("label", sa.String(64)),
        sa.Column("title", sa.String(1024)),
        # Выноски с названиями структур: текст с самого изображения
        sa.Column("labels", postgresql.ARRAY(sa.Text())),
        sa.Column("bbox", postgresql.ARRAY(sa.Float())),
        sa.Column("page_width", sa.Float()),
        sa.Column("page_height", sa.Float()),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0.5"),
        sa.Column("vk_attachment_id", sa.String(128)),
        sa.Column("embedding", Vector(EMBEDDING_DIM)),
        sa.Column("search_vector", postgresql.TSVECTOR()),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("extra", postgresql.JSONB()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
    )

    op.create_index("ix_document_figures_document_id", "document_figures", ["document_id"])
    op.create_index("ix_document_figures_page_number", "document_figures", ["page_number"])
    op.create_index("ix_document_figures_created_at", "document_figures", ["created_at"])
    # Основная выборка: рисунки на страницах найденного фрагмента
    op.create_index(
        "ix_document_figures_doc_page", "document_figures", ["document_id", "page_number"]
    )
    op.create_index(
        "ix_document_figures_doc_page_idx",
        "document_figures",
        ["document_id", "page_number", "index_on_page"],
        unique=True,
    )
    op.execute(
        "CREATE INDEX ix_document_figures_search ON document_figures "
        "USING gin (search_vector)"
    )
    op.execute(
        "CREATE INDEX ix_document_figures_embedding ON document_figures "
        "USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64)"
    )

    # Полнотекстовый вектор считается в БД — как и у фрагментов.
    # Выноски весят как подпись ('A'): в атласе названия структур есть
    # только в них, и искать рисунок приходится именно по ним. Их же
    # добавляем конфигурацией simple — латинские названия русский
    # стеммер искажает («musculus» → «muscul»).
    op.execute(
        """
        CREATE FUNCTION document_figures_tsv_trigger() RETURNS trigger AS $$
        BEGIN
            NEW.search_vector :=
                setweight(to_tsvector('russian', coalesce(NEW.label, '')), 'A') ||
                setweight(to_tsvector('russian', coalesce(NEW.title, '')), 'A') ||
                setweight(to_tsvector('russian',
                    coalesce(array_to_string(NEW.labels, ' '), '')), 'A') ||
                setweight(to_tsvector('simple',
                    coalesce(array_to_string(NEW.labels, ' '), '')), 'B');
            RETURN NEW;
        END
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER document_figures_tsv_update
        BEFORE INSERT OR UPDATE OF label, title, labels ON document_figures
        FOR EACH ROW EXECUTE FUNCTION document_figures_tsv_trigger();
        """
    )

    # Настройки раздела «Изображения» заменены разделом «Иллюстрации»:
    # прежние ключи больше не читаются и в панели не показываются
    op.execute(
        "DELETE FROM app_settings WHERE key IN "
        "('images_enabled', 'images_max_count', 'images_min_score')"
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS document_figures_tsv_update ON document_figures"
    )
    op.execute("DROP FUNCTION IF EXISTS document_figures_tsv_trigger()")
    op.drop_table("document_figures")
    op.execute("DROP TYPE IF EXISTS figure_kind")

    op.drop_column("documents", "figures_count")
    op.drop_column("messages", "attached_figures")
    op.add_column("messages", sa.Column("attached_images", postgresql.JSONB()))

    # Возвращаем таблицу ручных картинок в том виде, в каком её создавала
    # первая миграция
    op.create_table(
        "atlas_images",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("title", sa.String(512), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("structures_ru", postgresql.ARRAY(sa.String(255))),
        sa.Column("structures_lat", postgresql.ARRAY(sa.String(255))),
        sa.Column("section", sa.String(255)),
        sa.Column("source_title", sa.String(512)),
        sa.Column("source_authors", sa.String(512)),
        sa.Column("source_page", sa.Integer()),
        sa.Column("license_note", sa.String(512)),
        sa.Column("original_filename", sa.String(512), nullable=False),
        sa.Column("stored_path", sa.String(1024), nullable=False),
        sa.Column("thumbnail_path", sa.String(1024)),
        sa.Column("mime_type", sa.String(128)),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("width", sa.Integer()),
        sa.Column("height", sa.Integer()),
        sa.Column("content_hash", sa.String(64)),
        sa.Column("vk_attachment_id", sa.String(128)),
        sa.Column("embedding", Vector(EMBEDDING_DIM)),
        sa.Column("search_vector", postgresql.TSVECTOR()),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("extra", postgresql.JSONB()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
    )
    op.create_index("ix_atlas_images_section", "atlas_images", ["section"])
    op.create_index("ix_atlas_images_content_hash", "atlas_images", ["content_hash"])
    op.create_index("ix_atlas_images_created_at", "atlas_images", ["created_at"])
    op.execute(
        "CREATE INDEX ix_atlas_images_search ON atlas_images USING gin (search_vector)"
    )
    op.execute(
        "CREATE INDEX ix_atlas_images_embedding ON atlas_images "
        "USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64)"
    )
    op.execute(
        """
        CREATE FUNCTION atlas_images_tsv_trigger() RETURNS trigger AS $$
        BEGIN
            NEW.search_vector :=
                setweight(to_tsvector('russian', coalesce(NEW.title, '')), 'A') ||
                setweight(to_tsvector('russian',
                    coalesce(array_to_string(NEW.structures_ru, ' '), '')), 'A') ||
                setweight(to_tsvector('simple',
                    coalesce(array_to_string(NEW.structures_lat, ' '), '')), 'A') ||
                setweight(to_tsvector('russian', coalesce(NEW.description, '')), 'B');
            RETURN NEW;
        END
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER atlas_images_tsv_update
        BEFORE INSERT OR UPDATE OF title, description, structures_ru, structures_lat
        ON atlas_images
        FOR EACH ROW EXECUTE FUNCTION atlas_images_tsv_trigger();
        """
    )
