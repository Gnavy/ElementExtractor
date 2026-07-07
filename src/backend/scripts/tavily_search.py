#!/usr/bin/env python3
"""
Tavily 联网检索（Case1 当地政策 / 规划指标辅助）。

依赖环境变量 TAVILY_API_KEY（由 Worker 注入，勿写入仓库）。

用法（cwd = extract_root）：
  python tools/tavily_search.py --query "成都市 房地产 限购 限贷 政策 2024"
  python tools/tavily_search.py --region 成都 --topic "城市总体规划 东客站板块" --out outputs/tavily_planning_chengdu.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path


def tavily_search(
    query: str,
    *,
    max_results: int = 5,
    search_depth: str = "advanced",
    include_answer: bool = True,
) -> dict:
    api_key = os.environ.get("TAVILY_API_KEY", "").strip()
    if not api_key:
        raise SystemExit(
            "TAVILY_API_KEY 未设置。请在 backend/.env 配置后重启 Celery Worker。"
        )

    body = {
        "api_key": api_key,
        "query": query.strip(),
        "search_depth": search_depth,
        "include_answer": include_answer,
        "max_results": max(1, min(max_results, 10)),
    }
    req = urllib.request.Request(
        "https://api.tavily.com/search",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")[:2000]
        raise SystemExit(f"Tavily HTTP {e.code}: {detail}") from e
    except urllib.error.URLError as e:
        raise SystemExit(f"Tavily 请求失败: {e}") from e


def _format_markdown(data: dict, query: str) -> str:
    lines = [f"# Tavily 检索：{query}", ""]
    answer = data.get("answer")
    if answer:
        lines.extend(["## 摘要", str(answer), ""])
    results = data.get("results") or []
    if results:
        lines.append("## 来源片段")
        for i, r in enumerate(results, 1):
            title = r.get("title") or "(无标题)"
            url = r.get("url") or ""
            content = (r.get("content") or "").strip()
            lines.append(f"### {i}. {title}")
            if url:
                lines.append(f"- URL: {url}")
            if content:
                lines.append(f"- 摘录: {content[:800]}")
            lines.append("")
    return "\n".join(lines).strip() + "\n"


def main() -> None:
    p = argparse.ArgumentParser(description="Tavily 政策/规划检索")
    p.add_argument("--query", help="完整检索语句")
    p.add_argument("--region", help="城市/区县，如 成都、成华区")
    p.add_argument("--topic", help="与 --region 组合：检索主题")
    p.add_argument("--max-results", type=int, default=5)
    p.add_argument("--depth", choices=["basic", "advanced"], default="advanced")
    p.add_argument("--out", help="JSON 输出路径，如 outputs/tavily_policy.json")
    p.add_argument("--md-out", help="Markdown 摘要路径")
    args = p.parse_args()

    if args.query:
        query = args.query.strip()
    elif args.region and args.topic:
        query = f"{args.region.strip()} {args.topic.strip()}"
    else:
        p.error("请提供 --query，或同时提供 --region 与 --topic")

    cwd = Path.cwd().resolve()
    data = tavily_search(
        query,
        max_results=args.max_results,
        search_depth=args.depth,
    )

    payload = {
        "query": query,
        "answer": data.get("answer"),
        "results": [
            {
                "title": r.get("title"),
                "url": r.get("url"),
                "content": r.get("content"),
                "score": r.get("score"),
            }
            for r in (data.get("results") or [])
        ],
    }

    if args.out:
        out = (cwd / args.out).resolve()
        if not str(out).startswith(str(cwd)):
            raise SystemExit("输出路径必须在当前工作目录之下")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"ok": True, "out": args.out, "query": query}, ensure_ascii=False))
    else:
        print(json.dumps(payload, ensure_ascii=False, indent=2))

    if args.md_out:
        md_out = (cwd / args.md_out).resolve()
        if not str(md_out).startswith(str(cwd)):
            raise SystemExit("md-out 路径必须在当前工作目录之下")
        md_out.parent.mkdir(parents=True, exist_ok=True)
        md_out.write_text(_format_markdown(data, query), encoding="utf-8")


if __name__ == "__main__":
    main()
