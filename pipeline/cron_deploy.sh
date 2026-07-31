#!/bin/bash
# Точка входа для планового обновления (cron/systemd timer).
# Сохраняет предыдущий снапшот для сравнения, гоняет deploy.sh, шлёт краткий свод в Telegram.
set -e
cd "$(dirname "$0")"

if [ -f monthly_data_v2.json ]; then
    cp monthly_data_v2.json monthly_data_v2.prev.json
fi

./deploy.sh

python3 summarize_changes.py
