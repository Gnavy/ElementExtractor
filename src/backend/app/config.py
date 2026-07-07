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

    claude_bin: str = "claude"
    claude_timeout_sec: int = 3600
    claude_stream_to_console: bool = Field(
        default=True,
        description="Celery worker 执行时将 Claude CLI 输出实时打印到控制台（CLAUDE_STREAM_TO_CONSOLE）",
    )
    claude_verbose: bool = Field(
        default=False,
        description="为 Claude CLI 追加 --verbose，输出更多调试信息（CLAUDE_VERBOSE）",
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
    skip_claude: bool = Field(False, description="Skip Claude CLI; write stub JSON for pipeline smoke tests")
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
