# MCP_INTEGRATION.md —— 麦当劳 MCP 接入说明

> 本文件说明本项目实际使用的麦当劳 MCP Server、调用的工具、完整调用流程，以及由此产生的业务价值。
> 所有凭据仅通过环境变量 `MCD_MCP_TOKEN` 注入，仓库内不存在任何真实密钥。

---

## 1. 使用的 MCP Server

| 项 | 值 |
|---|---|
| 名称 | `mcd-mcp` |
| 端点 | `https://mcp.mcd.cn` |
| 传输 | Streamable HTTP（MCP over HTTP，JSON-RPC 2.0） |
| 鉴权 | `Authorization: Bearer ${MCD_MCP_TOKEN}` |
| 会话 | 首次 `initialize` 后由服务端下发 `Mcp-Session-Id`，后续请求携带 |
| Token 申请 | <https://open.mcd.cn/mcp>（手机号登录 → 控制台 → 激活 → 申请 Token） |
| 限流 | 600 次/分钟 |

客户端实现见 `skill/scripts/mcp_client.py`，**零第三方依赖**（仅标准库 `urllib`），完整实现四步握手：

```
initialize  →  notifications/initialized  →  tools/list  →  tools/call
```

---

## 2. 实际调用的 Tool

| Tool | 用途 | 在本项目中的作用 |
|---|---|---|
| `list-nutrition-foods` | 拉取官方全量营养库 | 餐品热量 / 蛋白质 / 脂肪 / 碳水 / 钠 / 钙 的**唯一权威来源**，按规格拆分（如可乐 小 107 / 中 147 / 大 224 kcal） |
| `query-meals` | 查询指定门店在售菜单与价格 | 提供**实时价格**与门店在售状态，解决价格随城市/门店/时段浮动的问题 |
| `query-meal-detail` | 查询套餐详情与可换项 | 支撑套餐级替换建议（如薯条换玉米杯、可乐换无糖） |
| `calculate-price` | 计算组合价格 | 校验自定义组合的实际结算价，避免估算偏差 |

> 工具名做了兼容处理：若服务端使用下划线命名（`query_meals` 等），客户端会自动匹配，见 `mcp_client.pick_tool()`。

---

## 3. 调用流程

### 3.1 一键同步（推荐）

```bash
export MCD_MCP_TOKEN='你的Token'
python skill/scripts/mcp_client.py sync --store 1420227
```

内部时序：

```
① POST initialize
   {"jsonrpc":"2.0","id":1,"method":"initialize",
    "params":{"protocolVersion":"2025-06-18","capabilities":{},
              "clientInfo":{"name":"mcd-cut-coach","version":"1.0.0"}}}
   ← 响应头 Mcp-Session-Id: <sid>

② POST notifications/initialized        （单向通知，无 id）

③ POST tools/list                       → 拿到工具清单并挑选目标 tool

④ POST tools/call  name=list-nutrition-foods
   → 官方营养库 → 落盘 skill/references/mcp-nutrition.txt

⑤ POST tools/call  name=query-meals  {"storeCode":"1420227"}
   → 门店菜单与实时价 → 落盘 skill/references/mcp-meals.json

⑥ 本地合并：mcd.py refresh 把 ④⑤ 合并进
   skill/references/menu-nutrition.json，并重算派生指标
```

### 3.2 单次调用

```bash
python skill/scripts/mcp_client.py ping
python skill/scripts/mcp_client.py tools
python skill/scripts/mcp_client.py nutrition -o nutrition.json
python skill/scripts/mcp_client.py meals --store 1420227 -o meals.json
python skill/scripts/mcp_client.py call --name query-meals --args '{"storeCode":"1420227"}'
```

### 3.3 数据匹配策略（关键设计）

官方营养库**按规格拆分**，而门店菜单往往只有一个笼统名。直接精确匹配会大面积落空，因此采用四级匹配：

| 级别 | 策略 | 输出 |
|---|---|---|
| 1 | 名称 + 规格完全命中 | 精确值 |
| 2 | 名称唯一命中 | 精确值 |
| 3 | 名称多规格命中 | **输出区间**（如 107–224 kcal） |
| 4 | 未命中 | 标注「不详」 |

> **宁可输出区间，也不猜一个"看起来很精确的错误值"。**

价格同理：优先取 `query-meals` 返回的 `currentPrice`（标记为 `¥`，实测价）；无实时价时使用公开网页参考价（标记为 `≈¥`）；两者都没有则显示 `—`，**绝不编造**。

---

## 4. 业务价值

| 维度 | 价值 |
|---|---|
| **对用户** | 把"吃麦当劳"和"控热量"从对立变成可计算的选择——给出能直接照着点的组合，而不是让用户自己对着营养表算 |
| **对麦当劳** | 基于官方数据在官方菜单内做推荐，引导用户留在菜单内做更合适的搭配，减少"想吃但不敢吃"导致的流失 |
| **对开发者** | 提供一套可直接复用的 MCP over HTTP 客户端 + 数据清洗/匹配层，换任何品类都能复用 |
| **数据权威性** | 营养数据来自麦当劳官方 MCP，不是爬虫拼凑或模型臆测 |

### 三个刻意的设计决策

1. **三指标并排，永不单指标排行**
   只看"蛋白质性价比"会得出错误结论：麦辣鸡腿堡蛋白性价比排前列，但钠含量是全场最高档。因此热量、蛋白质、钠**永远同时呈现**。

2. **价格标注来源，不猜**
   `¥` = MCP 实测 / `≈¥` = 网页参考（±10~20%）/ `—` = 待补录。价格随门店浮动，编一个数字最害人。

3. **约束无解时显式放宽，而非静默输出次优解**
   当热量上限 + 预算 + 蛋白下限无可行组合时，自动放宽一档（预算 +10 元 / 蛋白 -5 g），并在输出顶部**明确告知放宽了什么**。

---

## 5. 只读边界（安全设计）

本项目**仅调用查询类工具**，代码中不包含、也不会调用下单、支付、领券、抽奖、积分扣减等任何写操作。

| 类别 | 处理 |
|---|---|
| 下单 / 支付 / 领券 / 抽奖 | 明确禁止调用 |
| 官方 `draw-lottery` 类工具 | 不接入（会真实扣减用户权益） |
| Token | 仅从环境变量读取，不落盘、不打印、不入库 |
| 网络失败 | 自动降级到本地数据集，并在输出标注数据来源与降级原因 |

---

## 6. 验证方式

```bash
# 1. 连通性与工具清单自检
export MCD_MCP_TOKEN='你的Token'
python skill/scripts/mcp_client.py ping

# 2. 拉取并合并官方数据
python skill/scripts/mcp_client.py sync --store 1420227

# 3. 验证数据已生效
python skill/scripts/mcd.py rank --sort ppy --top 10
python skill/scripts/mcd.py cut --kcal-cap 500 --budget 30
```

数据合并后，`skill/references/menu-nutrition.json` 的 `meta` 字段会自动记录数据来源与拉取时间，便于核验。
