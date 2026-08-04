import json, re, sys

REPO = "/root/agent-workspace/projects/elami-dashboard"
DATA_PATH = f"{REPO}/pipeline/monthly_data_v2.json"
GOODS_STOCK_PATH = f"{REPO}/pipeline/goods_stock.json"
HTML_PATH = f"{REPO}/index.html"

data = json.load(open(DATA_PATH, encoding="utf-8"))
compact = json.dumps(data, ensure_ascii=False, separators=(",", ":"))

html = open(HTML_PATH, encoding="utf-8").read()
new_line = f"const MONTHLY_DATA = {compact};"

pattern = re.compile(r"const MONTHLY_DATA = \{.*?\};\n", re.DOTALL)
if not pattern.search(html):
    print("MONTHLY_DATA declaration not found in index.html — aborting, nothing written")
    sys.exit(1)

html = pattern.sub(new_line + "\n", html, count=1)

goods_stock = json.load(open(GOODS_STOCK_PATH, encoding="utf-8"))
goods_compact = json.dumps(goods_stock, ensure_ascii=False, separators=(",", ":"))
goods_line = f"const GOODS_STOCK = {goods_compact};"

goods_pattern = re.compile(r"const GOODS_STOCK = \[.*?\];\n", re.DOTALL)
if goods_pattern.search(html):
    html = goods_pattern.sub(goods_line + "\n", html, count=1)
else:
    html = html.replace(new_line + "\n", new_line + "\n" + goods_line + "\n", 1)

open(HTML_PATH, "w", encoding="utf-8").write(html)
print("embedded MONTHLY_DATA + GOODS_STOCK into", HTML_PATH)
