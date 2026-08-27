#!/usr/bin/env python3
"""token-score12.py —— 12 条评分引擎（聪明钱融合版 v3 核心模块）

诚顺 12 条评分（是=1 分）+ 融合版门槛层：
  门槛层（一票否决，不过直接出局）：
    1. 官网存在 + 推特存在（2026-08-27 诚顺定：官网+推特=门槛，然后才是推特质量）
    2. 权限干净：SOL 铸币权+冻结权双放弃；EVM 非貔貅+所有权放弃+开源
    3. 无黑幕：非洗盘、rug≤0.3、bundler≤0.3、老鼠仓≤0.3、top10<40%（安全线按场景调）
    4. 无技术问题：非 honeypot、税率≤10%
    5. 市值 $1万-$1000万（2026-08-27 诚顺定）
  评分层（0-12 分，自动可算 + 未知待补）：
    自动可算 6 条：1 池子>$3万 / 3 铸币关 / 4 冻结关 / 5 top10<20%(加分) / 6 分布干净 / 11 量≥流动性一半
    未知待补 6 条：2 流动性锁定 / 7 开发者无弃币史 / 8 社交>1周 / 9 粉丝真实 /
                   10 持有者24h增 / 12 一句话故事（agent/人工补判，补不了标 unknown 不计分）

用法：
  from token_score12 import score_token
  r = score_token(token_dict, chain)
  r = {"gates": ["官网+推特", "权限干净", ...], "passed": True/False,
       "score": 5, "auto_total": 6, "unknown": ["流动性锁定", ...],
       "detail": [{"k": "池子>$3万", "v": 1}, ...], "grade": "B"}

独立运行: python3 token-score12.py <json_file> [chain]   # 对单个 token json 打分
"""
import json, os, sys

# ===== 市值区间（2026-08-27 诚顺定：$1万 - $1000万）=====
MC_MIN = 10_000
MC_MAX = 10_000_000

# 自动可算条目的键名（detail 顺序与 12 条原文一致）
AUTO_KEYS = {
    1: "池子>$3万",
    3: "铸币权限关闭",
    4: "冻结权限关闭",
    5: "前10持有<20%",
    6: "钱包分布干净",
    11: "量≥流动性一半",
}
UNKNOWN_KEYS = {
    2: "流动性锁定",
    7: "开发者无弃币史",
    8: "社交>1周",
    9: "粉丝真实",
    10: "持有者24h增",
    12: "一句话故事",
}


def is_true(v):
    return v in (1, True, "1", "yes", "true")


def is_false(v):
    return v in (0, False, "0", "no", "false")


def _num(v, default=0.0):
    try:
        return float(v or default)
    except (TypeError, ValueError):
        return default


def _clean_twitter(v):
    if not v:
        return ""
    v = str(v).strip()
    if "/status/" in v or v.startswith("http") and "x.com" not in v and "twitter.com" not in v:
        return ""
    return v


def _clean_website(v):
    if not v:
        return ""
    v = str(v).strip()
    if "x.com" in v or "twitter.com" in v:
        return ""  # 官网字段混入推特链接 = 假官网
    return v


def gates_check(c, chain):
    """门槛层（一票否决），返回 (passed, gates_ok列表, gates_fail列表)"""
    ok, fail = [], []

    # 1. 官网 + 推特门槛（2026-08-27 诚顺定）
    tw = _clean_twitter(c.get("twitter_handle") or c.get("twitter") or c.get("twitter_username") or "")
    web = _clean_website(c.get("website") or "")
    if tw and web:
        ok.append("官网+推特")
    else:
        fail.append("缺官网或推特" + ("" if web else " (无官网)") + ("" if tw else " (无推特)"))

    # 2. 权限干净
    if chain == "sol":
        if is_false(c.get("renounced_mint")):
            fail.append("铸币权未放弃")
        else:
            ok.append("权限干净(SOL)")
        if is_false(c.get("renounced_freeze_account")):
            fail.append("冻结权未放弃")
        else:
            ok.append("冻结权关闭")
    else:
        if is_true(c.get("is_honeypot")) or is_true(c.get("honeypot")):
            fail.append("貔貅盘")
        elif is_false(c.get("is_renounced")) and is_false(c.get("owner_renounced")):
            fail.append("所有权未放弃")
        else:
            ok.append("权限干净(EVM)")
        if is_false(c.get("is_open_source")) and is_false(c.get("open_source")):
            fail.append("合约不开源")

    # 3. 无黑幕（top10 安全线 40%，2026-08-27 诚顺拍板：<40% 安全，<20% 才在评分得分）
    if is_true(c.get("is_wash_trading")):
        fail.append("疑似洗盘")
    if _num(c.get("rug_ratio")) > 0.3:
        fail.append(f"rug风险{_num(c.get('rug_ratio')):.2f}")
    if max(_num(c.get("bundler_rate")), _num(c.get("bundler_trader_amount_rate"))) > 0.3:
        fail.append("bundler集中")
    if _num(c.get("rat_trader_amount_rate")) > 0.3:
        fail.append("老鼠仓占比高")
    if _num(c.get("top_10_holder_rate")) > 0.4:
        fail.append("筹码集中>40%")
    if not fail and len(fail) == 0:
        ok.append("无黑幕")

    # 4. 无技术问题
    if _num(c.get("buy_tax")) > 0.10 or _num(c.get("sell_tax")) > 0.10:
        fail.append("税率过高")
    else:
        ok.append("税率健康")

    # 5. 市值区间 $1万-$1000万
    mc = _num(c.get("market_cap") or c.get("usd_market_cap"))
    if mc and not (MC_MIN <= mc <= MC_MAX):
        fail.append(f"市值超区间(${mc/1000:.0f}K)")
    else:
        ok.append("市值区间")

    # 去重 ok（避免同一类重复计数）
    ok = list(dict.fromkeys(ok))
    fail = list(dict.fromkeys(fail))
    return (len(fail) == 0, ok, fail)


