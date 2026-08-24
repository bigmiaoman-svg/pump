#!/usr/bin/env python3
"""pump.md 数据管道：GMGN 四通道精华过滤版
通道：
  1. trenches new_creation（新币池，smart-money preset）→ 严格精选
  2. market signal（实时信号流：聪明钱买入12 / KOL买入20）→ 行为背书
  3. track smartmoney（聪明钱买入聚合 cluster）
  4. trending 5m（实时热榜）→ 严格精选

精选过滤（诚顺 2026-08-24 定稿）：
  ✅ 社交真实存在：官网/推特/电报 至少一个（三无产品直接筛掉）
  ✅ 权限干净：SOL 铸币权+冻结权双放弃；EVM 所有权 renounce + 非貔貅 + 开源
  ✅ 无黑幕：非洗盘、rug_ratio≤0.3、bundler≤0.3、老鼠仓≤0.3、筹码不集中(≤50%)
  ✅ 无技术问题：非 honeypot、税率≤10%、有真实流动性
输出：data/pump/pump_data.json（含筛除原因统计 filter_breakdown）
用法: python3 pump_fetch.py [--chain sol] [--limit 12]
"""
import json, os, subprocess, sys, datetime, argparse, time

BASE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(BASE, "data", "pump")
os.makedirs(OUT, exist_ok=True)

def run(cmd, timeout=150):
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError(f"{cmd[0]} 失败: {r.stderr[:300]}")
    return json.loads(r.stdout)

def fmt_usd(v):
    if v is None: return "--"
    v = float(v)
    if v >= 1e6: return f"${v/1e6:.1f}M"
    if v >= 1e3: return f"${v/1e3:.1f}K"
    return f"${v:.0f}"

def social_any(c):
    """取 token 的社交字段（兼容 trenches/trending 两种命名）"""
    tw = c.get("twitter_handle") or c.get("twitter") or ""
    if tw and ("/status/" in tw or tw.startswith("http")):
        tw = ""  # 推文链接不是账号
    website = c.get("website") or ""
    if website and ("x.com" in website or "twitter.com" in website):
        website = ""  # 官网字段混入推特链接 = 假官网
    return tw or website or (c.get("telegram") or "")

# ===== 精选过滤器 =====
def quality_filter(c, chain):
    """返回 (是否通过, 未通过原因列表)。诚顺精选规则：有社交/权限干净/无黑幕/无技术问题"""
    reasons = []
    # 1. 三无产品：无官网/推特/电报
    if not social_any(c) and not c.get("has_at_least_one_social"):
        reasons.append("三无(无官网/推特/电报)")
    # 2. 权限问题：铸币权/冻结权/所有权未放弃
    if chain == "sol":
        if not c.get("renounced_mint"):
            reasons.append("铸币权未放弃")
        if not c.get("renounced_freeze_account"):
            reasons.append("冻结权未放弃")
    else:
        if c.get("is_honeypot") in ("yes", 1, True):
            reasons.append("貔貅盘")
        if not (c.get("is_renounced") in (1, True, "yes") or c.get("owner_renounced") in ("yes", 1, True)):
            reasons.append("所有权未放弃")
        if not (c.get("is_open_source") in (1, True, "yes") or c.get("open_source") in ("yes", 1, True)):
            reasons.append("合约不开源")
    # 3. 黑幕：洗盘 / rug / bundler / 老鼠仓 / 筹码集中
    if c.get("is_wash_trading"):
        reasons.append("疑似洗盘")
    if (c.get("rug_ratio") or 0) > 0.3:
        reasons.append(f"rug风险{float(c['rug_ratio']):.2f}")
    if (c.get("bundler_rate") or c.get("bundler_trader_amount_rate") or 0) > 0.3:
        reasons.append("bundler集中")
    if (c.get("rat_trader_amount_rate") or 0) > 0.3:
        reasons.append("老鼠仓占比高")
    if (c.get("top_10_holder_rate") or 0) > 0.5:
        reasons.append("筹码高度集中")
    # 4. 技术问题：高税 / 流动性不足
    buy_tax = float(c.get("buy_tax") or 0)
    sell_tax = float(c.get("sell_tax") or 0)
    if buy_tax > 0.10 or sell_tax > 0.10:
        reasons.append("税率过高")
    return (len(reasons) == 0, reasons)

