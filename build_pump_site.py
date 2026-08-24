#!/usr/bin/env python3
"""pump.md 云端构建：pump_data.json + pump.html 模板 → index.html（GitHub Actions 用）"""
import json, os

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "data", "pump", "pump_data.json")
TEMPLATE = os.path.join(BASE, "pump.html")
OUT = os.path.join(BASE, "index.html")

def main():
    with open(TEMPLATE, encoding="utf-8") as f:
        tpl = f.read()
    if os.path.exists(DATA):
        with open(DATA, encoding="utf-8") as f:
            pump = json.load(f)
    else:
        pump = {"new_coins": [], "smart_money": [], "signals": [], "stats": {}, "scanned_at": "", "chain": "sol"}
    js = json.dumps(pump, ensure_ascii=False).replace("</script>", "<\\/script>")
    out = tpl.replace("const PUMP = __PUMP_DATA__;", f"const PUMP = {js};")
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(out)
    print(f"构建完成: {OUT} (新币 {len(pump['new_coins'])} / 信号流 {len(pump.get('signals', []))} / 异动 {len(pump['smart_money'])})")

if __name__ == "__main__":
    main()
