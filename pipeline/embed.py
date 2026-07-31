import json, re, sys

REPO = "/root/agent-workspace/projects/elami-dashboard"
DATA_PATH = f"{REPO}/pipeline/monthly_data_v2.json"
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
open(HTML_PATH, "w", encoding="utf-8").write(html)
print("embedded MONTHLY_DATA into", HTML_PATH)
