from starlette.requests import Request
from fastapi import HTTPException

from src.common.types import UserContext
from app import AuthService


async def get_current_user(request: Request, auth_service: AuthService) -> UserContext:
    token = request.headers.get("Authorization", "").removeprefix("Bearer ")
    product_id = request.headers.get("PRODUCT-ID", "")
    tenant_id = request.headers.get("TENANT-ID", "")

    if not token:
        raise HTTPException(status_code=401, detail="未登录")

    return await auth_service.get_current_user(token, product_id, tenant_id)
