#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
mcp_client.py —— 麦当劳中国官方 MCP 客户端（Streamable HTTP）

零第三方依赖（只用标准库 urllib），完整实现 MCP over HTTP 的握手与调用：

    initialize -> notifications/initialized -> tools/list -> tools/call

凭据只从环境变量 MCD_MCP_TOKEN 读取，绝不写入任何文件。

用法：
    export MCD_MCP_TOKEN='你的Token'
    python mcp_client.py ping                          # 连通性 + 工具数
    python mcp_client.py tools                         # 打印工具清单
    python mcp_client.py nutrition -o nutrition.json   # 官方营养库
    python mcp_client.py meals --store 1420227 -o m.json
    python mcp_client.py sync --store 1420227          # 一键写回本地数据集
    python mcp_client.py call --name query-meals --args '{"storeCode":"1420227"}'
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

BASE = Path(__file__).resolve().parent.parent
REFERENCES = BASE / "references"

DEFAULT_URL = os.environ.get("MCD_MCP_URL", "https://mcp.mcd.cn")
PROTOCOL_VERSION = "2025-06-18"
CLIENT_INFO = {"name": "mcd-cut-coach", "version": "1.0.0"}


class McpError(RuntimeError):
    pass


class McpClient:
    """麦当劳 MCP Streamable HTTP 客户端。"""

    def __init__(self, url: str | None = None, token: str | None = None,
                 timeout: float = 30.0):
        self.url = (url or DEFAULT_URL).rstrip("/")
        self.token = token if token is not None else os.environ.get("MCD_MCP_TOKEN", "")
        self.timeout = timeout
        self.session_id: str | None = None
        self._seq = 0

    # ------------------------------------------------------------ 底层
    def _id(self) -> int:
        self._seq += 1
        return self._seq

    def _headers(self) -> dict:
        h = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        if self.session_id:
            h["Mcp-Session-Id"] = self.session_id
        return h

    def _post(self, payload: dict, notify: bool = False):
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(self.url, data=data,
                                     headers=self._headers(), method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                sid = resp.headers.get("Mcp-Session-Id")
                if sid and not self.session_id:
                    self.session_id = sid
                ctype = resp.headers.get("Content-Type", "")
                body = resp.read().decode("utf-8", errors="ignore")
        except urllib.error.HTTPError as e:
            detail = ""
            try:
                detail = e.read().decode("utf-8", errors="ignore")[:400]
            except Exception:
                pass
            raise McpError(f"HTTP {e.code} {e.reason} {detail}")
        except urllib.error.URLError as e:
            raise McpError(f"网络错误：{e.reason}")

        if notify or not body.strip():
            return None
        return self._parse(body, ctype)

    # -------------------------------------------------------- 健壮解析
    @staticmethod
    def _parse(body: str, ctype: str):
        if "text/event-stream" in (ctype or ""):
            return McpClient._from_sse(body)
        try:
            return json.loads(body)
        except Exception:
            obj = McpClient._from_sse(body)
            return obj if obj is not None else McpClient._extract_loose(body)

    @staticmethod
    def _from_sse(body: str):
        buf = [ln[5:].strip() for ln in body.splitlines() if ln.startswith("data:")]
        if not buf:
            return None
        s = "\n".join(buf)
        try:
            return json.loads(s)
        except Exception:
            return McpClient._extract_loose(s)

    @staticmethod
    def _extract_loose(s: str):
        """从混杂文本里抠出第一个合法 JSON 对象/数组。"""
        dec = json.JSONDecoder()
        for i, ch in enumerate(s):
            if ch in "{[":
                try:
                    obj, _ = dec.raw_decode(s[i:])
                    return obj
                except Exception:
                    continue
        return None

    @staticmethod
    def _extract_payload(text: str):
        """官方工具返回体常是「字段说明 + ## Original Response + JSON」混合文本。"""
        if not text:
            return None
        s = text.strip()
        try:
            return json.loads(s)
        except Exception:
            pass
        idx = s.find("Original Response")
        if idx >= 0:
            tail = s[idx:]
            tail = tail.split("\n", 1)[1] if "\n" in tail else tail
            obj = McpClient._extract_loose(tail)
            if obj is not None:
                return obj
        return McpClient._extract_loose(s)

    # ------------------------------------------------------------ 握手
    def initialize(self):
        r = self._post({
            "jsonrpc": "2.0", "id": self._id(), "method": "initialize",
            "params": {"protocolVersion": PROTOCOL_VERSION,
                       "capabilities": {}, "clientInfo": CLIENT_INFO},
        })
        if isinstance(r, dict) and r.get("error"):
            raise McpError(json.dumps(r["error"], ensure_ascii=False))
        self._post({"jsonrpc": "2.0", "method": "notifications/initialized"},
                   notify=True)
        return r or {}

    def list_tools(self) -> list:
        r = self._post({"jsonrpc": "2.0", "id": self._id(),
                        "method": "tools/list", "params": {}})
        if isinstance(r, dict) and r.get("error"):
            raise McpError(json.dumps(r["error"], ensure_ascii=False))
        return ((r or {}).get("result") or {}).get("tools", []) if isinstance(r, dict) else []

    def call_tool(self, name: str, arguments: dict | None = None) -> dict:
        r = self._post({"jsonrpc": "2.0", "id": self._id(), "method": "tools/call",
                        "params": {"name": name, "arguments": arguments or {}}})
        if not isinstance(r, dict):
            return {"text": "", "payload": None, "raw": r}
        if r.get("error"):
            raise McpError(json.dumps(r["error"], ensure_ascii=False))
        res = r.get("result") or {}
        texts = [c.get("text", "") for c in (res.get("content") or [])
                 if c.get("type") == "text"]
        payload = None
        for t in texts:
            payload = self._extract_payload(t)
            if payload is not None:
                break
        return {
            "text": "\n".join(texts),
            "payload": payload,
            "isError": bool(res.get("isError")),
            "raw": res,
        }


# ---------------------------------------------------------------- 工具适配
NUTRITION_TOOL_CANDIDATES = ("list-nutrition-foods", "list_nutrition_foods")
MEALS_TOOL_CANDIDATES = ("query-meals", "query_meals")
DETAIL_TOOL_CANDIDATES = ("query-meal-detail", "query_meal_detail")
PRICE_TOOL_CANDIDATES = ("calculate-price", "calculate_price")


def pick_tool(tools: list, candidates) -> str | None:
    names = {t.get("name") for t in tools if isinstance(t, dict)}
    for c in candidates:
        if c in names:
            return c
    return None


def parse_nutrition(payload) -> list:
    """官方营养库：兼容 {data:[...]} / [...] / {data:{list:[...]}} 三种形态。"""
    rows = []
    node = payload
    if isinstance(payload, dict):
        for k in ("data", "list", "foods", "items", "result"):
            if k in payload:
                node = payload[k]
                if isinstance(node, dict):
                    inner = [node.get(x) for x in ("list", "items", "data", "records")
                             if isinstance(node.get(x), list)]
                    node = inner[0] if inner else node
                break
    if isinstance(node, dict):
        node = [node]
    if not isinstance(node, list):
        return rows

    for r in node:
        if not isinstance(r, dict):
            continue
        def g(*keys):
            for k in keys:
                v = r.get(k)
                if v not in (None, ""):
                    try:
                        return float(v)
                    except (TypeError, ValueError):
                        return v
            return None
        name = r.get("name") or r.get("foodName") or r.get("productName")
        if not name:
            continue
        spec = r.get("spec") or r.get("specification") or r.get("size") or ""
        rows.append({
            "name": str(name).strip(),
            "spec": str(spec).strip(),
            "energy_kj": g("energyKj", "energy_kj", "kj", "energy"),
            "kcal": g("kcal", "energyKcal", "energy_kcal", "calorie", "calories"),
            "protein": g("protein", "proteinG"),
            "fat": g("fat", "fatG"),
            "carb": g("carb", "carbohydrate", "carbG", "carbohydrateG"),
            "sodium": g("sodium", "sodiumMg", "na"),
            "calcium": g("calcium", "calciumMg", "ca"),
        })
    return rows


def parse_meals(payload) -> list:
    """query-meals：{data:{categories:[{name,meals:[{code}]}], meals:{code:{name,currentPrice}}}}"""
    out = []
    data = payload.get("data", payload) if isinstance(payload, dict) else {}
    meals = (data or {}).get("meals", {}) if isinstance(data, dict) else {}
    cats = (data or {}).get("categories", []) if isinstance(data, dict) else []

    catmap = {}
    for c in cats or []:
        cname = c.get("name", "")
        for m in (c.get("meals") or []):
            if isinstance(m, dict) and m.get("code"):
                catmap[str(m["code"])] = cname

    for code, info in (meals or {}).items():
        if not isinstance(info, dict):
            continue
        try:
            p = float(info.get("currentPrice") or 0) or None
        except (TypeError, ValueError):
            p = None
        out.append({"code": str(code), "name": info.get("name"),
                    "price": p, "category": catmap.get(str(code), "")})
    return out


# ---------------------------------------------------------------- 命令
def cmd_ping(a):
    c = McpClient()
    if not c.token:
        print("未检测到 MCD_MCP_TOKEN。请先：export MCD_MCP_TOKEN='你的Token'")
        print("Token 申请：https://open.mcd.cn/mcp （手机号登录 → 控制台 → 激活）")
        return 1
    print(f"端点：{c.url}")
    info = c.initialize()
    srv = ((info.get("result") or {}).get("serverInfo") or {}) if isinstance(info, dict) else {}
    if srv:
        print(f"服务：{srv.get('name', '?')} v{srv.get('version', '?')}")
    print(f"会话：{'已建立 ' + c.session_id[:12] + '…' if c.session_id else '（服务端未下发）'}")
    tools = c.list_tools()
    print(f"工具数：{len(tools)}")
    for t in tools:
        d = (t.get("description") or "").split("\n")[0][:58]
        print(f"  - {t.get('name')}  {d}")
    return 0


def cmd_tools(a):
    c = McpClient()
    if not c.token:
        sys.exit("未检测到 MCD_MCP_TOKEN")
    c.initialize()
    print(json.dumps(c.list_tools(), ensure_ascii=False, indent=2))
    return 0


def cmd_nutrition(a):
    c = McpClient()
    if not c.token:
        sys.exit("未检测到 MCD_MCP_TOKEN")
    c.initialize()
    tools = c.list_tools()
    name = pick_tool(tools, NUTRITION_TOOL_CANDIDATES)
    if not name:
        sys.exit(f"该 MCP 未提供营养查询工具。当前工具：{[t.get('name') for t in tools]}")
    r = c.call_tool(name, {})
    rows = parse_nutrition(r["payload"]) if r["payload"] is not None else []
    out = {"meta": {"tool": name, "endpoint": c.url, "count": len(rows)}, "rows": rows}
    if a.out:
        p = Path(a.out)
        p.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
        t = REFERENCES / "mcp-nutrition.txt"
        t.write_text(r["text"], encoding="utf-8")
        print(f"已写入 {p}（{len(rows)} 条）；原始文本 → {t}")
    else:
        print(json.dumps(out, ensure_ascii=False, indent=2)[:4000])
    return 0


def cmd_meals(a):
    c = McpClient()
    if not c.token:
        sys.exit("未检测到 MCD_MCP_TOKEN")
    c.initialize()
    tools = c.list_tools()
    name = pick_tool(tools, MEALS_TOOL_CANDIDATES)
    if not name:
        sys.exit(f"该 MCP 未提供菜单查询工具。当前工具：{[t.get('name') for t in tools]}")
    args = {}
    if a.store:
        args["storeCode"] = a.store
    r = c.call_tool(name, args)
    meals = parse_meals(r["payload"]) if r["payload"] is not None else []
    out = {"meta": {"tool": name, "store": a.store, "count": len(meals)}, "meals": meals}
    if a.out:
        p = Path(a.out)
        p.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"已写入 {p}（{len(meals)} 个餐品）")
    else:
        print(json.dumps(out, ensure_ascii=False, indent=2)[:4000])
    return 0


