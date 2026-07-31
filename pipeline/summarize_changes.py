import json, sys, urllib.request, urllib.parse

PIPE = "/root/agent-workspace/projects/elami-dashboard/pipeline"
CUR_PATH = f"{PIPE}/monthly_data_v2.json"
PREV_PATH = f"{PIPE}/monthly_data_v2.prev.json"

BOT_TOKEN_FILE = "/root/elamik-home/.claude/channels/telegram/.env"
CHAT_ID = "289566273"  # Настя


def load_token():
    for line in open(BOT_TOKEN_FILE):
        if line.startswith("TELEGRAM_BOT_TOKEN="):
            return line.strip().split("=", 1)[1]
    raise RuntimeError("bot token not found")


def fmt_delta(cur, prev, unit=""):
    if prev is None:
        return f"{cur:,}{unit}".replace(",", " ")
    d = cur - prev
    sign = "+" if d >= 0 else ""
    return f"{cur:,}{unit} ({sign}{d:,}{unit})".replace(",", " ")


def send_telegram(text):
    token = load_token()
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = urllib.parse.urlencode({"chat_id": CHAT_ID, "text": text}).encode()
    req = urllib.request.Request(url, data=data)
    with urllib.request.urlopen(req, timeout=15) as resp:
        resp.read()


def main():
    cur = json.load(open(CUR_PATH, encoding="utf-8"))
    try:
        prev = json.load(open(PREV_PATH, encoding="utf-8"))
    except FileNotFoundError:
        prev = None

    months = sorted(cur.keys())
    latest = months[-1]
    cur_m = cur[latest]
    prev_m = prev.get(latest) if prev else None

    lines = [f"🎩 Эламик: дашборд обновлён. Текущий месяц ({latest}):"]
    lines.append(f"Выручка: {fmt_delta(cur_m['revenue'], prev_m['revenue'] if prev_m else None, ' ₽')}")
    lines.append(f"Визиты: {fmt_delta(cur_m['visits'], prev_m['visits'] if prev_m else None)}")
    lines.append(f"Скидки: {fmt_delta(cur_m['discountTotal'], prev_m['discountTotal'] if prev_m else None, ' ₽')}")

    if prev is not None and latest not in prev:
        lines.append(f"Новый месяц в данных: {latest}")

    if prev is None:
        lines.append("(первый запуск — сравнивать не с чем, база сохранена)")

    text = "\n".join(lines)
    send_telegram(text)
    print(text)


if __name__ == "__main__":
    main()
