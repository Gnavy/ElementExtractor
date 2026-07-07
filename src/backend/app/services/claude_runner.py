import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import IO, TextIO

from app.config import settings

_TRANSIENT_CLAUDE_MARKERS = (
    "overloaded_error",
    "529",
    "1305",
    "访问量过大",
    "rate_limit",
    "timeout",
    "temporarily unavailable",
)


CLAUDE_PROMPT = """你是业务审查材料处理助手。工作目录已解压且包含用户上传的项目文件。

必须执行：
1. 阅读当前目录下的 `.task-meta.json`：含 classification_basis、extract_schema；若存在 `collection_template_path`，表示用户上传了信息收集表模板（xlsx/xlsm），须在 SKILL 指引下分析表头并生成 `outputs/collection_filled.xlsx`。
2. 若存在 `.claude/skills/business-review-case1/SKILL.md`，优先严格遵循该 Skill；否则遵循 `.claude/skills/business-review/SKILL.md`。
3. 在 `outputs/` 目录生成：
   - `classification.json`：对文件的分类结果。
   - `extracted.json`：按 extract_schema 抽取的结构化结果。
   - 若 meta 含信息收集表路径，还须生成 `outputs/collection_filled.xlsx`。
4. 优先阅读 `ocr_text/` 下与 PDF 对应的 Markdown（若存在）；并系统读取原始 pdf/docx/xlsx/ppt/pptx（可用 tools 脚本）。
5. 不要运行来源不明的可执行文件；可按 SKILL 使用项目内 `tools/` 下的 Python 辅助脚本；不要访问外网。

完成后仅回复一行：DONE"""

def _case1_user_rules_block(meta: dict) -> str:
    rules = (meta.get("indicator_judgment_rules") or "").strip()
    if not rules:
        return ""
    preview = rules if len(rules) <= 3000 else rules[:3000] + "\n…（全文见 inputs/indicator_judgment_rules.md）"
    return f"""

【用户指标判断规则 · 最高优先级】
填表前**必须**阅读：
- `inputs/indicator_judgment_rules.md`
- `.task-meta.json` 字段 `indicator_judgment_rules`
与本节规则冲突时，**以用户规则为准**（仍须在尽调/补充材料或 Tavily 检索结果中可复核；禁止无依据编造）。

用户规则全文：
---
{preview}
---
"""


_CASE1_PROMPT_SUFFIX = """

【Case1 债权管理尽调 · 模板驱动填表】
1. 必读（按顺序）：
   - `.claude/skills/business-review-case1/SOP_信息收集表填报.md`（填表主规范）
   - `.claude/skills/business-review-case1/SKILL.md`
   - `.claude/skills/business-review-case1/SOP_债权管理尽职调查要素抽取.md`（尽调取证，辅助）
2. 填表前 **必须** 运行并阅读：
   - `python tools/dump_collection_template.py --src inputs/collection_template.xlsx`
   - 生成的 `outputs/template_row_catalog.json`（全部 indicator_groups）
3. **首要交付** `outputs/collection_filled.xlsx`：
   - 复制模板后仅填写 D「指标选择」、E「备注」；禁止照抄模板旧值。
   - `choice_mode=yes_no`（□选项）：**每行独立** 填「是」或「否」。
   - `choice_mode=exclusive`（1./2./3.选项）：组内 **仅一行** D 填入选项全文（与 C 列一致），其余 D 留空。
   - E 列备注：**一句话** 说明理由（含用于判断的关键事实与数据源文件），禁止长段 logic_trace。
   - 证据取证必须覆盖 `template_row_catalog.json` 中的 `data_source_priority`：优先按模板列“数据源优先顺序”指定的材料集合检索事实；当尽调 docx 未覆盖但补充材料（如可研/PPT 中的板块房价）有时，仍必须使用补充材料取证并写入备注。
   - 若某行的 `data_source_priority` 明确包含（或优先于）补充材料类型（如“研判报告”“可研”“PPT”对应材料），则必须至少引用一次补充材料中的关键事实；允许尽调 docx 缺失时仅用补充材料得出结论，但不得违反该行的数据源优先顺序。
4. **当地政策 / 规划指标（Tavily）**：`template_row_catalog.json` 中 `requires_tavily_search=true` 的指标组，须先用 `tools/tavily_search.py` 检索项目所在城市/区县的最新政策与规划，再结合尽调与补充材料填表；备注须引用 Tavily 结果 URL 或官方文件名称。
5. 禁止仅用 `elements_extracted.json` 批量映射填表；该 JSON 仅可作交叉校验（可选产出）。
6. 须写 `outputs/collection_fill_notes.md`（每行：row、选项、指标选择、一句备注）。
7. 完成后运行：`python tools/validate_collection_filled.py --catalog outputs/template_row_catalog.json --filled outputs/collection_filled.xlsx`
8. 回复 DONE 前确认 `collection_filled.xlsx` 存在且校验通过或已修正全部违规项。
"""