def cmd_sync(a):
    """一键同步：营养库 + 门店价格 → 合并进 references/menu-nutrition.json"""
    c = McpClient()
    if not c.token:
        sys.exit("未检测到 MCD_MCP_TOKEN")
    c.initialize()
    tools = c.list_tools()

    REFERENCES.mkdir(parents=True, exist_ok=True)
    stats = {}

    nt = pick_tool(tools, NUTRITION_TOOL_CANDIDATES)
    if nt:
        r = c.call_tool(nt, {})
        (REFERENCES / "mcp-nutrition.txt").write_text(r["text"], encoding="utf-8")
        stats["nutrition_rows"] = len(parse_nutrition(r["payload"])) if r["payload"] else 0
        print(f"✔ 营养库已拉取：{stats['nutrition_rows']} 条")
    else:
        print("✘ 未找到营养工具，跳过")

    mt = pick_tool(tools, MEALS_TOOL_CANDIDATES)
    if mt and a.store:
        r = c.call_tool(mt, {"storeCode": a.store})
        meals = parse_meals(r["payload"]) if r["payload"] else []
        (REFERENCES / "mcp-meals.json").write_text(
            json.dumps({"storeCode": a.store, "meals": meals},
                       ensure_ascii=False, indent=2), encoding="utf-8")
        stats["meals"] = len(meals)
        print(f"✔ 门店菜单已拉取：{len(meals)} 个餐品（门店 {a.store}）")
    else:
        print("✘ 未指定门店或未找到菜单工具，跳过价格同步")

    # 调用主脚本合并
    here = str(Path(__file__).resolve().parent)
    if here not in sys.path:
        sys.path.insert(0, here)
    try:
        import mcd
    except ImportError:
        print("（未找到 mcd.py，跳过合并）")
        return 0
    ns = argparse.Namespace(
        nutrition=str(REFERENCES / "mcp-nutrition.txt") if nt else None,
        meals=str(REFERENCES / "mcp-meals.json") if (mt and a.store) else None)
    mcd.cmd_refresh(ns)
    return 0


