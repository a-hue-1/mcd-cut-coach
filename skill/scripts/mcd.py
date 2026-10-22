#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
mcd.py —— 麦当劳中国「热量 × 价格」点餐计算器

子命令：
  rank     按价格 / 热量 / 蛋白密度等维度排列餐品
  cut      减脂模式：给热量上限（+可选预算），输出推荐单品与套餐组合
  combo    计算指定几样东西的合计热量与总价
  compare  对比 2~N 个餐品
  price    补录/覆盖某城市门店的价格（写入 price-overrides.json）
  refresh  用 MCP 拉到的实时数据合并进本地数据集

示例：
  python mcd.py rank --sort price --cat 汉堡和卷
  python mcd.py rank --sort pd --min-protein 20 --top 10
  python mcd.py cut --kcal-cap 500 --budget 30
  python mcd.py cut --kcal-cap 400 --mode strict
  python mcd.py combo --items "板烧鸡腿堡,玉米杯(小),无糖可口可乐(中)"
  python mcd.py compare --items "巨无霸,麦辣鸡腿汉堡"
  python mcd.py price --set "板烧鸡腿堡=22.5,巨无霸=25.5"
  python mcd.py refresh --meals mcp_meals.json --nutrition mcp_nutrition.txt
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import re
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
DATA = BASE / "references" / "menu-nutrition.json"
OVERRIDES = BASE / "references" / "price-overrides.json"

ROLE_BY_CAT = {
    "汉堡和卷": "main",
    "小食": "side",
    "饮料": "drink",
    "甜品": "dessert",
    "早餐": "breakfast",
    "开心乐园餐": "kids",
    "McCafé": "drink",
}
ROLE_CN = {"main": "主食", "side": "小食/配餐", "drink": "饮料",
           "dessert": "甜品", "breakfast": "早餐", "kids": "儿童餐"}

SORT_KEYS = {
    "price": ("price", "价格"),
    "kcal": ("kcal", "热量"),
    "protein": ("protein", "蛋白质"),
    "fat": ("fat", "脂肪"),
    "carb": ("carb", "碳水"),
    "sodium": ("sodium", "钠"),
    "pd": ("protein_per_100kcal", "蛋白密度 g/100kcal"),
    "ppy": ("protein_per_yuan", "蛋白性价比 g/元"),
    "kpy": ("kcal_per_yuan", "热量/元"),
}

TAG_ICON = {"green": "🟢", "yellow": "🟡", "red": "🔴"}


# ---------------------------------------------------------------- 数据加载
def _parse_ov_key(k):
    """支持三种写法：'名称(规格)' / '名称|规格' / '名称'"""
    k = (k or "").strip()
    m = re.match(r"^(.*?)[（(]([^（）()]+)[）)]\s*$", k)
    if m:
        return norm(m.group(1)), norm(m.group(2))
    if "|" in k:
        a, b = k.split("|", 1)
        return norm(a), norm(b)
    return norm(k), None


def load():
    if not DATA.exists():
        sys.exit(f"数据集不存在：{DATA}")
    payload = json.loads(DATA.read_text(encoding="utf-8"))
    items = payload["items"]

    ov_spec, ov_name = {}, {}
    if OVERRIDES.exists():
        raw_ov = json.loads(OVERRIDES.read_text(encoding="utf-8")).get("prices", {})
        for k, v in raw_ov.items():
            nm, sp = _parse_ov_key(k)
            if sp:
                ov_spec[(nm, sp)] = v
            else:
                ov_name[nm] = v

    for it in items:
        it["role"] = ROLE_BY_CAT.get(it["category"], "other")
        nn, ss = norm(it["name"]), norm(it["spec"])
        if (nn, ss) in ov_spec:
            it["price"] = ov_spec[(nn, ss)]
            it["price_source"] = "override"
        elif nn in ov_name:
            it["price"] = ov_name[nn]
            it["price_source"] = "override"
    return payload, items


def fmt_px(it) -> str:
    if it["price"] is None:
        return "—"
    return f"¥{it['price']:.1f}" if it["price_source"] == "measured" else f"≈¥{it['price']:.1f}"


def label(it) -> str:
    s = it["spec"]
    if s and s not in ("默认", "1个", "1份", it["name"]):
        return f"{it['name']}({s})"
    return it["name"]


