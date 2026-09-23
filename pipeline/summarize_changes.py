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

    # .get(...) throughout — prev_m may be an older snapshot missing fields added later
    # (e.g. servicesRevenue, 2026-09-13), and should degrade to "no delta" rather than crash.
    prev_master = (prev_m or {}).get("revenueByMaster", {})
    prev_goods = (prev_m or {}).get("goodsTotal", {})
    prev_subs = (prev_m or {}).get("subscriptionsTotal", {})

    lines = [f"🎩 Эламик: дашборд обновлён. Текущий месяц ({latest}):"]
    lines.append(f"Выручка: {fmt_delta(cur_m['revenue'], (prev_m or {}).get('revenue'), ' ₽')}")
    lines.append(f"  из них Эльвира: {fmt_delta(cur_m['revenueByMaster']['elvira'], prev_master.get('elvira'), ' ₽')}")
    lines.append(f"  из них остальные: {fmt_delta(cur_m['revenueByMaster']['others'], prev_master.get('others'), ' ₽')}")
    lines.append(f"Визиты: {fmt_delta(cur_m['visits'], (prev_m or {}).get('visits'))}")
    lines.append(f"Скидки: {fmt_delta(cur_m['discountTotal'], (prev_m or {}).get('discountTotal'), ' ₽')}")

    lines.append("")
    lines.append("По типам:")
    lines.append(f"  Услуги: {fmt_delta(cur_m['servicesRevenue'], (prev_m or {}).get('servicesRevenue'), ' ₽')}")
    lines.append(f"  Товары: {fmt_delta(cur_m['goodsTotal']['sum'], prev_goods.get('sum'), ' ₽')}")
    lines.append(f"  Абонементы: {fmt_delta(cur_m['subscriptionsTotal']['sum'], prev_subs.get('sum'), ' ₽')}")

    plan = cur_m.get("revenuePlan")
    if plan:
        plan_total = plan["elvira"] + plan["others"]
        fact_total = cur_m["revenueByMaster"]["elvira"] + cur_m["revenueByMaster"]["others"]
        pct = round(fact_total / plan_total * 100, 1) if plan_total else 0
        lines.append("")
        lines.append(f"План-факт ({latest}): {fact_total:,} ₽ из {plan_total:,} ₽ ({pct}%)".replace(",", " "))
        for who, label in (("elvira", "Эльвира"), ("others", "Остальные")):
            f = cur_m["revenueByMaster"][who]
            p = plan[who]
            pct_who = round(f / p * 100, 1) if p else 0
            lines.append(f"  {label}: {f:,} ₽ из {p:,} ₽ ({pct_who}%)".replace(",", " "))

    if prev is not None and latest not in prev:
        lines.append(f"Новый месяц в данных: {latest}")

    if prev is None:
        lines.append("(первый запуск — сравнивать не с чем, база сохранена)")

    text = "\n".join(lines)
    send_telegram(text)
    print(text)


if __name__ == "__main__":
    main()
