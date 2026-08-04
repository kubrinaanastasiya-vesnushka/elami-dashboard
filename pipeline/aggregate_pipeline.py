import json
from collections import defaultdict, Counter
from datetime import datetime, timedelta

CAT_TITLE = json.load(open("/root/agent-workspace/projects/elami-dashboard/pipeline/cat_title.json", encoding="utf-8"))
CAT_TITLE = {int(k): v for k, v in CAT_TITLE.items()}
SERVICE_CAT = json.load(open("/root/agent-workspace/projects/elami-dashboard/pipeline/service_cat.json", encoding="utf-8"))
SERVICE_CAT = {int(k): v for k, v in SERVICE_CAT.items()}
MONTHLY_RAW = json.load(open("/root/agent-workspace/projects/elami-dashboard/pipeline/monthly_raw.json", encoding="utf-8"))

REVENUE_EXPENSE_TYPES = {"Оказание услуг", "Продажа товаров", "Продажа абонементов", "Продажа сертификатов", "Пополнение счета"}
CAT_COLORS = ['#97C459', '#5DCAA5', '#EDA100', '#888780', '#6B8FCE', '#C77DBB']
# same TYPE_MAP convention as client_days_pipeline.py — transactions-based sum+count,
# consistent with how revenue is defined everywhere else in this dashboard (cash basis).
TYPE_MAP = {"Продажа товаров": "goods", "Продажа абонементов": "subscriptions", "Пополнение счета": "deposits"}
# Nastya, 2026-07-27: these are miscategorized in YClients itself as "goods" (Товары) —
# they're actually multi-session massage packages, should count as Абонементы. Reclassify
# in both the summary sum+count row and the top-products table (excluded there entirely).
RECLASSIFY_GOODS_AS_SUBSCRIPTION = {"Массаж Тринити терапия 6 процедур", "Массаж Тринити терапия 12 процедур"}
# Топы page (2026-07-27): Nastya wants top-10 services broken out per business area, with
# "лазерка" and "массаж" each merging two real YClients categories into one table.
TOP_CATEGORY_GROUPS = {
    "Инъекционная косметология": ["Инъекционная косметология"],
    "Эстетическая косметология": ["Эстетическая косметология"],
    "Лазерная эпиляция": ["Женская эпиляция", "Мужская ЛЭ"],
    "Массаж": ["Ручной массаж", "Аппаратный массаж"],
}
# Client-card categories that are status labels, not acquisition sources — excluded from
# "откуда узнали" breakdown (Nastya, 2026-07-27: this replaces the booking-source card on
# Overview; real source lives in the client's YClients category/tag, not from_url/record_from).
REFERRAL_EXCLUDE_TAGS = {"VIP", "MAX"}

# ====================== instrument ledger (2026-07-29, Nastya's correction) ======================
# Nastya: don't infer non-discount payments from free-text comments (admins can describe
# things wrong) or trust the `discount`% field either — instead reconstruct it structurally:
# a client's deposit top-ups and abonement/certificate purchases are real transactions, and
# a later service-price gap should be attributed to drawing down THAT balance, not called a
# discount, only to the extent the balance can actually cover it. Any gap is a discount
# EXCEPT the portion explained by an abonement/certificate/deposit the client actually has.
INSTRUMENT_TYPES = {"Пополнение счета", "Продажа абонементов", "Продажа сертификатов"}

def _parse_tx_date(s):
    return datetime.strptime(s[:19], "%Y-%m-%dT%H:%M:%S")

def _parse_rec_date(s):
    return datetime.strptime(s, "%Y-%m-%d %H:%M:%S")

_credits_by_client = defaultdict(list)  # cid -> [(date, amount), ...]
for _ym, _raw in MONTHLY_RAW.items():
    for _t in _raw["transactions"]:
        if (_t.get("expense") or {}).get("title") in INSTRUMENT_TYPES:
            _c = _t.get("client") or {}
            _cid = _c.get("id")
            if _cid is not None:
                _credits_by_client[_cid].append((_parse_tx_date(_t["date"]), _t["amount"]))

