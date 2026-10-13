"""三份配置：各自的前缀、各自的文件，以及一份配置的两个实例。

``library`` 只有一份配置，所以这几件事在那边看不到。
"""

from __future__ import annotations

from canary_framework.test import running, unit

from shop.graph import ShopGraph
from shop.settings import (
    MainWarehouseSettings,
    OverflowWarehouseSettings,
    PaymentSettings,
    ShopSettings,
    WarehouseSettings,
)
from shop.vault import Vault


class FakeVault(Vault):
    """A double for the key store —— 替身必须是被替换类型的实例。"""

    def read(self, name: str) -> str:
        return f"fake-{name}"


def test_each_settings_unit_reads_its_own_prefix(monkeypatch) -> None:
    monkeypatch.setenv("SHOP_STORE_NAME", "白瓷商城")
    monkeypatch.setenv("SHOP_TAX_RATE", "0.13")
    monkeypatch.setenv("PAY_PROVIDER", "wechat")
    monkeypatch.setenv("PAY_FEE_BPS", "38")

    shop = ShopSettings()
    payment = PaymentSettings()
    assert (shop.store_name, shop.tax_rate) == ("白瓷商城", 0.13)
    assert (payment.provider, payment.fee_bps) == ("wechat", 38)


def test_a_subclass_only_overrides_the_prefix() -> None:
    """``model_config`` 与基类的合并，所以 ``env_file`` 不用在子类里重写。"""
    assert WarehouseSettings.model_config["env_file"] == ".env"
    assert MainWarehouseSettings.model_config["env_file"] == ".env"
    assert MainWarehouseSettings.model_config["env_prefix"] == "WH_MAIN_"
    assert OverflowWarehouseSettings.model_config["env_prefix"] == "WH_OVERFLOW_"
    # ``config`` 扩展包塞进去的那一条（让 dep() 不被当成字段）也还在
    assert MainWarehouseSettings.model_config["ignored_types"]


def test_the_two_warehouse_configs_read_their_own_variables(monkeypatch) -> None:
    monkeypatch.setenv("WH_MAIN_CITY", "苏州")
    monkeypatch.setenv("WH_OVERFLOW_CITY", "湖州")
    monkeypatch.setenv("WH_OVERFLOW_CUTOFF_HOUR", "9")

    assert MainWarehouseSettings().city == "苏州"
    overflow = OverflowWarehouseSettings()
    assert (overflow.city, overflow.cutoff_hour) == ("湖州", 9)
    # 前缀不串门
    assert MainWarehouseSettings().cutoff_hour == 18


def test_a_dependency_declared_in_a_model_is_not_a_field() -> None:
    assert "vault" not in PaymentSettings.model_fields
    assert set(PaymentSettings.model_fields) == {"provider", "fee_bps", "api_key"}


async def test_a_settings_unit_can_fill_a_field_from_its_dependency() -> None:
    """配置自己有依赖与钩子。时序：依赖的 ``@init`` 早于本单元的 ``@init``。"""
    async with running(PaymentSettings, {Vault: FakeVault()}) as payment:
        assert payment.api_key == "fake-alipay"


async def test_an_explicit_key_is_left_alone(monkeypatch) -> None:
    monkeypatch.setenv("PAY_API_KEY", "from-env")
    async with running(PaymentSettings, {Vault: FakeVault()}) as payment:
        assert payment.api_key == "from-env"


async def test_the_whole_graph_shares_one_instance_of_each(monkeypatch) -> None:
    monkeypatch.setenv("SHOP_VIP_DISCOUNT", "0.2")
    async with running(ShopGraph) as root:
        assert root.rules.shop is unit(root, ShopSettings)
        assert root.rules.payment is unit(root, PaymentSettings)
        quote = root.rules.quote("QC-1001", "vip")
        assert quote.discount_cents == 2560  # 20%
