---
name: business-review
description: 业务审查材料：分类、要素抽取；可选按用户上传的 xlsx/xlsm 信息收集表以尽职调查口径全面填报 outputs/collection_filled.xlsx（覆盖诉讼/保全/裁决等文书并多轮校验）；产出 classification.json 与 extracted.json。
---

# 业务审查材料处理

## 何时使用

- 工作目录为解压后的项目文件夹，根目录存在 `.task-meta.json`。
- 需要将目录内文件按用户给定的「分类依据」归类，并按 `extract_schema` 抽取结构化字段。

## 必读输入

1. **`.task-meta.json`**：`classification_basis`、`extract_schema`；若存在 **`collection_template_path`**，则表示用户已上传信息收集表模板（相对路径，如 `inputs/collection_template.xlsx`），**必须**完成填报流程（见下文「信息收集表」）。
2. **`ocr_text/`**（若存在）：与 PDF 路径对应的 Markdown，优先使用其中的正文。
3. 若无 OCR 侧车文件，可读取原始 **pdf / docx / xlsx**（使用可用工具逐文件读取，大文件可抽样页或摘要）。

## 分类输出

在 **`outputs/classification.json`** 写入 UTF-8 JSON，建议结构：

```json
{
  "task_id": "<与 .task-meta.json 一致>",
  "categories": [
    {
      "label": "<类别名，贴合用户分类依据>",
      "files": [
        {
          "relative_path": "<相对项目根的路径>",
          "file_type": "pdf|docx|xlsx|other",
          "notes": "<可选简短说明>"
        }
      ]
    }
  ],
  "unclassified": [ { "relative_path": "...", "reason": "..." } ]
}

```

要求：

- `relative_path` 使用正斜杠，相对当前项目根目录。
- 每个输入文件至少出现在一个类别或 `unclassified` 中，避免遗漏。

## 抽取输出

解析 `extract_schema`：应为 JSON，形如 `{ "fields": [ { "name": "...", "description": "...", "type": "<可选类型>" } ] }`；其中 **`type` 为 `"image"`** 时表示证件/区域截图类字段（见下文「图片/证件类字段」）。

在 **`outputs/extracted.json`** 写入：

```json
{
  "task_id": "<与 meta 一致>",
  "fields": {
    "<字段名>": {
      "value": "<抽取值或 null>",
      "confidence": "high|medium|low",
      "source_files": ["<贡献信息的文件相对路径>"],
      "evidence": [
        {
          "file": "<材料相对路径，与 source_files 中之一对应>",
          "quote": "<引用原文片段，短而准>",
          "page_hint": "<可选：页码、章节或 ocr 位置说明>"
        }
      ],
      "notes": "<可选>"
    }
  }
}

```

- 无法确定的字段显式填 `null`，并在 `notes` 说明原因。
- `source_files` 尽量列出具体证据文件路径。
- **`evidence`**：对关键字段尽量给出 1 条或多条引文；`quote` 优先从 `ocr_text` 下对应 `.md` 中摘录；无把握时 `evidence` 可为 `[]`。
- 若某文件无 OCR 侧车，可从正文工具读取结果中摘句作为 `quote`。

### 信息收集表（可选，`.task-meta.json` 含 `collection_template_path` 时必做）

当 meta 中给出 **`collection_template_path`**（指向项目内的 `.xlsx` 或 `.xlsm`）时，信息收集表与任务下发的 **抽取要素 schema（`extract_schema` / `extracted.json` 的字段结构）无对应关系**：须**单独**按模板 **各 sheet 的表头与版式**理解要填什么，从材料（优先 `ocr_text/`、原始 pdf/docx/xlsx 等）中检索并填入；`outputs/extracted.json` 若存在，仅可作事实参考，**不得**用抽取字段名去硬套模板列。产出写入 **`outputs/collection_filled.xlsx`**（固定文件名）。

**尽职调查口径（信息收集表——完整性优先）**

