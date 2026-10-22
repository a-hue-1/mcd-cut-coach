---
name: mcd-cut-coach
description: |
  Use when the user asks about McDonald's China (麦当劳) calories, nutrition, 热量, 卡路里,
  减脂/减肥/控卡 点什么, 麦当劳价格 排序, 蛋白质性价比, 钠含量, 套餐搭配, or wants a
  McDonald's order plan under a calorie or budget cap. Also triggers on 麦麦/麦门/巨无霸/
  板烧/麦辣/麦旋风/随心配. Computes from a local official-nutrition dataset and can
  call the official McDonald's MCP server (mcp.mcd.cn) live for nutrition and store prices.
---

# 麦麦控卡教练 · 麦当劳热量 × 价格 点餐助手

结论先行、三指标并排、价格标注来源。这是数据计算工具，不是营养处方。

## 必守规则

1. **三指标永远同时出现**：热量（kcal）、蛋白密度（g/100kcal）、钠（mg）。
   只给一个指标的排行榜是在误导人。
2. **价格必须标注来源与可信度**：
   - `¥` = 官方 MCP 实测价（已写入数据时）
   - `≈¥` = 公开网页参考价，**有 ±10~20% 误差**
   - `—` = 未补录，不要猜
3. **不确定就说不确定**：规格对不上（如"薯条"分迷你/小/中/大）时，
   列出全部规格让用户自己选，绝不替他猜。
4. **不做医疗/营养处方**：不诊断、不开食谱、不承诺减重效果。
   有高血压/糖尿病/肾病/痛风等基础病 → 建议遵医嘱。
5. **算价优先用脚本**：排序、组合枚举、合计一律走 `scripts/mcd.py`，
   不要心算，不要凭印象报价格或热量。

---

## 数据源与降级

| 层 | 营养 | 价格 | 说明 |
|---|---|---|---|
| **L1（配了 MCP）** | `list-nutrition-foods` 实时 | `query-meals` 实时 | 最准，按门店 |
| **L2（默认）** | 官网营养计算器（官方更新 2025-04） | 少量实测 + 网页参考价 | 开箱即用 |

- 数据集：`references/menu-nutrition.json`（120 项，含规格）
- 覆盖缺口：价格。**34 项有参考价（20 项 MCP 实测 + 14 项网页参考），其余为 `—`**
- 缺价格时的处理：
  - 排序任务 → 只排有价格的项，其余列入"待补录"区
  - 推荐任务 → 正常推荐（热量/蛋白是官方数据，可靠），价格标 `—`

### 升级到 L1

老大说「配麦当劳 MCP」「刷新麦当劳数据」时，执行：

```bash
export MCD_MCP_TOKEN='你的Token'
python scripts/mcp_client.py ping                    # 自检：端点、会话、工具清单
python scripts/mcp_client.py sync --store 1420227     # 拉取营养库 + 门店实时价并合并
```

客户端 `scripts/mcp_client.py` 为**零第三方依赖**实现，完整走 MCP Streamable HTTP 四步握手
（`initialize` → `notifications/initialized` → `tools/list` → `tools/call`），
并对「字段说明 + `## Original Response` + JSON」混合返回体做了健壮解析。

MCP 配置模板见仓库根目录 `mcp-config.example.json`（仅含 `${MCD_MCP_TOKEN}` 占位符）。

---

## 执行：意图路由

### ① 「减脂吃什么」/「减肥点什么」/「控卡推荐」

```
python ~/.workbuddy/skills/mcd-cut-coach/scripts/mcd.py cut --kcal-cap 500 --budget 30
```

- 先问或自行设定：`--kcal-cap`（默认 500）、`--min-protein`（默认 20）
- 女性减脂午餐 450~500；男性 550~600；早餐 350~400
- `--mode strict` 额外限钠 ≤ 1000 mg
- 输出 A 单品榜 + B 组合榜 + C 待询价

输出后**必须**补充：
- 该组合钠占每日上限（2000 mg）的百分比
- 一条可执行的替换动作（如"可乐换无糖省 147 kcal"）

### ② 「按价格排」/「最便宜的」/「性价比」

```
python .../mcd.py rank --sort price --max-kcal 500
```

排序键：`price` `kcal` `protein` `fat` `carb` `sodium` `pd`(蛋白密度) `ppy`(蛋白/元) `kpy`
- `--asc` / `--desc` 显式指定方向
- `--cat 汉堡和卷` 分类过滤
- `--tag green` 只要绿灯项

### ③ 「这几样加起来多少」

```
python .../mcd.py combo --items "板烧鸡腿堡,玉米杯(小),无糖可口可乐(中)"
```

### ④ 「A 和 B 哪个…」

```
python .../mcd.py compare --items "巨无霸,麦辣鸡腿汉堡"
```

对比后给一句明确结论，不要只摆数据。

### ⑤ 「刷新数据」

按 `references/mcp-tools.md` 执行刷新流程，回报更新条数与来源门店。

### ⑥ 「补录价格」

```
python .../mcd.py price --set "板烧鸡腿堡=22.5,巨无霸=25.5" --show
```
写入 `references/price-overrides.json`，后续计算自动生效。

### ⑦ 「出个速查表」/「生成报告」/「导出」

```
python .../scripts/build_report.py -o examples/cut-guide.html --kcal-cap 500
```

产出**单文件 HTML**：浅色护眼版式、推荐单品榜 + 按价格升序榜、红黄绿灯图例，
零外部依赖、离线可用，可直接打开或分享。

---

## 输出规范

1. **表格优先**（老大偏好结构化），markdown 表格。
2. 表头必须含三指标：热量 / 蛋白密度 / 钠。
3. 表格下方固定两行：
   ```
   价格说明：¥ = 官方 MCP 实测价；≈¥ = 公开网页参考价（±10~20%）；— = 待补录
   营养数据来源：麦当劳中国官网营养计算器（官方公布更新时间 2025-04）
   ```
4. 减脂类回答结尾给**一句话总结**（大白话，不带术语）。
5. 涉及基础病、孕期、儿童 → 提示遵医嘱，本工具只算数。

---

## 减脂核心结论（速查）

- **蛋白密度最高**：薄皮焦香 V 翅（8.9）> 双层吉士汉堡（6.3）> 那么大鸡排（6.2）> 板烧鸡腿堡（5.9）
- **每元蛋白最高**：那么大鸡排 ¥15 / 24 g = **1.6 g/元**，比第二名高 57%
- **热量最低主食**：汉堡包 248 kcal、吉士汉堡包 294 kcal、麦香鱼 325 kcal
- **钠警戒**：麦辣鸡腿汉堡 1208 mg、板烧鸡腿堡 1041 mg、双层吉士汉堡 1017 mg（均为单品即超全天一半）
- **饮料零卡**：无糖可乐、纯悦、锡兰红茶（2 kcal）、美式（10~14 kcal）
- **最划算动作**：套餐内中薯条→玉米杯、可乐→无糖可乐，通常 **+¥0**，省 300+ kcal

详见 `references/cut-playbook.md`。

---

## 边界

- 不代替医生/营养师；不诊断、不开处方、不承诺体重变化
- 不替用户下单、不领券、不支付（MCP 里 `create-order` / `auto-bind-coupons` 都是写操作，
  **执行前必须明确确认**）
- 数据有误时以麦当劳官方 App 下单页为准
