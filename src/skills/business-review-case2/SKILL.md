---
name: business-review-case2
description: Case2 模板填报：导出整表 fill_plan（待填项含义+坐标），智能体填同一 JSON，程序回填 xlsx。
---

# Case2 模板驱动填报

## 必读顺序

1. `.task-meta.json`
2. **`inputs/fill_logic_rules.md`**（若存在：用户填表逻辑与计算规则，**优先适用**）
3. `SOP_模板填报.md`
4. `outputs/case2_fill_schema.json`（`schema_version=2` 的 **fill_plan**）

## fill_plan 结构（禁止改顶层）

```json
{
  "schema_version": 2,
  "mode": "fill_plan",
  "sheets": [
    {
      "sheet": "资产负债表",
      "column_headers": {"C": "最近一期报告", "D": "本期(年报）", ...},
      "items": [
        {
          "item_id": "资产负债表:r6",
          "row": 6,
          "label": "货币资金",
          "meaning": "货币资金（各列含义说明）",
          "fields": {
            "C": {"cell": "C6", "column_label": "...", "value_type": "number", "value": null},
            "D": {"cell": "D6", ...}
          },
          "confidence": null,
          "reason_one_line": null,
          "evidence_refs": []
        }
      ]
    }
  ]
}
```

- **1 个 item = 1 个待填单元**（财务报表通常为「一行科目」；指标表为「一行选项 + 选择 + 备注」）。
- 智能体在**每个 item** 上填：`fields.*.value`，以及 item 级的 `confidence` / `reason_one_line` / `evidence_refs`。
- **`evidence_refs`** 须指向实际 OCR 文件路径（如 `ocr_text/sources/xxx.pdf.md`），便于回填时匹配 OCR 置信度；无需填写 OCR 分数（由程序根据 sidecar 标黄）。
- **禁止**拆成数百个独立 cell 任务；**禁止**改写 `sheets/items/fields/cell` 坐标。

## 必做产物

1. `outputs/case2_fill_schema.json`（脚本生成，只读参考）
2. `outputs/case2_filled_schema.json`（复制 fill_plan 结构后填写）
3. `outputs/collection_fill_notes.md`
4. `outputs/collection_filled.xlsx`（回填脚本生成）

## 强制流程

### 1) 导出 fill_plan

```bash
python tools/dump_sheet_headers.py --src inputs/collection_template.xlsx --formulas
python tools/dump_case2_fill_schema.py --src inputs/collection_template.xlsx --out outputs/case2_fill_schema.json --catalog-out outputs/template_row_catalog.json
```

### 2) 阅读源文件

- `sources/`、`ocr_text/`；可用 `outputs/*_index.json` 辅助定位。

### 3) 填充 fill_plan（核心）

- 将 `case2_fill_schema.json` **整份复制** 为 `case2_filled_schema.json`，按 **item** 填值：
  - 财务报表：一次读完源表一行，填该行 `fields` 中 C/D/E/F 的 `value`。
  - 指标表：填 `fields.choice.value` 与 `fields.remark.value`（若有）。
- 硬规则：数据必须来自用户文件直接证据；无证据则对应 `value` 留空，`reason_one_line` 写「文件中未发现相关信息」。
- **计算例外**：`inputs/fill_calc_rules.json` 中的规则由 Python 工具对已有 components 求和；**禁止 LLM 手算合计**。
- 不直接编辑 xlsx。

### 3b) 应用计算规则

```bash
python tools/apply_case2_calc_rules.py \
  --filled outputs/case2_filled_schema.json \
  --rules inputs/fill_calc_rules.json \
  --report outputs/calc_rules_report.json
```

CALC 块语法（写在用户规则的 `---CALC---` 与 `---END---` 之间）：

```
sum|<sheet>|<target_label>|<source>[,<source>...]
sum_if_missing|<sheet>|<target_label>|<source>[,<source>...]
```

### 4) 校验

Worker 自动回填并校验 `written_cells`；你须保证 JSON 合法且结构与 fill_plan 一致。回填后 `backfill_report.json` 含 `ocr_low_confidence_cells`（OCR 置信度低于 70% 且已标黄的单元格数）；对应 xlsx 单元格为黄色并带 OCR 批注。

## 禁止事项

- 禁止自创 `subject_sets` / 按单元格拆成数百条无结构 JSON。
- 禁止无证据推断填值。
- 禁止忽略模板说明与下拉候选。
