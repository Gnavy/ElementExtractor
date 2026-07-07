# 业务审查任务 — 对外 API 对接手册

本文档描述如何通过 **统一任务接口** `/api/v1` 对接四种任务类型。

| `task_type` | 说明 |
|-------------|------|
| `classification` | 材料分类 |
| `extraction` | 要素抽取 |
| `due_diligence` | 债权管理尽调指标填报 |
| `template_fill` | 通用模板驱动填报 |

- **Swagger UI**：`http://<host>:8000/docs`（筛选 tag `v1-tasks`，点击 Authorize 填入 API Key）
- **OpenAPI JSON**：`http://<host>:8000/openapi.json` 或仓库内 [`openapi-v1.json`](openapi-v1.json)

---

## 1. 快速开始

### 1.1 鉴权

所有 `/api/v1/*` 请求须携带 API Key，任选其一：

| 方式 | 示例 |
|------|------|
| 推荐：`X-API-Key` | `X-API-Key: your-secret-key-here` |
| Bearer | `Authorization: Bearer your-secret-key-here` |

`/health`、`/docs`、`/openapi.json` 无需鉴权。

### 1.2 最小调用示例（债权尽调填报）

```bash
export BASE_URL=http://localhost:8000
export API_KEY=your-secret-key-here

curl -sS -X POST "$BASE_URL/api/v1/tasks" \
  -H "X-API-Key: $API_KEY" \
  -F "task_type=due_diligence" \
  -F "due_diligence_docx=@/path/to/report.docx" \
  -F "run_ocr=true"
```

响应（201）：

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "PENDING",
  "task_type": "due_diligence"
}
```

---

## 2. 异步任务流程

任务为**异步执行**：创建后立即返回 `PENDING`，由 Celery Worker 处理。

```
POST /api/v1/tasks  →  返回 task id
        ↓
GET  /api/v1/tasks/{id}  轮询（建议 5–10 秒间隔）
        ↓
status = COMPLETED  →  GET /api/v1/tasks/{id}/download?path=...
status = FAILED     →  查看 error_message；可 POST .../resume 续跑
```

### 任务状态

| status | 含义 |
|--------|------|
| `PENDING` | 已入队 |
| `EXTRACTING` | 解压材料 |
| `OCR_RUNNING` | OCR 识别中 |
| `AGENT_RUNNING` | 智能体处理中 |
| `COMPLETED` | 成功 |
| `FAILED` | 失败 |

轮询示例：

```bash
TASK_ID=550e8400-e29b-41d4-a716-446655440000

curl -sS "$BASE_URL/api/v1/tasks/$TASK_ID" \
  -H "X-API-Key: $API_KEY" | jq '.status, .task_type, .progress_message, .error_message'
