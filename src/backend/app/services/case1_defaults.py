import json

CASE1_CLASSIFICATION_BASIS = (
    "债权管理服务项目尽职调查材料：主依据为上传的尽调报告 Word（.docx），"
    "补充材料（pptx/pdf/xlsx 等）仅作背景或交叉引用；"
    "交易结构、增信、违约处置、监管、还款来源等条款性内容以 docx 为准。"
)

CASE1_ELEMENT_NAMES = [
    "风险隔离措施",
    "本息支付情况",
    "增信措施约定",
    "风险隔离措施（SPV层面）",
    "SPV的分配顺序和清偿顺序",
    "项目违约后我司罚息利率超出固定收益率的倍数",
    "违约处置退出方式",
    "其他还款来源",
    "监管方案设置",
    "项目销售考核设置情况",
    "现金流入流出的确定性约定",
]

CASE1_COLLECTION_TEMPLATE_DISPLAY_NAME = "指标对应选项及备注信息260522.xlsx"


def case1_extract_schema_json() -> str:
    fields = [
        {"name": name, "description": "SOP 要素；见 elements_extracted.json", "type": "text"}
        for name in CASE1_ELEMENT_NAMES
    ]
    return json.dumps({"fields": fields}, ensure_ascii=False)
