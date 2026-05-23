import logging

import httpx
from fastapi import HTTPException

from app.common.types import UserContext
from cf import service, on_init, on_end, Context

logger = logging.getLogger(__name__)


@service(name="AuthService")
class AuthService:
    @on_init
    def init(self, ctx: Context):
        self._base_url = ctx.config.pigx_base
        self._http_client = httpx.AsyncClient(timeout=10.0)

    @on_end
    async def end(self):
        await self._http_client.aclose()

    async def get_current_user(self, token: str, product_id: str, tenant_id: str) -> UserContext:
        if not self._base_url:
            raise HTTPException(status_code=500, detail="PIGX_BASE 未配置")

        try:
            response = await self._http_client.get(
                f"{self._base_url}/ai-studio-adapter/v1/java-adapter/auth/current-user",
                headers={
                    "Authorization": f"Bearer {token}",
                    "PRODUCT-ID": product_id,
                    "TENANT-ID": tenant_id,
                },
            )
            data = response.json()
            if data.get("code") != 0:
                raise HTTPException(status_code=401, detail="认证失败")

            user_data = data["data"]
            return UserContext(
                user_id=user_data.get("userId", ""),
                username=user_data.get("username", ""),
                tenant_id=user_data.get("tenantId"),
                roles=user_data.get("authorities", []),
            )
        except HTTPException:
            raise
        except Exception as e:
            logger.exception("认证请求异常: %s", e)
            raise HTTPException(status_code=401, detail="认证失败")
