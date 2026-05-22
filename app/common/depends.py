from fastapi import Request, HTTPException

from app.common.types import UserContext
from app.shared.pigx.service.auth_service import AuthService


async def get_current_user(request: Request) -> UserContext:
    token = request.headers.get("Authorization", "").removeprefix("Bearer ")
    product_id = request.headers.get("PRODUCT-ID", "")
    tenant_id = request.headers.get("TENANT-ID", "")

    if not token:
        raise HTTPException(status_code=401, detail="未登录")

    registry = request.app.state.cf_registry
    auth_service: AuthService = registry.get_instance(AuthService)
    return await auth_service.get_current_user(token, product_id, tenant_id)