def score_token(c, chain="sol"):
    """对单个 token 打分。返回完整评分结构。"""
    passed, gates_ok, gates_fail = gates_check(c, chain)
    detail, score, unknown = [], 0, []

    # 自动可算条目
    mc = _num(c.get("market_cap") or c.get("usd_market_cap"))
    liq = _num(c.get("liquidity"))
    vol = _num(c.get("volume_24h") or c.get("volume"))
    top10 = _num(c.get("top_10_holder_rate"))
    bundler = max(_num(c.get("bundler_rate")), _num(c.get("bundler_trader_amount_rate")))
    rat = _num(c.get("rat_trader_amount_rate"))

    def add(k, v):
        detail.append({"k": k, "v": v})

    # 1 池子>$3万
    add("池子>$3万", 1 if liq > 30_000 else 0)
    score += 1 if liq > 30_000 else 0

    # 3 铸币权限关闭
    if chain == "sol":
        mint_off = is_true(c.get("renounced_mint"))
        add("铸币权限关闭", 1 if mint_off else 0)
        score += 1 if mint_off else 0
    else:
        ren = is_true(c.get("is_renounced")) or is_true(c.get("owner_renounced"))
        add("铸币权限关闭", 1 if ren else 0)
        score += 1 if ren else 0

    # 4 冻结权限关闭（SOL）
    if chain == "sol":
        frz = is_true(c.get("renounced_freeze_account"))
        add("冻结权限关闭", 1 if frz else 0)
        score += 1 if frz else 0
    else:
        add("冻结权限关闭", None)
        unknown.append("冻结权限关闭(EVM无字段)")

    # 5 前10<20%（安全线 40%，评分加分 20%）
    v5 = 1 if top10 < 0.2 else 0
    add("前10持有<20%", v5)
    score += v5

    # 6 钱包分布干净（门槛 0.3，评分要 0.1 才算干净）
    v6 = 1 if max(bundler, rat) <= 0.1 else 0
    add("钱包分布干净", v6)
    score += v6

    # 11 量≥流动性一半
    v11 = 1 if liq > 0 and vol >= liq * 0.5 else 0
    add("量≥流动性一半", v11)
    score += v11

    # 未知待补条目
    for k in UNKNOWN_KEYS.values():
        unknown.append(k)
        detail.append({"k": k, "v": None})

    # 分档（v4：自动层 6 分制映射；完整 12 分档需 agent 补判 6 条后另行评估）
    #   6/6 自动全绿=A 罕见 · 4-5=B 干净 · 2-3=C 有风险 · 0-1=D 待观察
    grade = "D"
    if score >= 6:
        grade = "A"
    elif score >= 4:
        grade = "B"
    elif score >= 2:
        grade = "C"

    return {
        "passed": passed,
        "gates_ok": gates_ok,
        "gates_fail": gates_fail,
        "score": score,
        "auto_total": 6,
        "unknown": unknown,
        "detail": detail,
        "grade": grade,
        "mc": mc,
        "liq": liq,
        "vol": vol,
        "top10": top10,
        "bundler": bundler,
        "rat": rat,
    }


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python3 token-score12.py <token.json> [chain]")
        sys.exit(1)
    with open(sys.argv[1]) as f:
        tok = json.load(f)
    ch = sys.argv[2] if len(sys.argv) > 2 else "sol"
    r = score_token(tok, ch)
    print(json.dumps(r, ensure_ascii=False, indent=2))