# Certificates need a separate data source entirely: confirmed with Nastya 2026-07-29 (real
# example: Шатилова Алина, certificate №72) that a GIFTED/comp certificate (100% discount,
# 0 ₽ paid at issuance) generates NO transaction at all in the API — not "Продажа
# сертификатов", not anything — so no transaction-based ledger can ever see it, regardless of
# who purchased vs who redeems it. She pulled a manual export (Аналитика → отчёт по
# сертификатам, all history 01.01.2025 onward) that has what the API doesn't: certificate
# code, nominal value, client PHONE NUMBER, sale date, and one row per redemption event
# (date + amount — a single certificate can be split across many redemptions). Matched into
# the ledger via phone number (reliable, present on both sides) rather than name (found
# comment/name text to be unreliable elsewhere in this project already).
CERTIFICATES_CSV = "/root/agent-workspace/projects/elami-dashboard/pipeline/certificates_20250101_20260729.csv"
import csv as _csv
_cert_credits_by_phone = defaultdict(list)  # phone -> [(sale_date, nominal), ...]
with open(CERTIFICATES_CSV, encoding="utf-8") as _f:
    _cert_rows = list(_csv.reader(_f))
_cur_phone, _cur_sale_date, _cur_nominal = None, None, None
for _row in _cert_rows[1:]:
    if _row[0]:  # new certificate row — Код is present
        _cur_phone = _row[5].strip() or None
        _cur_sale_date = _row[6].strip() or None
        _cur_nominal = float(_row[3]) if _row[3] else 0.0
        if _cur_phone and _cur_sale_date:
            _cert_credits_by_phone[_cur_phone].append((datetime.strptime(_cur_sale_date, "%d.%m.%Y"), _cur_nominal))
    # redemption columns (Дата списания/Сумма списания) are informational only here — the
    # ledger simulation below re-derives redemption amounts from each client's own service
    # gaps, so only the credit (nominal, at sale date) needs importing from this report.

_phone_to_cid = {}
for _ym, _raw in MONTHLY_RAW.items():
    for _r in _raw["records"]:
        _c = _r.get("client") or {}
        _phone = (_c.get("phone") or "").lstrip("+")
        _cid = _c.get("id")
        if _phone and _cid is not None and _phone not in _phone_to_cid:
            _phone_to_cid[_phone] = _cid

for _phone, _credits in _cert_credits_by_phone.items():
    _cid = _phone_to_cid.get(_phone)
    if _cid is not None:
        _credits_by_client[_cid].extend(_credits)

_debits_by_client = defaultdict(list)  # cid -> [(date, record_id, service_idx, gap_amount), ...]
for _ym, _raw in MONTHLY_RAW.items():
    _recs = [r for r in _raw["records"] if not r.get("deleted") and r.get("attendance", 1) != -1]
    for _r in _recs:
        _c = _r.get("client") or {}
        _cid = _c.get("id")
        if _cid is None:
            continue
        _rdate = _parse_rec_date(_r["date"])
        for _si, _s in enumerate(_r.get("services", [])):
            _paid = _s.get("cost_to_pay", 0) or 0
            _gap = (_s.get("first_cost", 0) or 0) - _paid
            # Only a FULLY comped line (cost_to_pay == 0 — nothing charged at all) is a
            # candidate for instrument coverage. Found 2026-07-29 checking Журавлева Татьяна:
            # her genuine 30%-discount Full Face Botox (cost_to_pay 22400, confirmed by a
            # real "Оказание услуг" transaction for exactly 22400) was being greedily netted
            # against her UNRELATED deposit/abonement balance just because a gap existed —
            # that's wrong, real cash was collected for the discounted price, so it's a
            # genuine discount, not instrument spend. Left unchecked, this starves later
            # genuine abonement redemptions (e.g. her own Тринити sessions) of balance they
            # should rightfully still have. Partial-payment gaps (0 < paid < first) are
            # always a discount outright, never ledger-eligible.
            if _gap > 0 and _paid == 0:
                _debits_by_client[_cid].append((_rdate, _r["id"], _si, _gap))