def find(items, q):
    q = q.strip().replace("（", "(").replace("）", ")")
    hits = [x for x in items if label(x).replace("（", "(").replace("）", ")") == q]
    if hits:
        return hits[0]
    hits = [x for x in items if q in label(x).replace("（", "(").replace("）", ")")]
    if hits:
        return hits[0]
    qn = q.replace(" ", "")
    hits = [x for x in items if qn in x["name"].replace(" ", "")]
    return hits[0] if hits else None


def num(v):
    return v if isinstance(v, (int, float)) else None


# ---------------------------------------------------------------- 表格输出
def cell(v, w, align="l"):
    s = str(v)
    # 中文字符按 2 宽度算
    disp = sum(2 if ord(c) > 127 else 1 for c in s)
    pad = max(0, w - disp)
    if align == "r":
        return " " * pad + s
    return s + " " * pad


def width(s):
    return sum(2 if ord(c) > 127 else 1 for c in str(s))


def table(rows, headers):
    widths = [max([width(r[i]) for r in rows] + [width(headers[i])])
              for i in range(len(headers))]
    line = "| " + " | ".join(str(h).ljust(widths[i]) for i, h in enumerate(headers)) + " |"
    sep = "| " + " | ".join("-" * widths[i] for i in range(len(headers))) + " |"
    out = [line, sep]
    for r in rows:
        out.append("| " + " | ".join(cell(c, widths[i]) for i, c in enumerate(r)) + " |")
    return "\n".join(out)


# ---------------------------------------------------------------- rank
def cmd_rank(a):
    payload, items = load()
    xs = list(items)

    if a.cat:
        xs = [x for x in xs if a.cat in x["category"]]
    if a.max_kcal is not None:
        xs = [x for x in xs if (x["kcal"] or 0) <= a.max_kcal]
    if a.min_kcal is not None:
        xs = [x for x in xs if (x["kcal"] or 0) >= a.min_kcal]
    if a.min_protein is not None:
        xs = [x for x in xs if (x["protein"] or 0) >= a.min_protein]
    if a.max_sodium is not None:
        xs = [x for x in xs if (x["sodium"] or 0) <= a.max_sodium]
    if a.max_price is not None:
        xs = [x for x in xs if x["price"] is not None and x["price"] <= a.max_price]
    if a.tag:
        xs = [x for x in xs if x["cut_tag"] == a.tag]

    key, kname = SORT_KEYS[a.sort]
    # 缺省方向：价格/热量/钠 升序更自然；蛋白相关降序更自然
    desc = a.desc if a.desc is not None else (a.sort in ("protein", "pd", "ppy", "kpy"))

    def sk(x):
        v = num(x.get(key))
        return (v is None, -(v or 0) if desc else (v or 0), x["kcal"] or 0)

    xs.sort(key=sk)
    if a.top:
        xs = xs[:a.top]

    headers = ["#", "餐品", "规格", "价格", "热量 kcal", "蛋白 g", "脂肪 g", "碳水 g", "钠 mg",
               "g蛋白/100kcal", "g蛋白/元", "灯"]
    rows = []
    for i, x in enumerate(xs, 1):
        rows.append([
            i, x["name"], x["spec"] or "-", fmt_px(x), x["kcal"] if x["kcal"] is not None else "-",
            x["protein"] if x["protein"] is not None else "-", x["fat"] if x["fat"] is not None else "-",
            x["carb"] if x["carb"] is not None else "-", x["sodium"] if x["sodium"] is not None else "-",
            x["protein_per_100kcal"] if x["protein_per_100kcal"] is not None else "-",
            x["protein_per_yuan"] if x["protein_per_yuan"] is not None else "-",
            TAG_ICON.get(x["cut_tag"], ""),
        ])

    if a.json:
        print(json.dumps(xs, ensure_ascii=False, indent=2))
        return
    print(f"排序维度：{kname}（{'降序' if desc else '升序'}）· 命中 {len(rows)} 项")
    print(table(rows, headers))
    print("\n价格说明：¥ = 官方 MCP 实测价（门店 1420227，2026-10-16）；≈¥ = 公开网页参考价；— = 待补录")
    print("提示：配好 mcd-mcp 后说「刷新麦当劳数据」，可把本地价格换成你所在门店的实时价。")


