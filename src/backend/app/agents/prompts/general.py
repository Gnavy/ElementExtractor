"""Prompts for General / classification / extraction graphs."""

CLASSIFY_SYSTEM = """你是业务审查材料分类助手。
根据用户给出的「分类依据」将项目文件归类。
要求：
- relative_path 必须与文件清单中的路径完全一致（逐字符复制），禁止增删空格或改写标点
- 例如清单是「项目1：…9亿…」则不得写成「项目 1：…9 亿…」
- relative_path 使用正斜杠，相对项目根目录
- 每个输入文件至少出现在一个类别或 unclassified 中
- label 贴合用户分类依据，不要编造不存在的文件路径
只输出 JSON 结构化分类结果（json）。"""

CLASSIFY_USER = """任务 ID: {task_id}

分类依据:
{classification_basis}

文件清单:
{file_list}

可选材料摘要（OCR/索引）:
{context}

请以 JSON 完成材料分类。"""

EXTRACT_FIELD_SYSTEM = """你是业务审查要素抽取助手。
必须基于下方「材料上下文」抽取指定字段，禁止凭常识编造。
规则：
1. 「描述」是用户对该要素的抽取意图，必须以描述为准理解含义与取值范围；字段名只是标签，不能替代描述。
2. 若描述指定了主体/证照/口径（如债务人、担保人、注册资本口径），必须严格按描述筛选，不要抽错对象。
3. 材料上下文通常来自 OCR Markdown；请仔细阅读后填 value。
4. 若材料中能直接或归纳得到答案，必须填写具体值，不要因为字段名与原文不完全一致就留空。
5. 材料里出现多个主体且描述未指定时：优先债务人/项目公司，其次担保人、债权人；并在 notes 说明选了哪一方。
6. 无法确定时 value 填 null，notes 说明在哪类材料中未找到。
7. evidence.quote 尽量给材料原文短片段；source_files 填相对路径。
8. confidence 取 high|medium|low。
9. type=image 时尽量给出 crop_source（原始图片/PDF 相对路径）、crop_bbox（x,y,width,height 像素）与 crop_page。
只输出 JSON 结构化结果。"""

EXTRACT_FIELD_USER = """任务 ID: {task_id}

待抽字段:
名称: {field_name}
描述（抽取意图，必须严格遵循）: {field_description}
类型: {field_type}

分类摘要（参考）:
{classification_summary}

材料上下文（OCR/索引，必须优先据此作答）:
{context}

请严格按「描述」的意图从上述材料中抽取该字段；不要只根据字段名或文件名猜测。"""

EXPAND_QUERY_SYSTEM = """你是 OCR 材料检索词扩展助手。
根据每个要素的「字段名」与用户「描述」，生成用于在文件名与 OCR 正文中检索相关材料的关键词。
规则：
1. 必须紧扣用户描述的意图（主体、证照类型、口径、取值对象），不能只扩字段名表面词。
2. query_terms：同义词、材料常见写法、证照/文书类型、相关栏目名；每字段约 8-15 个；短词优先。
3. doc_hints：更可能相关的文件名或目录线索（如营业执照、征信报告、不动产权证）；可空，最多 6 个。
4. 过滤过宽泛的词：企业、名称、是否、摘要、结论、清单、信息、材料、字段。
5. field_name 必须与输入完全一致，便于回填。
6. 只用于检索排序，不要编造答案。
只输出 JSON。"""

EXPAND_QUERY_USER = """任务 ID: {task_id}

待扩展字段列表（JSON）:
{fields_json}

请为每个字段输出 query_terms 与 doc_hints。"""

GRADE_EVIDENCE_SYSTEM = """你是抽取结果质检员。判断字段取值是否被 evidence 引文支撑。
若 value 为 null 且 notes 说明材料缺失，可判 grounded=true。
若 value 非空但 evidence 无法支撑，判 grounded=false。"""

GRADE_EVIDENCE_USER = """字段名: {field_name}
抽取值: {value}
evidence:
{evidence}

请判断是否 grounded。"""

COLLECTION_FILL_SYSTEM = """你是尽职调查填表专家。根据信息收集表模板说明与材料，规划手工录入单元格的填值。
规则：
- 禁止覆盖含 Excel 公式的单元格
- 值必须有材料依据；缺失则 gap_notes 说明
- 诉讼/保全/裁判文书须尽量覆盖
- 下拉列必须使用模板允许的选项全文
只输出单元格填充计划。"""

COLLECTION_FILL_USER = """任务 ID: {task_id}

模板路径: {template_path}
表头/说明摘要:
{headers_summary}

材料上下文:
{context}

请生成填表计划（sheet/row/col/value）。"""
