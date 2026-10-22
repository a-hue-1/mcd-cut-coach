# workbuddy.md — 使用 WorkBuddy 开发的对话上下文

> 本文件记录本项目使用 **WorkBuddy**（Agent 模式）完成开发的全过程，供「麦当劳程序员创意开发大赛 × WorkBuddy 联动奖励」核验。
> 所有凭据均已脱敏；Token 仅通过环境变量 `MCD_MCP_TOKEN` 使用，**未写入任何文件**。

---

## 1. 开发环境

| 项 | 值 |
|---|---|
| 开发工具 | WorkBuddy（Agent 模式） |
| 会话日期 | 2026-10-22（19:11 – 19:5x） |
| 运行环境 | Windows + Git Bash |
| 使用运行时 | Python 3.13（WorkBuddy 托管） |
| 使用的 WorkBuddy 能力 | Skill 管理、Bash、WebSearch / WebFetch、GitHub MCP 连接器、TaskCreate 任务管理、本地文件读写、present_files 交付、workspace memory |

---

## 2. 开发时间线（按用户指令推进）

### 阶段 0 · 需求提出

> **用户**：「基于这个 https://github.com/M-China/mcd-mcp-server，开发一个 skill 助手，关于麦当劳产品热量的。包含减脂人推荐吃什么单品或者套餐，根据价格排列的麦当劳产品热量等」

WorkBuddy 先拉取仓库内容做**安全审计**：确认该仓库**仅含 README、无可执行代码**，判定为 P2（安全），同时提取出关键信息——麦当劳中国官方 MCP 端点 `https://mcp.mcd.cn`（Streamable HTTP + Bearer Token）及其工具集。

### 阶段 1 · 数据采集（先找真实数据，再写代码）

不臆造数据。先后：

1. 抓取麦当劳官网营养计算器页与各分类菜单页，提取出 **71 个产品页地址**
2. 批量抓取每个产品页的营养成分表，清洗后得到 **120 条官方营养数据**（规格级，官方更新时间 2025-04）
3. 检索公开价格信息作为参考，形成 34 条价格覆盖

过程中诊断并修掉一个 bug：无糖可乐等 0 卡条目被误判为"数据缺失"（代码用 `if not kcal` 判断，0 是 falsy）。

### 阶段 2 · Skill 主体开发

在 `~/.workbuddy/skills/mcd-calorie/` 建立结构：

- `SKILL.md`：6 类意图路由 + 输出规范
- `references/cut-playbook.md`：减脂手册（热量预算表、三硬指标、红黄绿灯、5 大场景方案）
- `references/mcp-tools.md`：MCP 工具契约 + 踩坑清单
- `scripts/mcd.py`：`rank` / `cut` / `combo` / `compare` / `price` / `refresh` 六个子命令

并做了三轮输出调优：
- 表格宽度计算逻辑重写（原实现有冗余循环）
- 蛋白性价比排序默认改为降序
- 组合枚举加入"自动放宽约束"逻辑

### 阶段 3 · 参赛适配（当前阶段）

> **用户**：阅读赛事推文并按步骤参赛

WorkBuddy 拉取官方赛事仓库 `M-China/mcd-developer-innovation-challenge`，逐条比对 `activityGuidelines.md` 的**强制文件清单**，识别出差距：

| 检查项 | 状态 | 处理 |
|---|---|---|
| README.md | 已有但不满足参赛格式 | 重写为「介绍/安装/使用示例/目标用户」四段式 |
| CONTEST_DECLARATION.md | **缺失** | 从官方仓库 raw 下载，并用 git blob SHA 校验字节级一致 |
| MCP_INTEGRATION.md | 仅有 references 版 | 新建根目录版，说明 Server/Tool/流程/价值 |
| 源代码 | 已有 | 迁移到 `skill/` |
| workbuddy.md | **缺失** | 本文件 |
| mcp-config.example.json | 需要 | 新建，仅含 `${MCD_MCP_TOKEN}` 占位符 |

同时补齐最关键的短板：**实现真正能跑通的 MCP 客户端** `skill/scripts/mcp_client.py`（零依赖，完整四步握手），使"真实使用麦当劳 MCP 能力"从文档声明变为可运行代码。

---

## 3. 关键设计决策

| 决策 | 理由 |
|---|---|
| **三指标并排，永不单指标排行** | 麦辣鸡腿堡蛋白性价比排前列，但钠是全场最高档。只看一个维度会得出完全错误的结论 |
| **价格标注来源，不猜** | `¥` MCP实测 / `≈¥` 网页参考 / `—` 待补录。价格随门店浮动，编数字最害人 |
| **热量匹配多命中时输出区间** | 官方营养表按规格拆分，猜一个单值会显示"看起来精确的错误值" |
| **约束无解时显式放宽** | 自动放宽一档并在输出顶部告知放宽了什么，而非静默给次优解 |
| **MCP 客户端零依赖** | 只用标准库 urllib，任何 Python 3.9+ 环境开箱即用，无需 pip install |
| **只读边界** | 仅调用查询类工具，明确禁止下单/支付/领券/抽奖等写操作 |
| **Token 只走环境变量** | 源码、数据集、示例中均无任何真实凭证 |

---

## 4. 安全与合规处理

- **凭据**：全程未使用也未记录任何真实 Token。代码仅从 `MCD_MCP_TOKEN` 环境变量读取；`mcp-config.example.json` 只含 `${MCD_MCP_TOKEN}` 占位符；`.gitignore` 排除 `mcp-config.json` 与 `.env`。
- **只读**：Skill 只调用 4 个查询类工具，代码中不存在写操作调用。
- **合规措辞**：README 与声明中明确"非麦当劳官方产品""仅供参考、不构成营养建议""以官方渠道实时结果为准"，不对品牌作负面评价、不作跨品牌对比，不宣扬极端节食。
- **数据授权**：营养数据采集自麦当劳官方公开营养信息页面，仅用于本地查询与展示。

---

## 5. 产出清单

| 产物 | 位置 |
|---|---|
| MCP 客户端 | `skill/scripts/mcp_client.py` |
| 主计算器 | `skill/scripts/mcd.py` |
| Skill 主脑 | `skill/SKILL.md` |
| 官方营养数据集 | `skill/references/menu-nutrition.json` |
| 减脂手册 | `skill/references/cut-playbook.md` |
| MCP 契约与踩坑 | `skill/references/mcp-tools.md` |
| 参赛文档 | `README.md`、`CONTEST_DECLARATION.md`、`MCP_INTEGRATION.md`、本文件 |
| 脱敏配置 | `mcp-config.example.json` |

---

## 6. 核验方式

```bash
# 注入 Token 后自检（真实调用麦当劳官方 MCP）
export MCD_MCP_TOKEN='你的Token'
python skill/scripts/mcp_client.py ping        # 打印端点、会话、工具清单
python skill/scripts/mcp_client.py sync --store 1420227   # 拉取并合并官方数据

# 无 Token 时亦可离线运行（走内置官方营养数据集）
python skill/scripts/mcd.py cut --kcal-cap 500 --budget 30
python skill/scripts/mcd.py rank --sort price --asc --min-protein 15 --top 8
```

数据集 `skill/references/menu-nutrition.json` 的 `meta` 字段会记录数据来源与拉取时间，可直接核验。
