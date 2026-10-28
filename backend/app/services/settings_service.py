"""Реестр настроек, которые администратор меняет из панели.

Каждая настройка описана здесь: значение по умолчанию, границы и текст
подсказки для интерфейса. Фронтенд рисует форму по этому описанию, так
что добавление нового параметра — правка одного места.

Значения кэшируются в памяти процесса на TTL, иначе на каждый вопрос
студента уходил бы лишний запрос в БД.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.setting import AppSetting

log = get_logger(__name__)

CACHE_TTL_SECONDS = 15

# Чем подменяется секрет при отдаче наружу. Если поле пришло обратно с этим
# значением, значит его не трогали — сохраняем прежний ключ.
SECRET_MASK = "••••••••"


@dataclass(frozen=True)
class SettingSpec:
    key: str
    default: Any
    # secret — ключ или токен: наружу отдаётся маской, в форме поле-пароль
    type: Literal["float", "int", "bool", "str", "text", "select", "secret"]
    label: str
    group: str
    description: str = ""
    minimum: float | None = None
    maximum: float | None = None
    step: float | None = None
    options: list[str] = field(default_factory=list)
    placeholder: str = ""
    # Из какой переменной .env берётся значение, если в панели пусто
    env_fallback: str = ""


SETTING_SPECS: list[SettingSpec] = [
    # ------------------------------------------------------ генерация
    SettingSpec(
        key="temperature", default=0.2, type="float", group="Генерация",
        label="Температура", minimum=0.0, maximum=2.0, step=0.05,
        description=(
            "Насколько модель отходит от наиболее вероятного ответа. "
            "Для фактических вопросов по анатомии держите низкой (0.1–0.3): "
            "высокая температура повышает риск выдуманных деталей."
        ),
    ),
    SettingSpec(
        key="top_p", default=0.9, type="float", group="Генерация",
        label="Top-p", minimum=0.1, maximum=1.0, step=0.05,
        description="Отсечение по суммарной вероятности токенов.",
    ),
    SettingSpec(
        key="max_tokens", default=1024, type="int", group="Генерация",
        label="Максимум токенов в ответе", minimum=128, maximum=8192, step=64,
        description="Для VK разумно 700–1200: длинные сообщения там неудобно читать.",
    ),
    SettingSpec(
        key="answer_style", default="balanced", type="select", group="Генерация",
        label="Стиль ответа", options=["short", "balanced", "detailed"],
        description="Краткий, сбалансированный или подробный ответ по умолчанию.",
    ),

    # --------------------------------------------------------- поиск
    SettingSpec(
        key="retrieval_top_k", default=20, type="int", group="Поиск",
        label="Кандидатов из базы (top-k)", minimum=1, maximum=100, step=1,
        description="Сколько фрагментов достаём на первом этапе, до реранка.",
    ),
    SettingSpec(
        key="rerank_top_n", default=5, type="int", group="Поиск",
        label="Фрагментов в контекст (top-n)", minimum=1, maximum=20, step=1,
        description="Сколько лучших фрагментов после реранка уходит в промпт.",
    ),
    SettingSpec(
        key="use_reranker", default=True, type="bool", group="Поиск",
        label="Использовать реранкер",
        description=(
            "Заметно повышает точность подбора фрагментов. Отключайте только "
            "если критична скорость."
        ),
    ),
    SettingSpec(
        key="hybrid_alpha", default=0.6, type="float", group="Поиск",
        label="Вес векторного поиска", minimum=0.0, maximum=1.0, step=0.05,
        description=(
            "0 — только полнотекстовый поиск, 1 — только векторный. "
            "Полнотекстовый лучше ловит точные латинские термины."
        ),
    ),
    SettingSpec(
        key="min_relevance_score", default=0.35, type="float", group="Поиск",
        label="Порог релевантности", minimum=0.0, maximum=1.0, step=0.01,
        description=(
            "Если лучший фрагмент набрал меньше — бот отвечает «не нашёл в базе» "
            "вместо того, чтобы додумывать. Ключевой параметр против галлюцинаций."
        ),
    ),
    SettingSpec(
        key="expand_query_with_glossary", default=True, type="bool", group="Поиск",
        label="Расширять запрос по словарю терминов",
        description=(
            "Подмешивает к запросу латинский или русский эквивалент термина. "
            "Помогает найти фрагмент, подписанный на другом языке."
        ),
    ),
    SettingSpec(
        key="max_context_chars", default=8000, type="int", group="Поиск",
        label="Максимум символов контекста", minimum=1000, maximum=40000, step=500,
        description="Ограничение суммарного размера фрагментов в промпте.",
    ),

    # ------------------------------------------------------ индексация
    SettingSpec(
        key="chunk_size", default=900, type="int", group="Индексация",
        label="Размер фрагмента (символов)", minimum=200, maximum=4000, step=50,
        description=(
            "Применяется при следующей индексации. Уже разобранные документы "
            "нужно переиндексировать вручную."
        ),
    ),
    SettingSpec(
        key="chunk_overlap", default=150, type="int", group="Индексация",
        label="Перекрытие фрагментов (символов)", minimum=0, maximum=1000, step=25,
        description="Чтобы предложение на стыке не терялось между фрагментами.",
    ),
    SettingSpec(
        key="ocr_enabled", default=True, type="bool", group="Индексация",
        label="OCR для сканов",
        description=(
            "Если в PDF нет текстового слоя, страницы распознаются tesseract. "
            "Заметно медленнее, качество нужно проверять вручную."
        ),
    ),

    # ------------------------------------------------------ иллюстрации
    SettingSpec(
        key="figures_enabled", default=True, type="bool", group="Иллюстрации",
        label="Ссылаться на изображения из материалов",
        description=(
            "Если на странице, по которой собран ответ, есть рисунок или "
            "схема, бот разберёт, что на ней обозначено, и укажет файл и "
            "страницу, где её посмотреть. Картинки берутся из самих "
            "загруженных учебников — отдельно ничего загружать не нужно."
        ),
    ),
    SettingSpec(
        key="figures_max_count", default=3, type="int", group="Иллюстрации",
        label="Максимум изображений в ответе", minimum=1, maximum=8, step=1,
        description=(
            "На странице атласа рисунок обычно один, в учебнике — до "
            "нескольких. Больше трёх в одном ответе читать неудобно."
        ),
    ),
    SettingSpec(
        key="figures_min_confidence", default=0.5, type="float", group="Иллюстрации",
        label="Порог уверенности разбора", minimum=0.0, maximum=1.0, step=0.05,
        description=(
            "Насколько надёжно найденная картинка — именно иллюстрация. "
            "0.95 ставится, когда рядом нашлась подпись «Рис. N», 0.5 — "
            "когда в файле просто картинка подходящего размера. Поднимите "
            "до 0.9, если бот ссылается на элементы оформления."
        ),
    ),
    SettingSpec(
        key="figures_page_slack", default=1, type="int", group="Иллюстрации",
        label="Захват соседних страниц", minimum=0, maximum=3, step=1,
        description=(
            "На сколько страниц вокруг найденного фрагмента искать рисунки. "
            "В учебниках иллюстрация часто стоит на соседней странице "
            "разворота, а не там, где её описывают. 0 — только страницы "
            "самого фрагмента."
        ),
    ),
    SettingSpec(
        key="figures_search_fallback", default=True, type="bool", group="Иллюстрации",
        label="Искать изображения отдельным запросом",
        description=(
            "Если на страницах ответа рисунков не нашлось, искать по "
            "подписям и обозначениям по всей базе. Нужно для атласов: там у "
            "страницы почти нет текста, кроме надписей на самом рисунке, и "
            "обычный поиск её пропускает."
        ),
    ),
    SettingSpec(
        key="figures_min_score", default=0.45, type="float", group="Иллюстрации",
        label="Порог релевантности при отдельном поиске",
        minimum=0.0, maximum=1.0, step=0.01,
        description=(
            "Применяется только к отдельному поиску изображений. Лучше не "
            "приложить картинку, чем приложить не ту."
        ),
    ),

    # ------------------------------------------------------------ LLM
    SettingSpec(
        key="llm_provider_override", default="", type="select", group="Языковая модель",
        label="Кто формирует ответ",
        options=["", "ollama", "gigachat"],
        description=(
            "Оставьте пустым, чтобы использовать то, что задано на сервере "
            "в файле .env — это обычный режим. Выбирайте вручную, только когда "
            "нужно временно переключиться: например, работать на GigaChat, "
            "пока сервер с видеокартой не готов."
        ),
    ),
    SettingSpec(
        key="llm_model_override", default="", type="str", group="Языковая модель",
        label="Название модели",
        placeholder="оставьте пустым",
        description=(
            "Какую именно модель просить сформировать ответ. Пустое поле — "
            "взять ту, что указана на сервере; в большинстве случаев так и надо. "
            "Заполняйте, только если хотите другую модель у того же провайдера. "
            "Имя зависит от провайдера: у Ollama — короткое имя из ollama pull "
            "(qwen3:8b), у GigaChat — GigaChat-2, GigaChat-2-Pro или "
            "GigaChat-2-Max. Модель должна быть заранее загружена на сервер: "
            "произвольное имя её не скачает, а приведёт к ошибке генерации."
        ),
    ),
    SettingSpec(
        key="fallback_on_error", default=True, type="bool", group="Языковая модель",
        label="Подстраховка резервным провайдером",
        description=(
            "Если основная модель не ответила — сервер с видеокартой выключен, "
            "перегружен или упал, — ответ сформирует GigaChat. В логах такой "
            "ответ помечен провайдером gigachat."
        ),
    ),

    # ------------------------------------------------------- GigaChat
    SettingSpec(
        key="gigachat_auth_key", default="", type="secret", group="GigaChat",
        label="Ключ авторизации",
        env_fallback="GIGACHAT_AUTH_KEY",
        placeholder="строка из личного кабинета Сбера",
        description=(
            "developers.sber.ru/studio → ваш проект GigaChat API → «Получить ключ» "
            "→ поле «Авторизационные данные». Это одна длинная строка, а не пара "
            "логин-пароль. Ключ сохраняется в базе и подменяется точками при "
            "показе; чтобы заменить — впишите новый, чтобы оставить — не трогайте."
        ),
    ),
    SettingSpec(
        key="gigachat_scope", default="", type="select", group="GigaChat",
        label="Тип доступа",
        options=["", "GIGACHAT_API_PERS", "GIGACHAT_API_B2B", "GIGACHAT_API_CORP"],
        env_fallback="GIGACHAT_SCOPE",
        description=(
            "PERS — для физических лиц, B2B — для ИП и юрлиц по предоплате, "
            "CORP — корпоративный доступ. Неверный тип даёт ошибку авторизации. "
            "Пусто — брать из настроек сервера."
        ),
    ),
    SettingSpec(
        key="gigachat_model", default="", type="select", group="GigaChat",
        label="Модель GigaChat",
        options=["", "GigaChat-2", "GigaChat-2-Pro", "GigaChat-2-Max"],
        env_fallback="GIGACHAT_MODEL",
        description=(
            "Pro и Max отвечают точнее, но дороже и медленнее. Для вопросов по "
            "готовым фрагментам учебника обычно достаточно обычной GigaChat-2. "
            "Пусто — брать из настроек сервера."
        ),
    ),

    # --------------------------------------------------- приветствие
    SettingSpec(
        key="greeting_enabled", default=True, type="bool", group="Приветствие",
        label="Отвечать на приветствия отдельным сообщением",
        description=(
            "«Привет», «добрый день» и подобные — бот сразу отправит текст ниже, "
            "не пытаясь искать ответ в базе материалов."
        ),
    ),
    SettingSpec(
        key="greeting_message", type="text", group="Приветствие",
        label="Текст приветствия",
        default=(
            "Здравствуйте! Я помогу разобраться в анатомии человека.\n\n"
            "Задайте вопрос своими словами, например:\n"
            "• Какие ветви имеет наружная сонная артерия?\n"
            "• Расскажи строение плечевой кости\n"
            "• Что проходит через яремное отверстие?\n\n"
            "Отвечаю только по учебным материалам кафедры и всегда указываю "
            "источник. Если нужных сведений в базе нет, я скажу об этом прямо, "
            "а не буду додумывать."
        ),
    ),

    # ------------------------------------------------------- ВКонтакте
    SettingSpec(
        key="vk_enabled", default=False, type="bool", group="ВКонтакте",
        label="Бот отвечает студентам",
        description=(
            "Выключите, чтобы приостановить работу бота, не останавливая сервер. "
            "Изменение подхватывается в течение минуты."
        ),
    ),
    SettingSpec(
        key="vk_group_token", default="", type="secret", group="ВКонтакте",
        label="Ключ доступа сообщества",
        env_fallback="VK_GROUP_TOKEN",
        placeholder="vk1.a....",
        description=(
            "Сообщество → Управление → Работа с API → Ключи доступа → создать "
            "ключ с правами «Сообщения сообщества». Там же, в разделе Long Poll API, "
            "включите его и отметьте событие «Входящее сообщение»."
        ),
    ),
    SettingSpec(
        key="vk_group_id", default="", type="str", group="ВКонтакте",
        label="ID сообщества",
        env_fallback="VK_GROUP_ID",
        placeholder="123456789",
        description=(
            "Только цифры, без минуса и без слова club. Виден в адресе страницы "
            "или в разделе «Управление → Адрес страницы»."
        ),
    ),

    # ---------------------------------------------------------- лимиты
    SettingSpec(
        key="rate_limit_per_minute", default=10, type="int", group="Лимиты",
        label="Запросов в минуту с пользователя", minimum=1, maximum=120, step=1,
    ),
    SettingSpec(
        key="history_turns", default=3, type="int", group="Лимиты",
        label="Реплик истории диалога", minimum=0, maximum=10, step=1,
        description="Сколько предыдущих пар вопрос-ответ передавать модели.",
    ),
]

SPECS_BY_KEY = {spec.key: spec for spec in SETTING_SPECS}
DEFAULTS = {spec.key: spec.default for spec in SETTING_SPECS}

_cache: dict[str, Any] = {}
_cache_ts: float = 0.0


def _validate(spec: SettingSpec, value: Any) -> Any:
    """Приводит значение к типу и зажимает в допустимые границы."""
    if spec.type == "bool":
        return bool(value)
    if spec.type == "secret":
        return str(value).strip()
    if spec.type == "int":
        value = int(value)
    elif spec.type == "float":
        value = float(value)
    elif spec.type == "select":
        value = str(value)
        if spec.options and value not in spec.options:
            raise ValueError(f"Недопустимое значение для «{spec.label}»: {value}")
        return value
    else:
        return str(value)

    if spec.minimum is not None:
        value = max(spec.minimum, value)
    if spec.maximum is not None:
        value = min(spec.maximum, value)
    return int(value) if spec.type == "int" else value


async def get_all(db: AsyncSession, *, use_cache: bool = True) -> dict[str, Any]:
    """Все настройки: значения из БД поверх значений по умолчанию."""
    global _cache_ts

    if use_cache and _cache and (time.monotonic() - _cache_ts) < CACHE_TTL_SECONDS:
        return dict(_cache)

    rows = (await db.execute(select(AppSetting))).scalars().all()
    values = dict(DEFAULTS)
    for row in rows:
        if row.key in SPECS_BY_KEY:
            # value хранится как {"v": ...} — JSONB требует объект верхнего уровня
            values[row.key] = row.value.get("v")

    _cache.clear()
    _cache.update(values)
    _cache_ts = time.monotonic()
    return dict(values)


async def get(db: AsyncSession, key: str) -> Any:
    return (await get_all(db)).get(key, DEFAULTS.get(key))


SECRET_KEYS = {spec.key for spec in SETTING_SPECS if spec.type == "secret"}


async def get_all_masked(db: AsyncSession) -> dict[str, Any]:
    """Значения для панели: ключи и токены подменены точками.

    Отдавать секреты в браузер незачем — админ и так знает, что вводил,
    а вот утечь через историю запросов или скриншот они могут запросто.
    """
    values = await get_all(db, use_cache=False)
    for key in SECRET_KEYS:
        if values.get(key):
            values[key] = SECRET_MASK
    return values


def resolve(values: dict[str, Any], key: str, env_value: Any = None) -> Any:
    """Значение из панели, а если там пусто — из переменных окружения.

    Панель приоритетнее: она правится без перезапуска контейнера.
    """
    value = values.get(key)
    if isinstance(value, str):
        value = value.strip()
    return value if value else env_value


async def update_many(
    db: AsyncSession, updates: dict[str, Any], updated_by: str | None = None
) -> dict[str, Any]:
    unknown = set(updates) - set(SPECS_BY_KEY)
    if unknown:
        raise ValueError(f"Неизвестные настройки: {', '.join(sorted(unknown))}")

    for key, raw in updates.items():
        spec = SPECS_BY_KEY[key]

        # Поле секрета вернулось нетронутым — значит менять его не просили
        if spec.type == "secret" and isinstance(raw, str) and raw.strip() == SECRET_MASK:
            continue

        value = _validate(spec, raw)
        stmt = (
            insert(AppSetting)
            .values(key=key, value={"v": value}, description=spec.label, updated_by=updated_by)
            .on_conflict_do_update(
                index_elements=[AppSetting.key],
                set_={"value": {"v": value}, "updated_by": updated_by},
            )
        )
        await db.execute(stmt)

    await db.commit()
    invalidate_cache()
    log.info("settings_updated", keys=sorted(updates), by=updated_by)
    return await get_all(db, use_cache=False)


def invalidate_cache() -> None:
    """Сбрасывает кэш. Вызывается после записи; в других процессах
    актуальность обеспечивается коротким TTL."""
    global _cache_ts
    _cache.clear()
    _cache_ts = 0.0


def describe() -> list[dict[str, Any]]:
    """Описание всех настроек для построения формы на фронтенде."""
    return [
        {
            "key": s.key,
            "type": s.type,
            "label": s.label,
            "group": s.group,
            "description": s.description,
            "default": s.default,
            "min": s.minimum,
            "max": s.maximum,
            "step": s.step,
            "options": s.options,
            "placeholder": s.placeholder,
            "env_fallback": s.env_fallback,
        }
        for s in SETTING_SPECS
    ]