- **角色**：按**尽职调查专家**标准执行——目标是**信息完整、可复核**，不是「应付填满」。模板列所指向的要素，只要材料中存在依据，就应写入；禁止因省事而大量留空，或用一句笼统概括代替可从文书摘录的具体事实（案号、主体、金额、期间、裁判结果等）。
- **文书类型须全覆盖**：除合同、借据、财报等常规材料外，须**主动检索并消化**与争议、担保实现、司法程序相关的文书，包括但不限于：**起诉状、受理通知书、应诉/举证通知、保全申请书、保全裁定、保全告知书 / 保全事项告知书、判决书、裁定书、调解书、仲裁通知与裁决、执行文书、破产与清偿类文书**等。路径或文件名含「诉讼」「保全」「裁定」「裁决」「受理」「执行」「仲裁」「调解」「判决」等线索的目录与文件应**逐项打开核对**，不能只读少量汇总材料就推断全貌。
- **检索策略**：结合 **`outputs/classification.json`**（若有）与项目目录**系统遍历**；对 `ocr_text/` 用当事人、统一社会信用代码、案号、法院名称、案由、债权金额等关键词**多轮、换词检索**；同一事实分散在多份文件时，应**合并归纳**填入对应单元格，并在模板备注列或独立备注栏**标注材料出处**（相对路径或文件名）。
- **多轮验证**：① 初稿完成后，**第二轮**按模板逐列自问「是否还有未检索到的相关路径/同类文书」；② **第三轮**对关键字段（金额、日期、案号、当事人名称、裁判/裁决主文结论）与 `ocr_text` 或原件摘录**交叉核对**；③ 发现材料之间冲突时，须在备注中**并列说明**并列出各自依据文件，不得静默择一。

**模板版式（必读）：说明区与公式**

- **列标题上方的说明区**：多数模板在正式表头行**之上**另有若干行（填写说明、口径、字段释义、注意事项）。须从每个 sheet **第 1 行起向下通读**，区分「说明行 / 表头行 / 数据区」；**表头不一定在第 1 行**，填报口径以说明区文字为准，不得仅凭列名字面猜测。
- **公式带出列**：模板中大量单元格由 **Excel 公式**从其他格计算得出。**禁止**写入、覆盖或删除这些单元格（否则会破坏公式或写入错误静态值）。填报时仅用 openpyxl **逐格写入**「手工录入」单元格；写入前判断 `cell.data_type == 'f'`（公式）则**跳过**。可先运行 `dump_sheet_headers.py --formulas` 获取各 sheet 的 **formula_cells** 清单以便避让。
- **清单驱动**：填报前应形成「待消化材料路径列表」（见下文 `ocr_inventory.py`），并对照模板列语义逐项检索，禁止只读少量汇总文件。

**流程建议：**

1. **读说明与表头**：打开模板每个 sheet，先读**说明区**，再锁定表头行与数据起始行。用 Python **openpyxl** 加载模板（路径即 `collection_template_path`）。可先运行（已由流水线复制到 `tools/`）：
   ```bash
   python tools/dump_sheet_headers.py --src <collection_template_path>
   python tools/dump_sheet_headers.py --src <collection_template_path> --formulas
   ```
   `dump_sheet_headers` 默认导出**第 1 行**文本作为 `headers` 参考；若真实表头不在第 1 行，以你在模板中识别的行为准，`headers` 仅作辅助。
2. **诉讼/争议文书路径清单**：在填报司法相关内容前，生成路径索引便于逐项核对：
   ```bash
   python tools/ocr_inventory.py --out outputs/ocr_litigation_index.txt
   ```
   需要全量 Markdown 列表时用 `python tools/ocr_inventory.py --all-md --out outputs/ocr_all_md_index.txt`。
3. **理解列语义**：**仅以模板与说明区为准**——根据列名、说明区文字及 sheet 名判断应对应哪类材料；通过关键词在 `ocr_text` 等中检索，并覆盖上文「尽职调查口径」中的诉讼与保全等分支。**不要**假设列与抽取 schema 或 `extracted.json` 字段一一对应。
4. **多行明细**：若表结构为「每户 / 每案 / 每笔一行」（表头含序号、案号、债务人、债权编号等重复维度），须按材料中出现的**独立案件或主体**扩展行填写，不得只在首行写汇总句。
5. **填值**：在尽职调查口径下逐 sheet、逐列处理**手工录入格**；单元格优先填**可从材料直接支撑的**文本或数字字符串（宜具体到文书称谓与要点）。仅在材料确实缺失时方可填「待补充」或留空；**不得**在已有裁判/保全/受理等文书可读的情况下仍大面积留白。**不要删除表头行、不要随意插入行列**，以免破坏模板结构。
   - **下拉 / 数据有效性**：若某列在原始模板中设置为**下拉选择**（Excel「数据验证」/ 列表来源为单元格区域或内联列表），填写的值**必须落在该列允许范围内**——即应使用**原始模板中已给出的数据范围/选项**（与列表条目的**文本完全一致**，含空格与标点需一致）。用 openpyxl 可读取 `DataValidation` 的 `formula1` 等，或从模板中列表所在区域解析出可选值；**不得**在输出表中写入不在下拉列表内的新造选项（除非模板本身允许自由输入且未限制）。若材料中的信息与列表都不匹配，优先选语义最接近的一项，或在 `notes`/备注列说明原因。
