import hashlib

import json

import shutil

from pathlib import Path



from sqlalchemy.orm import Session



from app.celery_app import celery_app

from app.config import settings

from app.database import SessionLocal

from app.models import Task, TaskStatus

from app.agents.llm import should_skip_agent
from app.agents.runner import run_agent
from app.services.case1_validate import run_case1_validation
from app.services.case1_xlsx_fill import try_fill_case1_collection_from_elements
from app.services.case2_schema_pipeline import (
    apply_case2_calc_rules,
    backfill_case2_schema,
    has_case2_filled_schema,
    validate_case2_backfill,
)
from app.services.ocr_runner import ocr_guards_enabled, run_ocr
from app.services.paths import (
    copy_collection_template_into_extract,
    ensure_storage,
    task_extract_dir,
)
from app.services.reuse_extract import (
    copy_extract_skip_outputs,
    find_reusable_extract,
)
from app.services.tools_sync import copy_task_tools_to_extract
from app.services.task_meta import write_task_meta
from app.services.unzip_service import extract_zip_archive




def _classification_outputs_ready(outputs_dir: Path) -> tuple[bool, str]:
    cls_json = outputs_dir / "classification.json"
    if not cls_json.is_file():
        return False, "缺少 outputs/classification.json"
    try:
        json.loads(cls_json.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return False, f"classification.json 解析失败: {exc}"
    return True, ""


def _extraction_outputs_ready(outputs_dir: Path) -> tuple[bool, str]:
    ext_json = outputs_dir / "extracted.json"
    if not ext_json.is_file():
        return False, "缺少 outputs/extracted.json"
    try:
        json.loads(ext_json.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return False, f"extracted.json 解析失败: {exc}"
    return True, ""


def _review_outputs_ready(outputs_dir: Path) -> tuple[bool, str]:
    """判定 classification.json / extracted.json 是否存在且为合法 JSON。"""
    cls_json = outputs_dir / "classification.json"
    ext_json = outputs_dir / "extracted.json"
    if not cls_json.is_file():
        return False, "缺少 outputs/classification.json"
    if not ext_json.is_file():
        return False, "缺少 outputs/extracted.json"
    try:
        json.loads(cls_json.read_text(encoding="utf-8"))
        json.loads(ext_json.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return False, f"outputs JSON 解析失败: {exc}"
    return True, ""


def _review_outputs_ready_for_kind(task_kind: str, outputs_dir: Path) -> tuple[bool, str]:
    if task_kind == "classification":
        return _classification_outputs_ready(outputs_dir)
    if task_kind == "extraction":
        return _extraction_outputs_ready(outputs_dir)
    return _review_outputs_ready(outputs_dir)


def _case1_outputs_ready(outputs_dir: Path) -> tuple[bool, str]:
    """Case1：以已填信息收集表为成功标准。"""
    filled = outputs_dir / "collection_filled.xlsx"
    if not filled.is_file():
        return False, "缺少 outputs/collection_filled.xlsx"
    if filled.stat().st_size < 512:
        return False, "collection_filled.xlsx 过小或可能损坏"
    return True, ""


def _case2_outputs_ready(outputs_dir: Path) -> tuple[bool, str]:
    """Case2：产物存在且业务校验通过才算可用。"""
    ok, msg = _case1_outputs_ready(outputs_dir)
    if not ok:
        return ok, msg
    extract_root = outputs_dir.parent
    if not has_case2_filled_schema(extract_root):
        return False, "缺少有效的 outputs/case2_filled_schema.json"
    return validate_case2_backfill(extract_root)


def _template_outputs_ready(
    task_kind: str, outputs_dir: Path
) -> tuple[bool, str]:
    if task_kind == "case2":
        return _case2_outputs_ready(outputs_dir)
    return _case1_outputs_ready(outputs_dir)


def _build_result_outputs(outputs_dir: Path, *, is_case1: bool, run_collection_fill: bool) -> dict:
    outs: dict[str, str] = {
        "classification": "outputs/classification.json",
        "extracted": "outputs/extracted.json",
        "agent_log": "outputs/agent.log",
        "claude_log": "outputs/claude.log",  # alias for API compat
    }
    if (outputs_dir / "ocr.log").is_file():
        outs["ocr_log"] = "outputs/ocr.log"
    filled_path = outputs_dir / "collection_filled.xlsx"
    if filled_path.is_file() and run_collection_fill:
        outs["collection_filled"] = "outputs/collection_filled.xlsx"
    notes = outputs_dir / "collection_fill_notes.md"
    if notes.is_file():
        outs["collection_fill_notes"] = "outputs/collection_fill_notes.md"
    elements = outputs_dir / "elements_extracted.json"
    if elements.is_file():
        outs["elements_extracted"] = "outputs/elements_extracted.json"
    if is_case1 and "collection_filled" in outs:
        ordered: dict[str, str] = {"collection_filled": outs["collection_filled"]}
        for k, v in outs.items():
            if k != "collection_filled":
                ordered[k] = v
        return ordered
    return outs


def _extract_has_material(extract_root: Path) -> bool:
    if (extract_root / ".task-meta.json").is_file():
        return True
    skip_parts = {".claude", "tools", "outputs", "inputs", "__MACOSX"}
    for p in extract_root.rglob("*"):
        if not p.is_file():
            continue
        if any(part in skip_parts for part in p.parts):
            continue
        if p.suffix.lower() in (".docx", ".pdf", ".pptx", ".ppt", ".xlsx", ".xlsm"):
            return True
    return False


def _ocr_already_done(extract_root: Path, outputs_dir: Path) -> bool:
    """仅当已有 OCR/正文 markdown 时视为完成；「用户未勾选已跳过」的 ocr.log 不算。"""
    del outputs_dir  # 保留参数兼容调用方
    ocr_text = extract_root / "ocr_text"
    return ocr_text.is_dir() and any(ocr_text.rglob("*.md"))


def _extract_has_pdf_or_pptx(extract_root: Path) -> bool:
    skip = {"ocr_text", "outputs", "inputs", "tools", "__MACOSX", ".claude"}
    for pattern in ("*.pdf", "*.pptx", "*.ppt"):
        for p in extract_root.rglob(pattern):
            if any(part in skip for part in p.parts):
                continue
            return True
    return False


def _db() -> Session:

    return SessionLocal()





@celery_app.task(name="process_review_task")

def process_review_task(task_id: str, resume: bool = False) -> dict:

    ensure_storage()

    db = _db()

    try:

        task = db.get(Task, task_id)

        if not task:

            return {"ok": False, "error": "task not found"}



        extract_root = task_extract_dir(task_id)

        zip_path = Path(task.zip_path) if task.zip_path else None



        task_kind = getattr(task, "task_kind", "general")
        is_case1 = task_kind == "case1"
        is_case2 = task_kind == "case2"
        is_template_case = is_case1 or is_case2
        is_review_case = task_kind in ("general", "classification", "extraction")

        task.status = TaskStatus.EXTRACTING.value

        task.progress_message = (
            "续跑：正在准备材料…"
            if resume and is_template_case
            else "续跑：正在解压…"
            if resume
            else ("正在准备材料…" if is_template_case else "正在解压 ZIP…")
        )

        task.extract_path = str(extract_root)
        task.error_message = None

        db.commit()



        if not zip_path or not zip_path.exists():

            task.status = TaskStatus.FAILED.value

            task.error_message = "ZIP 文件不存在"

            db.commit()

            return {"ok": False, "error": "missing zip"}



        if not task.zip_md5:

            task.zip_md5 = hashlib.md5(zip_path.read_bytes()).hexdigest()

            db.commit()



        reuse_src = None

        ocr_from_cache = False

        if task.zip_md5:

            guards_on = ocr_guards_enabled(task.task_kind or "")
            reuse_src, ocr_from_cache = find_reusable_extract(
                db,
                task.zip_md5,
                task_id,
                expected_ocr={
                    "text_layer_guard": guards_on and settings.ocr_text_layer_guard,
                    "table_split": guards_on and settings.ocr_table_split,
                },
            )



        keep_extract = resume and _extract_has_material(extract_root)

        if extract_root.exists() and not keep_extract:
            shutil.rmtree(extract_root)

        if keep_extract:
            task.progress_message = "续跑：保留已有解压目录与中间产物…"
            db.commit()
        elif reuse_src is not None:
            task.progress_message = (
                "ZIP MD5 与历史任务一致，复用解压目录（跳过重复解压）…"
            )
            db.commit()
            copy_extract_skip_outputs(reuse_src, extract_root)
        else:
            extract_zip_archive(zip_path, extract_root)



        ct_path, ct_fmt = copy_collection_template_into_extract(

            task_id,

            task.collection_template_original_filename,

            extract_root,

        )

        fill_coll = getattr(task, "run_collection_fill", True)

        meta_ct_path = ct_path if fill_coll else None

        meta_ct_fmt = ct_fmt if meta_ct_path else None

        judgment_rules = getattr(task, "indicator_judgment_rules", None)
        fill_logic_rules = getattr(task, "fill_logic_rules", None)

        write_task_meta(

            extract_root,

            task_id=task_id,

            classification_basis=task.classification_basis,

            extract_schema=task.extract_schema,

            collection_template_path=meta_ct_path,

            collection_template_format=meta_ct_fmt,

            task_kind=getattr(task, "task_kind", None),

            indicator_judgment_rules=judgment_rules,

            fill_logic_rules=fill_logic_rules,

        )

        if is_case1 and judgment_rules and str(judgment_rules).strip():
            inputs_dir = extract_root / "inputs"
            inputs_dir.mkdir(parents=True, exist_ok=True)
            rules_path = inputs_dir / "indicator_judgment_rules.md"
            rules_path.write_text(
                "# 用户指标判断规则（优先适用）\n\n"
                + str(judgment_rules).strip()
                + "\n",
                encoding="utf-8",
            )

        if is_case2 and fill_logic_rules and str(fill_logic_rules).strip():
            import sys

            scripts_dir = Path(__file__).resolve().parent.parent / "scripts"
            if str(scripts_dir) not in sys.path:
                sys.path.insert(0, str(scripts_dir))
            from parse_case2_calc_rules import write_fill_rules_files

            write_fill_rules_files(extract_root, str(fill_logic_rules).strip())

        # LangGraph agents load prompts from code; still sync helper scripts for debugging.
        copy_task_tools_to_extract(extract_root)



        outputs_dir = extract_root / "outputs"

        outputs_dir.mkdir(parents=True, exist_ok=True)



        task_run_ocr = getattr(task, "run_ocr", True)
        # Case1：补充材料含 PDF/PPT 且尚未产出 ocr_text 时自动开启 Docling
        if (
            is_case1
            and not settings.skip_ocr
            and not _ocr_already_done(extract_root, outputs_dir)
            and _extract_has_pdf_or_pptx(extract_root)
        ):
            task_run_ocr = True
            task.run_ocr = True
            db.commit()

        want_ocr = task_run_ocr and not settings.skip_ocr

        if resume and _ocr_already_done(extract_root, outputs_dir):
            want_ocr = False
            ocr_log_path = outputs_dir / "ocr.log"
            note = "续跑：OCR 已完成，已跳过。\n"
            if ocr_log_path.is_file():
                prev = ocr_log_path.read_text(encoding="utf-8")
                if note.strip() not in prev:
                    ocr_log_path.write_text(prev + "\n" + note, encoding="utf-8")
            else:
                ocr_log_path.write_text(note, encoding="utf-8")

        if want_ocr:

            if reuse_src is not None and ocr_from_cache:

                (outputs_dir / "ocr.log").write_text(

                    "OCR skipped: same ZIP MD5, reused ocr_text from another task.\n",

                    encoding="utf-8",

                )

            else:

                task.status = TaskStatus.OCR_RUNNING.value

                task.progress_message = "正在 OCR（Docling + RapidOCR）…"

                db.commit()

                code, ocr_log = run_ocr(
                    extract_root,
                    log_path=outputs_dir / "ocr.log",
                    task_kind=task.task_kind or "",
                )

                if code != 0:

                    task.status = TaskStatus.FAILED.value

                    task.error_message = f"OCR 失败: {ocr_log[-2000:]}"

                    task.progress_message = None

                    db.commit()

                    return {"ok": False, "error": "ocr failed"}

        elif not task_run_ocr:

            (outputs_dir / "ocr.log").write_text(

                "用户未勾选「执行 OCR」，已跳过。\n",

                encoding="utf-8",

            )



        task.status = TaskStatus.AGENT_RUNNING.value

        task.progress_message = (
            "智能体正在按模板填报…"
            if is_template_case
            else "正在调用智能体进行材料分类…"
            if task_kind == "classification"
            else "正在调用智能体进行要素抽取…"
            if task_kind == "extraction"
            else "正在调用 智能体 进行分类与抽取…"
        )

        db.commit()



        task_run_agent = getattr(task, "run_agent", True)
        want_agent = task_run_agent and not should_skip_agent()
        skip_note_cls = (
            "SKIP_AGENT 调试输出"
            if should_skip_agent()
            else "用户未勾选「分类与要素抽取」，已跳过智能体"
        )

        def _progress_cb(msg: str) -> None:
            try:
                t = db.get(Task, task_id)
                if t:
                    t.progress_message = msg[:500]
                    db.commit()
            except Exception:  # noqa: BLE001
                db.rollback()

        if not want_agent:
            cls_json = outputs_dir / "classification.json"
            ext_json = outputs_dir / "extracted.json"
            if task_kind in ("general", "classification"):
                cls_json.write_text(
                    json.dumps(
                        {
                            "task_id": task_id,
                            "categories": [],
                            "unclassified": [],
                            "note": skip_note_cls,
                        },
                        ensure_ascii=False,
                        indent=2,
                    ),
                    encoding="utf-8",
                )
            if task_kind in ("general", "extraction"):
                ext_json.write_text(
                    json.dumps(
                        {"task_id": task_id, "fields": {}},
                        ensure_ascii=False,
                        indent=2,
                    ),
                    encoding="utf-8",
                )
            skip_msg = "skip_agent=true, 智能体未执行\n"
            (outputs_dir / "agent.log").write_text(skip_msg, encoding="utf-8")
            (outputs_dir / "claude.log").write_text(skip_msg, encoding="utf-8")
            code, log_tail, err_tail = 0, "skip_agent", ""
            task.claude_log_tail = log_tail
        else:
            skip_agent_run = False
            log_tail = ""
            err_tail = ""

            if is_template_case and _template_outputs_ready(task_kind, outputs_dir)[0]:
                if is_case2 and not has_case2_filled_schema(extract_root):
                    skip_agent_run = False
                elif is_case1:
                    # 仅当指标表校验已通过才跳过；校验失败或缺少正文索引则重跑智能体
                    has_docx_body = (
                        extract_root / "outputs" / "docx_text_index.json"
                    ).is_file()
                    val_ok, _ = run_case1_validation(extract_root)
                    if val_ok and has_docx_body:
                        skip_agent_run = True
                        log_tail = "[续跑] 指标表已存在且校验通过，跳过智能体。"
                    else:
                        skip_agent_run = False
                else:
                    skip_agent_run = True
                    log_tail = "[续跑] 指标表已存在，跳过智能体。"
            elif is_case2 and has_case2_filled_schema(extract_root):
                calc_ok, calc_log = apply_case2_calc_rules(extract_root)
                bf_ok, bf_log = backfill_case2_schema(extract_root)
                br_ok, br_msg = (
                    validate_case2_backfill(extract_root) if bf_ok else (False, bf_log)
                )
                if bf_ok and br_ok and _case2_outputs_ready(outputs_dir)[0]:
                    skip_agent_run = True
                    log_tail = (
                        f"[续跑回填] calc={calc_log}\n{bf_log}\n[校验] {br_msg}"
                    )
            elif is_case1 and (extract_root / "outputs" / "elements_extracted.json").is_file():
                fb_ok, fb_log = try_fill_case1_collection_from_elements(extract_root)
                if fb_ok and _case1_outputs_ready(outputs_dir)[0]:
                    skip_agent_run = True
                    log_tail = f"[续跑兜底填表] {fb_log}"
                    (outputs_dir / "collection_fill_fallback.log").write_text(
                        fb_log, encoding="utf-8"
                    )
            elif is_review_case and _review_outputs_ready_for_kind(task_kind, outputs_dir)[0]:
                skip_agent_run = True
                log_tail = "[续跑] 目标 JSON 已存在，跳过智能体。"

            if skip_agent_run:
                code = 0
                task.claude_log_tail = log_tail
            else:
                code, log_tail, err_tail = run_agent(
                    extract_root,
                    outputs_dir,
                    task_id=str(task.id),
                    task_kind=getattr(task, "task_kind", None),
                    on_progress=_progress_cb,
                )
                if is_case2 and not has_case2_filled_schema(extract_root):
                    task.claude_log_tail = log_tail
                    task.status = TaskStatus.FAILED.value
                    task.error_message = (
                        "Case2 缺少 outputs/case2_filled_schema.json，"
                        "请检查智能体日志后重试。"
                    )
                    task.progress_message = None
                    db.commit()
                    return {"ok": False, "error": task.error_message}

            if is_template_case:
                if is_case1 and not _case1_outputs_ready(outputs_dir)[0]:
                    fb_ok, fb_log = try_fill_case1_collection_from_elements(
                        extract_root
                    )
                    if fb_ok:
                        log_tail = (log_tail or "") + f"\n---\n[兜底填表] {fb_log}\n"
                        (outputs_dir / "collection_fill_fallback.log").write_text(
                            fb_log, encoding="utf-8"
                        )
                outputs_ok, outputs_err = _template_outputs_ready(
                    task_kind, outputs_dir
                )
            else:
                outputs_ok, outputs_err = _review_outputs_ready_for_kind(
                    task_kind, outputs_dir
                )

            if not outputs_ok:
                task.claude_log_tail = log_tail
                task.status = TaskStatus.FAILED.value
                api_hint = ""
                low = (log_tail or "").lower()
                if "529" in (log_tail or "") or "overloaded" in low or "rate" in low:
                    api_hint = (
                        "\n提示：LLM API 瞬时错误。若中间产物已生成，"
                        "可续跑任务或检查 outputs/。"
                    )
                task.error_message = (
                    f"智能体退出码 {code}；{outputs_err}{api_hint}\n{err_tail}"
                )
                task.progress_message = None
                db.commit()
                return {"ok": False, "error": task.error_message}

            # 以磁盘合法 outputs 为准；非零退出码但产物齐全仍判成功
            if code != 0:
                success_desc = (
                    "outputs/collection_filled.xlsx 已生成"
                    if is_template_case
                    else "outputs/classification.json 已存在且可解析"
                    if task_kind == "classification"
                    else "outputs/extracted.json 已存在且可解析"
                    if task_kind == "extraction"
                    else "outputs/classification.json 与 extracted.json 已存在且可解析"
                )
                warn = (
                    f"\n---\n注意：智能体退出码为 {code}，"
                    f"但 {success_desc}，已判定任务成功。"
                    f"\nstderr 节选:\n{err_tail}"
                )
                task.claude_log_tail = log_tail + warn
            else:
                task.claude_log_tail = log_tail

        fill_coll = getattr(task, "run_collection_fill", True)

        if is_template_case and not want_agent:
            task.status = TaskStatus.FAILED.value
            task.error_message = "模板填报任务需要智能体执行，无法跳过"
            task.progress_message = None
            db.commit()
            return {"ok": False, "error": task.error_message}

        if is_template_case and want_agent:
            ok, err = _template_outputs_ready(task_kind, outputs_dir)
            if not ok:
                task.status = TaskStatus.FAILED.value
                task.error_message = err
                task.progress_message = None
                db.commit()
                return {"ok": False, "error": err}

            if is_case1:
                val_ok, val_msg = run_case1_validation(extract_root)
                if not val_ok:
                    task.status = TaskStatus.FAILED.value
                    task.error_message = (
                        f"{val_msg}；请续跑智能体按 template_row_catalog 修正填表，"
                        f"或查看 outputs/validation_report.json"
                    )
                    task.progress_message = None
                    db.commit()
                    return {"ok": False, "error": task.error_message}

        task.status = TaskStatus.COMPLETED.value
        task.progress_message = (
            "完成" if not is_template_case else "指标表已生成，可下载"
        )

        outs = _build_result_outputs(
            outputs_dir,
            is_case1=is_template_case,
            run_collection_fill=fill_coll,
        )
        if is_template_case and (outputs_dir / "validation_report.json").is_file():
            outs["validation_report"] = "outputs/validation_report.json"
        if is_template_case and (outputs_dir / "template_row_catalog.json").is_file():
            outs["template_row_catalog"] = "outputs/template_row_catalog.json"
        if is_case2 and (outputs_dir / "case2_fill_schema.json").is_file():
            outs["case2_fill_schema"] = "outputs/case2_fill_schema.json"
        if is_case2 and (outputs_dir / "case2_filled_schema.json").is_file():
            outs["case2_filled_schema"] = "outputs/case2_filled_schema.json"
        if is_case2 and (outputs_dir / "case2_evidence_catalog.json").is_file():
            outs["case2_evidence_catalog"] = "outputs/case2_evidence_catalog.json"
        if is_case2 and (outputs_dir / "case2_period_map.json").is_file():
            outs["case2_period_map"] = "outputs/case2_period_map.json"
        if is_case2 and (outputs_dir / "backfill_report.json").is_file():
            outs["backfill_report"] = "outputs/backfill_report.json"
        if is_case2 and (outputs_dir / "calc_rules_report.json").is_file():
            outs["calc_rules_report"] = "outputs/calc_rules_report.json"

        task.result_summary = {"outputs": outs}

        db.commit()

        return {"ok": True, "task_id": task_id}

    except Exception as exc:  # noqa: BLE001

        try:

            t = db.get(Task, task_id)

            if t:

                t.status = TaskStatus.FAILED.value

                t.error_message = str(exc)

                t.progress_message = None

                db.commit()

        except Exception:

            db.rollback()

        return {"ok": False, "error": str(exc)}

    finally:

        db.close()
