"""The fourth phase: ``@launch``.

守护进程需要一个"全图都起来之后"的位置——调度器必须等所有单元注册完作业才能开循环。
``@start`` 给不了这个位置：推进沿依赖向下，依赖的 ``@start`` 必然早于依赖者，而调度器
是被依赖的那一方，反而最先跑。

0.9.x 里只能绕：把 ``start_all()`` 挂在根单元的 ``@on_start`` 上，靠"根排在拓扑序最后"
这条没写进文档的性质。0.10.0 的阶段是一等对象，声明第四个阶段即可，不必向框架注册::

    launch = Phase("launch", after=start)

``after=start`` 是一道栅栏：``@launch`` 在某个单元上运行之前，该单元的 ``@start``
必须已经完成，否则抛 ``LifecycleError``——阶段不会被静默跳过。

推进它的是 ``TelemetryDaemon.start()``，见 ``daemon.py``。
"""

from canary_framework import Phase, start

#: 全图 ``@start`` 完成之后才推进的阶段——后台循环在这里开起来。
launch = Phase("launch", after=start)
