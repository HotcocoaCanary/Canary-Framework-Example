"""Two warehouses: one class, two configurations, two units.

两个仓库。同一组行为、两套取值，所以是**一个基类加两个子类**，各自依赖自己那份配置。

基类里**没有** ``settings = dep(...)``，只有一个类型注解。写了的话基类那条边也会成立
（依赖按类型收集，不像钩子那样按属性名覆盖），``WarehouseSettings`` 会被白构造一份。
这一条在 ``pipeline`` 场景里有最小复现。
"""

from __future__ import annotations

from canary_framework import Canary, dep

from shop.settings import (
    MainWarehouseSettings,
    OverflowWarehouseSettings,
    WarehouseSettings,
)


class Warehouse(Canary):
    """What a warehouse can tell you. 由子类给出它读哪份配置。"""

    settings: WarehouseSettings

    @property
    def code(self) -> str:
        return self.settings.code

    def view(self) -> dict[str, object]:
        return {
            "code": self.settings.code,
            "city": self.settings.city,
            "cutoff_hour": self.settings.cutoff_hour,
        }

    def ships_today(self, hour: int) -> bool:
        return hour < self.settings.cutoff_hour


class MainWarehouse(Warehouse):
    settings = dep(MainWarehouseSettings)


class OverflowWarehouse(Warehouse):
    settings = dep(OverflowWarehouseSettings)