# ---------------------------------------------------------------- cut（减脂）
def cmd_cut(a):
    payload, items = load()
    cap = a.kcal_cap
    budget = a.budget
    min_prot = a.min_protein

    roles = ("main", "breakfast") if getattr(a, "breakfast", False) else ("main",)
    mains = [x for x in items if x["role"] in roles]
    sides = [x for x in items if x["role"] in ("side", "dessert")]
    drinks = [x for x in items if x["role"] == "drink"]

    # ---- A. 单品榜
    sod_cap = 1000 if a.mode == "strict" else None

    def ok(parts):
        if (sum((p["kcal"] or 0) for p in parts)) > cap:
            return False
        if (sum((p["protein"] or 0) for p in parts)) < min_prot:
            return False
        if sod_cap is not None and sum((p["sodium"] or 0) for p in parts) > sod_cap:
            return False
        return True

    singles = [x for x in mains + [s for s in sides if (s["protein"] or 0) >= 8]
               if ok([x])]
    singles.sort(key=lambda x: (-(x["protein_per_100kcal"] or 0), x["kcal"] or 0))
    singles = singles[:a.top]

    # ---- B. 组合榜：主食 + 小食/不加 + 饮料
    combos = []
    side_opts = [None] + sides
    drink_opts = [None] + drinks
    for m in mains:
        for s in side_opts:
            for d in drink_opts:
                parts = [p for p in (m, s, d) if p]
                if len(parts) < 2:
                    continue
                k = sum((p["kcal"] or 0) for p in parts)
                if k > cap:
                    continue
                sod = sum((p["sodium"] or 0) for p in parts)
                if sod_cap is not None and sod > sod_cap:
                    continue
                pr = sum((p["protein"] or 0) for p in parts)
                prices = [p["price"] for p in parts]
                total = None if any(p is None for p in prices) else round(sum(prices), 2)
                combos.append({
                    "parts": parts, "kcal": k, "protein": round(pr, 1),
                    "fat": round(sum((p["fat"] or 0) for p in parts), 1),
                    "sodium": round(sum((p["sodium"] or 0) for p in parts)),
                    "price": total,
                    "pd": round(pr / k * 100, 1) if k else None,
                })

    def _pick(mp, bp):
        out = [c for c in combos
               if c["protein"] >= mp
               and (bp is None or (c["price"] is not None and c["price"] <= bp))]
        out.sort(key=lambda c: (c["price"] is None, c["price"] or 0, c["kcal"]))
        return out

    priced = _pick(min_prot, budget)
    relax_parts = []
    if not priced and budget is not None:                 # 先放宽预算
        priced = _pick(min_prot, budget + 10)
        if priced:
            relax_parts.append(f"预算 ≤ ¥{budget + 10}")
    if not priced and min_prot > 15:                      # 再放宽蛋白
        p2 = max(10, min_prot - 5)
        priced = _pick(p2, budget)
        if priced:
            relax_parts.append(f"蛋白 ≥ {p2} g")

    unpriced = [c for c in combos if c["price"] is None and c["protein"] >= min_prot]
    unpriced.sort(key=lambda c: (-(c["pd"] or 0), c["kcal"]))

    if a.json:
        print(json.dumps({"singles": singles,
                          "combos_priced": priced[:a.top * 2],
                          "combos_unpriced": unpriced[:a.top]},
                         ensure_ascii=False, indent=2, default=str))
        return

    print("=" * 78)
    print(f"减脂点餐方案 · 单餐热量上限 {cap} kcal · 蛋白下限 {min_prot} g"
          + (f" · 预算 ≤ ¥{budget}" if budget else ""))
    print("=" * 78)

    print("\n【A】单点推荐（满足上限，按「蛋白密度」排，越靠前越抗饿）")
    if singles:
        rows = [[i, x["name"], x["spec"] or "-", fmt_px(x), x["kcal"], x["protein"], x["fat"],
                 x["protein_per_100kcal"], TAG_ICON.get(x["cut_tag"], "")]
                for i, x in enumerate(singles, 1)]
        print(table(rows, ["#", "餐品", "规格", "价格", "kcal", "蛋白", "脂肪", "g蛋白/100kcal", "灯"]))
    else:
        print("  无符合条件单品，试试放宽 --kcal-cap 或降低 --min-protein")

    print("\n【B】套餐组合（主食 + 小食/甜品 + 饮料，按价格升序）")
    top = priced[:a.top * 2]
    if top:
        if relax_parts:
            print("  ⚠ 原约束下无可行组合，已自动放宽为：" + "、".join(relax_parts))
        rows = []
        for i, c in enumerate(top, 1):
            rows.append([i, " + ".join(label(p) for p in c["parts"]),
                         (f"¥{c['price']:.1f}" if c["price"] is not None else "—"),
                         c["kcal"], c["protein"], c["fat"], c["sodium"], c["pd"]])
        print(table(rows, ["#", "组合", "总价", "kcal", "蛋白", "脂肪", "钠 mg", "g蛋白/100kcal"]))
    else:
        print("  当前约束下无可行组合，试试放宽 --kcal-cap 或 --budget，或降低 --min-protein。")

    if unpriced and not a.json:
        print(f"\n【C】待询价组合 {len(unpriced)} 个（热量达标，但缺价格，按蛋白密度排前 {min(a.top, len(unpriced))}）")
        rows = []
        for i, c in enumerate(unpriced[:a.top], 1):
            rows.append([i, " + ".join(label(p) for p in c["parts"]), c["kcal"], c["protein"],
                         c["sodium"], c["pd"]])
        print(table(rows, ["#", "组合", "kcal", "蛋白", "钠 mg", "g蛋白/100kcal"]))

    print("\n" + "-" * 78)
    print("减脂铁律（详见 references/cut-playbook.md）：")
    print("  1. 饮料换无糖/水/黑咖：一餐立省 100~220 kcal")
    print("  2. 薯条降级：大→中→小→迷你/玉米杯；薯条钠不高但油多")
    print("  3. 钠警戒：单品 >1000 mg 或整餐 >1500 mg 当天其余两餐必须控盐")
    print("  4. 别为省 5 毛硬上套餐：先算单点差价，再看是否需要捆绑的高热量配餐")


