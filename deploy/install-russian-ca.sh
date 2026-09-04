#!/usr/bin/env bash
# Скачивает корневой сертификат НУЦ Минцифры для проверки TLS при обращении
# к GigaChat.
#
# Зачем: сервер GigaChat подписан этим удостоверяющим центром, а его нет в
# стандартном наборе доверенных сертификатов Linux-образа. Без сертификата
# остаётся только отключить проверку (GIGACHAT_VERIFY_SSL=false), что для
# прода нежелательно.
#
# Запуск из корня проекта:
#   bash deploy/install-russian-ca.sh
#
# После этого в .env:
#   GIGACHAT_VERIFY_SSL=/certs/russian_trusted.pem
# и перезапустить контейнеры: docker compose up -d api worker vkbot

set -euo pipefail

CERT_DIR="$(dirname "$0")/certs"
TARGET="$CERT_DIR/russian_trusted.pem"

ROOT_URL="https://gu-st.ru/content/Other/doc/russian_trusted_root_ca_pem.crt"
SUB_URL="https://gu-st.ru/content/Other/doc/russian_trusted_sub_ca_pem.crt"

mkdir -p "$CERT_DIR"

echo "Скачивание корневого сертификата НУЦ Минцифры..."
# Сам источник тоже подписан этим же УЦ, поэтому первая загрузка идёт без
# проверки — иначе получится замкнутый круг. Проверьте отпечаток вручную,
# если требования безопасности это предполагают.
curl -fsSL --insecure "$ROOT_URL" -o "$CERT_DIR/root.crt"
curl -fsSL --insecure "$SUB_URL" -o "$CERT_DIR/sub.crt"

cat "$CERT_DIR/root.crt" "$CERT_DIR/sub.crt" > "$TARGET"
rm -f "$CERT_DIR/root.crt" "$CERT_DIR/sub.crt"

echo
echo "Готово: $TARGET"
echo
echo "Отпечаток корневого сертификата (сверьте с сайтом Госуслуг):"
openssl x509 -in "$TARGET" -noout -fingerprint -sha256 2>/dev/null || true
echo
echo "Теперь укажите в .env:"
echo "  GIGACHAT_VERIFY_SSL=/certs/russian_trusted.pem"
echo "и перезапустите: docker compose up -d api worker vkbot"
