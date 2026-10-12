"""The shutdown journal.

停机日志。两步停机的每一步都往这里记一条，于是"顺序对不对"这件事既能在运维日志里看到，
也能在测试里断言——而不是靠读代码推。
"""

from __future__ import annotations

from canary_framework import Canary


class Journal(Canary):
    """An ordered list of what the lifecycle did.

    生命周期做过的事，按顺序。
    """

    entries: list[str]

    def __init__(self) -> None:
        self.entries = []

    def note(self, step: str) -> None:
        self.entries.append(step)

    def steps(self, kind: str) -> list[str]:
        return [entry for entry in self.entries if entry.startswith(kind)]
