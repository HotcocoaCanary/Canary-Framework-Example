"""Request and response models —— shared by both HTTP layers.

请求与响应模型，**两层 HTTP 共用**。两个包都把形参与返回值交给 pydantic，所以这些就是
最普通的 pydantic 模型，一个字都不用改。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class Heartbeat(BaseModel):
    """What a device reports every few seconds."""

    kind: str = Field(default="pos", description="设备类型：pos / scale / sensor …")
    metrics: dict[str, float] = Field(default_factory=dict)


class DeviceEvent(BaseModel):
    """Something that happened on a device."""

    kind: str = Field(description="事件类型：paper_out / tamper / restart …")
    payload: dict[str, Any] = Field(default_factory=dict)


class DeviceView(BaseModel):
    """A device as the API shows it."""

    device_id: str
    kind: str
    status: str
    last_seen: str | None
    heartbeats: int
    metrics: dict[str, float]


class Accepted(BaseModel):
    """The answer to an accepted event."""

    accepted: bool = True
    type: str
    device_id: str
