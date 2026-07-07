export type Case1RulePreset = {
  id: string;
  label: string;
  content: string;
};

/** 页面加载时默认填入 */
export const DEFAULT_INDICATOR_JUDGMENT_RULES = `【通用总则】
1. 按 template_row_catalog 每行的 data_source_priority 取证；尽调 docx 优先，模板要求时必须使用补充材料（可研/PPT 等）。
2. 禁止照抄模板 D/E 列旧值；无材料依据时填「否」或互斥组留空，备注写「文件中未发现相关信息」。
3. E 列备注一句话：关键事实 + 来源文件。
4. yes_no 每行独立判断；exclusive 组内仅一行 D 有值且与 C 列选项全文一致。`;

export const CASE1_RULE_PRESETS: Case1RulePreset[] = [
  {
    id: "general",
    label: "通用总则（默认）",
    content: DEFAULT_INDICATOR_JUDGMENT_RULES,
  },
  {
    id: "local_policy",
    label: "当地政策与规划",
    content: `【当地政策与规划】
1. catalog 中 requires_tavily_search=true 的指标，须先用 tavily_search.py 检索项目所在城市/区县最新政策与规划。
2. 结合尽调 docx 与补充材料交叉验证；备注引用 Tavily URL 或官方文件名称。
3. 限购/限贷/限售/人才政策等以检索到的最新公开政策为准，不得凭常识臆测。`,
  },
  {
    id: "credit_enhancement",
    label: "增信与担保",
    content: `【增信与担保】
1. □ 类增信措施逐行对照尽调报告「增信措施」章节原文。
2. 抵质押登记、担保人资质、还款承诺函等须全文检索关键词后再填是/否。
3. 尽调未明确写明的措施填「否」，备注说明检索结论。`,
  },
  {
    id: "sales_inventory",
    label: "销售与去化",
    content: `【销售与去化】
1. 区域内库存、去化周期等互斥档位：优先可研/PPT/研判报告中的板块数据，尽调未写时用补充材料。
2. 数据口径（片区/行政区）须在备注中说明与模板指标解释一致。
3. 多档择一时选与材料描述最匹配的一档，不得同时填多行 D。`,
  },
  {
    id: "deal_structure",
    label: "交易结构与监管",
    content: `【交易结构与监管】
1. 交易结构、SPV、信托、分配顺序、监管方案等以尽调 docx 交易结构/风控章节为主依据。
2. 监管力度、违约处置等互斥指标按尽调表述的整体档位择一。
3. 材料矛盾时以尽调报告正式表述为准，备注说明取舍理由。`,
  },
];
