"""Multi-provider LLM factory for LangGraph agents."""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage

from app.config import settings

_JSON_HINT = (
    "You must respond with valid JSON only. "
    "Output a single JSON object matching the required schema."
)


def _provider_name() -> str:
    return (settings.llm_provider or "anthropic").strip().lower()


def _is_bailian_family(provider: str | None = None) -> bool:
    return (provider or _provider_name()).lower() in (
        "bailian",
        "dashscope",
        "qwen",
        "aliyun",
    )


def _bailian_api_key() -> str | None:
    return settings.bailian_api_key or settings.dashscope_api_key or settings.openai_api_key


def _apply_stop_limits(kwargs: dict[str, Any]) -> dict[str, Any]:
    """按需注入 max_tokens 与 stop 止损参数。

    默认（未配置 LLM_MAX_TOKENS / LLM_STOP）不改动 kwargs，行为与原来完全一致；
    仅当 .env 显式设置时才生效（VM 特殊处理）。
    """
    if settings.llm_max_tokens:
        kwargs["max_tokens"] = settings.llm_max_tokens
    raw = settings.llm_stop or ""
    stop = [
        s.replace("\\n", "\n").replace("\\t", "\t").replace("\\r", "\r")
        for s in raw.split(",")
        if s
    ]
    if stop:
        kwargs["stop"] = stop
    return kwargs


def _apply_thinking_mode(kwargs: dict[str, Any]) -> dict[str, Any]:
    """按需注入 OpenAI/vLLM 的 Qwen thinking 配置。"""
    if settings.llm_enable_thinking is None:
        return kwargs

    extra_body = dict(kwargs.get("extra_body") or {})
    chat_template_kwargs = dict(extra_body.get("chat_template_kwargs") or {})
    chat_template_kwargs["enable_thinking"] = settings.llm_enable_thinking
    extra_body["chat_template_kwargs"] = chat_template_kwargs
    kwargs["extra_body"] = extra_body
    return kwargs


@lru_cache(maxsize=8)
def get_chat_model(
    *,
    provider: str | None = None,
    model: str | None = None,
    temperature: float | None = None,
) -> BaseChatModel:
    """
    Return a LangChain chat model for the configured provider.

    Providers:
      - anthropic: ChatAnthropic
      - openai: ChatOpenAI
      - zhipu: ChatOpenAI against Zhipu OpenAI-compatible endpoint
      - bailian / dashscope / qwen: 阿里云百炼 OpenAI 兼容端点
    """
    prov = (provider or _provider_name()).lower()
    model_name = model or settings.llm_model
    temp = settings.llm_temperature if temperature is None else temperature
    max_retries = settings.llm_max_retries

    if prov == "anthropic":
        from langchain_anthropic import ChatAnthropic

        kwargs: dict[str, Any] = {
            "model": model_name,
            "temperature": temp,
            "max_retries": max_retries,
            "timeout": settings.llm_timeout_sec,
            "streaming": settings.llm_streaming,
        }
        if settings.anthropic_api_key:
            kwargs["api_key"] = settings.anthropic_api_key
        return ChatAnthropic(**kwargs)

    if prov == "openai":
        from langchain_openai import ChatOpenAI

        kwargs = {
            "model": model_name,
            "temperature": temp,
            "max_retries": max_retries,
            "timeout": settings.llm_timeout_sec,
            "streaming": settings.llm_streaming,
        }
        if settings.openai_api_key:
            kwargs["api_key"] = settings.openai_api_key
        if settings.openai_base_url:
            kwargs["base_url"] = settings.openai_base_url
        return ChatOpenAI(**_apply_thinking_mode(_apply_stop_limits(kwargs)))

    if prov == "zhipu":
        from langchain_openai import ChatOpenAI

        kwargs = {
            "model": model_name or "glm-4-plus",
            "temperature": temp,
            "max_retries": max_retries,
            "timeout": settings.llm_timeout_sec,
            "streaming": settings.llm_streaming,
            "base_url": settings.zhipu_base_url,
        }
        if settings.zhipu_api_key:
            kwargs["api_key"] = settings.zhipu_api_key
        elif settings.openai_api_key:
            kwargs["api_key"] = settings.openai_api_key
        return ChatOpenAI(**_apply_stop_limits(kwargs))

    if _is_bailian_family(prov):
        from langchain_openai import ChatOpenAI

        # qwen3.5-plus 默认开启思考模式，会影响 structured output；关闭思考以确保稳定 JSON
        kwargs = {
            "model": model_name or "qwen3.5-plus",
            "temperature": temp,
            "max_retries": max_retries,
            "timeout": settings.llm_timeout_sec,
            "streaming": settings.llm_streaming,
            "base_url": settings.bailian_base_url,
            "extra_body": {"enable_thinking": False},
        }
        api_key = _bailian_api_key()
        if api_key:
            kwargs["api_key"] = api_key
        return ChatOpenAI(**_apply_stop_limits(kwargs))

    raise ValueError(
        f"未知 LLM_PROVIDER={prov!r}，支持：anthropic | openai | zhipu | bailian"
    )


