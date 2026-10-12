"""The intake gate.

接入闸门：一个布尔值加两个方法。它单独成一个单元，是因为**接入口和根单元都要碰它**——
路由单元读它决定要不要收，根单元的 ``@quiesce`` 关它。路由不能依赖根（那是一个环），
所以这件状态要有自己的节点。
"""

from __future__ import annotations

from canary_framework import Canary, start, stop


class Gate(Canary):
    """Whether this process still takes new work.

    本进程还收不收新活。``@start`` 里开闸，所以重启之后它是开的。
    """

    accepting: bool = False

    @start
    async def open(self) -> None:
        self.accepting = True

    @stop
    async def shut(self) -> None:
        """Closed again once the process is down —— 启动失败时也会走到这里。"""
        self.accepting = False

    def close(self) -> None:
        """Close it early, without stopping anything —— 停机第一步调它。"""
        self.accepting = False