# simulate a running balance per client, oldest-first, crediting top-ups/purchases and
# debiting price gaps as they occur — whatever the balance can cover is "instrument-paid",
# the rest (if any) is a genuine discount
INSTRUMENT_COVERED = {}  # (record_id, service_idx) -> amount covered by instrument balance
for _cid in set(list(_credits_by_client.keys()) + list(_debits_by_client.keys())):
    _timeline = [(d, "credit", amt, None) for d, amt in _credits_by_client.get(_cid, [])]
    _timeline += [(d, "debit", amt, key) for d, rid, si, amt in _debits_by_client.get(_cid, []) for key in [(rid, si)]]
    _timeline.sort(key=lambda x: x[0])
    _balance = 0.0
    for _d, _kind, _amt, _key in _timeline:
        if _kind == "credit":
            _balance += _amt
        else:
            _covered = min(_balance, _amt)
            if _covered > 0:
                INSTRUMENT_COVERED[_key] = _covered
                _balance -= _covered

def classify_source(rec):
    if rec.get("from_url"):
        if "2gis" in rec["from_url"]:
            return "2ГИС"
        return "Другой сайт/ссылка"
    rf = (rec.get("record_from") or "").strip()
    if rf:
        if "виджет" in rf.lower() or "форма" in rf.lower():
            return "Виджет на сайте"
        if "yplaces" in rf.lower():
            return "YPLACES"
        return rf
    if rec.get("online"):
        return "Онлайн-запись (прочее)"
    return "Оффлайн (звонок/визит)"

