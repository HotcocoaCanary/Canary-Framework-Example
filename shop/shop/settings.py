"""Three settings units: the shop, the payment file, and one warehouse config twice.

三份配置，压的是 ``library`` 只用一份时看不到的三件事：

**多份配置 = 多个单元。** ``ShopSettings`` 读 ``.env``，``PaymentSettings`` 读
``.env`` 加 ``.env.payment``（支付的密钥在另一份文件里，权限不同）。谁要用谁写
``dep(...)``，整张图各自共享一个实例。

**配置可以有依赖与钩子。** ``PaymentSettings`` 依赖 ``Vault``，``@init`` 里补上
``api_key``。``dep()`` 写在模型里不会被当成字段，这是 ``config`` 扩展包唯一替 pydantic
做的配置。

**同一份配置的多个实例 = 多个子类。** 两个仓库是同一组字段、两套取值，于是
``WarehouseSettings`` 出两个子类，各自只覆盖 ``env_prefix``；``model_config`` 会与基类的
合并，所以 ``env_file`` 不用重写。
"""

from __future__ import annotations

from canary_framework import dep, init
from canary_framework.config import Settings
from pydantic_settings import SettingsConfigDict

from shop.vault import Vault


class ShopSettings(Settings):
    """``SHOP_*`` —— 店名与算钱的规则。"""

    model_config = SettingsConfigDict(env_file=".env", env_prefix="SHOP_", extra="ignore")

    store_name: str = "青瓷商城"
    tax_rate: float = 0.06
    vip_discount: float = 0.1
    currency: str = "CNY"


class PaymentSettings(Settings):
    """``PAY_*`` —— 两份文件，加一个依赖。"""

    model_config = SettingsConfigDict(
        env_file=(".env", ".env.payment"), env_prefix="PAY_", extra="ignore"
    )

    vault = dep(Vault)

    provider: str = "alipay"
    #: 支付通道费，万分之几。
    fee_bps: int = 60
    api_key: str = ""

    @init
    def fill_in_key(self) -> None:
        if not self.api_key:
            self.api_key = self.vault.read(self.provider)

    def fee_cents(self, amount_cents: int) -> int:
        return round(amount_cents * self.fee_bps / 10_000)


class WarehouseSettings(Settings):
    """One warehouse's configuration. 子类各给一个 ``env_prefix``。"""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    code: str = "main"
    city: str = "上海"
    #: 当天截单时间，过了就算次日发货。
    cutoff_hour: int = 18


class MainWarehouseSettings(WarehouseSettings):
    """``WH_MAIN_*``"""

    model_config = SettingsConfigDict(env_prefix="WH_MAIN_")

    code: str = "main"
    city: str = "上海"


class OverflowWarehouseSettings(WarehouseSettings):
    """``WH_OVERFLOW_*``"""

    model_config = SettingsConfigDict(env_prefix="WH_OVERFLOW_")

    code: str = "overflow"
    city: str = "嘉兴"
    cutoff_hour: int = 12
