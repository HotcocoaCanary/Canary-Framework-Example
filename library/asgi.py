"""给原生 ASGI 服务器的入口 —— ``uvicorn asgi:app``。

应用单元**自己就是一个 ASGI 应用**，所以不需要我们的服务器单元也能跑：

    uv run uvicorn asgi:app --port 8012 --reload

这时驱动生命周期的是 uvicorn 的 lifespan 消息：启动时这个单元连同它的依赖按序
``init`` / ``start``（数据库、模型都就位），停止时逆序回收；启动失败的话 uvicorn 收到
``lifespan.startup.failed`` 并退出。

和 ``main.py`` 的区别只是"谁监听"：

* ``main.py`` —— 我们的 ``Server`` 单元监听，进程的生命周期归 Canary，可以一个进程多个
  端口（见 ``relay`` 场景）；
* 这里 —— uvicorn 监听，``--reload`` / ``--workers`` 这些都照用，代价是一个进程一个应用、
  一个端口。

两种都只是 ASGI 的两侧各自守协议，所以随便组合。
"""

from app.api.canary import LibraryApi

#: uvicorn 要的那个 ASGI 应用。
app = LibraryApi()
