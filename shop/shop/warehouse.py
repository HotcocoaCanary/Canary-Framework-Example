"""Two warehouses: one class, two configurations, two units.

两个仓库。同一组行为、两套取值，所以是**一个基类加两个子类**，各自依赖自己那份配置。

基类给一条默认依赖（``settings = dep(WarehouseSettings)``），子类换掉它——依赖和钩子一样
按**属性名**解析，所以基类那条边随覆盖消失：``WarehouseSettings`` 本身不会被构造。
上一轮不是这样的，当时依赖按类型收集，基类那条边会一起成立，只能把基类写成光注解。
"""

from __future__ import annotations

from canary_framework import Canary, dep

from shop.settings import (
    MainWarehouseSettings,
    OverflowWarehouseSettings,
    WarehouseSettings,
)


class Warehouse(Canary):
    """What a warehouse can tell you. 子类换掉这条默认依赖，换成自己那份配置。"""

    settings = dep(WarehouseSettings)

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