def month_metrics(ym):
    raw = MONTHLY_RAW[ym]
    records = [r for r in raw["records"] if not r.get("deleted") and r.get("attendance", 1) != -1]
    transactions = raw["transactions"]

    revenue = sum(t["amount"] for t in transactions if (t.get("expense") or {}).get("title") in REVENUE_EXPENSE_TYPES)

    visit_ids = set()
    services_revenue = 0.0
    cat_revenue = defaultdict(float)
    cat_count = defaultdict(float)
    cat_service_revenue = defaultdict(lambda: defaultdict(float))
    cat_service_count = defaultdict(lambda: defaultdict(float))
    spec_revenue = defaultdict(float)
    spec_visits = defaultdict(set)
    service_revenue = defaultdict(float)
    source_counter = Counter()
    discount_total = 0.0
    discount_by_label = defaultdict(float)
    clients_seen = {}
    referral_tags_by_client = {}
    spec_clients_seen = defaultdict(dict)  # staff_name -> {client_id: is_new_bool}
    goods_seen = {}  # dedup by goods_transactions line id — a shared visit can repeat a line across staff records

    for r in records:
        vid = r.get("visit_id") or r["id"]
        visit_ids.add(vid)
        staff_name = (r.get("staff") or {}).get("name", "—")
        src = classify_source(r)
        source_counter[vid] = src  # one per visit
        # Only count a client if this record has an actual billable service line — a record
        # can have a client attached but zero services (internal training/model/admin
        # bookings, e.g. comment "Обучение 10:00-16:00", "Модель ... оплачен переводом",
        # "Собрание, уборка" — found 2026-07-27 while verifying Мастера numbers with
        # Nastya: these were inflating client counts, e.g. Анна showed 34 distinct clients
        # for June 2026 vs only 30 real service-visits, which is impossible if every visit
        # belongs to one client). Requiring services here matches how revenue/visits are
        # already defined elsewhere in this pipeline (both also require a service line).
        client = r.get("client")
        if client and r.get("services"):
            cid = client.get("id")
            if cid is not None:
                clients_seen[cid] = clients_seen.get(cid, False) or bool(client.get("is_new"))
                if cid not in referral_tags_by_client:
                    tags = {t["title"] for t in (client.get("client_tags") or [])} - REFERRAL_EXCLUDE_TAGS
                    referral_tags_by_client[cid] = tags
                spec_seen = spec_clients_seen[staff_name]
                spec_seen[cid] = spec_seen.get(cid, False) or bool(client.get("is_new"))

        for _si, s in enumerate(r.get("services", [])):
            paid = s.get("cost_to_pay", 0) or 0
            first = s.get("first_cost", 0) or 0
            services_revenue += paid
            spec_revenue[staff_name] += paid
            spec_visits[staff_name].add(vid)
            cat_id = SERVICE_CAT.get(s["id"])
            cat_name = CAT_TITLE.get(cat_id, "Без категории")
            cat_revenue[cat_name] += paid
            cat_count[cat_name] += s.get("amount", 1) or 1
            cat_service_revenue[cat_name][s["title"]] += paid
            cat_service_count[cat_name][s["title"]] += s.get("amount", 1) or 1
            service_revenue[s["title"]] += paid
            # Nastya's rule (2026-07-29, final): a discount is ANY gap between first_cost and
            # cost_to_pay, EXCEPT the portion actually paid for via a deposit/abonement/
            # certificate — don't trust the `discount`% field or free-text comments (both can
            # be wrong/incomplete), reconstruct from the client's real transaction ledger
            # instead (see INSTRUMENT_COVERED, built globally above from Пополнение
            # счета/Продажа абонементов/Продажа сертификатов transactions, oldest-first
            # balance simulation). Known gap: gift certificates bought by a DIFFERENT client
            # than the one who redeems them are invisible to this ledger (confirmed with
            # Nastya via a real example, Шатилова Алина — paid by a certificate someone else
            # bought, no trace of it under her own client_id in the API) — the API exposes no
            # link between a certificate and its redemption across clients.
            gap = first - paid
            if gap > 0:
                covered = INSTRUMENT_COVERED.get((r["id"], _si), 0)
                disc_amt = gap - covered
                if disc_amt > 0:
                    discount_total += disc_amt
                    labels = r.get("record_labels") or []
                    if labels:
                        for lbl in labels:
                            discount_by_label[lbl["title"]] += disc_amt
                    else:
                        discount_by_label["Без категории"] += disc_amt

        for g in r.get("goods_transactions", []):
            gid = g.get("id")
            if gid is None or gid in goods_seen:
                continue
            goods_seen[gid] = {"name": g.get("title", "—"), "revenue": g.get("cost_to_pay", 0) or 0, "qty": abs(g.get("amount", 0) or 0)}

    # товары/абонементы/депозиты: transaction-based sum+count — same convention as
    # client_days_pipeline.py's TYPE_MAP, so this row ties to the same revenue definition
    # used everywhere else in the dashboard (cash basis, by payment transaction).
    by_type_sum = defaultdict(float)
    by_type_count = defaultdict(int)
    for t in transactions:
        title = (t.get("expense") or {}).get("title")
        if title == "Продажа товаров":
            good_name = goods_seen.get(t.get("sold_item_id"), {}).get("name")
            key = "subscriptions" if good_name in RECLASSIFY_GOODS_AS_SUBSCRIPTION else "goods"
        else:
            key = TYPE_MAP.get(title)
        if key:
            by_type_sum[key] += t["amount"]
            by_type_count[key] += 1

    goods_agg = defaultdict(lambda: {"revenue": 0.0, "qty": 0})
    for g in goods_seen.values():
        if g["name"] in RECLASSIFY_GOODS_AS_SUBSCRIPTION:
            continue
        goods_agg[g["name"]]["revenue"] += g["revenue"]
        goods_agg[g["name"]]["qty"] += g["qty"]
    goods_list = sorted(
        [{"name": n, "revenue": round(v["revenue"]), "qty": round(v["qty"])} for n, v in goods_agg.items()],
        key=lambda x: -x["revenue"]
    )

    # per-subscription-product breakdown, cash basis (transaction amount) so it sums exactly
    # to subscriptionsTotal — name comes from the matching goods_transactions line (same
    # sold_item_id lookup used for the Тринити reclassification above); unmatched sales
    # (small number of months where the transaction's sold_item_id wasn't found in this
    # month's records) bucket into "Без названия" rather than being silently dropped.
    subs_agg = defaultdict(lambda: {"revenue": 0.0, "qty": 0})
    for t in transactions:
        if (t.get("expense") or {}).get("title") == "Продажа абонементов":
            name = goods_seen.get(t.get("sold_item_id"), {}).get("name") or "Без названия"
            subs_agg[name]["revenue"] += t["amount"]
            subs_agg[name]["qty"] += 1
    subs_list = sorted(
        [{"name": n, "revenue": round(v["revenue"]), "qty": round(v["qty"])} for n, v in subs_agg.items()],
        key=lambda x: -x["revenue"]
    )

    # top services per business-area grouping (Топы page, one table per group)
    top_by_category = {}
    for group_name, cats in TOP_CATEGORY_GROUPS.items():
        merged_rev = defaultdict(float)
        merged_cnt = defaultdict(float)
        for cat in cats:
            for svc, rev in cat_service_revenue.get(cat, {}).items():
                merged_rev[svc] += rev
                merged_cnt[svc] += cat_service_count[cat][svc]
        top_by_category[group_name] = sorted(
            [{"name": n, "revenue": round(v), "count": round(merged_cnt[n])} for n, v in merged_rev.items()],
            key=lambda x: -x["revenue"]
        )

    visits = len(visit_ids)
    avg_check_total = revenue / visits if visits else 0
    avg_check_services = services_revenue / visits if visits else 0

    new_clients = sum(1 for v in clients_seen.values() if v)
    repeat_clients = sum(1 for v in clients_seen.values() if not v)

    # categories -> top3 + "Прочее" (used by Overview doughnut, unchanged)
    cat_items = sorted(cat_revenue.items(), key=lambda x: -x[1])
    cat_total = sum(cat_revenue.values())
    categories = []
    if cat_total > 0:
        top = cat_items[:3]
        rest = cat_items[3:]
        rest_sum = sum(v for _, v in rest)
        for i, (name, val) in enumerate(top):
            categories.append({"name": name, "revenue": round(val), "pct": round(val/cat_total*100, 1), "color": CAT_COLORS[i]})
        if rest_sum > 0:
            categories.append({"name": "Прочее", "revenue": round(rest_sum), "pct": round(rest_sum/cat_total*100, 1), "color": CAT_COLORS[3]})

    # ALL categories, no top3 collapse — used by the Categories page comparison table
    categories_full = [
        {"name": name, "revenue": round(val), "count": round(cat_count[name]), "pct": round(val/cat_total*100, 1) if cat_total else 0}
        for name, val in cat_items
    ]

    specialists = sorted(
        [{"name": n, "revenue": round(v), "avgCheck": round(v/len(spec_visits[n])) if spec_visits[n] else 0, "visits": len(spec_visits[n]),
          "newClients": sum(1 for is_new in spec_clients_seen[n].values() if is_new),
          "repeatClients": sum(1 for is_new in spec_clients_seen[n].values() if not is_new)}
         for n, v in spec_revenue.items()],
        key=lambda x: -x["revenue"]
    )

    top_services = sorted(service_revenue.items(), key=lambda x: -x[1])[:5]
    top_services = [{"name": n, "revenue": round(v)} for n, v in top_services]

    sources = Counter(source_counter.values())
    sources_total = sum(sources.values())
    sources_list = []
    if sources_total:
        for name, cnt in sources.most_common():
            sources_list.append({"name": name, "sharePct": round(cnt/sources_total*100, 1), "count": cnt})

    referral_counter = Counter()
    clients_with_tag = 0
    for tags in referral_tags_by_client.values():
        if tags:
            clients_with_tag += 1
            for t in tags:
                referral_counter[t] += 1
    clients_total = len(referral_tags_by_client)
    clients_no_tag = clients_total - clients_with_tag
    referral_list = []
    if clients_total:
        for name, cnt in referral_counter.most_common():
            referral_list.append({"name": name, "count": cnt, "sharePct": round(cnt/clients_total*100, 1)})
        if clients_no_tag:
            referral_list.append({"name": "Без категории", "count": clients_no_tag, "sharePct": round(clients_no_tag/clients_total*100, 1)})

    return {
        "revenue": round(revenue),
        "visits": visits,
        "avgCheckTotal": round(avg_check_total),
        "avgCheckServices": round(avg_check_services),
        "newClients": new_clients,
        "repeatClients": repeat_clients,
        "topServices": top_services,
        "specialists": specialists,
        "categories": categories,
        "categoriesFull": categories_full,
        "goodsTotal": {"sum": round(by_type_sum.get("goods", 0)), "count": by_type_count.get("goods", 0)},
        "subscriptionsTotal": {"sum": round(by_type_sum.get("subscriptions", 0)), "count": by_type_count.get("subscriptions", 0)},
        "depositsTotal": {"sum": round(by_type_sum.get("deposits", 0)), "count": by_type_count.get("deposits", 0)},
        "goods": goods_list,
        "subs": subs_list,
        "topByCategory": top_by_category,
        "sources": sources_list,
        "referralSources": referral_list,
        "discountTotal": round(discount_total),
        "discountPctOfServices": round(discount_total/(services_revenue+discount_total)*100, 1) if (services_revenue+discount_total) else 0,
        "discountByLabel": [{"name": k, "amount": round(v)} for k, v in sorted(discount_by_label.items(), key=lambda x: -x[1])],
    }

