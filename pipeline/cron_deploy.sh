#!/bin/bash
# Точка входа для планового обновления (cron/systemd timer).
# Сохраняет снапшот РОВНО недельной давности (из git-истории) для честного сравнения
# неделя-к-неделе, гоняет deploy.sh, шлёт краткий свод в Telegram.
#
# 2026-09-14/21: раньше просто копировали текущий monthly_data_v2.json в .prev.json прямо
# перед прогоном — это ломалось, если между понедельничными кронами я (агент) вручную
# гоняла deploy.sh посреди недели: .prev.json тогда содержал "состояние на среду", а не
# "неделю назад", и дельта в отчёте Насте занижалась/обнулялась (поймали дважды на живых
# примерах — Настя заметила "Эльвира +0₽" при том, что она реально работала всю неделю).
# Теперь берём файл из git-коммита, ближайшего к (сейчас − 7 дней), а не текущий файл на диске.
cd "$(dirname "$0")"

WEEK_AGO_COMMIT=$(git log --format="%H" --before="7 days ago" -1 -- monthly_data_v2.json)
if [ -n "$WEEK_AGO_COMMIT" ]; then
    git show "$WEEK_AGO_COMMIT:pipeline/monthly_data_v2.json" > monthly_data_v2.prev.json 2>/dev/null || rm -f monthly_data_v2.prev.json
fi

./deploy.sh

python3 summarize_changes.py
