#!/bin/bash
# Полный цикл обновления дашборда Elami: свежие данные из YClients -> пересчёт -> embed -> проверка -> деплой.
# Использование: ./deploy.sh
set -e
cd "$(dirname "$0")"

echo "[1/6] fetch_pipeline.py — тянем свежие данные из YClients API"
python3 fetch_pipeline.py
python3 fetch_goods_stock.py

echo "[2/6] aggregate_pipeline.py — пересчитываем метрики"
python3 aggregate_pipeline.py

echo "[3/6] embed.py — вшиваем MONTHLY_DATA + GOODS_STOCK в index.html"
python3 embed.py

echo "[4/6] node --check — синтаксическая проверка встроенного JS"
node -e "
const fs = require('fs');
const html = fs.readFileSync('../index.html', 'utf8');
const blocks = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)];
const main = blocks.map(b => b[1]).find(js => js.includes('MONTHLY_DATA'));
if (!main) { console.error('no script block with MONTHLY_DATA found'); process.exit(1); }
fs.writeFileSync('/tmp/elamik_check.js', main);
"
node --check /tmp/elamik_check.js

echo "[5/6] деплой на веб-сервер"
cp ../index.html /var/www/elami-dashboard/index.html

echo "[6/6] git commit + push"
cd ..
git add index.html pipeline/
git commit -m "Автообновление дашборда $(date +%Y-%m-%d)" --quiet || echo "нет изменений для коммита"
git push --quiet

echo "Готово. Дашборд обновлён: http://45.14.245.79:8080/"
