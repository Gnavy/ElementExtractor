from typing import Optional

from fastapi import Header, HTTPException, Security
from fastapi.security import APIKeyHeader

from app.config import settings

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)
_bearer_prefix = "bearer "


def _extract_bearer_key(authorization: Optional[str]) -> Optional[str]:
    if not authorization:
        return None
    value = authorization.strip()
    if value.lower().startswith(_bearer_prefix):
        return value[len(_bearer_prefix) :].strip() or None
    return None


async def verify_api_key(
    x_api_key: Optional[str] = Security(_api_key_header),
    authorization: Optional[str] = Header(None),
) -> str:
    """校验对外 API Key（X-API-Key 或 Authorization: Bearer）。"""
    if not settings.api_auth_enabled:
        return "auth-disabled"

    if not settings.api_keys:
        raise HTTPException(
            status_code=503,
            detail="API authentication is not configured (API_KEYS is empty)",
        )

    candidate = (x_api_key or "").strip() or _extract_bearer_key(authorization)
    if not candidate or candidate not in settings.api_keys:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")
    return candidate