```

---

## 3. API 端点一览

| 方法 | 路径 | 章节 |
|------|------|------|
| `POST` | `/api/v1/tasks` | [§4 创建任务](#4-创建任务-post-apiv1tasks) |
| `GET` | `/api/v1/tasks` | [§5 任务列表](#5-任务列表-get-apiv1tasks) |
| `GET` | `/api/v1/tasks/{id}` | [§6 任务详情](#6-任务详情-get-apiv1tasksid) |
| `GET` | `/api/v1/tasks/{id}/files` | [§7 文件列表](#7-文件列表-get-apiv1tasksidfiles) |
| `GET` | `/api/v1/tasks/{id}/download` | [§8 下载文件](#8-下载文件-get-apiv1tasksidownload) |
| `POST` | `/api/v1/tasks/{id}/resume` | [§9 失败续跑](#9-失败续跑-post-apiv1tasksidresume) |
| `POST` | `/api/v1/tasks/{id}/rerun` | [§10 任务重跑](#10-任务重跑-post-apiv1tasksidrerun) |
| `GET` | `/api/v1/tasks/{id}/artifacts/classification` | [§11 分类 JSON](#11-分类产物-get-apiv1tasksidartifactsclassification) |
| `GET` | `/api/v1/tasks/{id}/artifacts/extracted` | [§12 抽取 JSON](#12-抽取产物-get-apiv1tasksidartifactsextracted) |

除创建任务外，其余接口均为 **GET/POST + JSON 或文件流**，无需 `multipart/form-data`。

---

## 4. 创建任务：`POST /api/v1/tasks`

`Content-Type: multipart/form-data`

### 公共字段

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `task_type` | string | 是 | 见上表四种取值 |

---

### 4.1 `classification` — 材料分类

| 字段 | 必填 | 说明 |
|------|------|------|
| `files` | 是 | 材料文件，**同一字段名重复传多个**（见下方示例）；也支持上传 `.zip` 自动展开 |
| `classification_basis` | 是 | 分类依据文本 |
| `run_ocr` | 否 | 默认 `true`；对 PDF/PPTX 执行 OCR |

**支持的文件类型**

| 类别 | 扩展名 | 处理方式 |
|------|--------|----------|
| PDF 扫描件 | `.pdf` | `run_ocr=true` 时自动 OCR → `ocr_text/*.md` |
| 演示文稿 | `.pptx`、`.ppt` | 转 PDF 后 OCR（需 LibreOffice） |
| Word | `.docx`、`.doc` | 智能体直接读取正文 |
| Excel | `.xlsx`、`.xlsm`、`.xls` | 智能体直接读取单元格 |
| 图片 | `.png`、`.jpg`、`.jpeg` | 智能体读取（证件/截图类材料） |
| 文本 | `.txt`、`.md`、`.csv` | 智能体直接读取 |
| 压缩包 | `.zip` | 服务端解压后按内部文件处理 |

上传接口**不按扩展名硬性拦截**；上表为推荐且验证过的格式。单任务材料总大小默认 ≤ 5000 MB。

**单文件示例**

```bash
curl -sS -X POST "$BASE_URL/api/v1/tasks" \
  -H "X-API-Key: $API_KEY" \
  -F "task_type=classification" \
  -F "files=@/path/to/material.pdf" \
  -F "classification_basis=按材料类型分类" \
  -F "run_ocr=true"
```

**多文件示例**（字段名均为 `files`，可混合不同类型）

```bash
curl -sS -X POST "$BASE_URL/api/v1/tasks" \
  -H "X-API-Key: $API_KEY" \
  -F "task_type=classification" \
  -F "files=@/path/to/loan_contract.pdf" \
  -F "files=@/path/to/audit_report.docx" \
  -F "files=@/path/to/balance_sheet.xlsx" \
  -F "files=@/path/to/board_resolution.pdf" \
  -F "classification_basis=按文件类型归档：合同、财报、决议、其他" \
  -F "run_ocr=true"
```

Python `requests` 多文件上传：

```python
files = [
    ("files", ("loan_contract.pdf", open("loan_contract.pdf", "rb"), "application/pdf")),
    ("files", ("audit_report.docx", open("audit_report.docx", "rb"), "application/vnd.openxmlformats-officedocument.wordprocessingml.document")),
    ("files", ("balance_sheet.xlsx", open("balance_sheet.xlsx", "rb"), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")),
]
resp = requests.post(
    f"{BASE_URL}/api/v1/tasks",
    headers={"X-API-Key": API_KEY},
    data={"task_type": "classification", "classification_basis": "按材料类型归档", "run_ocr": "true"},
    files=files,
    timeout=120,
)
```

**主产物**：`outputs/classification.json`

---

### 4.2 `extraction` — 要素抽取

| 字段 | 必填 | 说明 |
|------|------|------|
| `files` | 是 | 材料文件，**同一字段名 `files` 重复传多个**（规则同 §4.1） |
| `extract_schema` | 是 | 抽取字段定义（JSON 字符串，见下文） |
| `classification_basis` | 否 | 可选分类依据（辅助智能体理解） |
| `run_ocr` | 否 | 默认 `true` |

#### `extract_schema` 格式

须为合法 JSON，顶层包含 `fields` 数组；**每个字段至少包含 `name` 与 `description`**，`type` 强烈建议填写：

```json
{
  "fields": [
    {
      "name": "公司名称",
      "description": "借款人营业执照或工商登记信息中的法定名称；无扫描件时可从尽调报告「债务人基本情况」摘录",
      "type": "string"
    },
    {
      "name": "注册资本",
      "description": "工商登记的注册资本金额，单位人民币元，保留数字不含千分位",
      "type": "currency"
    },
    {
      "name": "成立日期",
      "description": "营业执照上的成立/注册日期",
      "type": "date"
    },
    {
      "name": "经营范围",
      "description": "营业执照经营范围全文；过长时可保留关键业务表述",
      "type": "text"
    },
    {
      "name": "是否存在对外担保",
      "description": "根据材料判断债务人是否存在对外担保，填是或否",
      "type": "boolean"
    }
  ]
}
```

| 属性 | 必填 | 说明 |
|------|------|------|
| `name` | 是 | 字段名，对应 `outputs/extracted.json` → `fields` 下的键 |
| `description` | 是 | **抽取说明**：口径、材料来源、格式要求；智能体主要据此理解如何取值 |
| `type` | 建议 | 期望取值类型，见下表；省略时按短文本处理 |

#### 支持的 `type` 类型

| `type` | 含义 | `extracted.json` 中 `value` 示例 |
|--------|------|----------------------------------|
| `string` | 短文本（名称、编号、案号等） | `"浙江某某有限公司"` |
| `text` | 长文本（经营范围、裁判要旨等） | `"经营范围包括房地产开发…"` |
| `number` | 数值（不含货币单位） | `12345.67` 或 `"12345.67"` |
| `currency` | 金额（建议注明单位口径） | `"10000000"` |
| `date` | 日期 | `"2024-03-15"`（建议 ISO `YYYY-MM-DD`） |
| `boolean` | 是否 | `true` / `false` |
| `array` | 列表（多项并列） | `["案号1", "案号2"]` |
| `object` | 嵌套结构（子字段组合） | `{"案号": "…", "金额": "…"}` |
| `image` | 图片/证件区域截图 | `"outputs/image_crops/身份证正面.png"`（或路径数组） |

`type` 为 `image` 时，智能体会将裁剪图写入 `outputs/image_crops/`，`value` 填相对路径；详见 Skill `business-review` 中「图片/证件类字段」说明。

无法从材料确定的字段，智能体会在 `value` 填 `null`，并在 `notes` 说明原因；关键字段建议同时在 `description` 中写明「无依据时填 null」。

**主产物**：`outputs/extracted.json`（每字段含 `value`、`confidence`、`source_files`、`evidence`、`notes`）

```bash
curl -sS -X POST "$BASE_URL/api/v1/tasks" \
  -H "X-API-Key: $API_KEY" \
  -F "task_type=extraction" \
  -F "files=@/path/to/annual_report.pdf" \
  -F "files=@/path/to/business_license.pdf" \
  -F 'extract_schema={"fields":[{"name":"公司名称","description":"借款人营业执照或尽调报告中的法定名称","type":"string"},{"name":"注册资本","description":"工商登记注册资本，单位人民币元","type":"currency"},{"name":"成立日期","description":"营业执照登记成立日期，格式YYYY-MM-DD","type":"date"}]}' \
  -F "run_ocr=true"
```

可先调用 `classification` 再调用 `extraction`（两次独立任务）；若材料相同，各自上传即可。

---

### 4.3 `due_diligence` — 债权管理尽调指标填报

根据尽职调查 **Word 报告**及补充材料，按服务端内置指标表自动填报 Excel 收集表。

| 字段 | 必填 | 说明 |
|------|------|------|
| `due_diligence_docx` | 是 | 尽职调查主报告，须为 `.docx` |
| `supplementary_files` | 否 | 补充材料，**同一字段名重复传多个** |
| `run_ocr` | 否 | 默认 `false`；若补充材料含 PDF，服务端会自动开启 OCR |
| `indicator_judgment_rules` | 否 | 指标判断与填表口径说明，≤8000 字 |

**补充材料支持的类型**（服务端校验，不含图片）：

| 扩展名 |
|--------|
| `.pdf`、`.docx`、`.doc`、`.pptx`、`.ppt`、`.xlsx`、`.xlsm`、`.xls`、`.txt`、`.md` |

**说明**：指标收集表模板由服务端内置，**无需**上传 `collection_template`。

**创建响应 `201`**：

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "PENDING",
  "task_type": "due_diligence"
}
```

**主产物**（任务 `COMPLETED` 后）：

| 相对路径 | 说明 |
|----------|------|
| `outputs/collection_filled.xlsx` | 填好的指标收集表（首选下载） |
| `outputs/collection_fill_notes.md` | 填表说明与备注 |
| `outputs/validation_report.json` | 校验报告（缺项、冲突等） |
| `outputs/classification.json` | 材料分类（辅助） |
| `outputs/extracted.json` | 要素抽取（辅助） |

**单文件示例**：

```bash
curl -sS -X POST "$BASE_URL/api/v1/tasks" \
  -H "X-API-Key: $API_KEY" \
  -F "task_type=due_diligence" \
  -F "due_diligence_docx=@/path/to/dd_report.docx" \
  -F "run_ocr=false"
```

**含补充材料与规则**：

```bash
curl -sS -X POST "$BASE_URL/api/v1/tasks" \
  -H "X-API-Key: $API_KEY" \
  -F "task_type=due_diligence" \
  -F "due_diligence_docx=@/path/to/dd_report.docx" \
  -F "supplementary_files=@/path/to/judgment.pdf" \
  -F "supplementary_files=@/path/to/financials.xlsx" \
  -F "indicator_judgment_rules=优先适用当地政策；诉讼金额以裁判文书为准..." \
  -F "run_ocr=true"
```

Python：

```python
with open("dd_report.docx", "rb") as docx:
    resp = requests.post(
        f"{BASE_URL}/api/v1/tasks",
        headers=HEADERS,
        data={
            "task_type": "due_diligence",
            "indicator_judgment_rules": "诉讼金额以裁判文书为准",
            "run_ocr": "true",
        },
        files={
            "due_diligence_docx": ("dd_report.docx", docx),
            "supplementary_files": ("judgment.pdf", open("judgment.pdf", "rb"), "application/pdf"),
        },
        timeout=120,
    )
resp.raise_for_status()
task_id = resp.json()["id"]
```

---

### 4.4 `template_fill` — 通用模板驱动填报

根据用户提供的 **Excel 模板**与源材料，按填表逻辑与计算规则自动回填。

| 字段 | 必填 | 说明 |
|------|------|------|
| `source_files` | 是 | 源材料，**≥1 个**，同一字段名重复传多个 |
| `collection_template` | 是 | 填报模板 `.xlsx` 或 `.xlsm`，≤20 MB |
| `run_ocr` | 否 | 默认 `true`；若源材料含 PDF，服务端会自动开启 OCR |
| `fill_logic_rules` | 否 | 填表逻辑说明；可含 `---CALC---` 分隔的计算规则块，≤8000 字 |

**源材料支持的类型**（服务端校验，须 ≥1 个）：

| 扩展名 |
|--------|
| `.pdf`、`.docx`、`.doc`、`.pptx`、`.ppt`、`.xlsx`、`.xlsm`、`.xls`、`.csv`、`.txt`、`.md`、`.jpg`、`.jpeg`、`.png` |

**`fill_logic_rules` 示例**（自然语言 + 计算块）：

```
营业收入取年报「利润表」本年累计数。
---CALC---
总资产 = 流动资产合计 + 非流动资产合计
```

**主产物**（任务 `COMPLETED` 后）：

| 相对路径 | 说明 |
|----------|------|
| `outputs/collection_filled.xlsx` | 回填后的模板（首选下载） |
| `outputs/backfill_report.json` | 各单元格回填来源与置信度 |
| `outputs/calc_rules_report.json` | `---CALC---` 规则执行结果 |

**多源文件 + 模板示例**：

```bash
curl -sS -X POST "$BASE_URL/api/v1/tasks" \
  -H "X-API-Key: $API_KEY" \
  -F "task_type=template_fill" \
  -F "source_files=@/path/to/financials.pdf" \
  -F "source_files=@/path/to/notes.docx" \
  -F "collection_template=@/path/to/template.xlsx" \
  -F "fill_logic_rules=营业收入取年报利润表..." \
  -F "run_ocr=true"
```

Python：

```python
files = [
    ("source_files", ("financials.pdf", open("financials.pdf", "rb"), "application/pdf")),
    ("source_files", ("notes.docx", open("notes.docx", "rb"), "application/vnd.openxmlformats-officedocument.wordprocessingml.document")),
    ("collection_template", ("template.xlsx", open("template.xlsx", "rb"), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")),
]
resp = requests.post(
    f"{BASE_URL}/api/v1/tasks",
    headers=HEADERS,
    data={"task_type": "template_fill", "fill_logic_rules": "...", "run_ocr": "true"},
    files=files,
    timeout=120,
)
```

---

### 4.5 创建任务公共说明

| 项 | 说明 |
|----|------|
| HTTP 状态码 | 成功为 **`201 Created`** |
| 响应体 | `id`、`status`（初始为 `PENDING`）、`task_type` |
| 后续步骤 | 使用返回的 `id` 调用 [§6 任务详情](#6-任务详情-get-apiv1tasksid) 轮询 |

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "PENDING",
  "task_type": "classification"
}
```

---

## 5. 任务列表：`GET /api/v1/tasks`

按创建时间**倒序**返回任务摘要，用于控制台展示或批量对账。

### 请求

| 参数 | 位置 | 类型 | 必填 | 默认 | 说明 |
|------|------|------|------|------|------|
| `skip` | query | int | 否 | `0` | 跳过条数（分页偏移） |
| `limit` | query | int | 否 | `100` | 返回条数上限 |
| `task_type` | query | string | 否 | — | 过滤：`classification` / `extraction` / `due_diligence` / `template_fill` |

### 响应 `200`

JSON 数组，每项字段：

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | string | 任务 UUID |
| `status` | string | 任务状态（见 §2） |
| `task_type` | string | 对外任务类型 |
| `zip_filename` | string | 展示用材料包名称 |
| `source_docx_filename` | string \| null | 主文件名（尽调 docx 等） |
| `progress_message` | string \| null | 当前进度文案 |
| `error_message` | string \| null | 失败时的错误摘要 |
| `created_at` | string | ISO 8601 创建时间 |

```bash
# 全部任务（最近 20 条）
curl -sS "$BASE_URL/api/v1/tasks?limit=20" \
  -H "X-API-Key: $API_KEY"

# 仅要素抽取任务
curl -sS "$BASE_URL/api/v1/tasks?task_type=extraction&limit=50" \
  -H "X-API-Key: $API_KEY"
```

响应示例：

```json
[
  {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "status": "COMPLETED",
    "task_type": "classification",
    "zip_filename": "loan_contract.pdf",
    "source_docx_filename": null,
    "progress_message": "完成",
    "error_message": null,
    "created_at": "2026-07-01T08:30:00"
  }
]
```

---

## 6. 任务详情：`GET /api/v1/tasks/{id}`

**轮询主接口**：创建任务后周期性调用，直至 `status` 为 `COMPLETED` 或 `FAILED`。建议间隔 **5–10 秒**。

### 路径参数

| 参数 | 说明 |
|------|------|
| `id` | 创建任务时返回的 UUID |

### 响应 `200`

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | string | 任务 ID |
| `status` | string | `PENDING` / `EXTRACTING` / `OCR_RUNNING` / `AGENT_RUNNING` / `COMPLETED` / `FAILED` |
| `task_type` | string | 对外任务类型 |
| `progress_message` | string \| null | 进度说明，如「OCR 识别中」 |
| `error_message` | string \| null | 失败原因（`FAILED` 时有值） |
| `zip_filename` | string | 材料包展示名 |
| `classification_basis` | string | 创建时提交的分类依据（抽取任务可能为占位文案） |
| `extract_schema` | string | 创建时提交的 schema JSON 字符串 |
| `source_docx_filename` | string \| null | 主源文件名 |
| `indicator_judgment_rules` | string \| null | 尽调填报规则（`due_diligence`） |
| `fill_logic_rules` | string \| null | 模板填报规则（`template_fill`） |
| `collection_template_original_filename` | string \| null | 用户上传的模板原名 |
| `run_ocr` | boolean | 是否执行 OCR |
| `run_agent` | boolean | 是否调用智能体 |
| `run_collection_fill` | boolean | 是否填报收集表（对外抽取/分类任务为 `false`） |
| `result_summary` | object \| null | 完成后含 `outputs` 键，映射产物别名 → 相对路径 |
| `claude_log_tail` | string \| null | 智能体日志尾部（排障用） |
| `created_at` / `updated_at` | string | ISO 8601 时间 |

`result_summary.outputs` 示例（`due_diligence` 完成）：

```json
{
  "outputs": {
    "collection_filled": "outputs/collection_filled.xlsx",
    "collection_fill_notes": "outputs/collection_fill_notes.md",
    "validation_report": "outputs/validation_report.json",
    "classification": "outputs/classification.json",
    "extracted": "outputs/extracted.json",
    "claude_log": "outputs/claude.log"
  }
}
```

```bash
curl -sS "$BASE_URL/api/v1/tasks/$TASK_ID" \
  -H "X-API-Key: $API_KEY" | jq .
```

处理中响应片段：

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "AGENT_RUNNING",
  "task_type": "extraction",
  "progress_message": "正在调用智能体进行要素抽取…",
  "error_message": null,
  "result_summary": null
}
```

---

## 7. 文件列表：`GET /api/v1/tasks/{id}/files`

列出任务目录下**可下载**的上传材料与产出文件（不含内部工具目录、OCR 中间缓存等）。

### 响应 `200`

```json
{
  "files": [
    {
      "name": "loan_contract.pdf",
      "relative_path": "sources/loan_contract.pdf",
      "source": "uploaded",
      "size": 1048576,
      "extension": ".pdf"
    },
    {
      "name": "classification.json",
      "relative_path": "outputs/classification.json",
      "source": "output",
      "size": 2048,
      "extension": ".json"
    }
  ]
}
```

| 字段 | 说明 |
|------|------|
| `relative_path` | 下载时传给 `download?path=` 的路径 |
| `source` | `uploaded`（用户材料）或 `output`（任务产物） |
| `size` | 字节数 |
| `extension` | 小写后缀 |

任务尚未解压或无文件时返回 `{"files": []}`。

```bash
curl -sS "$BASE_URL/api/v1/tasks/$TASK_ID/files" \
  -H "X-API-Key: $API_KEY" | jq '.files[] | {relative_path, source, size}'
```

---

## 8. 下载文件：`GET /api/v1/tasks/{id}/download`

下载任务目录内的单个文件（二进制流）。

### 查询参数

| 参数 | 必填 | 说明 |
|------|------|------|
| `path` | 是 | 相对路径，如 `outputs/collection_filled.xlsx`；**禁止** `..` 或绝对路径 |

### 响应

| HTTP | 说明 |
|------|------|
| `200` | 文件流，`Content-Disposition: attachment` |
| `404` | 任务不存在或文件不存在 |
| `400` | 非法路径 |

常用 `path` 见 [§13 各任务类型主产物](#13-各任务类型主产物)。

```bash
# 下载分类结果
curl -sS -o classification.json \
  -H "X-API-Key: $API_KEY" \
  "$BASE_URL/api/v1/tasks/$TASK_ID/download?path=outputs/classification.json"

# 下载尽调填表结果
curl -sS -o collection_filled.xlsx \
  -H "X-API-Key: $API_KEY" \
  "$BASE_URL/api/v1/tasks/$TASK_ID/download?path=outputs/collection_filled.xlsx"
```

Python：

```python
resp = requests.get(
    f"{BASE_URL}/api/v1/tasks/{task_id}/download",
    headers=HEADERS,
    params={"path": "outputs/extracted.json"},
    timeout=120,
)
resp.raise_for_status()
Path("extracted.json").write_bytes(resp.content)
```

---

## 9. 失败续跑：`POST /api/v1/tasks/{id}/resume`

任务 **`FAILED`** 时，保留已解压目录与中间产物（含 OCR 结果），从断点重新入队。

### 适用场景

- 智能体 API 过载（529）导致失败，但 OCR 已完成
- 部分产物已生成，希望跳过已完成步骤

### 约束

| 条件 | 说明 |
|------|------|
| `status` 必须为 `FAILED` | 否则返回 `400`：`仅失败任务可续跑，当前状态：…` |
| 原始上传文件须仍在服务端 | 丢失则 `400` |

### 请求体

无（空 POST）。

### 响应 `200`

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "PENDING",
  "task_type": "extraction"
}
```

续跑后请继续 [§6 轮询](#6-任务详情-get-apiv1tasksid) 直至结束。

```bash
curl -sS -X POST "$BASE_URL/api/v1/tasks/$TASK_ID/resume" \
  -H "X-API-Key: $API_KEY"
```

---

## 10. 任务重跑：`POST /api/v1/tasks/{id}/rerun`

在 **`COMPLETED` 或 `FAILED`** 且非进行中状态下，**清空解压目录与 outputs**，从头完整执行流水线。

### 与续跑的区别

| | 续跑 `resume` | 重跑 `rerun` |
|--|---------------|--------------|
| 前置状态 | 仅 `FAILED` | `COMPLETED` 或 `FAILED` |
| 中间产物 | 保留 | 全部清除 |
| 适用 | 断点恢复 | 换规则后重做、结果不满意 |

### 约束

| 条件 | 说明 |
|------|------|
| `status` 不得为进行中 | `PENDING` / `EXTRACTING` / `OCR_RUNNING` / `AGENT_RUNNING` → `400` |
| 原始上传须存在 | 否则 `400` |

### 响应 `200`

同续跑，`status` 重置为 `PENDING`。

```bash
curl -sS -X POST "$BASE_URL/api/v1/tasks/$TASK_ID/rerun" \
  -H "X-API-Key: $API_KEY"
```

---

## 11. 分类产物：`GET /api/v1/tasks/{id}/artifacts/classification`

直接返回 `outputs/classification.json` 的 JSON 内容（等价于 `download?path=outputs/classification.json`，但响应为 `application/json`）。

### 适用任务

主要为 `classification`；其他任务若生成了该文件亦可读取。

### 响应 `200` 示例

```json
{
  "task_id": "550e8400-e29b-41d4-a716-446655440000",
  "categories": [
    {
      "label": "合同类",
      "files": [
        {
          "relative_path": "sources/loan_contract.pdf",
          "file_type": "pdf",
          "notes": "借款合同"
        }
      ]
    }
  ],
  "unclassified": [
    {
      "relative_path": "sources/misc_scan.pdf",
      "reason": "无法归入既定类别"
    }
  ]
}
```

| HTTP | 说明 |
|------|------|
| `404` | 任务不存在，或文件尚未生成 |

```bash
curl -sS "$BASE_URL/api/v1/tasks/$TASK_ID/artifacts/classification" \
  -H "X-API-Key: $API_KEY" | jq .
```

---

## 12. 抽取产物：`GET /api/v1/tasks/{id}/artifacts/extracted`

直接返回 `outputs/extracted.json` 的 JSON 内容。

### 适用任务

主要为 `extraction`。

### 响应 `200` 示例

```json
{
  "task_id": "550e8400-e29b-41d4-a716-446655440000",
  "fields": {
    "公司名称": {
      "value": "浙江某某有限公司",
      "confidence": "high",
      "source_files": ["sources/business_license.pdf"],
      "evidence": [
        {
          "file": "sources/business_license.pdf",
          "quote": "名称：浙江某某有限公司",
          "page_hint": "ocr_text/business_license.md"
        }
      ],
      "notes": null
    },
    "注册资本": {
      "value": "10000000",
      "confidence": "medium",
      "source_files": ["sources/business_license.pdf"],
      "evidence": [],
      "notes": null
    }
  }
}
```

| 字段（每个要素） | 说明 |
|------------------|------|
| `value` | 抽取值；无依据时为 `null` |
| `confidence` | `high` / `medium` / `low` |
| `source_files` | 证据材料相对路径列表 |
| `evidence` | 引文片段数组 |
| `notes` | 补充说明 |

```bash
curl -sS "$BASE_URL/api/v1/tasks/$TASK_ID/artifacts/extracted" \
  -H "X-API-Key: $API_KEY" | jq '.fields["公司名称"]'
```

---

## 13. 各任务类型主产物

任务 `COMPLETED` 后，优先下载以下路径（亦可通过 `files` 接口发现）：

| `task_type` | 主产物 `path` | 说明 |
|-------------|---------------|------|
| `classification` | `outputs/classification.json` | 分类树 |
| `extraction` | `outputs/extracted.json` | 结构化要素 |
| `due_diligence` | `outputs/collection_filled.xlsx` | 填好的指标表 |
| `due_diligence` | `outputs/validation_report.json` | 填表校验报告 |
| `template_fill` | `outputs/collection_filled.xlsx` | 按模板回填结果 |
| `template_fill` | `outputs/backfill_report.json` | 回填明细 |
| `template_fill` | `outputs/calc_rules_report.json` | 计算规则执行报告 |

辅助产物（排障）：`outputs/claude.log`、`outputs/ocr.log`（若执行 OCR）。

---

## 14. Python 完整流程示例

### 14.1 材料分类（classification）

```python
import time
from pathlib import Path

import requests

BASE_URL = "http://localhost:8000"
API_KEY = "your-secret-key-here"
HEADERS = {"X-API-Key": API_KEY}

files = [
    ("files", ("a.pdf", open("a.pdf", "rb"), "application/pdf")),
    ("files", ("b.docx", open("b.docx", "rb"), "application/vnd.openxmlformats-officedocument.wordprocessingml.document")),
]
create = requests.post(
    f"{BASE_URL}/api/v1/tasks",
    headers=HEADERS,
    data={"task_type": "classification", "classification_basis": "按文书类型分类", "run_ocr": "true"},
    files=files,
    timeout=120,
)
create.raise_for_status()
task_id = create.json()["id"]

while True:
    detail = requests.get(f"{BASE_URL}/api/v1/tasks/{task_id}", headers=HEADERS, timeout=30).json()
    print(detail["status"], detail.get("progress_message"))
    if detail["status"] in ("COMPLETED", "FAILED"):
        break
    time.sleep(8)

if detail["status"] == "FAILED":
    raise RuntimeError(detail.get("error_message"))

# 专用 artifacts 接口
classification = requests.get(
    f"{BASE_URL}/api/v1/tasks/{task_id}/artifacts/classification",
    headers=HEADERS,
    timeout=30,
).json()
```

### 14.2 债权尽调填报（due_diligence）

```python
import time
from pathlib import Path

import requests

BASE_URL = "http://localhost:8000"
API_KEY = "your-secret-key-here"
HEADERS = {"X-API-Key": API_KEY}

with open("report.docx", "rb") as docx:
    resp = requests.post(
        f"{BASE_URL}/api/v1/tasks",
        headers=HEADERS,
        data={"task_type": "due_diligence", "run_ocr": "true"},
        files={"due_diligence_docx": ("report.docx", docx)},
        timeout=120,
    )
resp.raise_for_status()
task_id = resp.json()["id"]

while True:
    detail = requests.get(f"{BASE_URL}/api/v1/tasks/{task_id}", headers=HEADERS, timeout=30).json()
    if detail["status"] in ("COMPLETED", "FAILED"):
        break
    time.sleep(8)

if detail["status"] == "COMPLETED":
    dl = requests.get(
        f"{BASE_URL}/api/v1/tasks/{task_id}/download",
        headers=HEADERS,
        params={"path": "outputs/collection_filled.xlsx"},
        timeout=120,
    )
    dl.raise_for_status()
    Path("collection_filled.xlsx").write_bytes(dl.content)
elif detail["status"] == "FAILED":
    # 可选：续跑
    requests.post(f"{BASE_URL}/api/v1/tasks/{task_id}/resume", headers=HEADERS).raise_for_status()
```

### 14.3 要素抽取（extraction）

```python
import json
import time

import requests

schema = {
    "fields": [
        {"name": "公司名称", "description": "营业执照法定名称", "type": "string"},
        {"name": "注册资本", "description": "工商登记注册资本，单位元", "type": "currency"},
    ]
}
files = [("files", ("license.pdf", open("license.pdf", "rb"), "application/pdf"))]
create = requests.post(
    f"{BASE_URL}/api/v1/tasks",
    headers={"X-API-Key": API_KEY},
    data={"task_type": "extraction", "extract_schema": json.dumps(schema, ensure_ascii=False), "run_ocr": "true"},
    files=files,
    timeout=120,
)
task_id = create.json()["id"]

# 轮询后读取 artifacts
while requests.get(f"{BASE_URL}/api/v1/tasks/{task_id}", headers={"X-API-Key": API_KEY}).json()["status"] not in ("COMPLETED", "FAILED"):
    time.sleep(8)

extracted = requests.get(
    f"{BASE_URL}/api/v1/tasks/{task_id}/artifacts/extracted",
    headers={"X-API-Key": API_KEY},
).json()
print(extracted["fields"]["公司名称"]["value"])
```

---

## 15. 错误码

| HTTP | 典型场景 | `detail` 示例 |
|------|----------|---------------|
| `400` | 参数缺失、任务状态不允许续跑/重跑、非法下载路径 | `仅失败任务可续跑，当前状态：COMPLETED` |
| `401` | 未带或错误 API Key | `Invalid or missing API key` |
| `404` | 任务 ID 不存在、产物文件未生成 | `任务不存在` / `文件不存在` |

错误体统一为：

```json
{"detail": "错误说明"}
```

---

## 16. 限制与说明

| 项 | 默认值 | 说明 |
|----|--------|------|
| 上传材料总大小 | 5000 MB | 单任务 `files` 合计上限 |
| 模板/收集表大小 | 20 MB | `collection_template` |
| 规则文本长度 | 8000 字 | `indicator_judgment_rules` / `fill_logic_rules` |
| 列表分页 | `limit` 默认 100 | 过大可能影响响应时间 |

- `task_type` 仍接受已废弃别名 `case1` / `case2`（创建时），响应统一为 `due_diligence` / `template_fill`。
- 导出 OpenAPI：`cd src/backend && python scripts/export_openapi.py` → `docs/openapi-v1.json`

