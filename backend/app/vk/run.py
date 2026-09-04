"""VK-бот в режиме Long Poll.

Запуск: python -m app.vk.run

Токен, идентификатор сообщества и признак «бот включён» берутся из
админ-панели, а если там пусто — из переменных окружения. Настройки
перечитываются на ходу, поэтому включить бота или заменить токен можно
без перезапуска контейнера.

Сообщения обрабатываются параллельно, но с ограничением: локальная модель
одна на всех, и без ограничителя очередь к ней растёт быстрее, чем
разбирается.
"""

from __future__ import annotations

import asyncio
import contextlib
import signal
from typing import Any

import httpx
import redis.asyncio as aioredis

from app.core.config import settings
from app.core.logging import get_logger, setup_logging
from app.db.session import db_session
from app.services import settings_service
from app.vk.api import VkApi, VkError
from app.vk.handlers import handle_message, parse_event

setup_logging()
log = get_logger("vkbot")

MAX_CONCURRENT_ANSWERS = 4
RECONNECT_DELAY_SECONDS = 5
# Как часто перечитывать настройки, пока бот выключен или не настроен
CONFIG_POLL_SECONDS = 30


async def load_vk_config() -> tuple[bool, str, str]:
    """Возвращает (включён, токен, id сообщества).

    Значения из панели приоритетнее: их меняют чаще и без доступа к серверу.
    """
    try:
        async with db_session() as db:
            values = await settings_service.get_all(db, use_cache=False)
    except Exception as exc:  # noqa: BLE001 — база может быть ещё не поднята
        log.warning("vk_config_from_env", reason=str(exc))
        return settings.vk_enabled, settings.vk_group_token or "", settings.vk_group_id or ""

    enabled = bool(settings_service.resolve(values, "vk_enabled", settings.vk_enabled))
    token = settings_service.resolve(values, "vk_group_token", settings.vk_group_token) or ""
    group_id = settings_service.resolve(values, "vk_group_id", settings.vk_group_id) or ""
    return enabled, str(token), str(group_id)


class LongPollBot:
    def __init__(self) -> None:
        # Токен подставляется при подключении: он может смениться в панели
        self.vk = VkApi("")
        self.redis = aioredis.from_url(settings.redis_url, decode_responses=True)
        self.semaphore = asyncio.Semaphore(MAX_CONCURRENT_ANSWERS)
        self.client = httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=10.0))
        self.running = True
        self._tasks: set[asyncio.Task] = set()

    async def _process(self, peer_id: int, from_id: int, text: str) -> None:
        async with self.semaphore:
            try:
                async with db_session() as db:
                    await handle_message(db, self.redis, self.vk, peer_id, from_id, text)
            except Exception:  # noqa: BLE001 — один сбойный вопрос не должен ронять бота
                log.exception("vk_message_failed", peer_id=peer_id)
                with contextlib.suppress(Exception):
                    await self.vk.send_message(
                        peer_id,
                        "Не удалось обработать вопрос из-за технической ошибки. "
                        "Попробуйте повторить чуть позже.",
                    )

    def _spawn(self, coro) -> None:
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _poll_once(self, server: dict[str, Any], ts: str) -> tuple[str, list[dict]]:
        response = await self.client.get(
            server["server"],
            params={"act": "a_check", "key": server["key"], "ts": ts, "wait": 25},
        )
        response.raise_for_status()
        data = response.json()

        # failed=1 — устарел ts, 2/3 — истёк ключ, нужен новый сервер
        failed = data.get("failed")
        if failed == 1:
            return str(data["ts"]), []
        if failed in (2, 3):
            raise ConnectionError("Ключ Long Poll устарел")

        return str(data.get("ts", ts)), data.get("updates", [])

    async def run(self) -> None:
        log.info("vk_bot_starting")
        waiting_logged = False

        while self.running:
            enabled, token, group_id = await load_vk_config()

            # Пока бот выключен или не настроен — ждём, не занимая VK-соединение.
            # Так его можно включить прямо из панели, не трогая сервер.
            if not enabled or not token or not group_id:
                if not waiting_logged:
                    log.info(
                        "vk_waiting_for_config",
                        enabled=enabled,
                        has_token=bool(token),
                        has_group_id=bool(group_id),
                    )
                    waiting_logged = True
                await asyncio.sleep(CONFIG_POLL_SECONDS)
                continue

            waiting_logged = False
            self.vk.token = token

            try:
                server = await self.vk.get_long_poll_server(group_id)
                ts = str(server["ts"])
                log.info("vk_longpoll_connected")

                while self.running:
                    ts, updates = await self._poll_once(server, ts)
                    for event in updates:
                        parsed = parse_event(event)
                        if parsed:
                            self._spawn(self._process(*parsed))

                    # Проверяем, не выключили ли бота и не сменили ли токен
                    enabled, new_token, new_group_id = await load_vk_config()
                    if not enabled or new_token != token or new_group_id != group_id:
                        log.info("vk_config_changed_reconnect", enabled=enabled)
                        break

            except (ConnectionError, httpx.HTTPError) as exc:
                if not self.running:
                    break
                log.warning("vk_longpoll_reconnect", error=str(exc))
                await asyncio.sleep(RECONNECT_DELAY_SECONDS)
            except VkError as exc:
                log.error("vk_api_error", error=str(exc))
                # Неверный токен исправляется только вручную — частые
                # повторы лишь упрутся в лимиты VK
                await asyncio.sleep(30)
            except asyncio.CancelledError:
                break
            except Exception:  # noqa: BLE001
                log.exception("vk_longpoll_unexpected_error")
                await asyncio.sleep(RECONNECT_DELAY_SECONDS)

    async def shutdown(self) -> None:
        self.running = False
        if self._tasks:
            log.info("vk_waiting_for_tasks", count=len(self._tasks))
            await asyncio.gather(*self._tasks, return_exceptions=True)

        await self.client.aclose()
        await self.vk.close()
        await self.redis.aclose()
        log.info("vk_bot_stopped")


async def main() -> None:
    # Бот сам ждёт, пока его включат в панели, — отдельная ветка простоя
    # больше не нужна
    bot = LongPollBot()
    loop = asyncio.get_running_loop()

    stop = asyncio.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, stop.set)

    runner = asyncio.create_task(bot.run())
    await stop.wait()

    runner.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await runner
    await bot.shutdown()


if __name__ == "__main__":
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(main())
