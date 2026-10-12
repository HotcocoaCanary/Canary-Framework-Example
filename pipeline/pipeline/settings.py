"""Settings for the whole pipeline.

一份配置，一个单元。两条通道的消费者数量写成 ``dict``，这样"同一种东西的多个实例"
（``FastLane`` / ``BulkLane``，见 ``workers.py``）各读自己那一项，而不必为每条通道加一个
字段。
"""

from __future__ import annotations

from canary_framework.config import Settings
from pydantic_settings import SettingsConfigDict


class PipelineSettings(Settings):
    """``PIPE_*`` —— 端口、通道、停机预算。"""

    model_config = SettingsConfigDict(env_file=".env", env_prefix="PIPE_", extra="ignore")

    host: str = "0.0.0.0"
    port: int = 8030

    #: 每条通道几个消费者。
    lane_workers: dict[str, int] = {"fast": 2, "bulk": 1}
    #: 每条通道的队列上限，满了就 429——接入口不排无限长的队。
    queue_size: int = 256
    #: 超过这么多行就走 bulk 通道（提交时没有显式指定通道的话）。
    bulk_threshold: int = 50

    #: 停机第二步最多等多久把在途任务做完。
    drain_timeout_seconds: float = 20.0
    #: 可重试的失败（账户冻结之类）最多重投几次。
    max_attempts: int = 3
    #: 每行记账的模拟耗时。默认 0；测试把它调大来造"在途任务"。
    row_seconds: float = 0.0