def _case2_user_rules_block(meta: dict) -> str:
    rules = (meta.get("fill_logic_rules") or "").strip()
    if not rules:
        return ""
    preview = rules if len(rules) <= 3000 else rules[:3000] + "\n…（全文见 inputs/fill_logic_rules.md）"
    return f"""

【用户填表逻辑与计算规则 · 最高优先级】
填表前**必须**阅读：
- `inputs/fill_logic_rules.md`
- `inputs/fill_calc_rules.json`（---CALC--- 块解析结果，供 Python 工具执行）
- `.task-meta.json` 字段 `fill_logic_rules`

与本节规则冲突时，**以用户规则为准**（直接摘录仍须源文件证据；**合计类字段由 Python 工具计算，禁止手算**）。

用户规则全文：
---
{preview}
---
"""


_CASE2_PROMPT_SUFFIX = """

【Case2 fill_plan 填表】
1. 必读：`.claude/skills/business-review-case2/SKILL.md` 与 `.claude/skills/business-review-case2/SOP_模板填报.md`。
2. 填表前生成 fill_plan（待填项含义+坐标，一个整对象）：
   - `python tools/dump_sheet_headers.py --src inputs/collection_template.xlsx --formulas`
   - `python tools/dump_case2_fill_schema.py --src inputs/collection_template.xlsx --out outputs/case2_fill_schema.json --catalog-out outputs/template_row_catalog.json`
3. **不要直接改 xlsx**。将 `outputs/case2_fill_schema.json` **整份复制** 为 `outputs/case2_filled_schema.json`，保持 `schema_version` / `sheets` / `items` / `fields` / `cell` 坐标不变，仅填值：
   - 按 **item**（一行科目或一行指标选项）阅读源文件后填写；
   - **先填可直接取证的原始科目**；合计/合并类 target 行可暂留空；
   - 每个 item 填 `fields` 下各列的 `value`（如 C/D/E/F 或 choice/remark）；
   - 每个 item 填 `confidence`、`reason_one_line`（一句话）、`evidence_refs`；
   - 财务报表：同一行各列尽量一次填完，不要拆成数百个独立任务。
4. 取证与硬规则：
   - 从 `sources/`、`ocr_text/` 直接提取；禁止推断/常识补全；
   - 无证据：`value` 留空，`reason_one_line` 写「文件中未发现相关信息」；
   - **例外**：`inputs/fill_calc_rules.json` 中的计算规则，在 components 已有证据时，由 Python 工具生成 target；`reason_one_line` 可写「计算规则: …」；
   - 映射类规则（如无法对应时填入「特殊报表科目」行）按 `inputs/fill_logic_rules.md` 执行。
5. **计算规则（禁止手算）**：填完原始科目后运行：
   - `python tools/apply_case2_calc_rules.py --filled outputs/case2_filled_schema.json --rules inputs/fill_calc_rules.json --report outputs/calc_rules_report.json`
   - Worker 也会自动执行；你须确认 `calc_rules_report.json` 中 applied 合理。
6. 交付：`case2_filled_schema.json`、`collection_fill_notes.md`；Worker 负责回填 xlsx。
7. 回复 DONE 前确认 `case2_filled_schema.json` 为合法 JSON 且结构与 fill_plan 一致。
"""