MONTHLY_DATA = {ym: month_metrics(ym) for ym in MONTHLY_RAW}

# ====================== retention / master-loyalty cohorts (2026-07-27, Nastya's request) ======================
# Needs cross-month client history (a return visit can land in a different month than the
# first visit), so this is a separate pass over MONTHLY_RAW rather than part of month_metrics().
RETENTION_WINDOW_DAYS = 90
NOW = datetime.now()  # data-collection cutoff, not literal max record date — some July
# records are future-dated scheduled appointments (attendance != -1 doesn't exclude "not yet
# happened"); those must not count as evidence of a return before they've actually occurred.

all_recs = []
for ym, d in MONTHLY_RAW.items():
    for r in d["records"]:
        if r.get("deleted") or r.get("attendance", 1) == -1 or not r.get("services"):
            continue
        client = r.get("client")
        if not client or client.get("id") is None:
            continue
        dt = datetime.strptime(r["date"], "%Y-%m-%d %H:%M:%S")
        if dt > NOW:
            continue
        rec_services = [{"title": s["title"], "cost_to_pay": s.get("cost_to_pay", 0) or 0} for s in r.get("services", [])]
        all_recs.append({"cid": client["id"], "date": dt, "staff": (r.get("staff") or {}).get("name", "—"), "is_new": bool(client.get("is_new")), "services": rec_services})