def cmd_call(a):
    c = McpClient()
    if not c.token:
        sys.exit("未检测到 MCD_MCP_TOKEN")
    c.initialize()
    args = json.loads(a.args) if a.args else {}
    r = c.call_tool(a.name, args)
    if a.raw:
        print(json.dumps(r["raw"], ensure_ascii=False, indent=2))
    elif r["payload"] is not None:
        print(json.dumps(r["payload"], ensure_ascii=False, indent=2)[:6000])
    else:
        print(r["text"][:6000])
    return 0


def main():
    p = argparse.ArgumentParser(description="麦当劳中国官方 MCP 客户端")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("ping", help="连通性自检")
    s.set_defaults(func=cmd_ping)

    s = sub.add_parser("tools", help="打印工具清单")
    s.set_defaults(func=cmd_tools)

    s = sub.add_parser("nutrition", help="拉取官方营养库")
    s.add_argument("-o", "--out")
    s.set_defaults(func=cmd_nutrition)

    s = sub.add_parser("meals", help="拉取门店菜单与价格")
    s.add_argument("--store", help="门店编码，如 1420227")
    s.add_argument("-o", "--out")
    s.set_defaults(func=cmd_meals)

    s = sub.add_parser("sync", help="一键同步营养+价格到数据集")
    s.add_argument("--store", help="门店编码")
    s.set_defaults(func=cmd_sync)

    s = sub.add_parser("call", help="调用任意工具")
    s.add_argument("--name", required=True)
    s.add_argument("--args", help='JSON 字符串，如 \'{"storeCode":"1420227"}\'')
    s.add_argument("--raw", action="store_true")
    s.set_defaults(func=cmd_call)

    a = p.parse_args()
    sys.exit(a.func(a) or 0)


if __name__ == "__main__":
    main()