_COLLECTION_PROMPT_SUFFIX = """

【信息收集表强化】`.task-meta.json` 中已配置 `collection_template_path`，你必须：
- 将「尽职调查式填报 `outputs/collection_filled.xlsx`」与 `classification.json` / `extracted.json` 置于**同等优先级**；须在尽量检索 `ocr_text/`、诉讼/保全/裁定等相关路径后再保存表格；分类与抽取可在覆盖材料前提下适度精简，但三类产出均须合法完整。
- 每个 sheet **先读列标题上方的填写说明与口径**，再认定表头行与数据区；**禁止覆盖含 Excel 公式的单元格**（仅写入手工录入格），详见 SKILL。
- 回复 DONE 前须已生成 `outputs/collection_filled.xlsx`（合法 xlsx）。
"""


_CLASSIFICATION_ONLY_SUFFIX = """

【仅材料分类】
本次任务**只需**在 `outputs/` 生成 `classification.json`，**不要**生成 `extracted.json` 或 `collection_filled.xlsx`。
严格遵循 `.claude/skills/business-review/SKILL.md` 中「分类输出」章节。
完成后仅回复一行：DONE"""

_EXTRACTION_ONLY_SUFFIX = """

【仅要素抽取】
本次任务**只需**在 `outputs/` 生成 `extracted.json`，**不要**生成 `classification.json` 或 `collection_filled.xlsx`。
严格遵循 `.claude/skills/business-review/SKILL.md` 中「抽取输出」章节；若目录中已有 `outputs/classification.json` 可作参考。
完成后仅回复一行：DONE"""


def build_claude_prompt(extract_root: Path) -> str:
    meta_path = extract_root / ".task-meta.json"
    base = CLAUDE_PROMPT.rstrip()
    if not meta_path.is_file():
        return base
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return base
    if meta.get("task_kind") == "case1":
        return base + _case1_user_rules_block(meta) + _CASE1_PROMPT_SUFFIX
    if meta.get("task_kind") == "case2":
        return base + _case2_user_rules_block(meta) + _CASE2_PROMPT_SUFFIX
    if meta.get("task_kind") == "classification":
        return base + _CLASSIFICATION_ONLY_SUFFIX
    if meta.get("task_kind") == "extraction":
        return base + _EXTRACTION_ONLY_SUFFIX
    if meta.get("collection_template_path"):
        return base + _COLLECTION_PROMPT_SUFFIX
    return base


def _is_transient_claude_error(text: str) -> bool:
    low = text.lower()
    return any(m in low for m in _TRANSIENT_CLAUDE_MARKERS)


def _pipe_to_log_and_console(
    pipe: IO[str],
    log_fp: TextIO,
    chunks: list[str],
    *,
    stream_to_console: bool,
    console_prefix: str,
    is_stderr: bool,
) -> None:
    try:
        for line in iter(pipe.readline, ""):
            if not line:
                break
            chunks.append(line)
            log_fp.write(line)
            log_fp.flush()
            if stream_to_console:
                target = sys.stderr if is_stderr else sys.stdout
                target.write(f"{console_prefix}{line}")
                target.flush()
    finally:
        pipe.close()


def _claude_subprocess_env(task_kind: str | None) -> dict[str, str] | None:
    """Case1 注入 TAVILY_API_KEY；其余沿用 Worker 进程环境。"""
    if task_kind != "case1":
        return None
    if not settings.tavily_enabled or not settings.tavily_api_key:
        return None
    env = os.environ.copy()
    env["TAVILY_API_KEY"] = settings.tavily_api_key
    return env


