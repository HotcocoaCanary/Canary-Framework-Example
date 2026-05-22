from typing import Optional

from pydantic import BaseModel


class UserContext(BaseModel):
    user_id: str
    username: str
    tenant_id: Optional[str] = None
    roles: list[str] = []
