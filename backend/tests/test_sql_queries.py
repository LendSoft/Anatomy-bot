"""Проверка сырых SQL-запросов.

Ловит ошибки, которые иначе всплывают только на живой базе: неразобранные
параметры и опечатки в синтаксисе. Подключение к Postgres не требуется —
запросы компилируются под его диалект.

Отдельно проверяется приведение типов: postgres-форма `:param::type` ломает
разбор параметров в SQLAlchemy, потому что двоеточия принимаются за часть
имени. Допустим только CAST.
"""

from __future__ import annotations

import re

import pytest
from sqlalchemy import text
from sqlalchemy.dialects import postgresql

from app.rag import retriever
from app.services import stats_service

# Все сырые запросы проекта: имя -> SQL
RAW_QUERIES: dict[str, str] = {
    "retriever.vector": str(retriever._VECTOR_SQL),
    "retriever.text": str(retriever._TEXT_SQL),
}


def _module_sql(module) -> dict[str, str]:
    """Достаёт SQL-строки из вызовов text(...) в модуле."""
    import inspect

    source = inspect.getsource(module)
    return {
        f"{module.__name__}[{i}]": block
        for i, block in enumerate(re.findall(r'text\(\s*"""(.*?)"""', source, re.DOTALL))
    }


ALL_QUERIES = {**RAW_QUERIES, **_module_sql(stats_service)}


def test_queries_found():
    """Если запросы перестали находиться, тест ниже проверял бы пустоту."""
    assert len(ALL_QUERIES) >= 6


@pytest.mark.parametrize("name", sorted(ALL_QUERIES))
def test_no_postgres_cast_shorthand(name):
    """`::` рядом с параметром не даёт SQLAlchemy подставить значение."""
    sql = ALL_QUERIES[name]
    assert "::" not in sql, (
        f"В запросе {name} используется сокращение `::`. "
        f"Замените на CAST(x AS тип), иначе параметр не подставится."
    )


@pytest.mark.parametrize("name", sorted(ALL_QUERIES))
def test_compiles_for_postgres(name):
    """Запрос должен компилироваться под диалект Postgres."""
    compiled = text(ALL_QUERIES[name]).compile(dialect=postgresql.dialect())
    assert str(compiled)


def test_daily_query_binds_since():
    """Параметр :since должен распознаваться, а не уезжать в SQL как текст."""
    daily_sql = next(
        sql for name, sql in ALL_QUERIES.items()
        if "generate_series" in sql
    )
    statement = text(daily_sql)
    assert "since" in statement._bindparams, (
        "Параметр since не распознан — проверьте, нет ли рядом `::`"
    )
