#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_report.py —— 生成「控卡点餐速查表」单文件 HTML 报告

用法：
    python skill/scripts/build_report.py -o examples/cut-guide.html
    python skill/scripts/build_report.py --kcal-cap 500 --budget 40

产出为单文件 HTML：零外部依赖、可直接分享、离线可用。
视觉采用浅色护眼底色。
"""
from __future__ import annotations

import argparse
import html
import json
import sys
from datetime import datetime
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import mcd  # noqa: E402


def esc(s) -> str:
    return html.escape(str(s if s is not None else ""))


def px(it) -> str:
    return mcd.fmt_px(it)


def tag(it) -> str:
    return mcd.TAG_ICON.get(it.get("cut_tag"), "")


def css() -> str:
    return """
:root{
  --bg:#f6f3ee; --card:#fffdf9; --ink:#2f2a24; --ink2:#6b6257;
  --line:#e4ddd2; --accent:#c8442b; --accent2:#2f6f4e; --accent3:#b8862b;
  --green:#3f8f5f; --yellow:#c99a2e; --red:#c8442b;
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
  font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;
  line-height:1.6;-webkit-font-smoothing:antialiased}
.wrap{max-width:1080px;margin:0 auto;padding:32px 20px 64px}
header{background:var(--card);border:1px solid var(--line);border-radius:14px;
  padding:28px 28px 22px;margin-bottom:22px}
h1{margin:0 0 6px;font-size:26px;letter-spacing:.5px}
.sub{color:var(--ink2);font-size:14px;margin:0}
.meta{margin-top:14px;font-size:12px;color:var(--ink2);
  border-top:1px dashed var(--line);padding-top:12px}
h2{font-size:18px;margin:28px 0 12px;display:flex;align-items:center;gap:8px}
h2::before{content:"";width:4px;height:16px;background:var(--accent);border-radius:2px}
.lead{color:var(--ink2);font-size:13px;margin:-4px 0 12px}
table{width:100%;border-collapse:collapse;background:var(--card);
  border:1px solid var(--line);border-radius:10px;overflow:hidden;font-size:13px}
