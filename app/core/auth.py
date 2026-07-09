import hmac
from typing import Annotated

from fastapi import Header, HTTPException

from app.core.config import API_KEY


def _bearer_token(authorization: str | None) -> str | None:
    if not authorization:
        return None

    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        return None
    return token.strip()


def require_api_key(
    x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
    authorization: Annotated[str | None, Header()] = None,
) -> None:
    if not API_KEY:
        raise HTTPException(status_code=503, detail="api key authentication is not configured")

    supplied_key = x_api_key or _bearer_token(authorization)
    if not supplied_key or not hmac.compare_digest(supplied_key, API_KEY):
        raise HTTPException(
            status_code=401,
            detail="invalid api key",
            headers={"WWW-Authenticate": "ApiKey"},
        )
