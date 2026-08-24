#!/usr/bin/env python3
"""pump.md 云端构建：pump_data.json + pump.html 模板 → index.html（GitHub Actions 用）"""
import json, os

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "data", "pump", "pump_data.json")
TEMPLATE = next(p for p in (os.path.join(BASE, "pump.html"), os.path.join(BASE, "site", "pump.html"))
                if os.path.exists(p))
OUT = os.path.join(BASE, "index.html")

def main():
    with open(TEMPLATE, encoding="utf-8") as f:
        tpl = f.read()
    if os.path.exists(DATA):
        with open(DATA, encoding="utf-8") as f:
            pump = json.load(f)
    else:
        pump = {"new_coins": [], "smart_money": [], "signals": [], "stats": {}, "scanned_at": "", "chain": "sol", "chains": ["sol"], "by_chain": {}}
    js = json.dumps(pump, ensure_ascii=False).replace("</script>", "<\\/script>")
    out = tpl.replace("const PUMP = __PUMP_DATA__;", f"const PUMP = {js};")
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(out)
    chains = pump.get("chains", [pump.get("chain", "sol")] if "by_chain" not in pump else [])
    if "by_chain" in pump and pump.get("by_chain"):
        chains = list(pump["by_chain"].keys())
    total = sum(len(v.get("new_coins", [])) for v in pump.get("by_chain", {}).values()) or len(pump.get("new_coins", []))
    print(f"构建完成: {OUT} (链 {chains} | 新币 {total})")

if __name__ == "__main__":
    main()
