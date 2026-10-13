"""OpenAPI, written from the application unit's endpoint table.

``canary_framework.web.asgi.app`` 不生成 OpenAPI，但它公开了接口表：``App.endpoints`` 里每个
``Endpoint`` 说明一个接口的方法、完整路径、形参各从哪里取值、返回注解。把类型翻成 JSON Schema
是 pydantic 的本职，所以剩下的只是这一个函数——它不属于框架，想加 ``tags``、安全方案、错误
响应就直接改这里。

对照 ``app/api/fastapi/``：那一层的 ``/openapi.json`` 是 FastAPI 自带的。
"""

from __future__ import annotations

import inspect
from collections.abc import Iterable
from typing import Any

from canary_framework.web.asgi.app import Endpoint, Response
from pydantic import TypeAdapter


def openapi(endpoints: Iterable[Endpoint], title: str, version: str = "0.1.0") -> dict[str, Any]:
    """An OpenAPI 3.1 document for *endpoints*.

    每个接口翻成一个 operation：路径与查询参数进 ``parameters``，``body`` 进 ``requestBody``，
    返回注解进 ``responses``；模型的 schema 收进 ``components.schemas``，别处用 ``$ref`` 指过去。
    """
    schemas: dict[str, Any] = {}

    def schema(annotation: Any, mode: Any = "validation") -> dict[str, Any]:
        found = TypeAdapter(annotation).json_schema(
            ref_template="#/components/schemas/{model}", mode=mode
        )
        schemas.update(found.pop("$defs", {}))
        return found

    paths: dict[str, Any] = {}
    for endpoint in endpoints:
        operation: dict[str, Any] = {"operationId": endpoint.name}
        if endpoint.call.__doc__:
            operation["summary"] = inspect.cleandoc(endpoint.call.__doc__).splitlines()[0]
        operation["parameters"] = [
            {"name": p.name, "in": p.source, "required": p.required, "schema": schema(p.annotation)}
            for p in endpoint.params
            if p.source in ("path", "query")
        ]
        for p in endpoint.params:
            if p.source == "body" and p.annotation is not bytes:
                content = {"application/json": {"schema": schema(p.annotation)}}
                operation["requestBody"] = {"required": p.required, "content": content}
        if endpoint.returns is type(None):
            status = 204 if endpoint.status == 200 else endpoint.status
            operation["responses"] = {str(status): {"description": "No Content"}}
        elif endpoint.returns in (Any, Response):
            operation["responses"] = {str(endpoint.status): {"description": "OK"}}
        else:
            content = {"application/json": {"schema": schema(endpoint.returns, "serialization")}}
            operation["responses"] = {
                str(endpoint.status): {"description": "OK", "content": content}
            }
        paths.setdefault(endpoint.path, {})[endpoint.method.lower()] = operation
    return {
        "openapi": "3.1.0",
        "info": {"title": title, "version": version},
        "paths": paths,
        "components": {"schemas": schemas},
    }
