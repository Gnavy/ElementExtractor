# 业务审查场景（Zip + Celery + LangGraph）

## 前置条件

- Python 3.11+（后端）
- Node 18+（前端）
- Redis（在项目 `src` 目录执行 `docker compose up -d`；容器将 **6379 映射到主机 6380**，避免与本机已有 Redis 冲突。后端需设置 `REDIS_URL=redis://localhost:6380/0`）
- Conda 环境 `v312`（Docling + RapidOCR，用于 OCR 脚本）
- **LibreOffice**（`soffice`，用于 PPTX 先转 PDF 再 OCR；macOS：`brew install --cask libreoffice`；Linux：`libreoffice` 包）
- 上传的 ZIP 会计算 **MD5**；与历史任务相同时**复用解压目录与 `ocr_text`**（不复制 `outputs/`，智能体仍按本次参数重新生成分类与抽取）
- 配置 **LLM API Key**（见下方 `LLM_PROVIDER` / `ANTHROPIC_API_KEY` 等）；智能体由 **LangGraph** 编排，不再依赖 Claude Code CLI

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

环境变量（可选，`.env`，完整示例见 `backend/.env.example`）：

- `REDIS_URL`（默认 `redis://localhost:6380/0`，与 Docker 映射一致）
- `DATABASE_URL`（默认 SQLite：`backend/data/app.db`）
- `SKIP_OCR=true` 跳过 OCR（调试）
- `SKIP_AGENT=true` 跳过 LangGraph 智能体，仅写占位 JSON（调任务流 / 无 API 时冒烟；兼容旧名 `SKIP_CLAUDE`）
- `CONDA_ENV=v312`（在未设置 `OCR_PYTHON` 时配合 `conda run`）
- **`OCR_PYTHON`**：可选，已安装 Docling 的解释器绝对路径
- **`LIBREOFFICE_BIN`** / **`PPTX_CONVERT_TIMEOUT_SEC`**
- **`LLM_PROVIDER`**：`anthropic` | `openai` | `zhipu` | `bailian`（默认 anthropic；百炼用 `bailian`）
- **`LLM_MODEL`**：模型名（如 `qwen3.5-plus`、`claude-sonnet-4-20250514`、`gpt-4o`、`glm-4-plus`）
- **`BAILIAN_API_KEY`** / **`DASHSCOPE_API_KEY`**：阿里云百炼 Key；`BAILIAN_BASE_URL` 默认 `https://dashscope.aliyuncs.com/compatible-mode/v1`
- **`ANTHROPIC_API_KEY`** / **`OPENAI_API_KEY`** / **`ZHIPU_API_KEY`**
- **`OPENAI_BASE_URL`** / **`ZHIPU_BASE_URL`**：OpenAI 兼容端点
- **`LLM_TIMEOUT_SEC`** / **`LLM_MAX_RETRIES`** / **`LLM_TEMPERATURE`**
- **`AGENT_STREAM_TO_CONSOLE=true`**：Worker 终端打印智能体进度；日志写入 `outputs/agent.log`（并保留 `outputs/claude.log` 兼容别名）
- **`TAVILY_API_KEY`** / **`TAVILY_ENABLED`**：Case1 当地政策联网检索
- **`OCR_CONFIDENCE_THRESHOLD=0.7`**：Case2 回填低置信度标黄

### OCR 报错 `No module named 'docling'`

1. 在终端确认：`conda run -n v312 python -c "import docling"`；若失败则在 **该环境** 安装：`pip install docling rapidocr onnxruntime`。
2. 查解释器路径：`conda run -n v312 which python`，把结果写入 `.env` 的 **`OCR_PYTHON=...`**，并**重启** Celery Worker。

## 前端

```bash
cd src/frontend
npm install
npm run dev
```

浏览器打开 `http://localhost:5173`。任务详情会展示智能体分节点进度（如「正在填表：指标组 12/48」）。

## LangGraph 智能体

实现位于 `backend/app/agents/`：

| `task_kind` | Graph | 说明 |
|-------------|-------|------|
| `general` / `classification` / `extraction` | `graphs/general.py` | 分类、字段级并行抽取、证据校验、可选信息收集表 |
| `case1` | `graphs/case1.py` | 模板解析、Tavily、指标组并行填表、Python 写 xlsx、校验修复 |
| `case2` | `graphs/case2.py` | fill_plan 批处理、CALC、回填 xlsx |

业务规范文档仍保留在 [`skills/`](skills/)（人工维护）；运行时由 `app/agents/prompts/` 驱动，不再复制到 `.claude/skills/`。

## Case1：债权管理尽调指标填报

入口：`http://localhost:5173/#/case1`

流程由 LangGraph Case1 图执行：解析 `template_row_catalog` → 材料索引 → 地区推断 → Tavily（按需）→ 指标组并行填 D/E 列 → 写 `collection_filled.xlsx` → 校验与违规组修复。

若 API 瞬时错误且仅有 `elements_extracted.json`，Worker 可能应急运行 `fill_case1_collection.py`（精度较低）；建议点「续跑任务」。

## Case2：通用模板独立填报

入口：`http://localhost:5173/#/case2`

脚本导出 fill_plan → LangGraph 按 item 批填 `case2_filled_schema.json` → Python CALC → 回填 `collection_filled.xlsx`（OCR 低置信度标黄）。

## 对外 API（OpenAPI / API Key）

见 [`docs/EXTERNAL_API.md`](../docs/EXTERNAL_API.md)。产物路径与原先兼容；日志字段仍暴露 `claude_log_tail` / `outputs/claude.log` 别名，同时写入 `outputs/agent.log`。

## 技能文档与脚本

- 业务规范（文档）：[`skills/business-review/SKILL.md`](skills/business-review/SKILL.md) 等
- OCR：`backend/scripts/ocr_pdf.py`
- Case2 回填 / CALC：`backend/scripts/backfill_case2_schema.py`、`apply_case2_calc_rules.py`
