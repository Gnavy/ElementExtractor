# Case1 信息收集表填报 SOP

**版本**：case1-fill-v1  
**适用**：`inputs/collection_template.xlsx` → `outputs/collection_filled.xlsx`  
**前置**：必须先运行 `python tools/dump_collection_template.py` 生成 `outputs/template_row_catalog.json`

---

## 一、总原则

0. **用户指标判断规则（最高优先级）**：若任务提供 `indicator_judgment_rules`（见 `.task-meta.json` 与 `inputs/indicator_judgment_rules.md`），填表前必读；与下列原则冲突时**以用户规则为准**（仍禁止无材料依据编造）。
1. **模板先行**：以 `template_row_catalog.json` 中的每一「指标组 / 数据行」为填表单位，不得仅用 SOP 11 要素摘要批量映射。
2. **材料优先级（强制按模板）**：对每个指标行，必须读取模板列 `数据源优先顺序`（catalog 中对应 `data_source_priority`），按其中的材料优先级依次取证；默认尽调报告为最高优先级，但当该行优先级要求使用补充材料（如项目所在板块房价/可研/PPT 等）时，即使尽调报告未覆盖也必须使用补充材料取证。
3. **禁止照抄**：不得保留模板 D/E 列旧值；不得写「原模板预填」类说明。
4. **备注**：每个填写了「指标选择」的行，E 列用 **一句话** 说明理由（含关键事实，如「尽调报告××节约定……」）。

---

## 二、两种填报模式

### 2.1 `yes_no`（独立是/否）

**识别**：`choice_mode === "yes_no"`，或 `指标选项` 以 `□` 开头。

**规则**：
- **每一行** 单独判断：该选项在项目中是否成立。
- D 列仅填 **`是`** 或 **`否`**（须符合下拉校验）。
- 同一指标名称下多行互不影响（例如增信措施 3 个□选项可分别是 是/否/是）。

**示例（模板行 2–4 · 增信措施约定）**：
- □抵质押物可办妥登记 → 对照 docx 增信措施是否第一顺位抵押。
- □实际控制人担保能力强 → 对照保证人及担保能力描述。
- □还款承诺函 → 全文检索「还款承诺函」，无则填否并在备注说明。

### 2.2 `exclusive`（互斥多选一）

**识别**：`choice_mode === "exclusive"`，组内多行 `指标选项` 为 `1.` / `2.` / `3.` 等编号选项。

**规则**：
- 先根据 `指标名称` + `指标解释` 阅读尽调报告，判断项目 **整体** 属于哪一种档位。
- **仅在选中那一行** 的 D 列填入与该行 C 列 `指标选项` **一致** 的完整文本（或 `allowed_choices` 中的合法值）。
- **同组其余行 D 列必须留空**。

**示例**：
- 行 15–17「原债权人对项目的投后监管力度」：三档监管强度择一。
- 行 21–22「风险隔离措施」：`1.可落实财产权信托…` vs `2.未设立…` 择一。
- 行 33–36「区域内一手房库存和去化情况」：四档去化周期择一。

**反例（禁止）**：
- 互斥组内多行 D 列同时有值。
- D 列填「是/否」而非选项全文（互斥组不用是/否）。

---

## 三、推荐执行步骤

```
Step1  dump_collection_template.py → template_row_catalog.json
Step2  extract 索引 + 对 requires_tavily_search 指标运行 tavily_search.py（见 SOP_当地政策联网检索.md）
Step3  复制模板 → outputs/collection_filled.xlsx（保留公式与校验）
Step4  按 catalog 顺序，对每个 indicator_group：
         - 读 indicator_name、indicator_explanation
         - 按 catalog 中该组/行的 `data_source_priority` 对应材料集合检索取证（docx / supplements/ 内文件等），并把用于判断的关键事实写入备注的一句话里
         - 按 choice_mode 填写各行 D、E
Step4  （可选）产出 elements_extracted.json 作交叉校验，不替代 Step4
Step5  写 collection_fill_notes.md（每行：row、选项摘要、指标选择、一句备注）
Step6  python tools/validate_collection_filled.py（若可用）
```

---

## 四、与尽调 SOP 的关系

| 用途 | 文档 |
|------|------|
| **填哪一行、填什么格式** | 本 SOP + `template_row_catalog.json` |
| **尽调事实从哪找、如何理解条款** | `SOP_债权管理尽职调查要素抽取.md` |

`sop_element_hint` 字段仅作检索提示；模板中许多行（尤其客观部分）无对应 11 要素，仍须按 `指标解释` 单独取证。

---

## 五、备注一句话规范

**合格**：
- 「尽调报告交易结构节约定设立财产权信托，SPV 为委托人及唯一指令权人。」
- 「正文未见还款承诺函，仅有资金缺口补足承诺函。」

**不合格**：
- 照搬 `logic_trace` 多句堆砌。
- 只写「见尽调报告」无具体判断。
- 「原模板预填」「按满分处理」而无材料依据（除非指标解释明确允许不适用/满分规则且备注说明依据）。

---

## 六、质量自检

- [ ] 已读取 `template_row_catalog.json` 全部 `indicator_groups`
- [ ] 每个 `yes_no` 行 D 列为「是」或「否」
- [ ] 每个 `exclusive` 组仅有 **1** 行 D 非空，且文案与 C 列选项一致
- [ ] 填写了 D 的行均有 **一句话** E 列备注
- [ ] 未覆盖含公式的单元格

---

*文档结束*