# ---------------------------------------------------------------- combo / compare
def _resolve(items, names):
    out, miss = [], []
    for n in names:
        hit = find(items, n)
        if hit is None:
            miss.append(n)
        else:
            out.append(hit)
    return out, miss


def cmd_combo(a):
    _, items = load()
    names = [x.strip() for x in a.items.split(",") if x.strip()]
    picked, miss = _resolve(items, names)
    if miss:
        print(f"未找到：{', '.join(miss)}（已忽略）", file=sys.stderr)
    if not picked:
        sys.exit("没有有效餐品")

    tot = {
        "kcal": sum(x["kcal"] or 0 for x in picked),
        "protein": sum(x["protein"] or 0 for x in picked),
        "fat": sum(x["fat"] or 0 for x in picked),
        "carb": sum(x["carb"] or 0 for x in picked),
        "sodium": sum(x["sodium"] or 0 for x in picked),
    }
    has_price = all(x["price"] is not None for x in picked)
    price = round(sum(x["price"] for x in picked), 2) if has_price else None

    if a.json:
        print(json.dumps({"items": [label(x) for x in picked], "totals": tot, "price": price},
                         ensure_ascii=False, indent=2))
        return

    rows = [[label(x), fmt_px(x), x["kcal"] or 0, x["protein"] or 0, x["fat"] or 0,
             x["carb"] or 0, x["sodium"] or 0] for x in picked]
    print(table(rows, ["餐品", "价格", "kcal", "蛋白", "脂肪", "碳水", "钠 mg"]))
    print("\n合计：" + " · ".join([
        f"{tot['kcal']} kcal", f"蛋白 {round(tot['protein'],1)} g",
        f"脂肪 {round(tot['fat'],1)} g", f"碳水 {round(tot['carb'],1)} g",
        f"钠 {round(tot['sodium'])} mg",
        (f"总价 ¥{price:.1f}" if price is not None else "总价 —（缺价格数据）"),
    ]))
    print(f"钠占每日推荐上限(2000mg)：{round(tot['sodium']/2000*100)}%")


def cmd_compare(a):
    _, items = load()
    names = [x.strip() for x in a.items.split(",") if x.strip()]
    picked, miss = _resolve(items, names)
    if miss:
        print(f"未找到：{', '.join(miss)}", file=sys.stderr)
    if len(picked) < 2:
        sys.exit("至少需要 2 个餐品")

    headers = ["指标"] + [label(x) for x in picked]
    metrics = [("价格", "price"), ("热量 kcal", "kcal"), ("蛋白 g", "protein"),
               ("脂肪 g", "fat"), ("碳水 g", "carb"), ("钠 mg", "sodium"),
               ("钙 mg", "calcium"), ("g蛋白/100kcal", "protein_per_100kcal"),
               ("g蛋白/元", "protein_per_yuan")]
    rows = []
    for cn, k in metrics:
        row = [cn]
        for x in picked:
            v = x.get(k)
            if v is None:
                row.append("—")
            elif k == "price":
                row.append(fmt_px(x))
            elif isinstance(v, float):
                row.append(round(v, 2))
            else:
                row.append(v)
        rows.append(row)
    rows.append(["减脂灯"] + [TAG_ICON.get(x["cut_tag"], "") for x in picked])
    print(table(rows, headers))

    best = max(picked, key=lambda x: x["protein_per_100kcal"] or 0)
    lowk = min(picked, key=lambda x: x["kcal"] or 0)
    print(f"\n蛋白密度最高：{label(best)}（{best['protein_per_100kcal']} g/100kcal）")
    print(f"热量最低：{label(lowk)}（{lowk['kcal']} kcal）")


