#!/usr/bin/env python3
"""pump.md 数据管道：GMGN 五链三通道精华过滤版（v4：聪明钱融合评分版）
通道（每链）：
  1. trenches new_creation（新币池，smart-money preset）→ 严格精选
  2. trending 5m（实时热榜）→ 严格精选
  3. market signal（聪明钱买入12 / KOL买入20）+ track smartmoney（聪明钱聚合）
     → 合并为统一信号流（v3，诚顺 2026-08-24 要求：实时信号与聪明钱异动合并一个版本）

v4 融合（2026-08-27 诚顺定案）：
  - 门槛层升级：官网 + 推特 = 双门槛（电报不再算门槛）；市值区间 $1万-$1000万
  - 12 条评分引擎（token-score12.py）：门槛过后自动算 6 条 + 6 条未知待补
  - 评分写入 pump_data.json，前端展示 🛡 评分徽章
  - top10 安全线 40%（<20% 才在评分得分）

v3 遗留：
  - 信号合并：实时信号 + 聪明钱异动 → 统一信号流，触发徽章 + score 排序
  - 历史留存：retention 池每链 ≤20 条，last_seen 超 24h 滑出，跨 run 持久化
  - robinhood 链纳入默认五链

输出：data/pump/pump_data.json（by_chain + retention + 筛除统计 + score12）
用法: python3 pump_fetch.py [--chains sol,bsc,base,eth,robinhood] [--limit 8]
"""
import json, os, subprocess, sys, datetime, argparse, time

BASE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(BASE, "data", "pump")
os.makedirs(OUT, exist_ok=True)

# 评分引擎（v4 融合）：优先仓库内副本（云端 Actions），回退本地 ~/.hermes/scripts
_LOCAL_SCORE12 = os.path.expanduser("~/.hermes/scripts/token_score12.py")
if os.path.exists(os.path.join(BASE, "token_score12.py")):
    sys.path.insert(0, BASE)
elif os.path.exists(_LOCAL_SCORE12):
    sys.path.insert(0, os.path.dirname(_LOCAL_SCORE12))
import token_score12 as ts12

# 市值区间（2026-08-27 诚顺定：$1万-$1000万）
MC_MIN = ts12.MC_MIN
MC_MAX = ts12.MC_MAX

# signal 通道支持的链（GMGN 限定），其他链跳过信号流
SIGNAL_CHAINS = {"sol", "bsc", "robinhood", "arc"}

RETENTION_TTL = 24 * 3600   # 留存池过期：24h 未再出现即滑出
RETENTION_MAX = 20          # 每链留存上限（诚顺要求 ~20 个）
SIGNAL_MAX = 12             # 每链信号流上限（合并后）

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

def is_true(v):
    return v in (1, True, "1", "yes", "true")

def is_false(v):
    return v in (0, False, "0", "no", "false")

# ===== 精选过滤器（v4：走评分引擎门槛层）=====
def quality_filter(c, chain):
    """返回 (是否通过, 未通过原因列表)。门槛层=评分引擎 gates_check：官网+推特 / 权限 / 黑幕 / 技术 / 市值区间"""
    passed, ok, fail = ts12.gates_check(c, chain)
    if passed and fail:
        pass  # fail 不应在 passed 时出现，防御
    return (passed, fail)

def to_coin(c, chain):
    """精选通过的 token → 展示结构（v4：带 12 条评分）"""
    mc = c.get("market_cap") or c.get("usd_market_cap") or 0
    vol = c.get("volume_24h") or c.get("volume") or 0
    created = c.get("created_timestamp") or c.get("creation_timestamp") or int(time.time())
    s = ts12.score_token(c, chain)
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
        # v4：12 条评分（自动可算 6 条 + 未知待补 6 条）
        "score12": {
            "score": s["score"],
            "auto_total": s["auto_total"],
            "unknown": s["unknown"],
            "grade": s["grade"],
            "detail": s["detail"],
        },
    }

