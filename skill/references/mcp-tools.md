# mcd-mcp 接口速查（麦当劳中国官方 MCP）

- 服务器：`https://mcp.mcd.cn`
- 协议：Streamable HTTP
- 鉴权：`Authorization: Bearer <TOKEN>`（Token 在 https://open.mcd.cn/mcp 手机号登录后申请）
- 限流：**600 次/分钟**，超了返回 `429`
- 适用范围：中国大陆门店（不含港澳台）
- 实测：35 个工具（2026-10-16）

> 官方 README 的工具名与实测 `tools/list` 有出入（如 README 写 `query-partystore-date`，
> 实际是 `query-party-store-date`）。**一律以 `tools/list` 为准。**

---

## 本 Skill 主要依赖的两个工具

### `list-nutrition-foods` —— 营养库（无入参）

返回：**字符串形式的类 CSV**，158 项，字段顺序：

```
productName, nutritionDescription, energyKj, energyKcal,
protein, fat, carbohydrate, sodium, calcium
```

- `nutritionDescription` 是官方自带的类比描述（如「能量约鲈鱼 1 条」），部分为 `null`。
- **优先引用官方类比，不要自己编比喻。**
- 单位：能量千焦/千卡，其余克，钠/钙毫克。

### `query-meals` —— 门店菜单与价格

入参：`storeCode`, `orderType`, `beType`

返回结构：

```
data.categories[].name            分类名
data.categories[].meals[].code    餐品编码
data.categories[].meals[].tags    标签
data.meals{code}.name             餐品名
data.meals{code}.image            图片 URL
data.meals{code}.currentPrice     现价（字符串，单位【元】）
data.meals{code}.originalPrice    原价（字符串，单位【元】）
data.meals{code}.discountType     优惠类型（null / 早餐卡 / 促销 / 麦金卡 / 随单购…）
data.meals{code}.canWithOrder     是否可随单购
data.frequent                     常点餐品
```

---

## orderType × beType 配对（最容易错）

| 场景 | beType | orderType | beCode |
|---|---|---|---|
| 到店自取 | 1 | 1 | **不传**（传了报错） |
| 得来速 DT | 5 | 1 | 必传（来自 `query-nearby-stores`） |
| 麦乐送 / 外送 | 2 | 2 | 必传（来自 `delivery-query-stores`） |
| 企业团餐 | 6 | 2 | 必传（来自 `delivery-query-stores`） |

预约场景额外传 `reservationDate`，格式 `yyyy-MM-dd HH:mm`；非预约**不要传**。

---

## 其他工具（按需）

| 工具 | 用途 | 写操作 |
|---|---|---|
| `query-nearby-stores` | 查可点餐门店（`beType`, `searchType`(1收藏/2搜索), `city`, `keyword`） | 否 |
| `delivery-query-stores` | 查可配送门店 | 否 |
| `delivery-query-addresses` | 配送地址列表 | 否 |
| `delivery-create-address` | 新增配送地址 | **是** |
| `query-meal-detail` | 套餐组成 / 可替换项 | 否 |
| `calculate-price` | 算价（含优惠券） | 否 |
| `create-order` | 创建订单 | **是** |
| `cancel-order` | 取消订单 | **是** |
| `order-list` / `query-order` | 历史订单 / 订单详情 | 否 |
| `query-store-coupons` | **指定门店**当前可用券（权威） | 否 |
| `query-my-coupons` | 我的券包（**不承诺可用**） | 否 |
| `available-coupons` | 麦麦省可领券列表 | 否 |
| `auto-bind-coupons` | 一键领券 | **是** |
| `query-my-account` | 积分账户 | 否 |
| `mall-points-products` / `mall-product-detail` | 积分商城 | 否 |
| `mall-create-order` | 积分兑换下单 | **是** |
| `query-lottery-info` / `draw-lottery` / `query-my-prizes` | 积分抽奖 | 抽奖**是**写操作 |
| `campaign-calendar` | 当月活动日历（返回富文本，非结构化） | 否 |
| `query-party-city/store/date/session` | 主题活动预约 | 否 |
| `party-order-create` | 主题活动下单 | **是** |
| `now-time-info` | 服务器时间（零副作用，适合连通性自检） | 否 |

---

## 已知坑（血泪清单）

1. **菜单与营养表的规格不是一回事**
   营养表按「份」给（麦乐鸡 4 块 / 5 块两行），菜单按「品」卖（只有一个麦乐鸡）。
   没有字段告诉你该选哪个。**规格不明时宁可不排，不要猜。**

2. **两个接口的金额单位不一样**
   - `query-meals` → **元**，且是**字符串**（`"15"`）
   - `calculate-price` → **分**，是**整数**（`1500`）
   同一个服务两套单位，不细看会错 100 倍。

3. **`tools/call` 返回值不能直接 `json.loads`**
   `content[0].text` 是「给模型看的说明 + 原始 JSON」的混合体。
   定位 `## Original Response` 锚点，再用 `JSONDecoder.raw_decode()` 从锚点后逐位置试探，取第一个带 `code` 的 dict。

4. **套餐子项 code ≠ 菜单同名单品 code**
   套餐里的「可乐中杯」是 `3050`，单点的「可乐」是 `9900008751`。
   **名字一样 ID 不一样**，想用套餐子项关联菜单价格只能靠名称匹配。

5. **`query-my-coupons` 不校验门店/渠道/配送方式**，官方明确说"不承诺可用于当前订单"。
   要做"这单能用什么券"必须走 `query-store-coupons`。

6. **`currentPrice` 与 `originalPrice` 可能完全相等**（实测门店 1420227 无划线促销价）。
   不要假设两者总有差异。

7. **官方字段拼写是 `Mouth` 不是 `Month`**（`currentMouthExpirePoint`），照抄别改。

---

## 错误码

| code | 含义 | 处理 |
|---|---|---|
| `200` | 成功 | — |
| `600022` | 一单仅支持一张券 | 不叠券，改单张最优券策略 |
| `600050` | 收藏门店为空 | 转 `searchType=2` 搜索 |
| `401` | Token 无效 / 过期 / 未提供 | 重新申请 MCP Token |
| `429` | 触发限流（>600 次/分钟） | 降频重试 |

> 返回体的 `success` 字段是会变的，**判断成败优先看 `code`**。

---

## 数据刷新流程（Agent 执行）

老大说「刷新麦当劳数据」时按此执行：

1. 调 `now-time-info` 做连通性自检（失败 → 引导重新申请 Token）
2. 调 `list-nutrition-foods` → 把返回文本存到临时文件 `mcp_nutrition.txt`
3. 调 `query-meals`（需先 `query-nearby-stores` 拿 `storeCode`）→ 存为 `mcp_meals.json`
4. 执行：
   ```
   python ~/.workbuddy/skills/mcd-calorie/scripts/mcd.py refresh \
     --nutrition mcp_nutrition.txt --meals mcp_meals.json
   ```
5. 回报更新条数，并说明价格来自哪个门店

> 若未配置 MCP：本地数据集照常可用（营养为官方 2025-04 版，价格为参考值），
> 按 `SKILL.md` 的降级流程处理。