# ---------------------------------------------------------------- price 补录
def cmd_price(a):
    ov = {"prices": {}}
    if OVERRIDES.exists():
        ov = json.loads(OVERRIDES.read_text(encoding="utf-8"))
    ov.setdefault("prices", {})

    if a.set:
        for seg in a.set.split(","):
            if "=" not in seg:
                continue
            k, v = seg.split("=", 1)
            try:
                ov["prices"][k.strip()] = float(v.strip())
            except ValueError:
                print(f"跳过无法解析：{seg}", file=sys.stderr)

    if a.show:
        for k, v in ov["prices"].items():
            print(f"{k} = ¥{v}")

    OVERRIDES.parent.mkdir(parents=True, exist_ok=True)
    OVERRIDES.write_text(json.dumps(ov, ensure_ascii=False, indent=2), encoding="utf-8")
    if a.set:
        print(f"已写入 {OVERRIDES}（当前 {len(ov['prices'])} 条覆盖）")


# ---------------------------------------------------------------- refresh（MCP 数据合并）
def parse_nutrition_text(text: str):
    """解析 list-nutrition-foods 返回的类 CSV 文本。"""
    rows = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("|"):
            continue
        try:
            cells = next(csv.reader(io.StringIO(line)))
        except Exception:
            continue
        if len(cells) < 6:
            continue
        def f(i):
            try:
                if i < len(cells) and cells[i] not in ("", "null", "None", "-"):
                    return float(cells[i])
            except ValueError:
                pass
            return None
        name = cells[0].strip()
        if not name or name.lower() in ("productname", "product_name"):
            continue
        rows.append({
            "name": name, "desc": cells[1] if len(cells) > 1 else None,
            "energy_kj": f(2), "kcal": f(3), "protein": f(4), "fat": f(5),
            "carb": f(6), "sodium": f(7), "calcium": f(8),
        })
    return rows


def parse_meals_json(obj):
    """解析 query-meals 返回：{data:{categories:[...], meals:{code:{name,currentPrice}}}}"""
    out = []
    data = obj.get("data", obj) if isinstance(obj, dict) else {}
    meals = data.get("meals", {}) if isinstance(data, dict) else {}
    cats = data.get("categories", []) if isinstance(data, dict) else []

    catmap = {}
    for c in cats or []:
        cname = c.get("name", "")
        for m in c.get("meals", []) or []:
            catmap[m.get("code")] = cname

    for code, info in (meals or {}).items():
        if not isinstance(info, dict):
            continue
        try:
            p = float(info.get("currentPrice") or 0) or None
        except (TypeError, ValueError):
            p = None
        out.append({
            "code": str(code), "name": info.get("name"),
            "price": p, "category": catmap.get(code, ""),
        })
    return out


def norm(s):
    return (s or "").replace("（", "(").replace("）", ")").replace(" ", "").strip()


