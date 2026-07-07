# Case1 当地政策 / 规划指标 · Tavily 联网检索 SOP

**适用**：`template_row_catalog.json` 中 `requires_tavily_search: true` 的指标组（个性化政策、规划指标、限购限贷限售等）。

---

## 何时使用

1. 指标名称/解释/数据源优先顺序涉及 **当地、区域、城市政策、规划、调控** 等，且尽调 docx 或补充材料 **未覆盖或明显过时**。
2. 需判断「是否限购/限贷/限售」「规划是否利好/中性/利空」等 **依赖最新公开政策** 的选项。

**仍优先**：模板 `data_source_priority` 指定的本地材料（可研/PPT/研判报告）；Tavily 用于 **补充与交叉验证**，不得与本地材料矛盾时随意覆盖；若冲突，备注说明并以 **官方来源 + 本地材料** 综合判断。

---

## 工具

```bash
# 方式 1：完整 query
python tools/tavily_search.py \
  --query "成都市 成华区 房地产 限购 限贷 限售 政策 2024 2025" \
  --out outputs/tavily_policy_chengdu.json \
  --md-out outputs/tavily_policy_chengdu.md

# 方式 2：城市 + 主题（从尽调/可研推断项目所在城市后使用）
python tools/tavily_search.py \
  --region 成都 \
  --topic "城市总体规划 东客站板块 规划" \
  --out outputs/tavily_planning_chengdu.json \
  --md-out outputs/tavily_planning_chengdu.md
```

- API Key 由 Worker 注入环境变量 `TAVILY_API_KEY`，**勿**写入任务目录或 Git。
- 检索结果保存到 `outputs/tavily_*.json` / `*.md`，填表备注引用 **URL 或文件标题 + 一句话结论**。

---

## 填表要求

1. 填表前阅读 catalog，列出所有 `requires_tavily_search=true` 的 `indicator_name` 与 `tavily_query_hint`。
2. 从尽调 docx / 可研 / PPT 推断 **城市、区县、板块**，构造检索词（含政策类型 + 年份）。
3. 每个相关指标组至少 **1 次** Tavily 检索（可合并同类 query）。
4. E 列备注示例：「Tavily 检索成都市住建官网，2024-04-29 起全市取消购房资格审核，故选……」

---

## 禁止

- 禁止在无 Tavily/官方依据时凭常识编造当地政策。
- 禁止将 Tavily 摘要直接粘贴进 E 列（仍须 **一句话** 结论 + 来源）。