def fetch_chain(chain, limit, drop):
    """抓取并精选单链数据，返回 {coins, signals, stats}（signals 为合并版统一信号流）"""
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
            print(f"[warn] {chain} {label}: {e}")
            continue
        items = raw.get("new_creation", []) if label == "trenches" else (raw.get("data") or {}).get("rank", [])
        pool.extend((label, c) for c in items)

    seen, coins = set(), []
    pool.sort(key=lambda x: (-(x[1].get("smart_degen_count") or 0), 0 if x[0] == "trenches" else 1))
    for label, c in pool:
        addr = c.get("address", "")
        if not addr or addr in seen:
            continue
        mc = c.get("market_cap") or c.get("usd_market_cap") or 0
        if not (MC_MIN <= mc <= MC_MAX):
            # 市值区间外（v4：$1万-$1000万，2026-08-27 诚顺定）
            if mc < MC_MIN:
                note_drops(["市值过低(<1万)"])
            else:
                note_drops(["市值过高(>1000万)"])
            continue
        ok, reasons = quality_filter(c, chain)
        if not ok:
            note_drops(reasons)
            continue
        seen.add(addr)
        coins.append(to_coin(c, chain))
        if len(coins) >= limit:
            break

    # ===== 2+3. 统一信号流（v3）：market signal（12/20）+ smartmoney 聚合 → 合并 =====
    signals_map = {}  # address -> 信号条目

    def sig_seed(addr, d, s):
        """新建/复用信号条目骨架"""
        tw = d.get("twitter_handle") or d.get("twitter_username") or d.get("twitter") or ""
        if tw and ("/status/" in tw or (tw.startswith("http") and "x.com" not in tw and "twitter.com" not in tw)):
            tw = ""
        web = d.get("website") or ""
        if web and ("x.com" in web or "twitter.com" in web):
            web = ""
        return signals_map.setdefault(addr, {
            "symbol": d.get("symbol") or addr[:6],
            "name": d.get("name", ""),
            "address": addr,
            "logo": d.get("logo", ""),
            "launchpad": d.get("launchpad") or d.get("launchpad_platform", ""),
            "src": [], "wallets": 0, "buy_total_raw": 0.0,
            "mc_raw": float(s.get("market_cap") or 0),
            "trigger_mc": float(s.get("trigger_mc") or 0),
            "ath": float(s.get("ath") or 0),
            "ts": int(s.get("trigger_at") or 0) or int(s.get("timestamp") or 0),
            "age_min": None, "passed": False,
            "social": {"twitter": tw, "website": web},
            "liquidity": float(d.get("liquidity") or 0),
            "vol": float(d.get("volume_24h") or d.get("volume") or 0),
        })

    if chain in SIGNAL_CHAINS:
        try:
            sig = run(["gmgn-cli", "market", "signal", "--chain", chain,
                       "--signal-type", "12", "--signal-type", "20", "--raw"])
        except RuntimeError as e:
            print(f"[warn] {chain} signal: {e}")
            sig = []
        sig_map = {12: "聪明钱", 20: "KOL"}
        for s in (sig or []):
            d = s.get("data") or {}
            t = s.get("signal_type")
            if t not in sig_map:
                continue
            addr = s.get("token_address", "")
            if not addr:
                continue
            ok, reasons = quality_filter(d, chain)
            if not ok:
                note_drops([f"信号源:{reasons[0]}"])
                continue
            g = sig_seed(addr, d, s)
            if sig_map[t] not in g["src"]:
                g["src"].append(sig_map[t])
            created = d.get("created_timestamp") or d.get("creation_timestamp") or 0
            if created:
                g["age_min"] = max(1, int((time.time() - created) / 60))

    # smartmoney buy 聚合（cluster 检测）
    try:
        sm = run(["gmgn-cli", "track", "smartmoney", "--chain", chain,
                  "--side", "buy", "--limit", "50", "--raw"])
    except RuntimeError as e:
        print(f"[warn] {chain} smartmoney: {e}")
        sm = {"list": []}

    agg = {}
    for t in sm.get("list", []):
        a = t.get("base_address", "")
        sym = (t.get("base_token") or {}).get("symbol") or "?"
        usd = t.get("amount_usd") or 0
        if not a or usd < 300:
            continue
        if sym.upper() in ("WSOL", "SOL", "USDC", "USDT", "JUP", "WIF", "WBNB", "BNB", "WETH", "ETH", "WBTC", "BTC"):
            continue
        if a not in agg:
            agg[a] = {"symbol": sym, "address": a, "total": 0, "wallets": set(),
                      "max": 0, "ts": 0, "launchpad": (t.get("base_token") or {}).get("launchpad", "")}
        g = agg[a]
        g["total"] += usd
        g["wallets"].add(t.get("maker", ""))
        g["max"] = max(g["max"], usd)
        g["ts"] = max(g["ts"], t.get("timestamp", 0))

    for a, g in sorted(agg.items(), key=lambda x: -x[1]["total"]):
        ent = signals_map.setdefault(a, {
            "symbol": g["symbol"], "name": "", "address": a, "logo": "",
            "launchpad": g["launchpad"], "src": [], "wallets": 0, "buy_total_raw": 0.0,
            "mc_raw": 0.0, "trigger_mc": 0.0, "ath": 0.0,
            "ts": g["ts"], "age_min": None, "passed": False,
            "social": {"twitter": "", "website": ""},
            "liquidity": 0.0, "vol": 0.0,
        })
        if "聪明钱聚合" not in ent["src"]:
            ent["src"].append("聪明钱聚合")
        ent["wallets"] = max(ent["wallets"], len(g["wallets"]))
        ent["buy_total_raw"] += g["total"]
        ent["ts"] = max(ent["ts"], g["ts"])

    # 统一触发徽章 + score（v3 规则，诚顺 2026-08-24 定案）
    passed_addr = {c["address"] for c in coins}
    signals = []
    for addr, g in signals_map.items():
        g["passed"] = addr in passed_addr
        triggers, score = [], 0
        n = g["wallets"]
        if n >= 3:
            triggers.append(f"🐋聪明钱×{n} cluster")
            score += 3
        elif n >= 1:
            triggers.append(f"🐋聪明钱×{n}")
            score += n
        if "聪明钱" in g["src"] and n == 0:
            triggers.append("🐋聪明钱买入")
            score += 2
        if "KOL" in g["src"]:
            triggers.append("🔥KOL买入")
            score += 1
        if g["mc_raw"] and g["mc_raw"] < 5_000_000:
            triggers.append("💰市值<500万")
            score += 1
        if g["age_min"] is not None and g["age_min"] <= 1440:
            triggers.append(f"🆕上线{g['age_min']}分钟")
            score += 1
        if g["passed"]:
            triggers.append("✅已过精选")
            score += 2
        g["triggers"] = triggers
        g["score"] = score
        g["mc"] = fmt_usd(g["mc_raw"])
        g["buy_total"] = fmt_usd(g["buy_total_raw"])
        g["src"] = "/".join(g["src"]) or "未知"
        # v4：信号流也补 12 条评分（字段缺则自动 unknown，不硬编）
        s = ts12.score_token({
            "market_cap": g.get("mc_raw") or 0,
            "liquidity": g.get("liquidity") or 0,
            "volume_24h": g.get("vol") or 0,
            "twitter_handle": (g.get("social") or {}).get("twitter") or "",
            "website": (g.get("social") or {}).get("website") or "",
        }, chain)
        g["score12"] = {
            "score": s["score"],
            "auto_total": s["auto_total"],
            "unknown": s["unknown"],
            "grade": s["grade"],
            "detail": s["detail"],
        }
        signals.append(g)

    signals.sort(key=lambda x: (-x["score"], -x["ts"]))
    signals = signals[:SIGNAL_MAX]

    return {
        "chain": chain,
        "new_coins": coins,
        "signals": signals,
        "stats": {
            "new_filtered": len(coins),
            "signal_total": len(signals),
        },
    }

