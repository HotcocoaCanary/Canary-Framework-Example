"""共享 fixture：装配真实 AppModule。

注意：TestClient 不使用 with 上下文（不触发 lifespan/startup），
测试因此不依赖数据库与网络。
"""

import pytest
from starlette.testclient import TestClient

from main import AppModule


@pytest.fixture(scope="session")
def app():
    instance = AppModule()
    instance.init()
    return instance


@pytest.fixture(scope="session")
def client(app):
    # raise_server_exceptions=False：handler 内未处理异常表现为 500 响应而非测试崩溃
    return TestClient(app.asgi_app, raise_server_exceptions=False)
