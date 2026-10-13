"""The product catalogue —— a unit whose state is loaded at ``@start``.

商品目录。它的数据在 ``@start`` 里装载、在 ``@stop`` 里卸掉——这在迁移场景里很重要：
``mount()`` 只会把路由挂上去，**没有反操作**，所以一旦图停了，应用对象上那些路由还在，
但它们背后的单元已经空了。这个单元因此直说"目录没装载"，而不是悄悄返回空列表。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from canary_framework import Canary, dep, start, stop

from shop.settings import ShopSettings


class CatalogNotLoaded(RuntimeError):
    """The catalogue is not loaded —— 图没启动，或者已经停了。"""


@dataclass(slots=True)
class Product:
    sku: str
    title: str
    list_cents: int
    #: 仓库代号 → 件数。
    stock: dict[str, int] = field(default_factory=dict)

    def view(self) -> dict[str, object]:
        return {
            "sku": self.sku,
            "title": self.title,
            "list_cents": self.list_cents,
            "stock": dict(self.stock),
            "on_hand": sum(self.stock.values()),
        }


#: 迁移期的"数据库"：老系统里这是一张表，这里就是几行常量。
SEED = [
    ("QC-1001", "青瓷茶杯", 12800, {"main": 40, "overflow": 10}),
    ("QC-1002", "青瓷茶壶", 46800, {"main": 12, "overflow": 0}),
    ("QC-2001", "竹制茶盘", 23800, {"main": 0, "overflow": 25}),
]


class Catalog(Canary):
    """Products, loaded while the graph runs.

    商品。图跑着的时候才有。
    """

    config = dep(ShopSettings)

    products: dict[str, Product]
    loaded: bool = False

    @start
    async def load(self) -> None:
        self.products = {
            sku: Product(sku=sku, title=title, list_cents=cents, stock=dict(stock))
            for sku, title, cents, stock in SEED
        }
        self.loaded = True

    @stop
    async def unload(self) -> None:
        self.products = {}
        self.loaded = False

    def require(self, sku: str) -> Product:
        if not self.loaded:
            raise CatalogNotLoaded("目录未装载：这张图没有在运行")
        product = self.products.get(sku)
        if product is None:
            raise KeyError(sku)
        return product

    def all(self) -> list[Product]:
        if not self.loaded:
            raise CatalogNotLoaded("目录未装载：这张图没有在运行")
        return sorted(self.products.values(), key=lambda item: item.sku)