def cmd_refresh(a):
    payload, items = load()
    stats = {"nutrition_updated": 0, "price_updated": 0, "new_items": 0}

    if a.nutrition:
        txt = Path(a.nutrition).read_text(encoding="utf-8", errors="ignore")
        nrows = parse_nutrition_text(txt)
        idx = {norm(x["name"]): x for x in items}
        for r in nrows:
            k = norm(r["name"])
            if k in idx:
                it = idx[k]
                for src, dst in (("kcal", "kcal"), ("protein", "protein"), ("fat", "fat"),
                                 ("carb", "carb"), ("sodium", "sodium"), ("calcium", "calcium"),
                                 ("energy_kj", "energy_kj")):
                    if r[src] is not None:
                        it[dst] = r[src]
                stats["nutrition_updated"] += 1
            else:
                items.append({
                    "name": r["name"], "spec": "", "category": "", "energy_kj": r["energy_kj"],
                    "kcal": r["kcal"], "protein": r["protein"], "fat": r["fat"], "carb": r["carb"],
                    "sodium": r["sodium"], "calcium": r["calcium"], "price": None,
                    "price_source": None, "role": "other", "cut_tag": "green",
                })
                stats["new_items"] += 1

    if a.meals:
        obj = json.loads(Path(a.meals).read_text(encoding="utf-8"))
        for m in parse_meals_json(obj):
            hit = find(items, m["name"]) if m["name"] else None
            if hit and m["price"]:
                hit["price"] = m["price"]
                hit["price_source"] = "measured"
                if m["category"]:
                    hit["category"] = m["category"]
                    hit["role"] = ROLE_BY_CAT.get(m["category"], "other")
                stats["price_updated"] += 1

    # 重算派生指标
    for it in items:
        k, p, pr = it.get("kcal") or 0, it.get("price"), it.get("protein") or 0
        it["protein_per_100kcal"] = round(pr / k * 100, 1) if k else None
        it["protein_per_yuan"] = round(pr / p, 2) if p else None
        it["kcal_per_yuan"] = round(k / p, 1) if p else None
        it["cut_tag"] = ("red" if (k >= 600 or (it.get("sodium") or 0) >= 1000 or (it.get("fat") or 0) >= 35)
                         else "yellow" if (k >= 450 or (it.get("sodium") or 0) >= 700 or (it.get("fat") or 0) >= 25)
                         else "green")

    payload["items"] = items
    payload["meta"]["count"] = len(items)
    if a.nutrition:
        payload["meta"]["nutrition_source"] = "麦当劳官方 MCP list-nutrition-foods 实时拉取（" + a.nutrition + "）"
    if a.meals:
        payload["meta"]["price_source"] = "麦当劳官方 MCP query-meals 实时拉取（" + a.meals + "）"
    DATA.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print("已更新", DATA)
    print(json.dumps(stats, ensure_ascii=False, indent=2))


# ---------------------------------------------------------------- CLI
def main():
    p = argparse.ArgumentParser(description="麦当劳中国 热量×价格 点餐计算器")
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("rank", help="按维度排列餐品")
    r.add_argument("--sort", default="kcal",
                   choices=list(SORT_KEYS), help="排序字段（默认 kcal）")
    r.add_argument("--desc", action="store_true", default=None, help="强制降序")
    r.add_argument("--asc", dest="desc", action="store_false", help="强制升序")
    r.add_argument("--cat", help="分类过滤，如 汉堡和卷 / 早餐 / 饮料")
    r.add_argument("--max-kcal", type=float)
    r.add_argument("--min-kcal", type=float)
    r.add_argument("--min-protein", type=float)
    r.add_argument("--max-sodium", type=float)
    r.add_argument("--max-price", type=float)
    r.add_argument("--tag", choices=["green", "yellow", "red"])
    r.add_argument("--top", type=int)
    r.add_argument("--json", action="store_true")
    r.set_defaults(func=cmd_rank)

    c = sub.add_parser("cut", help="减脂推荐")
    c.add_argument("--kcal-cap", type=float, default=500, help="单餐热量上限（默认 500）")
    c.add_argument("--budget", type=float, help="预算上限（元）")
    c.add_argument("--min-protein", type=float, default=20, help="蛋白下限（默认 20g）")
    c.add_argument("--mode", choices=["strict", "balanced"], default="balanced",
                   help="strict = 额外限制整餐钠 ≤ 1000mg")
    c.add_argument("--breakfast", action="store_true", help="把早餐主食也纳入组合枚举")
    c.add_argument("--top", type=int, default=5)
    c.add_argument("--json", action="store_true")
    c.set_defaults(func=cmd_cut)

    b = sub.add_parser("combo", help="合计任意组合")
    b.add_argument("--items", required=True, help="逗号分隔的餐品名")
    b.add_argument("--json", action="store_true")
    b.set_defaults(func=cmd_combo)

    cp = sub.add_parser("compare", help="对比餐品")
    cp.add_argument("--items", required=True, help="逗号分隔的餐品名")
    cp.set_defaults(func=cmd_compare)

    pr = sub.add_parser("price", help="按门店补录价格")
    pr.add_argument("--set", help='如 "板烧鸡腿堡=22.5,巨无霸=25.5"')
    pr.add_argument("--show", action="store_true")
    pr.set_defaults(func=cmd_price)

    rf = sub.add_parser("refresh", help="合并 MCP 实时数据")
    rf.add_argument("--meals", help="query-meals 原始 JSON 文件")
    rf.add_argument("--nutrition", help="list-nutrition-foods 返回的文本文件")
    rf.set_defaults(func=cmd_refresh)

    a = p.parse_args()
    a.func(a)


if __name__ == "__main__":
    main()
