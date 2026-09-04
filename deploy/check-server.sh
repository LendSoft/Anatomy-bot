#!/usr/bin/env bash
# Проверка сервера перед развёртыванием.
#
# Запуск на сервере из корня проекта:
#   bash deploy/check-server.sh
#
# Ничего не устанавливает и не меняет — только сообщает, что готово,
# а что нужно доделать.

set -uo pipefail

ok()   { echo "  [ OK ] $1"; }
warn() { echo "  [ !! ] $1"; }
fail() { echo "  [ХХХХ] $1"; PROBLEMS=$((PROBLEMS + 1)); }

PROBLEMS=0

echo "=== Docker ==="
if command -v docker >/dev/null 2>&1; then
    ok "docker установлен: $(docker --version | cut -d, -f1)"
    if docker info >/dev/null 2>&1; then
        ok "демон запущен"
    else
        fail "демон не отвечает — запустите: sudo systemctl start docker"
    fi
    if docker compose version >/dev/null 2>&1; then
        ok "compose v2: $(docker compose version --short)"
    else
        fail "нет плагина docker compose v2"
    fi
else
    fail "docker не установлен"
fi

echo
echo "=== Видеокарта ==="
if command -v nvidia-smi >/dev/null 2>&1; then
    nvidia-smi --query-gpu=name,memory.total,driver_version \
               --format=csv,noheader 2>/dev/null | while read -r line; do
        ok "$line"
    done

    # Без NVIDIA Container Toolkit контейнер карту не увидит,
    # даже если на хосте она работает
    if docker run --rm --gpus all nvidia/cuda:12.4.0-base-ubuntu22.04 \
            nvidia-smi >/dev/null 2>&1; then
        ok "контейнеры видят GPU (NVIDIA Container Toolkit работает)"
    else
        fail "контейнеры НЕ видят GPU — нужен nvidia-container-toolkit"
        echo "         https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html"
    fi
else
    warn "nvidia-smi не найден — vLLM не запустится"
    warn "работайте на GigaChat или Ollama (профиль ollama)"
fi

echo
echo "=== Ресурсы ==="
if command -v free >/dev/null 2>&1; then
    RAM_GB=$(free -g | awk '/^Mem:/{print $2}')
    if [ "${RAM_GB:-0}" -ge 16 ]; then
        ok "оперативная память: ${RAM_GB} ГБ"
    else
        warn "оперативной памяти ${RAM_GB} ГБ — эмбеддингам на CPU нужно 8+ ГБ"
    fi
fi

DISK_GB=$(df -BG . 2>/dev/null | awk 'NR==2{gsub("G","",$4); print $4}')
if [ "${DISK_GB:-0}" -ge 60 ]; then
    ok "свободно на диске: ${DISK_GB} ГБ"
else
    warn "свободно ${DISK_GB} ГБ — образы и веса моделей занимают около 40 ГБ"
fi

echo
echo "=== Конфигурация ==="
if [ -f .env ]; then
    ok "файл .env на месте"

    check_var() {
        local name="$1" placeholder="$2"
        local value
        value=$(grep -E "^${name}=" .env 2>/dev/null | cut -d= -f2-)
        if [ -z "$value" ]; then
            fail "$name не заполнен"
        elif [ -n "$placeholder" ] && [ "$value" = "$placeholder" ]; then
            fail "$name оставлен со значением из шаблона"
        else
            ok "$name заполнен"
        fi
    }

    check_var POSTGRES_PASSWORD "change_me_please"
    check_var SECRET_KEY "change_me_generate_with_openssl_rand_hex_32"
    check_var FIRST_ADMIN_PASSWORD "change_me_admin_password"

    ENVIRONMENT_VALUE=$(grep -E "^ENVIRONMENT=" .env | cut -d= -f2)
    if [ "$ENVIRONMENT_VALUE" = "production" ]; then
        ok "ENVIRONMENT=production"
        DOMAIN=$(grep -E "^PUBLIC_DOMAIN=" .env | cut -d= -f2)
        if [ -z "$DOMAIN" ] || [ "$DOMAIN" = "anatomy-bot.example.ru" ]; then
            fail "PUBLIC_DOMAIN не указан — Caddy не выпустит сертификат"
        else
            ok "домен: $DOMAIN"
        fi
    else
        warn "ENVIRONMENT=$ENVIRONMENT_VALUE — для боевого сервера поставьте production"
    fi
else
    fail "нет файла .env — скопируйте: cp .env.example .env"
fi

echo
if [ "$PROBLEMS" -eq 0 ]; then
    echo "Проблем не найдено. Запуск:"
    echo "  docker compose -f docker-compose.yml -f docker-compose.prod.yml --profile gpu up -d --build"
else
    echo "Найдено проблем: $PROBLEMS. Устраните их перед запуском."
    exit 1
fi