by_client = defaultdict(list)
for rec in all_recs:
    by_client[rec["cid"]].append(rec)
for cid in by_client:
    by_client[cid].sort(key=lambda x: x["date"])

# cohort month = month of a client's first visit IN OUR DATA, but only trust it as a genuine
# "new" cohort if YClients' own is_new flag agrees on that earliest record — otherwise the
# client's true first visit predates our Jan-2025 data start (left-censored) and would
# wrongly inflate the earliest months' cohorts.
first_visit = {}
for cid, recs in by_client.items():
    fv = recs[0]
    if fv["is_new"]:
        first_visit[cid] = fv

cohorts = defaultdict(list)
for cid, fv in first_visit.items():
    cohorts[fv["date"].strftime("%Y-%m")].append(cid)

def month_end(ym):
    y, m = map(int, ym.split("-"))
    return (datetime(y, m + 1, 1) if m < 12 else datetime(y + 1, 1, 1)) - timedelta(seconds=1)

def window_closed(ym):
    return (NOW - month_end(ym)).days >= RETENTION_WINDOW_DAYS

retention = {}
master_loyalty = defaultdict(dict)
for ym in MONTHLY_RAW:
    cids = cohorts.get(ym, [])
    total = len(cids)
    returned = 0
    for cid in cids:
        fv_date = first_visit[cid]["date"]
        for rec in by_client[cid][1:]:
            delta = (rec["date"] - fv_date).days
            if 0 < delta <= RETENTION_WINDOW_DAYS:
                returned += 1
                break
    retention[ym] = {
        "cohortSize": total,
        "returned": returned,
        "returnPct": round(returned / total * 100, 1) if total else None,
        "windowClosed": window_closed(ym),
    }

    staff_cids = defaultdict(list)
    for cid in cids:
        staff_cids[first_visit[cid]["staff"]].append(cid)
    for staff, s_cids in staff_cids.items():
        s_total = len(s_cids)
        s_returned = 0
        for cid in s_cids:
            fv = first_visit[cid]
            for rec in by_client[cid][1:]:
                delta = (rec["date"] - fv["date"]).days
                if 0 < delta <= RETENTION_WINDOW_DAYS and rec["staff"] == staff:
                    s_returned += 1
                    break
        master_loyalty[ym][staff] = {
            "cohortSize": s_total,
            "returnedSame": s_returned,
            "loyaltyPct": round(s_returned / s_total * 100, 1) if s_total else None,
            "windowClosed": window_closed(ym),
        }

