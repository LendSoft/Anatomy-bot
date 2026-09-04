"""Тесты валидации runtime-настроек.

Значения приходят из формы админки, поэтому важно, что выход за границы
зажимается, а не сохраняется как есть: температура 99 сделала бы ответы
бессмысленными.
"""

from __future__ import annotations

import pytest

from app.services import settings_service as s


def test_all_specs_have_defaults():
    assert set(s.DEFAULTS) == {spec.key for spec in s.SETTING_SPECS}


def test_describe_covers_every_spec():
    described = s.describe()
    assert len(described) == len(s.SETTING_SPECS)
    assert all(item["label"] and item["group"] for item in described)


@pytest.mark.parametrize(
    ("key", "raw", "expected"),
    [
        ("temperature", 99, 2.0),        # выше максимума
        ("temperature", -5, 0.0),        # ниже минимума
        ("temperature", "0.35", 0.35),   # строка из формы
        ("retrieval_top_k", "7", 7),     # приведение к int
        ("retrieval_top_k", 500, 100),   # зажим сверху
        ("use_reranker", "", False),
        ("use_reranker", 1, True),
    ],
)
def test_validation_clamps_and_casts(key, raw, expected):
    assert s._validate(s.SPECS_BY_KEY[key], raw) == expected


def test_unknown_select_value_rejected():
    with pytest.raises(ValueError, match="Недопустимое значение"):
        s._validate(s.SPECS_BY_KEY["answer_style"], "нечто")


def test_provider_options_include_gigachat():
    options = s.SPECS_BY_KEY["llm_provider_override"].options
    assert "gigachat" in options
    # Пустое значение означает «брать из переменных окружения»
    assert "" in options


def test_min_relevance_score_is_in_unit_range():
    """Порог сравнивается с нормализованной оценкой, диапазон должен быть [0, 1]."""
    spec = s.SPECS_BY_KEY["min_relevance_score"]
    assert spec.minimum == 0.0
    assert spec.maximum == 1.0