def _message_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and item.get("type") == "text":
                parts.append(str(item.get("text") or ""))
        return "\n".join(parts)
    return str(content or "")


def _ensure_json_word_in_messages(messages: Any) -> Any:
    """
    DashScope requires the literal word 'json' in messages when using
    response_format=json_object (used by with_structured_output).
    """
    if isinstance(messages, str):
        if "json" not in messages.lower():
            return messages + f"\n\n{_JSON_HINT}"
        return messages

    if isinstance(messages, tuple) and len(messages) == 2 and isinstance(messages[0], str):
        # ("system"|"human", content) single pair — callers usually pass a list
        role, content = messages
        text = _message_text(content)
        if "json" not in text.lower():
            return [(role, text + f"\n\n{_JSON_HINT}")]
        return [messages]

    if not isinstance(messages, list):
        return messages

    blob = ""
    for m in messages:
        if isinstance(m, BaseMessage):
            blob += _message_text(m.content)
        elif isinstance(m, tuple) and len(m) >= 2:
            blob += _message_text(m[1])
        elif isinstance(m, dict):
            blob += _message_text(m.get("content"))
        else:
            blob += str(m)
    if "json" in blob.lower():
        return messages

    out = list(messages)
    # Prefer augmenting the last human / user message
    for i in range(len(out) - 1, -1, -1):
        m = out[i]
        if isinstance(m, HumanMessage):
            out[i] = HumanMessage(content=_message_text(m.content) + f"\n\n{_JSON_HINT}")
            return out
        if isinstance(m, tuple) and len(m) >= 2 and str(m[0]).lower() in ("human", "user"):
            out[i] = (m[0], _message_text(m[1]) + f"\n\n{_JSON_HINT}")
            return out
        if isinstance(m, dict) and str(m.get("role", "")).lower() in ("user", "human"):
            out[i] = {**m, "content": _message_text(m.get("content")) + f"\n\n{_JSON_HINT}"}
            return out

    out.append(("human", _JSON_HINT))
    return out


class _BailianStructuredRunnable:
    """Wrap structured LLM so Bailian prompts always contain the word json."""

    def __init__(self, bound: Any) -> None:
        self._bound = bound

    def invoke(self, input: Any, config: Any = None, **kwargs: Any) -> Any:
        return self._bound.invoke(_ensure_json_word_in_messages(input), config=config, **kwargs)

    async def ainvoke(self, input: Any, config: Any = None, **kwargs: Any) -> Any:
        return await self._bound.ainvoke(
            _ensure_json_word_in_messages(input), config=config, **kwargs
        )


def structured_llm(schema: type, *, model: BaseChatModel | None = None):
    """Return LLM bound to a Pydantic structured output schema."""
    llm = model or get_chat_model()

    # 百炼对 json_object/json_schema 常返回空对象；function_calling 更可靠。
    # 同时仍注入 json 提示，兼容部分模型回退到 json_object 的情况。
    if _is_bailian_family():
        try:
            bound = llm.with_structured_output(schema, method="function_calling")
        except Exception:  # noqa: BLE001
            bound = llm.with_structured_output(schema, method="json_mode")
        return _BailianStructuredRunnable(bound)

    try:
        return llm.with_structured_output(schema, method="json_schema")
    except Exception:  # noqa: BLE001
        return llm.with_structured_output(schema)


def should_skip_agent() -> bool:
    """True when SKIP_AGENT or legacy SKIP_CLAUDE is set."""
    return bool(settings.skip_agent or settings.skip_claude)


def clear_chat_model_cache() -> None:
    """Clear cached chat models (call after env/config reload)."""
    get_chat_model.cache_clear()
