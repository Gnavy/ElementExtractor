---
name: business-review-case1
description: 债权管理尽调 Case1：模板驱动逐行填报指标表；尽调 SOP 用于材料取证与交叉校验。
---

# 业务审查填报（Case1 · 债权管理尽调）

## 权威规范（阅读顺序）

| 顺序 | 文档 | 用途 |
|------|------|------|
| 1 | `SOP_信息收集表填报.md` | **填表主规范**（yes_no / exclusive、备注一句话） |
| 2 | `outputs/template_row_catalog.json` | 机器可读行目录（须先生成） |
| 3 | `SOP_当地政策联网检索.md` | **当地政策/规划指标** Tavily 联网检索（`requires_tavily_search`） |
| 4 | `SOP_债权管理尽职调查要素抽取.md` | 尽调报告取证、11 要素理解（**辅助**，不替代逐行填表） |

---

## 目标产物

1. **`outputs/template_row_catalog.json`**（必做，填表前）
2. **`outputs/collection_filled.xlsx`**（必做，主交付）
3. **`outputs/collection_fill_notes.md`**（必做）
4. `outputs/docx_comments_index.json`（建议）
5. `outputs/ppt_text_index.json`（建议）
6. `outputs/elements_extracted.json`（可选，交叉校验）
7. `outputs/field_logic_catalog.json`（可选）
8. `outputs/classification.json`、`outputs/extracted.json`（可精简）

---

## 必须遵循

1. 若 `.task-meta.json` 含 `indicator_judgment_rules` 或存在 `inputs/indicator_judgment_rules.md`，**填表前必读且优先适用**（高于模板默认口径，仍须材料/Tavily 可复核）。
2. 先读 `.task-meta.json`；`collection_template_path` 指向 `inputs/collection_template.xlsx`。
3. **禁止**未读模板目录即填表；**禁止**仅按 11 要素 JSON 批量映射 D/E 列。
4. 按模板每一行的 `数据源优先顺序`（catalog 中 `data_source_priority`）取证；默认尽调 docx 优先，但当该行要求使用补充材料（如可研/PPT 中的板块房价）时必须使用补充材料；对交易结构、增信、违约、监管类要素行仍以尽调报告为主依据。
5. 不覆盖含 Excel 公式的单元格；`指标选择` 必须使用模板允许的下拉值。
6. 对 `requires_tavily_search=true` 的指标，须先执行 Tavily 检索（见 `SOP_当地政策联网检索.md`），再填 D/E 列。

---

## 执行流程

### 阶段 1：解析模板（最先）

```bash
python tools/dump_collection_template.py --src inputs/collection_template.xlsx
python tools/dump_sheet_headers.py --src inputs/collection_template.xlsx --formulas
```

阅读 `outputs/template_row_catalog.json`，掌握全部 `indicator_groups` 的 `choice_mode` 与 `rows`。

### 阶段 2：材料索引

```bash
python tools/extract_docx_comments.py --src . --out outputs/docx_comments_index.json
python tools/extract_pptx_text.py --src . --out outputs/ppt_text_index.json
```

### 阶段 2b：当地政策 / 规划（Tavily，按需）

阅读 `template_row_catalog.json`，对 `requires_tavily_search: true` 的指标组，严格按 `SOP_当地政策联网检索.md` 使用：

```bash
python tools/tavily_search.py --region <城市> --topic "<政策或规划主题>" \
  --out outputs/tavily_<主题>.json --md-out outputs/tavily_<主题>.md
```

从尽调/可研推断城市与板块后再检索；结果用于填表判断，备注须引用来源 URL 或官方文件名。

### 阶段 3：逐行填表（核心）

严格按 `SOP_信息收集表填报.md`：

1. 复制 `inputs/collection_template.xlsx` → `outputs/collection_filled.xlsx`。
2. 按 catalog 中每个 `indicator_group`：
   - 理解 `indicator_name`、`indicator_explanation`；
   - 按 catalog 中该组/行的 `data_source_priority` 在对应材料中针对 **本组各行的 option_text** 检索事实（可参考 `sop_element_hint` 回查尽调 SOP 要素卡）；
   - **`yes_no`**：每行 D 填 `是` 或 `否`；E 列 **一句话** 备注；
   - **`exclusive`**：组内 **仅一行** D 填入选项全文，其余 D 留空；E 列 **一句话** 备注。
3. 保存 xlsx。

### 阶段 4：尽调要素（可选）

可按 `SOP_债权管理尽职调查要素抽取.md` 产出 `outputs/elements_extracted.json`，用于与 xlsx 行级结论交叉核对，**不得**用其替代阶段 3。

### 阶段 5：说明与校验

`outputs/collection_fill_notes.md` 至少包含：

| 列 | 内容 |
|----|------|
| row | Excel 行号 |
| indicator_name | 指标名称 |
| option_text | 指标选项摘要 |
| filled_choice | 指标选择 |
| remark | **一句话** 理由 |

```bash
python tools/validate_collection_filled.py \
  --catalog outputs/template_row_catalog.json \
  --filled outputs/collection_filled.xlsx
```

---

## 完成标准

- `template_row_catalog.json` 与 `collection_filled.xlsx` 已生成。
- 所有 catalog 中有 `option_text` 的行均已处理（`yes_no` 有 D；`exclusive` 组有且仅有 1 个 D）。
- 备注为一句话，可复核至对应材料来源（docx 或 supplements 中的文件）。
- `validate_collection_filled.py` 通过或已知违规已在 notes 说明。

---

## 与通用 business-review 的关系

本 Skill 优先于 `business-review`；**填表口径以本目录 `SOP_信息收集表填报.md` 为准**。
