export type Case2RulePreset = {
  id: string;
  label: string;
  content: string;
};

export const DEFAULT_CASE2_FILL_LOGIC_RULES = `【财务报表计算与映射总则】
1. 应收票据及应收账款 = 其中应收票据 + 应收账款（各报告期分别计算）
2. 源表科目无法与模板行一一对应时，归入对应区块的「(特殊报表科目)」行
3. 利润表若无「营业总成本」行，则营业总成本 = 其下费用科目之和（至「营业利润」前）

---CALC---
sum|资产负债表|应收票据及应收账款|其中应收票据,应收账款
sum_if_missing|利润表|营业总成本|其中：营业成本,利息支出,手续费及佣金支出,退保金,赔付支出净额,提取保险合同准备金净额,保单红利支出,分保费用,税金及附加,销售费用,管理费用,研发费用,财务费用
---END---`;

export const CASE2_RULE_PRESETS: Case2RulePreset[] = [
  {
    id: "general",
    label: "通用总则（默认）",
    content: DEFAULT_CASE2_FILL_LOGIC_RULES,
  },
  {
    id: "balance_sheet_calc",
    label: "资产负债表合并科目",
    content: `【资产负债表合并科目】
应收票据及应收账款 = 其中应收票据 + 应收账款（C/D/E/F 各列分别计算，禁止手算）

---CALC---
sum|资产负债表|应收票据及应收账款|其中应收票据,应收账款
---END---`,
  },
  {
    id: "income_sum_if_missing",
    label: "利润表营业总成本",
    content: `【利润表营业总成本】
若源利润表无「营业总成本」行，则按下列费用科目求和填入模板「营业总成本」行。

---CALC---
sum_if_missing|利润表|营业总成本|其中：营业成本,利息支出,手续费及佣金支出,退保金,赔付支出净额,提取保险合同准备金净额,保单红利支出,分保费用,税金及附加,销售费用,管理费用,研发费用,财务费用
---END---`,
  },
  {
    id: "special_row_mapping",
    label: "特殊报表科目映射",
    content: `【特殊报表科目映射】
源表科目无法与模板标准行一一对应时，按所属区块填入带「(特殊报表科目)」后缀的模板行；备注说明原科目名称与来源文件。`,
  },
];