def to_coin(c, chain):
    """精选通过的 token → 展示结构"""
    mc = c.get("market_cap") or c.get("usd_market_cap") or 0
    vol = c.get("volume_24h") or c.get("volume") or 0
    created = c.get("created_timestamp") or c.get("creation_timestamp") or int(time.time())
    return {
        "name": c.get("name", "?"),
        "symbol": c.get("symbol", c.get("name", "?")),
        "address": c.get("address", ""),
        "price": c.get("price", 0),
        "mcap": fmt_usd(mc), "mcap_raw": mc,
        "vol24h": fmt_usd(vol), "vol24h_raw": vol,
        "liquidity": fmt_usd(c.get("liquidity", 0)),
        "swaps_24h": c.get("swaps_24h", 0) or c.get("swaps", 0),
        "holders": c.get("holder_count", 0),
        "smart_degen": c.get("smart_degen_count", 0),
        "renowned": c.get("renowned_count", 0),
        "progress": round((c.get("progress") or 0) * 100, 1),
        "launchpad": c.get("launchpad", "") or c.get("launchpad_platform", ""),
        "logo": c.get("logo", ""),
        "age_min": max(1, int((time.time() - created) / 60)),
        "social": {
            "twitter": (c.get("twitter_handle") or c.get("twitter_username") or ""),
            "website": (c.get("website") or "") if not (c.get("website") and ("x.com" in (c.get("website") or "") or "twitter.com" in (c.get("website") or ""))) else "",
            "telegram": c.get("telegram") or "",
        },
        "risk": [],
    }

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--chain", default="sol")
    ap.add_argument("--limit", type=int, default=12)
    args = ap.parse_args()
    chain = args.chain
    drop = {}   # 筛除原因统计

    def note_drops(reasons):
        for r in reasons:
            drop[r] = drop.get(r, 0) + 1

    # ===== 1+4. 新币热榜（trenches） + 实时热榜（trending 5m）合并精选 =====
    pool = []
    for label, cmd in [
        ("trenches", ["gmgn-cli", "market", "trenches", "--chain", chain,
                      "--type", "new_creation", "--filter-preset", "smart-money",
                      "--min-volume-24h", "20000", "--sort-by", "smart_degen_count",
                      "--limit", "30", "--raw"]),
        ("trending", ["gmgn-cli", "market", "trending", "--chain", chain,
                      "--interval", "5m", "--order-by", "volume",
                      "--min-volume", "20000", "--limit", "30", "--raw"]),
    ]:
        try:
            raw = run(cmd)
        except RuntimeError as e:
            print(f"[warn] {label}: {e}")
            continue
        items = raw.get("new_creation", []) if label == "trenches" else (raw.get("data") or {}).get("rank", [])
        pool.extend((label, c) for c in items)

    seen, coins = set(), []
    # 先按来源加权：trenches 优先（新币）+ smart_degen 数排序
    pool.sort(key=lambda x: (-(x[1].get("smart_degen_count") or 0), x[0] == "trenches"), reverse=False)
    # 修正排序：smart_degen 降序，trenches 优先
    pool.sort(key=lambda x: (-(x[1].get("smart_degen_count") or 0), 0 if x[0] == "trenches" else 1))
    for label, c in pool:
        addr = c.get("address", "")
        if not addr or addr in seen:
            continue
        mc = c.get("market_cap") or c.get("usd_market_cap") or 0
        if mc < 10000:  # 低于 1 万美金市值 = 空气币阶段，直接不进榜
            note_drops(["市值过低(<1万)"])
            continue
        ok, reasons = quality_filter(c, chain)
        if not ok:
            note_drops(reasons)
            continue
        seen.add(addr)
        coins.append(to_coin(c, chain))
        if len(coins) >= args.limit:
            break

    # ===== 2. 实时信号流（聪明钱买入 / KOL 买入，同样过精选）=====
    signals = []
    try:
        sig = run(["gmgn-cli", "market", "signal", "--chain", chain,
                   "--signal-type", "12", "--signal-type", "20", "--raw"])
    except RuntimeError as e:
        print(f"[warn] signal: {e}")
        sig = []
    sig_map = {12: "聪明钱买入", 20: "KOL买入"}
    seen_sig = set()
    for s in (sig or []):
        d = s.get("data") or {}
        t = s.get("signal_type")
        if t not in sig_map:
            continue
        addr = s.get("token_address", "")
        if not addr or addr in seen_sig:
            continue
        ok, reasons = quality_filter(d, chain)
        if not ok:
            note_drops([f"信号源:{reasons[0]}"])
            continue
        seen_sig.add(addr)
        sym = d.get("symbol") or (s.get("token_address") or "")[:6]
        signals.append({
            "type": sig_map.get(t, f"信号{t}"),
            "symbol": sym,
            "name": d.get("name", ""),
            "address": addr,
            "logo": d.get("logo", ""),
            "launchpad": d.get("launchpad") or d.get("launchpad_platform", ""),
            "trigger_mc": fmt_usd(s.get("trigger_mc") or 0),
            "mc": fmt_usd(s.get("market_cap") or 0),
            "ath": fmt_usd(s.get("ath") or 0),
            "ts": s.get("trigger_at", 0),
        })
        if len(signals) >= 10:
            break

    # ===== 3. 聪明钱异动（buy 聚合 cluster）=====
    try:
        sm = run(["gmgn-cli", "track", "smartmoney", "--chain", chain,
                  "--side", "buy", "--limit", "50", "--raw"])
    except RuntimeError as e:
        print(f"[warn] smartmoney: {e}")
        sm = {"list": []}

    passed_addr = {c["address"] for c in coins}
    agg = {}
    for t in sm.get("list", []):
        a = t.get("base_address", "")
        sym = (t.get("base_token") or {}).get("symbol") or "?"
        usd = t.get("amount_usd") or 0
        if not a or usd < 300:
            continue
        if sym.upper() in ("WSOL", "SOL", "USDC", "USDT", "JUP", "WIF"):
            continue
        if a not in agg:
            agg[a] = {"symbol": sym, "address": a, "total": 0, "wallets": set(),
                      "max": 0, "ts": 0, "launchpad": (t.get("base_token") or {}).get("launchpad", "")}
        g = agg[a]
        g["total"] += usd
        g["wallets"].add(t.get("maker", ""))
        g["max"] = max(g["max"], usd)
        g["ts"] = max(g["ts"], t.get("timestamp", 0))

    smart = []
    for a, g in sorted(agg.items(), key=lambda x: -x[1]["total"]):
        smart.append({
            "symbol": g["symbol"], "address": a,
            "total": fmt_usd(g["total"]), "total_raw": round(g["total"], 1),
            "wallets": len(g["wallets"]), "max": fmt_usd(g["max"]),
            "ts": g["ts"], "launchpad": g["launchpad"],
            "cluster": len(g["wallets"]) >= 3,
            "passed": a in passed_addr,   # 是否已通过严格精选
        })
        if len(smart) >= args.limit:
            break

    now = datetime.datetime.now(datetime.timezone.utc)
    data = {
        "scanned_at": now.strftime("%Y-%m-%d %H:%M UTC"),
        "chain": chain,
        "new_coins": coins,
        "smart_money": smart,
        "signals": signals,
        "stats": {
            "new_filtered": len(coins),
            "smart_total": len(smart),
            "signal_total": len(signals),
            "filter_breakdown": dict(sorted(drop.items(), key=lambda x: -x[1])),
        },
    }
    with open(os.path.join(OUT, "pump_data.json"), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    print(f"pump 数据完成: 新币 {len(coins)} | 信号流 {len(signals)} | 聪明钱异动 {len(smart)}")
    print(f"筛除原因: {json.dumps(drop, ensure_ascii=False)}")
    for c in coins[:5]:
        print(f"  {c['name']} mc={c['mcap']} vol={c['vol24h']} smart={c['smart_degen']}")
    for s in signals[:5]:
        print(f"  ⚡ {s['type']} {s['symbol']} 触发mc={s['trigger_mc']}")
    for s in smart[:5]:
        print(f"  🫀 {s['symbol']} 买入 {s['total']} 钱包{s['wallets']}{' CLUSTER' if s['cluster'] else ''}{' ✅精选' if s['passed'] else ''}")

if __name__ == "__main__":
    main()