def run_claude(
    extract_root: Path,
    outputs_dir: Path,
    *,
    task_id: str | None = None,
    task_kind: str | None = None,
) -> tuple[int, str, str]:
    """
    Invoke Claude Code CLI in non-interactive mode. Returns (code, combined_log_tail, stderr_tail).
    对 API 过载(529)等瞬时错误自动重试。
    """
    outputs_dir.mkdir(parents=True, exist_ok=True)
    log_file = outputs_dir / "claude.log"

    prompt = build_claude_prompt(extract_root)
    cmd = [
        settings.claude_bin,
        "-p",
        prompt,
        "--print",
        "--output-format",
        "text",
        "--permission-mode",
        "bypassPermissions",
        "--no-session-persistence",
    ]
    if settings.claude_verbose:
        cmd.append("--verbose")

    max_attempts = 3
    combined = ""
    err_tail = ""
    returncode = 1
    stream = settings.claude_stream_to_console
    prefix = f"[claude task={task_id}] " if task_id else "[claude] "

    for attempt in range(1, max_attempts + 1):
        stdout_chunks: list[str] = []
        stderr_chunks: list[str] = []
        log_mode = "a" if attempt > 1 else "w"

        with open(log_file, log_mode, encoding="utf-8", errors="replace") as log_fp:
            if attempt > 1:
                retry_msg = (
                    f"\n---\n[worker] Claude 瞬时错误，"
                    f"第 {attempt}/{max_attempts} 次重试…\n"
                )
                log_fp.write(retry_msg)
                log_fp.flush()
                if stream:
                    sys.stderr.write(retry_msg)
                    sys.stderr.flush()

            proc = subprocess.Popen(
                cmd,
                cwd=str(extract_root),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
                env=_claude_subprocess_env(task_kind),
            )
            t_out = threading.Thread(
                target=_pipe_to_log_and_console,
                args=(proc.stdout, log_fp, stdout_chunks),
                kwargs={
                    "stream_to_console": stream,
                    "console_prefix": prefix,
                    "is_stderr": False,
                },
                daemon=True,
            )
            t_err = threading.Thread(
                target=_pipe_to_log_and_console,
                args=(proc.stderr, log_fp, stderr_chunks),
                kwargs={
                    "stream_to_console": stream,
                    "console_prefix": f"{prefix}[stderr] ",
                    "is_stderr": True,
                },
                daemon=True,
            )
            t_out.start()
            t_err.start()
            try:
                returncode = proc.wait(timeout=settings.claude_timeout_sec)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
                returncode = 124
                timeout_msg = (
                    f"\n[worker] Claude 超时 ({settings.claude_timeout_sec}s)\n"
                )
                log_fp.write(timeout_msg)
                log_fp.flush()
                if stream:
                    sys.stderr.write(timeout_msg)
                    sys.stderr.flush()
            t_out.join()
            t_err.join()

        combined = "".join(stdout_chunks)
        if stderr_chunks:
            combined += "\n--- STDERR ---\n" + "".join(stderr_chunks)
        err_tail = ("".join(stderr_chunks))[-2000:]

        if returncode == 0:
            break
        if attempt < max_attempts and _is_transient_claude_error(combined):
            wait = 30 * attempt
            combined += (
                f"\n---\n[worker] Claude 瞬时错误，{wait}s 后第 {attempt + 1}/{max_attempts} 次重试…\n"
            )
            log_file.write_text(combined, encoding="utf-8", errors="replace")
            if stream:
                sys.stderr.write(combined[-500:])
                sys.stderr.flush()
            time.sleep(wait)
            continue
        break
    tail = combined[-6000:] if len(combined) > 6000 else combined
    return returncode, tail, err_tail
