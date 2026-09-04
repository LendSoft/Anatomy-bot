"""Начальная схема базы данных

Revision ID: 0001
Revises:
Create Date: 2026-09-04
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EMBEDDING_DIM = 1024  # BAAI/bge-m3

# Перечень типов и их значений. Создаются ниже отдельным блоком,
# поэтому здесь create_type=False — иначе create_table попытается создать
# тип повторно и миграция упадёт на «type already exists».
ENUM_VALUES: dict[str, tuple[str, ...]] = {
    "document_status": ("pending", "parsing", "chunking", "embedding", "ready", "failed"),
    "prompt_kind": ("system", "reference_answers", "query_rewrite", "judge"),
    "chat_channel": ("vk", "web", "test"),
    "message_role": ("user", "assistant"),
    "answer_status": ("answered", "refused", "error", "rate_limited"),
    "run_status": ("pending", "running", "completed", "failed"),
}

document_status = postgresql.ENUM(name="document_status", create_type=False)
prompt_kind = postgresql.ENUM(name="prompt_kind", create_type=False)
chat_channel = postgresql.ENUM(name="chat_channel", create_type=False)
message_role = postgresql.ENUM(name="message_role", create_type=False)
answer_status = postgresql.ENUM(name="answer_status", create_type=False)
run_status = postgresql.ENUM(name="run_status", create_type=False)


def upgrade() -> None:
    # pgvector — векторный поиск, pg_trgm — нечёткий поиск по терминам
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    # Создаём типы идемпотентно. Если предыдущая попытка миграции упала
    # на полпути, типы могли остаться — повтор не должен на этом спотыкаться.
    for name, values in ENUM_VALUES.items():
        literals = ", ".join(f"'{v}'" for v in values)
        op.execute(
            f"""
            DO $$ BEGIN
                CREATE TYPE {name} AS ENUM ({literals});
            EXCEPTION WHEN duplicate_object THEN NULL;
            END $$;
            """
        )

    # ------------------------------------------------------------ admin_users
    op.create_table(
        "admin_users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("email", sa.String(255), nullable=False, unique=True),
        sa.Column("hashed_password", sa.String(255), nullable=False),
        sa.Column("full_name", sa.String(255)),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("is_superuser", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("last_login_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
    )
    op.create_index("ix_admin_users_email", "admin_users", ["email"])
    op.create_index("ix_admin_users_created_at", "admin_users", ["created_at"])

    # -------------------------------------------------------------- vk_users
    op.create_table(
        "vk_users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("vk_id", sa.BigInteger(), nullable=False, unique=True),
        sa.Column("first_name", sa.String(128)),
        sa.Column("last_name", sa.String(128)),
        sa.Column("is_blocked", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("messages_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_seen_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
    )
    op.create_index("ix_vk_users_vk_id", "vk_users", ["vk_id"])
    op.create_index("ix_vk_users_created_at", "vk_users", ["created_at"])

    # ---------------------------------------------------------- app_settings
    op.create_table(
        "app_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("key", sa.String(128), nullable=False, unique=True),
        sa.Column("value", postgresql.JSONB(), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("updated_by", sa.String(255)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
    )
    op.create_index("ix_app_settings_key", "app_settings", ["key"])
    op.create_index("ix_app_settings_created_at", "app_settings", ["created_at"])

    # --------------------------------------------------------------- prompts
    op.create_table(
        "prompts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("kind", prompt_kind, nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("name", sa.String(255)),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("examples", postgresql.JSONB()),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_by", sa.String(255)),
        sa.Column("comment", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
    )
    op.create_index("ix_prompts_kind", "prompts", ["kind"])
    op.create_index("ix_prompts_created_at", "prompts", ["created_at"])
    op.create_index("ix_prompts_kind_version", "prompts", ["kind", "version"], unique=True)
    op.create_index(
        "ix_prompts_kind_active", "prompts", ["kind"],
        unique=True, postgresql_where=sa.text("is_active"),
    )

    # --------------------------------------------------------- anatomy_terms
    op.create_table(
        "anatomy_terms",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("term_ru", sa.String(255), nullable=False),
        sa.Column("term_lat", sa.String(255)),
        sa.Column("synonyms", postgresql.ARRAY(sa.String(255))),
        sa.Column("section", sa.String(255)),
        sa.Column("definition", sa.Text()),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
    )
    op.create_index("ix_anatomy_terms_term_ru", "anatomy_terms", ["term_ru"])
    op.create_index("ix_anatomy_terms_term_lat", "anatomy_terms", ["term_lat"])
    op.create_index("ix_anatomy_terms_section", "anatomy_terms", ["section"])
    op.create_index("ix_anatomy_terms_created_at", "anatomy_terms", ["created_at"])
    op.create_index("ix_anatomy_terms_ru_lat", "anatomy_terms", ["term_ru", "term_lat"],
                    unique=True)
    op.execute(
        "CREATE INDEX ix_anatomy_terms_ru_trgm ON anatomy_terms "
        "USING gin (term_ru gin_trgm_ops)"
    )

    # ------------------------------------------------------------- documents
    op.create_table(
        "documents",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("title", sa.String(512), nullable=False),
        sa.Column("authors", sa.String(512)),
        sa.Column("edition", sa.String(255)),
        sa.Column("year", sa.Integer()),
        sa.Column("section", sa.String(255)),
        sa.Column("original_filename", sa.String(512), nullable=False),
        sa.Column("stored_path", sa.String(1024), nullable=False),
        sa.Column("mime_type", sa.String(128)),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("content_hash", sa.String(64)),
        sa.Column("status", document_status, nullable=False, server_default="pending"),
        sa.Column("error_message", sa.Text()),
        sa.Column("progress", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("pages_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("chunks_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("indexed_at", sa.DateTime(timezone=True)),
        sa.Column("extra", postgresql.JSONB()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
    )
    op.create_index("ix_documents_section", "documents", ["section"])
    op.create_index("ix_documents_status", "documents", ["status"])
    op.create_index("ix_documents_content_hash", "documents", ["content_hash"])
    op.create_index("ix_documents_created_at", "documents", ["created_at"])

    # -------------------------------------------------------- document_chunks
    op.create_table(
        "document_chunks",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("document_id", sa.Integer(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("heading", sa.String(512)),
        sa.Column("page_from", sa.Integer()),
        sa.Column("page_to", sa.Integer()),
        sa.Column("token_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("embedding", Vector(EMBEDDING_DIM)),
        sa.Column("search_vector", postgresql.TSVECTOR()),
        sa.Column("extra", postgresql.JSONB()),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_document_chunks_document_id", "document_chunks", ["document_id"])
    op.create_index("ix_document_chunks_doc_idx", "document_chunks",
                    ["document_id", "chunk_index"], unique=True)
    op.execute(
        "CREATE INDEX ix_document_chunks_search ON document_chunks "
        "USING gin (search_vector)"
    )
    op.execute(
        "CREATE INDEX ix_document_chunks_embedding ON document_chunks "
        "USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64)"
    )

    # ----------------------------------------------------------- atlas_images
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

    # ---------------------------------------------------------- conversations
    op.create_table(
        "conversations",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("channel", chat_channel, nullable=False),
        sa.Column("external_id", sa.String(128), nullable=False),
        sa.Column("vk_user_id", sa.Integer()),
        sa.Column("title", sa.String(512)),
        sa.Column("last_message_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["vk_user_id"], ["vk_users.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_conversations_channel", "conversations", ["channel"])
    op.create_index("ix_conversations_external_id", "conversations", ["external_id"])
    op.create_index("ix_conversations_vk_user_id", "conversations", ["vk_user_id"])
    op.create_index("ix_conversations_last_message_at", "conversations", ["last_message_at"])
    op.create_index("ix_conversations_created_at", "conversations", ["created_at"])
    op.create_index("ix_conversations_channel_ext", "conversations",
                    ["channel", "external_id"])

    # -------------------------------------------------------------- messages
    op.create_table(
        "messages",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("conversation_id", sa.BigInteger(), nullable=False),
        sa.Column("role", message_role, nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("status", answer_status),
        sa.Column("retrieved_chunks", postgresql.JSONB()),
        sa.Column("attached_images", postgresql.JSONB()),
        sa.Column("generation_params", postgresql.JSONB()),
        sa.Column("prompt_version", sa.Integer()),
        sa.Column("llm_provider", sa.String(64)),
        sa.Column("llm_model", sa.String(255)),
        sa.Column("prompt_tokens", sa.Integer()),
        sa.Column("completion_tokens", sa.Integer()),
        sa.Column("retrieval_ms", sa.Integer()),
        sa.Column("generation_ms", sa.Integer()),
        sa.Column("total_ms", sa.Integer()),
        sa.Column("top_score", sa.Float()),
        sa.Column("error_message", sa.Text()),
        sa.Column("feedback", sa.Integer()),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_messages_conversation_id", "messages", ["conversation_id"])
    op.create_index("ix_messages_created_at", "messages", ["created_at"])
    op.create_index("ix_messages_conv_created", "messages", ["conversation_id", "created_at"])
    op.create_index("ix_messages_status_created", "messages", ["status", "created_at"])

    # ------------------------------------------------------------- test_sets
    op.create_table(
        "test_sets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("section", sa.String(255)),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
    )
    op.create_index("ix_test_sets_created_at", "test_sets", ["created_at"])

    op.create_table(
        "test_questions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("test_set_id", sa.Integer(), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("reference_answer", sa.Text()),
        sa.Column("expected_source", sa.String(512)),
        sa.Column("should_refuse", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("tags", postgresql.JSONB()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["test_set_id"], ["test_sets.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_test_questions_test_set_id", "test_questions", ["test_set_id"])
    op.create_index("ix_test_questions_created_at", "test_questions", ["created_at"])

    op.create_table(
        "test_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("test_set_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(255)),
        sa.Column("status", run_status, nullable=False, server_default="pending"),
        sa.Column("settings_snapshot", postgresql.JSONB()),
        sa.Column("prompt_version", sa.Integer()),
        sa.Column("llm_model", sa.String(255)),
        sa.Column("total_questions", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("completed_questions", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("avg_score", sa.Float()),
        sa.Column("refusal_rate", sa.Float()),
        sa.Column("avg_latency_ms", sa.Float()),
        sa.Column("error_message", sa.Text()),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["test_set_id"], ["test_sets.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_test_runs_test_set_id", "test_runs", ["test_set_id"])
    op.create_index("ix_test_runs_status", "test_runs", ["status"])
    op.create_index("ix_test_runs_created_at", "test_runs", ["created_at"])

    op.create_table(
        "test_results",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("question_id", sa.Integer(), nullable=False),
        sa.Column("answer", sa.Text()),
        sa.Column("refused", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("retrieved_chunks", postgresql.JSONB()),
        sa.Column("top_score", sa.Float()),
        sa.Column("latency_ms", sa.Integer()),
        sa.Column("judge_score", sa.Float()),
        sa.Column("judge_comment", sa.Text()),
        sa.Column("manual_score", sa.Float()),
        sa.Column("manual_comment", sa.Text()),
        sa.Column("error_message", sa.Text()),
        sa.ForeignKeyConstraint(["run_id"], ["test_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["question_id"], ["test_questions.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_test_results_run_id", "test_results", ["run_id"])
    op.create_index("ix_test_results_question_id", "test_results", ["question_id"])
    op.create_index("ix_test_results_run_question", "test_results",
                    ["run_id", "question_id"], unique=True)

    # ---------------------------------------------------------------- триггеры
    # search_vector поддерживается на стороне БД: так он остаётся корректным
    # независимо от того, каким путём была записана строка.
    # Заголовок весит больше тела ('A' против 'B') — совпадение по названию
    # раздела важнее случайного упоминания термина в тексте.
    op.execute(
        """
        CREATE FUNCTION document_chunks_tsv_trigger() RETURNS trigger AS $$
        BEGIN
            NEW.search_vector :=
                setweight(to_tsvector('russian', coalesce(NEW.heading, '')), 'A') ||
                setweight(to_tsvector('russian', coalesce(NEW.content, '')), 'B');
            RETURN NEW;
        END
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER document_chunks_tsv_update
        BEFORE INSERT OR UPDATE OF content, heading ON document_chunks
        FOR EACH ROW EXECUTE FUNCTION document_chunks_tsv_trigger();
        """
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


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS atlas_images_tsv_update ON atlas_images")
    op.execute("DROP FUNCTION IF EXISTS atlas_images_tsv_trigger()")
    op.execute("DROP TRIGGER IF EXISTS document_chunks_tsv_update ON document_chunks")
    op.execute("DROP FUNCTION IF EXISTS document_chunks_tsv_trigger()")

    for table in ("test_results", "test_runs", "test_questions", "test_sets",
                  "messages", "conversations", "atlas_images", "document_chunks",
                  "documents", "anatomy_terms", "prompts", "app_settings",
                  "vk_users", "admin_users"):
        op.drop_table(table)

    for name in ENUM_VALUES:
        op.execute(f"DROP TYPE IF EXISTS {name}")
