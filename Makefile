# Частые команды. Требуется Docker Compose v2.
# В Windows запускать из Git Bash или WSL, либо выполнять команды вручную.

COMPOSE_DEV  := docker compose
COMPOSE_PROD := docker compose -f docker-compose.yml -f docker-compose.prod.yml

# BuildKit по умолчанию добавляет к образу attestation-манифесты. При
# повторной сборке уже существующего образа это ломается ошибкой
# «image ...: already exists» (Docker Desktop с containerd image store).
# Проекту эти манифесты не нужны — отключаем.
export BUILDX_NO_DEFAULT_ATTESTATIONS = 1

.PHONY: help init venv test lint up up-gpu down logs ps migrate revision \
        shell-api shell-db prod-up prod-down prod-logs prod-migrate \
        gigachat-ca backup restore clean

help:
	@echo "init         — создать .env из шаблона"
	@echo "venv         — локальное окружение Python для IDE и тестов"
	@echo "test         — прогнать тесты"
	@echo "lint         — проверить код линтером"
	@echo "up           — поднять окружение разработки (без GPU-контейнера)"
	@echo "up-gpu       — то же плюс локальная LLM на vLLM"
	@echo "down         — остановить"
	@echo "logs         — логи всех сервисов"
	@echo "migrate      — применить миграции"
	@echo "revision m=  — создать миграцию: make revision m='добавил поле'"
	@echo "gigachat-ca  — скачать сертификат НУЦ Минцифры для GigaChat"
	@echo "prod-up      — прод-сборка и запуск"
	@echo "backup       — дамп базы в backups/"

init:
	@test -f .env || (cp .env.example .env && echo "Создан .env — заполните пароли и токены")

venv:
	cd backend && python -m venv .venv && \
	 (.venv/Scripts/python.exe -m pip install -r requirements.txt -r requirements-dev.txt || \
	  .venv/bin/python -m pip install -r requirements.txt -r requirements-dev.txt)

test:
	cd backend && .venv/Scripts/python.exe -m pytest 2>/dev/null || \
	 (cd backend && .venv/bin/python -m pytest)

lint:
	cd backend && .venv/Scripts/python.exe -m ruff check app tests 2>/dev/null || \
	 (cd backend && .venv/bin/python -m ruff check app tests)

gigachat-ca:
	bash deploy/install-russian-ca.sh

up:
	$(COMPOSE_DEV) up -d --build

up-gpu:
	$(COMPOSE_DEV) --profile gpu up -d --build

down:
	$(COMPOSE_DEV) down

logs:
	$(COMPOSE_DEV) logs -f --tail=100

ps:
	$(COMPOSE_DEV) ps

migrate:
	$(COMPOSE_DEV) exec api alembic upgrade head

revision:
	$(COMPOSE_DEV) exec api alembic revision --autogenerate -m "$(m)"

shell-api:
	$(COMPOSE_DEV) exec api bash

shell-db:
	$(COMPOSE_DEV) exec postgres psql -U $${POSTGRES_USER:-anatomy} -d $${POSTGRES_DB:-anatomy}

prod-up:
	$(COMPOSE_PROD) --profile gpu up -d --build

prod-down:
	$(COMPOSE_PROD) down

prod-logs:
	$(COMPOSE_PROD) logs -f --tail=100

prod-migrate:
	$(COMPOSE_PROD) exec api alembic upgrade head

backup:
	@mkdir -p backups
	$(COMPOSE_DEV) exec -T postgres pg_dump -U $${POSTGRES_USER:-anatomy} $${POSTGRES_DB:-anatomy} \
		| gzip > backups/anatomy-$$(date +%Y%m%d-%H%M%S).sql.gz
	@echo "Дамп сохранён в backups/"

# Восстановление: make restore f=backups/anatomy-20260904-120000.sql.gz
restore:
	gunzip -c $(f) | $(COMPOSE_DEV) exec -T postgres psql -U $${POSTGRES_USER:-anatomy} -d $${POSTGRES_DB:-anatomy}

clean:
	$(COMPOSE_DEV) down -v
	@echo "Контейнеры и тома удалены"
