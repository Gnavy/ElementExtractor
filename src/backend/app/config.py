from pathlib import Path
from typing import Optional

from pydantic import Field, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict

_BACKEND_ROOT = Path(__file__).resolve().parent.parent


def _default_sqlite_url() -> str:
    return f"sqlite:///{(_BACKEND_ROOT / 'data' / 'app.db').as_posix()}"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = Field(default_factory=_default_sqlite_url)
    redis_url: str = "redis://localhost:6380/0"

    uploads_dir: Path = _BACKEND_ROOT / "uploads"
    extracts_dir: Path = _BACKEND_ROOT / "extracts"
    skills_source_dir: Path = _BACKEND_ROOT.parent / "skills"
    case1_template_path: Path = (
        _BACKEND_ROOT.parent / "assets" / "case1" / "collection_template.xlsx"
    )

    conda_bin: str = "conda"
    conda_env: str = "v312"
    ocr_python: Optional[Path] = Field(
        default=None,
        description="?????? docling ? python???? conda run????? OCR_PYTHON?",
    )
    ocr_script: Path = _BACKEND_ROOT / "scripts" / "ocr_pdf.py"
    libreoffice_bin: str = Field(
        default="soffice",
        description="LibreOffice soffice，用于 PPTX 转 PDF（环境变量 LIBREOFFICE_BIN）",
    )
    pptx_convert_timeout_sec: int = Field(
        default=300,
        description="单个 PPTX 经 LibreOffice 转 PDF 的超时秒数（PPTX_CONVERT_TIMEOUT_SEC）",
    )
    docling_num_threads: Optional[int] = Field(
        default=None,
        description="docling 的 layout / TableFormer 线程数（DOCLING_NUM_THREADS），"
        "不影响 OCR。留空用 docling 默认值",
    )
    omp_wait_policy: str = Field(
        default="",
        description="OpenMP 等待策略（OMP_WAIT_POLICY）。虚拟机上建议 PASSIVE，"
        "ACTIVE 忙等会空转烧 CPU；留空则不注入",
    )
    hf_offline: bool = Field(
        default=False,
        description="强制 HuggingFace 离线（HF_HUB_OFFLINE / TRANSFORMERS_OFFLINE）。"
        "隔离网下须开启，否则每次转换白等约 260 秒连接超时",
    )
    ocr_text_layer_guard: bool = Field(
        default=True,
        description="PDF 自带文本层金额规范率过低时改用强制整页 OCR"
        "（OCR_TEXT_LAYER_GUARD）。逐页体检约 0.25 秒/页，命中即停；"
        "关闭则一律信任已有文本层",
    )
    ocr_table_split: bool = Field(
        default=True,
        description="把被 docling 并成一张的双栏财务报表拆回两半"
        "（OCR_TABLE_SPLIT）。只在表头出现两个列名同格时触发，"
        "拆不开的格留空并记入日志；关闭则保留原始表格",
    )
    ocr_guard_kinds: str = Field(
        default="case2",
        description="上面两项 OCR 增强只对哪些场景生效，逗号分隔（OCR_GUARD_KINDS）。"
        "默认仅 case2：这两项是为财务报表设计的，case0 材料杂、文件多，"
        "前置体检的收益未验证而误判代价高（把好文本层换成 OCR）。"
        "留空表示所有场景都启用",
    )

    llm_provider: str = Field(
        default="anthropic",
        description="LLM 提供商：anthropic | openai | zhipu | bailian（LLM_PROVIDER）",
    )
    llm_model: str = Field(
        default="claude-sonnet-4-20250514",
        description="LLM 模型名（LLM_MODEL）",
    )
    llm_timeout_sec: int = Field(
        default=3600,
        description="LangGraph 智能体超时秒数（LLM_TIMEOUT_SEC）",
    )
    llm_max_retries: int = Field(
        default=3,
        description="LLM 调用瞬时错误重试次数（LLM_MAX_RETRIES）",
    )
    llm_temperature: float = Field(
        default=0.0,
        description="LLM 温度（LLM_TEMPERATURE）",
    )
    llm_streaming: bool = Field(
        default=False,
        description="LLM 是否流式调用（LLM_STREAMING）。模型服务前有反向代理时须开启，"
        "否则长请求会被代理的读超时掐断（浙商 VM nginx 为 60 秒）",
    )
    llm_max_tokens: int = Field(
        default=0,
        description="LLM 单次输出上限（LLM_MAX_TOKENS）。0=不限制、保持原行为；"
        "止损用：某些量化模型在结构化输出下 EOS 失效会无限生成，设上限强制截断",
    )
    llm_stop: str = Field(
        default="",
        description="LLM 停止词（LLM_STOP），逗号分隔，空=不启用、保持原行为；"
        r"支持 \n \t \r 转义，如 \n\n。止损兜底用",
    )
    llm_enable_thinking: Optional[bool] = Field(
        default=None,
        description="是否启用 Qwen thinking（LLM_ENABLE_THINKING）。"
        "仅用于 OpenAI/vLLM 兼容接口；留空不传参、保持模型服务默认行为",
    )
    llm_degeneration_whitespace_run: int = Field(
        default=200,
        description="退化探测：流式输出中连续空白字符超过该值即判为模型空转并中止本次调用"
        "（LLM_DEGENERATION_WHITESPACE_RUN）。0=关闭。"
        "某些量化模型在结构化输出下会在 JSON 冒号后无限吐空格，"
        "此时数据仍在流动，LLM_TIMEOUT_SEC 这种读超时拦不住，只能靠内容判断",
    )
    anthropic_api_key: Optional[str] = Field(
        default=None,
        description="Anthropic API Key（ANTHROPIC_API_KEY）",
    )
    openai_api_key: Optional[str] = Field(
        default=None,
        description="OpenAI API Key（OPENAI_API_KEY）",
    )
    openai_base_url: Optional[str] = Field(
        default=None,
        description="OpenAI 兼容 API Base URL（OPENAI_BASE_URL）",
    )
    zhipu_api_key: Optional[str] = Field(
        default=None,
        description="智谱 API Key（ZHIPU_API_KEY）",
    )
    zhipu_base_url: str = Field(
        default="https://open.bigmodel.cn/api/paas/v4/",
        description="智谱 OpenAI 兼容 Base URL（ZHIPU_BASE_URL）",
    )
    bailian_api_key: Optional[str] = Field(
        default=None,
        description="阿里云百炼 API Key（BAILIAN_API_KEY）",
    )
    dashscope_api_key: Optional[str] = Field(
        default=None,
        description="DashScope API Key 别名（DASHSCOPE_API_KEY）",
    )
    bailian_base_url: str = Field(
        default="https://dashscope.aliyuncs.com/compatible-mode/v1",
        description="百炼 OpenAI 兼容 Base URL（BAILIAN_BASE_URL）",
    )
    agent_stream_to_console: bool = Field(
        default=True,
        description="Celery worker 将智能体进度打印到控制台（AGENT_STREAM_TO_CONSOLE）",
    )
    agent_parallel_workers: int = Field(
        default=4,
        description="LangGraph 并行节点并发上限（AGENT_PARALLEL_WORKERS）",
    )

    tavily_api_key: Optional[str] = Field(
        default=None,
        description="Tavily Search API Key，Case1 当地政策检索（TAVILY_API_KEY）",
    )
    tavily_enabled: bool = Field(
        default=True,
        description="Case1 是否启用 Tavily 联网检索（TAVILY_ENABLED）",
    )

    skip_ocr: bool = Field(False, description="Skip Docling OCR step")
    skip_agent: bool = Field(
        False,
        description="Skip LangGraph agent; write stub JSON for pipeline smoke tests（SKIP_AGENT）",
    )
    # 兼容旧环境变量 SKIP_CLAUDE
    skip_claude: bool = Field(
        False,
        description="Deprecated alias of SKIP_AGENT（SKIP_CLAUDE）",
    )
    ocr_confidence_threshold: float = Field(
        default=0.7,
        description="OCR 置信度低于该阈值（0-1）时在 Case2 回填 xlsx 中标黄（OCR_CONFIDENCE_THRESHOLD）",
    )
    max_zip_mb: int = 5000
    max_collection_mb: int = 20

    api_keys_raw: str = Field(
        default="",
        validation_alias="API_KEYS",
        description="对外 API Key 列表，逗号分隔（API_KEYS）",
    )
    api_auth_enabled: bool = Field(
        default=True,
        description="是否对 /api/v1/* 启用 API Key 鉴权（API_AUTH_ENABLED）",
    )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def api_keys(self) -> list[str]:
        return [part.strip() for part in self.api_keys_raw.split(",") if part.strip()]


settings = Settings()
