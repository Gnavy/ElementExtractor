from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from app.config import settings
from app.agents.llm import guard_config, output_cap, structured_llm
from app.agents.prompts import case1 as prompts
from app.agents.schemas.case1_row import RegionResolve
from app.agents.tools.context import collect_ocr_snippets
from app.agents.tools.script_runner import run_tool_script


def resolve_region_node(state: dict[str, Any]) -> dict[str, Any]:
    root = Path(state["extract_root"])
    context = collect_ocr_snippets(root, max_files=8, max_total_chars=10000)
    llm = structured_llm(RegionResolve)
    # 只返回城市/区县/依据，2048 足够
    result: RegionResolve = llm.invoke(
        [
            ("system", prompts.REGION_SYSTEM),
            ("human", prompts.REGION_USER.format(context=context)),
        ],
        config=guard_config(),
        **output_cap(2048),
    )
    region = " ".join(x for x in [result.city, result.district] if x).strip()
    return {
        "region": region or result.city or "",
        "log_lines": [f"推断项目地区: {region or '未知'}"],
        "progress": f"项目地区: {region or '未知'}",
    }


def _safe_topic(name: str) -> str:
    s = re.sub(r"[^\w\u4e00-\u9fff]+", "_", name)[:40]
    return s or "policy"


def tavily_batch_node(state: dict[str, Any]) -> dict[str, Any]:
    root = Path(state["extract_root"])
    groups = state.get("indicator_groups") or []
    region = state.get("region") or "中国"
    results: dict[str, Any] = {}
    logs: list[str] = []

    if not settings.tavily_enabled or not settings.tavily_api_key:
        return {
            "tavily_results": {},
            "log_lines": ["Tavily 未启用或缺少 API Key，跳过联网检索"],
            "progress": "跳过 Tavily",
        }

    env = {"TAVILY_API_KEY": settings.tavily_api_key}
    for grp in groups:
        if not grp.get("requires_tavily_search"):
            continue
        name = grp.get("indicator_name") or "当地政策"
        topic = grp.get("tavily_query_hint") or name
        slug = _safe_topic(name)
        out_json = f"outputs/tavily_{slug}.json"
        out_md = f"outputs/tavily_{slug}.md"
        ok, log = run_tool_script(
            root,
            "tavily_search.py",
            [
                "--region",
                region or "中国",
                "--topic",
                str(topic)[:200],
                "--out",
                out_json,
                "--md-out",
                out_md,
            ],
            timeout=120,
            env_extra=env,
        )
        md_text = ""
        md_path = root / out_md
        if md_path.is_file():
            md_text = md_path.read_text(encoding="utf-8", errors="replace")[:6000]
        results[name] = {
            "ok": ok,
            "json": out_json,
            "md": out_md,
            "text": md_text,
            "log": log[-400:],
        }
        logs.append(f"Tavily {'OK' if ok else 'FAIL'}: {name}")

    return {
        "tavily_results": results,
        "log_lines": logs or ["无需 Tavily 的指标组"],
        "progress": f"Tavily 完成（{len(results)} 组）",
    }