6. **填报缺口自检（建议）**：生成 **`outputs/collection_gap_notes.txt`**（或 `.md`）：列出仍为空的**关键手工列**（按 sheet / 行 / 列或列名描述）；**公式列与说明区不计入「缺漏」**。每条注明原因：`材料缺失` 或 `待复核`。用于第二轮核对。
7. **保存**：将结果保存为 **`outputs/collection_filled.xlsx`**（与模板同逻辑结构）。保存前再次确认**未覆盖任何公式单元格**。  
   - **xlsm 说明**：若模板为 `.xlsm`，openpyxl **保存为 xlsx 会丢失 VBA 宏**，因此统一输出 **`collection_filled.xlsx`**；请在技能执行说明中理解此为预期行为。
8. **依赖**：需 **`pip install openpyxl`**（若当前环境无）；`ocr_inventory.py` 仅依赖标准库。

**输出文件**：任务完成后，服务端将 **`outputs/collection_filled.xlsx`** 作为可下载产物之一；你必须生成该文件（至少为基于模板复制后的已填版本）。建议同时提供 **`outputs/ocr_litigation_index.txt`**（若已生成）与 **`outputs/collection_gap_notes.txt`** 便于复核。

### 图片 / 证件类字段（`extract_schema.fields[].type === "image"`）

当抽取要素 JSON 中某字段 **`type` 为 `"image"`**（例如身份证、营业执照扫描件的「区域截图」）时，该字段的产出应为 **磁盘上的裁剪图**，而不是仅靠文字引用。

**约定：**

1. **目录**：将所有裁剪结果写入 **`outputs/image_crops/`**（UTF-8 路径，文件名简明，如 `身份证正面.png`）。
2. **`extracted.json` 中该字段**：
   - **`value`**：**字符串**，为裁剪图相对项目根的 POSIX 路径（推荐）：如 `outputs/image_crops/身份证正面.png`；若同一要素有多张图（正反面等），可用 **字符串数组**：`["outputs/image_crops/a.png","outputs/image_crops/b.png"]`。
   - **`source_files`**：填入原始材料路径（如 `.jpg` / `.pdf`）。
   - **`evidence`**：可为空；若有，`quote` 可简述「自 xxx 裁剪」，最终以 **`value` 指向的 PNG** 为准。
   - **`notes`**：建议记录 **页码（PDF）**、**bbox（像素坐标）**、或裁剪依据（如 `page=0 bbox=120,80,380,260 zoom=2`），便于复核。
3. **生成裁剪图**：优先使用项目根下 **`tools/crop_region.py`**（已由流水线复制到解压目录）。依赖：**Pillow**；PDF 另需 **PyMuPDF**。示例：
   ```bash
   python tools/crop_region.py --src <相对路径/证件.jpg> --out outputs/image_crops/id_front.png --bbox x,y,width,height
   python tools/crop_region.py --src <相对路径/扫描.pdf> --out outputs/image_crops/id_front.png --page 0 --bbox x,y,width,height --zoom 2
   ```
   - **`--bbox`**：`x,y,width,height` 均为 **像素**，相对于脚本渲染结果：栅格图为原图像素；PDF 为 `--zoom` 缩放后页面的像素（默认 `--zoom 2`）。
   - 若无 Python 依赖，可改用本机已安装的等价工具，但仍须把结果写入 `outputs/image_crops/` 并在 `value` 中给出相对路径。
4. **图片类与其它字段一致**：仍需写入合法的 **`outputs/extracted.json`**，且路径可被服务端作为静态文件读取（位于解压目录内）。

**示例片段（`extracted.json`）：**

```json
{
  "task_id": "<与 meta 一致>",
  "fields": {
    "身份证人像面": {
      "value": "outputs/image_crops/身份证人像面.png",
      "confidence": "high",
      "source_files": ["资料/借款人身份证.pdf"],
      "evidence": [],
      "notes": "page=0 bbox=… , zoom=2"
    }
  }
}
```

## 安全与边界

- **不要**运行来源不明的可执行文件或 `.sh/.bat/.exe`；**允许**按上文说明使用本项目自带的 **`tools/*.py`**（Python 辅助脚本）。
- **不要**假设需要访问互联网。
- 控制单次读取体量：超大 PDF 可先读 `ocr_text` 摘要或前几页。

## 自检

写入 JSON 前，确认可被标准解析器解析；路径均相对于项目根目录。若存在信息收集表任务，确认 **`outputs/collection_filled.xlsx`** 已生成，并对照上文「尽职调查口径」自查：**诉讼/保全/裁决等路径是否已覆盖**、关键字段是否经**至少两轮核对**、**公式格未被覆盖**、**说明区口径已遵守**。