th,td{padding:9px 10px;text-align:left;border-bottom:1px solid var(--line)}
th{background:#efe9e0;font-weight:700;font-size:12px;color:var(--ink2);white-space:nowrap}
tr:last-child td{border-bottom:none}
tbody tr:hover{background:#fbf7f1}
td.num,th.num{text-align:right;font-variant-numeric:tabular-nums}
.sec{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:18px 20px;margin-bottom:18px}
ol,ul{padding-left:20px;margin:8px 0}
li{margin:4px 0;font-size:14px}
.legend{display:flex;gap:16px;flex-wrap:wrap;font-size:13px;color:var(--ink2)}
.legend span{display:inline-flex;align-items:center;gap:5px}
.tip{background:#f2f6f3;border-left:3px solid var(--accent2);
  padding:10px 14px;border-radius:6px;font-size:13px;margin:12px 0}
.warn{background:#fdf4ee;border-left:3px solid var(--accent);
  padding:10px 14px;border-radius:6px;font-size:13px;margin:12px 0}
footer{margin-top:34px;padding-top:16px;border-top:1px solid var(--line);
  font-size:12px;color:var(--ink2)}
code{background:#efe9e0;padding:1px 5px;border-radius:4px;font-size:12px}
.bar{display:inline-block;height:6px;border-radius:3px;background:var(--accent3);vertical-align:middle}
"""


def build(items, payload, cap, budget, min_prot):
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    meta = payload.get("meta", {})
    priced = [x for x in items if x.get("price") is not None]

    # 单品榜：热量达标 + 蛋白达标 + 预算达标，按蛋白密度降序
    pool = [x for x in items
            if (x.get("kcal") or 9999) <= cap
            and (x.get("protein") or 0) >= min_prot
            and (budget is None or (x.get("price") is not None and x["price"] <= budget))]
    pool.sort(key=lambda x: (-(x.get("protein_per_100kcal") or 0), x.get("kcal") or 0))
    singles = pool[:8]

    # 价格升序榜
    by_price = sorted(priced, key=lambda x: (x["price"], x.get("kcal") or 0))[:10]

    h = []
    h.append("<!DOCTYPE html><html lang=\"zh-CN\"><head><meta charset=\"utf-8\">")
    h.append("<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">")
    h.append("<title>麦麦控卡教练 · 控卡点餐速查表</title>")
    h.append(f"<style>{css()}</style></head><body><div class=\"wrap\">")

    # Header
    h.append("<header>")
    h.append("<h1>🍔 麦麦控卡教练 · 控卡点餐速查表</h1>")
    h.append("<p class=\"sub\">身材管理期也能安心吃麦当劳 —— 热量、蛋白质、钠三指标并排看，避免「低卡高钠」陷阱。</p>")
    h.append("<div class=\"meta\">")
    h.append(f"生成时间：{esc(now)}　|　餐品数：{esc(meta.get('count', len(items)))} 项　|　"
             f"有价格：{len(priced)} 项<br>")
    h.append("营养数据来源：麦当劳官方 MCP <code>list-nutrition-foods</code>；"
             "价格来源：官方 MCP <code>query-meals</code>（门店 1420227）</div>")
    h.append("</header>")

    # 减脂铁律
    h.append("<h2>减脂点餐四铁律</h2>")
    h.append("<div class=\"sec\"><ol>")
    h.append("<li><b>饮料换无糖 / 水 / 黑咖</b> —— 一餐立省 100~220 kcal，性价比最高的改动。</li>")
    h.append("<li><b>薯条降级</b>：大 → 中 → 小 → 迷你 / 玉米杯。薯条钠不高但油多。</li>")
    h.append("<li><b>钠警戒线</b>：单品 &gt;1000 mg 或整餐 &gt;1500 mg 时，当天其余两餐必须控盐。</li>")
    h.append("<li><b>别为省几毛硬上套餐</b>：先算单点差价，再看捆绑的配餐是不是你真的需要的高热量项。</li>")
    h.append("</ol></div>")

    # 单品榜
    h.append(f"<h2>推荐单品 · ≤{int(cap)} kcal"
             + (f" · 预算 ≤¥{int(budget)}" if budget else "")
             + f" · 蛋白 ≥{int(min_prot)} g</h2>")
    h.append('<p class="lead">按「蛋白密度」（每 100 kcal 含多少克蛋白质）降序 —— 越靠前越抗饿。</p>')
    if singles:
        h.append("<table><thead><tr><th>#</th><th>餐品</th><th class=\"num\">价格</th>"
                 "<th class=\"num\">kcal</th><th class=\"num\">蛋白 g</th><th class=\"num\">脂肪 g</th>"
                 "<th class=\"num\">钠 mg</th><th class=\"num\">蛋白密度</th><th>灯</th></tr></thead><tbody>")
        for i, x in enumerate(singles, 1):
            h.append(f"<tr><td>{i}</td><td>{esc(mcd.label(x))}</td><td class=\"num\">{px(x)}</td>"
                     f"<td class=\"num\">{x.get('kcal')}</td><td class=\"num\">{x.get('protein')}</td>"
                     f"<td class=\"num\">{x.get('fat')}</td><td class=\"num\">{x.get('sodium')}</td>"
                     f"<td class=\"num\">{x.get('protein_per_100kcal')}</td><td>{tag(x)}</td></tr>")
        h.append("</tbody></table>")
    else:
        h.append('<div class="warn">当前约束下没有满足条件的单品，可放宽热量上限或预算。</div>')

    # 价格榜
    h.append("<h2>按价格升序 · 便宜优先</h2>")
    h.append('<p class="lead">预算敏感时先看这张表。注意：便宜不等于低卡，两列要一起看。</p>')
    if by_price:
        h.append("<table><thead><tr><th>#</th><th>餐品</th><th class=\"num\">价格</th>"
                 "<th class=\"num\">kcal</th><th class=\"num\">蛋白 g</th><th class=\"num\">钠 mg</th>"
                 "<th class=\"num\">g蛋白/元</th><th>灯</th></tr></thead><tbody>")
        for i, x in enumerate(by_price, 1):
            ppy = x.get("protein_per_yuan")
            h.append(f"<tr><td>{i}</td><td>{esc(mcd.label(x))}</td><td class=\"num\">{px(x)}</td>"
                     f"<td class=\"num\">{x.get('kcal')}</td><td class=\"num\">{x.get('protein')}</td>"
                     f"<td class=\"num\">{x.get('sodium')}</td>"
                     f"<td class=\"num\">{ppy if ppy is not None else '—'}</td><td>{tag(x)}</td></tr>")
        h.append("</tbody></table>")
    else:
        h.append('<div class="warn">暂无价格数据。配好 MCP 后运行 sync 即可填充。</div>')

    # 图例
    h.append('<div class="sec"><div class="legend">')
    h.append("<span>🟢 绿灯：热量 &lt;450 kcal 且 钠 &lt;700 mg 且 脂肪 &lt;25 g</span>")
    h.append("<span>🟡 黄灯：居中，注意分量</span>")
    h.append("<span>🔴 红灯：热量 ≥600 或 钠 ≥1000 或 脂肪 ≥35</span>")
    h.append("</div></div>")

    h.append('<div class="tip">💡 想看实时价格？配好 MCP 后运行 '
             '<code>python skill/scripts/mcp_client.py sync --store 你的门店编码</code>，'
             '价格覆盖会自动拉满。</div>')

    h.append("<footer>")
    h.append("本项目为 <b>2026 麦当劳程序员创意开发大赛参赛作品</b>，由参赛者独立开发，"
             "<b>非麦当劳官方产品</b>。输出仅供参考，<b>不构成医疗、营养或其他专业建议</b>；"
             "餐品信息、价格及供应状态以麦当劳官方渠道的实时结果为准。")
    h.append("</footer>")

    h.append("</div></body></html>")
    return "\n".join(h)


def main():
    p = argparse.ArgumentParser(description="生成控卡点餐速查表 HTML")
    p.add_argument("-o", "--out", default="examples/cut-guide.html")
    p.add_argument("--kcal-cap", type=float, default=500)
    p.add_argument("--budget", type=float)
    p.add_argument("--min-protein", type=float, default=20)
    a = p.parse_args()

    payload, items = mcd.load()
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(build(items, payload, a.kcal_cap, a.budget, a.min_protein),
                   encoding="utf-8")
    print(f"已生成 {out}（{len(items)} 项餐品）")


if __name__ == "__main__":
    main()
