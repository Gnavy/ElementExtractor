from __future__ import annotations

from pathlib import Path
from typing import Any

from app.agents.tools.context import write_json
from app.agents.tools.script_runner import run_tool_script


def crop_images_node(state: dict[str, Any]) -> dict[str, Any]:
    """Run crop_region.py for image-type fields that have bbox hints."""
    root = Path(state["extract_root"])
    crop_dir = root / "outputs" / "image_crops"
    crop_dir.mkdir(parents=True, exist_ok=True)
    fields = dict(state.get("extracted_fields") or {})
    updated = False
    logs: list[str] = []

    for name, entry in fields.items():
        if not isinstance(entry, dict):
            continue
        crop = entry.get("_crop") or {}
        bbox = crop.get("bbox")
        source = crop.get("source")
        if not bbox or not source:
            continue
        src_path = root / source
        if not src_path.is_file():
            logs.append(f"裁剪跳过 {name}: 源文件不存在 {source}")
            continue
        out_rel = f"outputs/image_crops/{name}.png"
        args = [
            "--src",
            source,
            "--out",
            out_rel,
            "--bbox",
            str(bbox),
        ]
        page = crop.get("page")
        if page is not None:
            args.extend(["--page", str(page), "--zoom", "2"])
        ok, log = run_tool_script(root, "crop_region.py", args, timeout=120)
        if ok and (root / out_rel).is_file():
            entry["value"] = out_rel
            entry["source_files"] = list(
                dict.fromkeys((entry.get("source_files") or []) + [source])
            )
            entry["notes"] = (
                (entry.get("notes") or "")
                + f" page={page} bbox={bbox}"
            ).strip()
            updated = True
            logs.append(f"已裁剪 {name} -> {out_rel}")
        else:
            logs.append(f"裁剪失败 {name}: {log[:200]}")

    if updated:
        meta = state.get("meta") or {}
        task_id = state.get("task_id") or meta.get("task_id") or ""
        clean = {
            k: {kk: vv for kk, vv in v.items() if kk != "_crop"}
            for k, v in fields.items()
            if isinstance(v, dict)
        }
        write_json(
            root / "outputs" / "extracted.json",
            {"task_id": task_id, "fields": clean},
        )
        return {
            "extracted_fields": fields,
            "log_lines": logs or ["无图片字段需裁剪"],
            "progress": "图片字段裁剪完成",
        }
    return {
        "log_lines": logs or ["无图片字段需裁剪"],
        "progress": "跳过图片裁剪",
    }
