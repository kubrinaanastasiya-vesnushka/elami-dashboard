import json, time, urllib.request, urllib.error
from collections import defaultdict, Counter
from datetime import date, timedelta

PARTNER_TOKEN = "pw52v3fY1E0OJai9BRYN"
USER_TOKEN = "b021835351847bac40a30b5afdd7a11d"
COMPANY_ID = 1033701
AUTH = f"Bearer {PARTNER_TOKEN}, User {USER_TOKEN}"

def api_get(path, params=""):
    url = f"https://api.yclients.com/api/v1/{path}{params}"
    req = urllib.request.Request(url, headers={
        "Accept": "application/vnd.yclients.v2+json",
        "Authorization": AUTH,
    })
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as e:
            print("HTTP error", e.code, path, params)
            time.sleep(1)
    return {"success": False, "data": None}

# --- static lookups ---
cats = api_get(f"company/{COMPANY_ID}/service_categories")["data"]
CAT_TITLE = {c["id"]: c["title"] for c in cats}

services = api_get(f"company/{COMPANY_ID}/services")["data"]
SERVICE_CAT = {s["id"]: s["category_id"] for s in services}
SERVICE_TITLE = {s["id"]: s["title"] for s in services}

json.dump(CAT_TITLE, open("/root/agent-workspace/projects/elami-dashboard/pipeline/cat_title.json","w",encoding="utf-8"), ensure_ascii=False)
json.dump(SERVICE_CAT, open("/root/agent-workspace/projects/elami-dashboard/pipeline/service_cat.json","w",encoding="utf-8"), ensure_ascii=False)
print("categories:", len(CAT_TITLE), "services:", len(SERVICE_CAT))

def month_range(ym):
    y, m = map(int, ym.split("-"))
    start = date(y, m, 1)
    if m == 12:
        end = date(y, 12, 31)
    else:
        end = date(y, m+1, 1) - timedelta(days=1)
    return start.isoformat(), end.isoformat()

def fetch_records(start, end):
    d = api_get(f"records/{COMPANY_ID}", f"?start_date={start}&end_date={end}&count=1000")
    return d.get("data") or []

def fetch_transactions(start, end):
    d = api_get(f"transactions/{COMPANY_ID}", f"?start_date={start}&end_date={end}&count=1000")
    return d.get("data") or []

months = []
today = date.today()
y, m = 2025, 1
while (y, m) <= (today.year, today.month):
    months.append(f"{y:04d}-{m:02d}")
    m += 1
    if m > 12:
        m = 1; y += 1

MONTHLY = {}
for ym in months:
    start, end = month_range(ym)
    records = fetch_records(start, end)
    transactions = fetch_transactions(start, end)
    MONTHLY[ym] = {"records": records, "transactions": transactions}
    print(ym, "records:", len(records), "transactions:", len(transactions))
    time.sleep(0.3)

json.dump(MONTHLY, open("/root/agent-workspace/projects/elami-dashboard/pipeline/monthly_raw.json","w",encoding="utf-8"), ensure_ascii=False)
print("done, saved monthly_raw.json")
