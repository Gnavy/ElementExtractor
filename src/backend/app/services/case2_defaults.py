import json

# 用户填表规则的长度上限。入库校验与注入提示词必须共用这一个口径，
# 否则超出部分会在进模型前被静默截掉，而用户习惯把特殊口径写在末尾。
MAX_FILL_LOGIC_RULES_LEN = 8000

CASE2_CLASSIFICATION_BASIS = (
    "Case2 模板驱动填报：先读取用户上传模板中的填写说明、字段口径、下拉校验与可填写区域，"
    "再从源文件集合中逐字段检索证据进行填报。"
)


def case2_extract_schema_json() -> str:
    # Case2 由模板定义字段，extract_schema 仅作结构占位
    return json.dumps(
        {
            "fields": [
                {
                    "name": "template_driven_fields",
                    "description": "字段由用户上传的 xlsx 模板定义",
                    "type": "object",
                }
            ]
        },
        ensure_ascii=False,
    )
