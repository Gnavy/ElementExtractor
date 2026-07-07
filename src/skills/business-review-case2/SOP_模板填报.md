# Case2 模板填报 SOP

## 适用范围

- 用户上传任意业务模板 `xlsx`（单文件）
- 用户上传多源材料（`pdf/ppt/pptx/doc/docx/xlsx/...`）
- 目标是按模板说明填写可填写字段并输出 `collection_filled.xlsx`

## 核心原则

0. **用户填表规则（最高优先级）**：若存在 `inputs/fill_logic_rules.md`，填表前必读；映射类规则（如无法对应时填入「特殊报表科目」）按该文件执行。
1. 先由脚本导出 **fill_plan**（待填项含义 + 单元格坐标），再读材料，最后填值。
2. 智能体只维护 **一个 JSON 对象**（`case2_filled_schema.json`），结构与 `case2_fill_schema.json` 一致。
3. 每个 **item** 对应一个业务待填单元（如资产负债表一行科目），不是每个格子一条任务。
4. 硬规则：数据必须可在源文件中直接定位；无证据则 `value` 留空，`reason_one_line` 说明「文件中未发现相关信息」。
5. **计算规则**：`inputs/fill_calc_rules.json` 由 Worker 解析用户规则中的 `---CALC---` 块生成；**禁止手算**，须运行 `apply_case2_calc_rules.py`（Worker 亦会自动执行）。

## 执行步骤

1. 解析模板并生成 fill_plan：
   - `python tools/dump_sheet_headers.py --src inputs/collection_template.xlsx --formulas`
   - `python tools/dump_case2_fill_schema.py --src inputs/collection_template.xlsx --out outputs/case2_fill_schema.json --catalog-out outputs/template_row_catalog.json`
2. 解析材料：`ocr_text/`、`sources/` 等。
3. 复制 `case2_fill_schema.json` → `case2_filled_schema.json`，按 **item** 填写 `fields.*.value` 与 item 级 `reason_one_line` / `evidence_refs`。
4. 运行计算规则工具（若存在 `inputs/fill_calc_rules.json`）：
   - `python tools/apply_case2_calc_rules.py --filled outputs/case2_filled_schema.json --rules inputs/fill_calc_rules.json --report outputs/calc_rules_report.json`
5. Worker 执行回填 → `collection_filled.xlsx`。

## 质量门禁

- 不覆盖公式单元格
- 下拉值在候选集中
- 回填报告 `written_cells` 与已填非空字段数量匹配
