from fastapi import HTTPException
from starlette.requests import Request


def parse_pagination(request: Request, default_size: int = 20) -> tuple[int, int]:
    try:
        current = int(request.query_params.get("current", "1"))
    except (ValueError, TypeError):
        raise HTTPException(status_code=422, detail="参数 current 必须为整数")
    try:
        size = int(request.query_params.get("size", str(default_size)))
    except (ValueError, TypeError):
        raise HTTPException(status_code=422, detail="参数 size 必须为整数")
    return current, size
