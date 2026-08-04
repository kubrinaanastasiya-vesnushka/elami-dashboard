import json, urllib.request

PARTNER_TOKEN = "pw52v3fY1E0OJai9BRYN"
USER_TOKEN = "b021835351847bac40a30b5afdd7a11d"
COMPANY_ID = 1033701
AUTH = f"Bearer {PARTNER_TOKEN}, User {USER_TOKEN}"
SALE_STORAGE_ID = 2086547  # "Товары" — розничные остатки; вторая касса ("Абонементы и сертификаты") не физический склад


def api_get(path, params=""):
    url = f"https://api.yclients.com/api/v1/{path}{params}"
    req = urllib.request.Request(url, headers={
        "Accept": "application/vnd.yclients.v2+json",
        "Authorization": AUTH,
    })
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


goods = api_get(f"goods/{COMPANY_ID}", "?count=1000")["data"]

stock = []
for g in goods:
    if "Сертификат" in g["title"]:
        continue  # сертификаты — не физический остаток, amount у них не про наличие на складе
    amount = next((a["amount"] for a in g.get("actual_amounts", []) if a["storage_id"] == SALE_STORAGE_ID), 0)
    stock.append({
        "name": g["title"],
        "category": g.get("category", ""),
        "amount": amount,
        "criticalAmount": g.get("critical_amount", 0),
        "cost": g.get("actual_cost", 0),
    })

stock.sort(key=lambda x: x["amount"])
json.dump(stock, open("/root/agent-workspace/projects/elami-dashboard/pipeline/goods_stock.json", "w", encoding="utf-8"), ensure_ascii=False)
print("goods_stock.json written:", len(stock), "items,", sum(1 for s in stock if s["amount"] <= 3), "with stock <= 3")
