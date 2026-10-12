"""Pricing —— the rules unit, and the router unit on top of it.

算钱。规则是一个普通单元（两份配置都要读），路由单元在它之上。

这是迁移里最舒服的一类模块：老代码里它是一个带 ``Depends(get_settings)`` 的函数，
搬过来之后"要用什么"写在类上，接口方法直接用 ``self``。
"""

from __future__ import annotations

from canary_framework import Canary, dep
from canary_framework.web.asgi.app import Router, get
from pydantic import BaseModel

from shop.catalog import Catalog
from shop.settings import PaymentSettings, ShopSettings


class Quote(BaseModel):
    """A price breakdown."""

    sku: str
    title: str
    level: str
    list_cents: int
    discount_cents: int
    tax_cents: int
    payment_fee_cents: int
    total_cents: int
    currency: str
    provider: str


class PricingRules(Canary):
    """Discount, tax and the payment channel fee.

    折扣、税、通道费。两份配置各管一段。
    """

    shop = dep(ShopSettings)
    payment = dep(PaymentSettings)
    catalog = dep(Catalog)

    def quote(self, sku: str, level: str = "normal") -> Quote:
        product = self.catalog.require(sku)
        discount = round(product.list_cents * self.shop.vip_discount) if level == "vip" else 0
        net = product.list_cents - discount
        tax = round(net * self.shop.tax_rate)
        fee = self.payment.fee_cents(net + tax)
        return Quote(
            sku=product.sku,
            title=product.title,
            level=level,
            list_cents=product.list_cents,
            discount_cents=discount,
            tax_cents=tax,
            payment_fee_cents=fee,
            total_cents=net + tax + fee,
            currency=self.shop.currency,
            provider=self.payment.provider,
        )


class PricingApi(Router, prefix="/v2/pricing"):
    """``/pricing/{sku}``"""

    rules = dep(PricingRules)

    @get("/{sku}")
    async def quote(self, sku: str, level: str = "normal") -> Quote:
        return self.rules.quote(sku, level)