for ym in MONTHLY_DATA:
    MONTHLY_DATA[ym]["retention"] = retention[ym]
    MONTHLY_DATA[ym]["masterLoyalty"] = [
        {"name": n, **v} for n, v in sorted(master_loyalty[ym].items(), key=lambda x: -x[1]["cohortSize"])
    ]

# ====================== new clients: first-month services + first master (2026-08-04, Nastya's request) ======================
# For each cohort of new clients (first-ever visit, is_new-verified, landing in month ym):
# what services did they take within that same calendar month (their whole "first month",
# not just the single first visit — a client can come back a second time in the same month),
# and which master saw them on that very first visit.
new_client_detail = {}
for ym in MONTHLY_RAW:
    cids = cohorts.get(ym, [])
    total = len(cids)
    service_stats = defaultdict(lambda: {"revenue": 0.0, "count": 0})
    master_counter = Counter()
    for cid in cids:
        master_counter[first_visit[cid]["staff"]] += 1
        for rec in by_client[cid]:
            if rec["date"].strftime("%Y-%m") != ym:
                continue
            for s in rec["services"]:
                stat = service_stats[s["title"]]
                stat["revenue"] += s["cost_to_pay"]
                stat["count"] += 1
    services_first_month = sorted(
        [{"name": k, "revenue": round(v["revenue"]), "count": v["count"]} for k, v in service_stats.items()],
        key=lambda x: -x["revenue"],
    )
    first_master_dist = [
        {"name": n, "count": c, "sharePct": round(c / total * 100, 1) if total else 0}
        for n, c in master_counter.most_common()
    ]
    new_client_detail[ym] = {
        "totalNew": total,
        "servicesFirstMonth": services_first_month,
        "firstMasterDist": first_master_dist,
    }

for ym in MONTHLY_DATA:
    MONTHLY_DATA[ym]["newClientDetail"] = new_client_detail[ym]

# ====================== lost clients (2026-07-27, Nastya's request) ======================
# "Потерянные клиенты" as of a given period's end date: among everyone who has EVER been a
# real client up to that date, how many have gone silent for more than 90 days. Nastya's own
# example: as of 30 June, a client is lost if their last visit was before 1 April (that's
# exactly 90 days earlier) — so the cutoff is strict: exactly 90 days silent is NOT lost yet,
# 91+ days is. Reuses the same all_recs/by_client built above for retention.
LOST_WINDOW_DAYS = 90
lost_clients = {}
for ym in MONTHLY_RAW:
    true_end = month_end(ym)
    snapshot_date = min(true_end, NOW)
    last_visit = {}
    for rec in all_recs:
        if rec["date"] <= snapshot_date:
            cid = rec["cid"]
            if cid not in last_visit or rec["date"] > last_visit[cid]:
                last_visit[cid] = rec["date"]
    total_clients = len(last_visit)
    lost = sum(1 for dt in last_visit.values() if (snapshot_date - dt).days > LOST_WINDOW_DAYS)
    lost_clients[ym] = {
        "lost": lost,
        "totalClients": total_clients,
        "lostPct": round(lost / total_clients * 100, 1) if total_clients else None,
        "isPartialMonth": true_end > NOW,  # snapshot taken before this month's real end (only the current month)
    }
    MONTHLY_DATA[ym]["lostClients"] = lost_clients[ym]

json.dump(MONTHLY_DATA, open("/root/agent-workspace/projects/elami-dashboard/pipeline/monthly_data_v2.json", "w", encoding="utf-8"), ensure_ascii=False)

print(json.dumps(MONTHLY_DATA["2026-06"]["retention"], ensure_ascii=False, indent=2))
print(json.dumps(MONTHLY_DATA["2026-06"]["masterLoyalty"], ensure_ascii=False, indent=2))
