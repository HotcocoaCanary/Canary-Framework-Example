"""The ledger the batches are posted into.

记账的那一本。它是这条流水线的终点，也是"失败有两种"的地方：

* 行级的拒收（账号为空、金额为 0）——这一行不要，任务照样完成；
* 账户被冻结——整批退回去重投，重投到上限才算失败。

两种失败在停机的时候表现不同，所以值得分开。
"""

from __future__ import annotations

from collections import defaultdict

from canary_framework import Canary

from pipeline.jobs import Row


class Rejected(Exception):
    """This row will never be accepted —— 行级拒收，不重试。"""


class AccountFrozen(Exception):
    """This account is frozen right now —— 批级失败，可重试。"""


class Ledger(Canary):
    """Balances, postings and the frozen set.

    余额、流水、冻结名单。状态在 ``__init__`` 里建：它不是"要回收的资源"，所以重启之后
    还在——这正是想要的，重启不该丢账。
    """

    balances: dict[str, int]
    postings: list[tuple[str, int, str]]
    frozen: set[str]

    def __init__(self) -> None:
        self.balances = defaultdict(int)
        self.postings = []
        self.frozen = set()

    def post(self, row: Row) -> None:
        if not row.account or row.amount_cents == 0:
            raise Rejected(f"{row.account or '<空账号>'}: {row.amount_cents}")
        if row.account in self.frozen:
            raise AccountFrozen(row.account)
        self.balances[row.account] += row.amount_cents
        self.postings.append((row.account, row.amount_cents, row.ref))

    def freeze(self, account: str) -> None:
        self.frozen.add(account)

    def unfreeze(self, account: str) -> None:
        self.frozen.discard(account)

    def summary(self) -> dict[str, object]:
        return {
            "accounts": len(self.balances),
            "postings": len(self.postings),
            "frozen": sorted(self.frozen),
            "total_cents": sum(self.balances.values()),
        }
