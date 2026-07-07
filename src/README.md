# 业务审查场景（Zip + Celery + Claude Code）

## 前置条件

- Python 3.11+（后端）
- Node 18+（前端）
- Redis（在项目 `src` 目录执行 `docker compose up -d`；容器将 **6379 映射到主机 6380**，避免与本机已有 Redis 冲突。后端需设置 `REDIS_URL=redis://localhost:6380/0`）
- Conda 环境 `v312`（Docling + RapidOCR，用于 OCR 脚本）
- **LibreOffice**（`soffice`，用于 PPTX 先转 PDF 再 OCR；macOS：`brew install --cask libreoffice`；Linux：`libreoffice` 包）
- 上传的 ZIP 会计算 **MD5**；与历史任务相同时**复用解压目录与 `ocr_text`**（不复制 `outputs/`，Claude 仍按本次参数重新生成分类与抽取）
- 已安装并登录 [Claude Code](https://docs.anthropic.com/) CLI（`claude`，非交互使用 `-p`）

## 后端

```bash
cd src/backend
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Celery Worker（另开终端，工作目录同上）：

```bash
cd src/backend
source .venv/bin/activate
celery -A app.celery_app:celery_app worker -l info
```

环境变量（可选，`.env`）：

- `REDIS_URL`（默认 `redis://localhost:6380/0`，与 Docker 映射一致）
- `DATABASE_URL`（默认 SQLite：`backend/data/app.db`）
- `SKIP_OCR=true` 跳过 OCR（调试）
- `SKIP_CLAUDE=true` 跳过 Claude，仅写占位 JSON（调任务流 / 无 API 时冒烟）
- `CONDA_ENV=v312`（在未设置 `OCR_PYTHON` 时配合 `conda run`）
- **`OCR_PYTHON`**：可选，已安装 Docling 的解释器绝对路径，例如 ` .../conda/envs/v312/bin/python`。**推荐**：Celery Worker 里经常出现 `conda run` 环境与终端不一致、找不到 docling，此时设此项可直接指向装有 Docling 的 Python。
- **`LIBREOFFICE_BIN`**：可选，`soffice` 可执行文件路径（默认在 PATH 中查找 `soffice`）
- **`PPTX_CONVERT_TIMEOUT_SEC`**：单个 PPTX 经 LibreOffice 转 PDF 的超时（默认 300 秒）
- `CLAUDE_BIN=claude`
- `CLAUDE_STREAM_TO_CONSOLE=true`（默认开启）：Celery Worker 终端实时打印 Claude CLI 输出；设为 `false` 则仅写入 `outputs/claude.log`
- `CLAUDE_VERBOSE=true`（默认关闭）：为 Claude CLI 追加 `--verbose`，便于观察工具调用等调试信息
- **`TAVILY_API_KEY`**：Case1 当地政策/规划 Tavily 检索 Key（见 `backend/.env.example`）
- **`TAVILY_ENABLED=true`**（默认开启）：Case1 向智能体注入 Tavily；设为 `false` 关闭联网检索
- **`OCR_CONFIDENCE_THRESHOLD=0.7`**（默认 0.7）：Case2 回填 xlsx 时，OCR 置信度低于该值（0–1）的单元格标黄并写批注；须 OCR 阶段生成 `ocr_text/**/*.ocr_cells.json` sidecar

### OCR 报错 `No module named 'docling'`

1. 在终端确认：`conda run -n v312 python -c "import docling"`；若失败则在 **该环境** 安装：`pip install docling rapidocr onnxruntime`。
2. 查解释器路径：`conda run -n v312 which python`，把结果写入 `.env` 的 **`OCR_PYTHON=...`**，并**重启** Celery Worker（环境变量在进程启动时读取）。

## 前端

```bash
cd src/frontend
npm install
npm run dev
```

浏览器打开 `http://localhost:5173`，通过 Vite 代理访问 API。前端提供**全部任务列表**、**Hash 详情**（`#/tasks/<id>`）、完成后的**分类树下载**与**抽取结果**（含 `evidence` 引用原文，见 Skill）。

## Case1：债权管理尽调指标填报（独立页）

入口：`http://localhost:5173/#/case1`（主站 header 亦有链接）。

1. 上传**尽职调查 `.docx`**（必填）及可选补充材料（pptx/pdf 等）。
2. 可选填写**指标判断规则**（默认预置「通用总则」，可编辑或追加当地政策/增信/去化等预置）；智能体填表时**优先遵循**该规则。
3. 服务端使用内置模板 `src/assets/case1/collection_template.xlsx`（源自测试资产表），与主站**共用同一 Celery Worker 队列**。
4. 智能体按 **模板驱动** 流程填表（见 `skills/business-review-case1/SOP_信息收集表填报.md`）：
   - 先 `dump_collection_template.py` 解析全部指标行（含 `requires_tavily_search` 标记）；
   - 对当地政策/规划类指标使用 `tools/tavily_search.py` 联网检索（见 `SOP_当地政策联网检索.md`）；
   - 再读尽调 docx + 尽调 SOP 取证，逐行填「指标选择」（□ 行填是/否；互斥组只选一行）；
   - 备注 **一句话** 说明理由。
5. 完成后下载 `outputs/collection_filled.xlsx`。

API：

- `POST /api/case1/tasks` — `due_diligence_docx` + 可选 `supplementary_files` + `run_ocr` + 可选 `indicator_judgment_rules`（≤8000 字）
- `GET /api/tasks?task_kind=case1` — Case1 任务列表（主站默认 `task_kind=general`）

任务详情、下载仍使用 `GET /api/tasks/{id}`、`GET /api/tasks/{id}/download?path=...`。

- **续跑** `POST /api/tasks/{id}/resume`（仅失败任务）：保留解压目录与中间产物，跳过已完成步骤。
- **重跑** `POST /api/tasks/{id}/rerun`（失败或已完成）：清空 `extracts/{id}` 与 outputs，从头完整执行。

填表相关脚本（复制到任务目录 `tools/`）：

- `dump_collection_template.py` → `outputs/template_row_catalog.json`（填表前必跑）
- `validate_collection_filled.py` → `outputs/validation_report.json`（Worker 在完成后自动校验）

若 API 过载(529) 且仅有 `elements_extracted.json`，Worker 可能应急运行 `fill_case1_collection.py`（**精度低**，有 catalog 时会拒绝运行）；建议点「续跑任务」。Claude 对 529 自动重试最多 3 次。

## Case2：通用模板独立填报（独立页）

入口：`http://localhost:5173/#/case2`

1. 上传多源文件（支持 `pdf/pptx/doc/docx/xlsx/...`）；
2. 上传单个模板文件（`xlsx`/`xlsm`）；
3. 可选填写**填表逻辑与计算规则**（自然语言 + `---CALC---` 块；默认含财务报表合并/特殊科目/营业总成本等预置）；
4. 系统排队后，脚本先将模板导出为 **fill_plan**，智能体填 `case2_filled_schema.json`，**Python 计算工具**应用 CALC 规则，再回填 `collection_filled.xlsx`。

API：

- `POST /api/case2/tasks`
  - `source_files`（多文件）
  - `collection_template`（单文件）
  - `run_ocr`（可选）
  - `fill_logic_rules`（可选，≤8000 字）
- `GET /api/tasks?task_kind=case2` 获取 Case2 任务列表

Case2 与主站/Case1共用同一 Celery 队列；任务详情/下载仍复用：

- `GET /api/tasks/{id}`
- `GET /api/tasks/{id}/download?path=...`
- `POST /api/tasks/{id}/resume`（续跑）
- `POST /api/tasks/{id}/rerun`（重跑）

## 对外 API（OpenAPI / API Key）

外部系统请使用版本化统一接口 **`/api/v1/*`**，完整对接手册见 [`docs/EXTERNAL_API.md`](../docs/EXTERNAL_API.md)。

1. 在 `backend/.env` 配置 `API_KEYS=your-key`（见 `.env.example`）
2. 所有 v1 请求携带 `X-API-Key: your-key`
3. **统一创建**：`POST /api/v1/tasks`，`task_type=classification|extraction|due_diligence|template_fill` + 对应材料
4. **轮询状态**：`GET /api/v1/tasks/{id}` 直至 `COMPLETED` / `FAILED`
5. **下载产物**：`GET /api/v1/tasks/{id}/download?path=outputs/...`

交互文档：`http://localhost:8000/docs`（tag `v1-tasks`）。导出 OpenAPI JSON：

```bash
cd src/backend && python scripts/export_openapi.py
# → docs/openapi-v1.json
```

内部 React 前端仍走 `/api/*`（无鉴权），与 v1 共用任务库与 Celery 队列。

## Skills 与脚本

- Claude Code 技能：[`skills/business-review/SKILL.md`](skills/business-review/SKILL.md)
- OCR / 文档转 Markdown：`backend/scripts/ocr_pdf.py`（**PDF** 直接 Docling+RapidOCR；**PPTX** 经 LibreOffice 转 PDF 再 OCR，输出 `ocr_text/*.md` 及同名 **`*.ocr_cells.json`**（逐行 OCR 置信度 sidecar）；默认 `conda run -n v312`；若配置了 `OCR_PYTHON` 则直接用该解释器）
- Case2 回填：`backend/scripts/backfill_case2_schema.py` 读取 sidecar，将证据来自 OCR 且置信度低于 `OCR_CONFIDENCE_THRESHOLD` 的单元格**标黄**并添加批注；旧任务若无 sidecar 需重新跑 OCR
- Case2 计算规则：`backend/scripts/parse_case2_calc_rules.py`（解析 `---CALC---` 块）+ `apply_case2_calc_rules.py`（对 filled schema 按列 sum / sum_if_missing）