def merge_retention(chain, res, old_ret, now):
    """本轮精选 coins 合并进留存池：去重/刷新 last_seen/24h 过期，返回 ≤RETENTION_MAX 条"""
    merged = {}
    for c in res["new_coins"]:
        c["latest"] = True
        c["last_seen"] = now
        merged[c["address"]] = c
    for r in (old_ret or []):
        if r.get("address") in merged:
            continue
        if now - (r.get("last_seen") or 0) > RETENTION_TTL:
            continue
        r["latest"] = False
        merged[r["address"]] = r
    out = sorted(merged.values(), key=lambda x: -(x.get("last_seen") or 0))
    return out[:RETENTION_MAX]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--chains", default="sol,bsc,base,eth,robinhood")
    ap.add_argument("--limit", type=int, default=8)
    args = ap.parse_args()
    chains = [c.strip() for c in args.chains.split(",") if c.strip()]
    drop = {}   # 全链筛除原因统计
    now = int(time.time())

    # 读旧数据：跨 run 持久化留存池
    old_data = {}
    old_path = os.path.join(OUT, "pump_data.json")
    if os.path.exists(old_path):
        try:
            with open(old_path, encoding="utf-8") as f:
                old_data = json.load(f)
        except Exception as e:
            print(f"[warn] 旧数据读取失败: {e}")

    by_chain = {}
    for chain in chains:
        try:
            res = fetch_chain(chain, args.limit, drop)
        except Exception as e:
            print(f"[warn] {chain} 失败: {e}")
            continue
        old_ret = ((old_data.get("by_chain") or {}).get(chain) or {}).get("retention")
        res["retention"] = merge_retention(chain, res, old_ret, now)
        by_chain[chain] = res
        print(f"  {chain}: 新币 {res['stats']['new_filtered']} | 信号 {res['stats']['signal_total']} | 留存 {len(res['retention'])}")

    now_dt = datetime.datetime.now(datetime.timezone.utc)
    total_coins = sum(len(v["new_coins"]) for v in by_chain.values())
    total_signals = sum(len(v["signals"]) for v in by_chain.values())
    total_ret = sum(len(v["retention"]) for v in by_chain.values())
    data = {
        "scanned_at": now_dt.strftime("%Y-%m-%d %H:%M UTC"),
        "chains": list(by_chain.keys()),
        "by_chain": by_chain,
        "stats": {
            "new_filtered": total_coins,
            "signal_total": total_signals,
            "retention_total": total_ret,
            "filter_breakdown": dict(sorted(drop.items(), key=lambda x: -x[1])),
        },
    }
    with open(old_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    print(f"pump 多链完成: 新币 {total_coins} | 信号流 {total_signals} | 留存池 {total_ret} | 链 {list(by_chain.keys())}")
    print(f"筛除原因: {json.dumps(drop, ensure_ascii=False)}")
    for ch, res in by_chain.items():
        for c in res["new_coins"][:3]:
            print(f"  [{ch}] {c['name']} mc={c['mcap']} vol={c['vol24h']} smart={c['smart_degen']}")

if __name__ == "__main__":
    main()
