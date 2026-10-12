"""Two lanes: the same thing twice, as two subclasses.

两条通道：**同一种东西的两个实例**。框架里"每个类型一个实例"，所以多一个实例就是多一个
子类——不需要工厂，也不需要给实例起名字，``dep(FastLane)`` 和 ``dep(BulkLane)`` 自己就是
那个名字。

代价是两条通道的差异只能写在类上（``lane`` 决定它读配置里的哪一项）。如果通道数要由配置
决定（"每个租户一条"），这条路就走不通了——那需要运行期构造实例，而图是静态的。这是框架
的一个明确取舍，不是疏漏。
"""

from __future__ import annotations

from canary_framework import dep

from pipeline.queue import JobQueue
from pipeline.workers import WorkerPool


class FastQueue(JobQueue):
    """小批量、要快的那条。"""


class BulkQueue(JobQueue):
    """大批量、可以慢的那条。"""


class FastLane(WorkerPool):
    lane = "fast"
    queue = dep(FastQueue)


class BulkLane(WorkerPool):
    lane = "bulk"
    queue = dep(BulkQueue)
