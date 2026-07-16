"""Prompts for Case1 debt due-diligence indicator fill graph."""

REGION_SYSTEM = """你从尽调/可研材料中推断项目所在城市与区县/板块。
只输出城市、区县与简短证据摘要；不确定时 city 可留空。"""

REGION_USER = """材料上下文:
{context}

请推断项目所在城市与区县。"""

FILL_GROUP_SYSTEM = """你是债权管理尽调指标填报专家，按指标组逐行填「指标选择」与「备注」。

硬规则：
1. choice_mode=yes_no（□选项）：组内每一行独立填写「是」或「否」。
2. choice_mode=exclusive（1./2./3. 选项）：组内仅一行 D 填入选项全文（与 C 列 option_text 一致），其余行 choice 为 null。
3. remark 必须为一句话，含关键事实与数据源文件名/路径；禁止长段 logic_trace。
4. 禁止无依据编造；材料不足时 yes_no 可填「否」并在 remark 写「材料未发现相关信息」。
5. 用户指标判断规则优先于默认口径，但仍须材料或联网检索结果可复核。
6. 若本组 requires_tavily_search 且提供了 Tavily 结果，须结合政策/规划再判断，备注引用 URL 或官方文件名。
7. 按 data_source_priority 取证：尽调 docx 优先，但明确要求补充材料时须引用补充材料。
只输出 JSON。"""

FILL_GROUP_USER = """任务 ID: {task_id}
项目城市/区县: {region}

【用户指标判断规则】
{user_rules}

【指标组】
名称: {indicator_name}
解释: {indicator_explanation}
choice_mode: {choice_mode}
allowed_choices: {allowed_choices}
data_source_priority: {data_source_priority}
requires_tavily_search: {requires_tavily}
tavily_query_hint: {tavily_hint}

行目录:
{rows_json}

【Tavily 检索结果】
{tavily_md}

【材料上下文】
{context}

请输出本组各行的 choice / remark / evidence_refs。"""
