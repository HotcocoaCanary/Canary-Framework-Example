"""The fourth and fifth phases: ``@serving`` and its leave, ``@quiesce``.

第四、第五个阶段。守护进程的停机不是一步：**先停止接受新工作，再把在途的做完，最后才
回收资源**。框架给的两条规则正好是互为镜像的两个方向：

* ``enter`` —— **依赖在前**。适合"准备资源"：队列先有，消费者才起。
* ``leave`` —— **本单元在前**。适合"停止接受"：根先关闸，再往下轮到各条通道排空。

所以"关闸"这一步必须是一次 ``leave``，而不是再加一个 ``enter``：如果写成
``Phase("quiesce", after=start)`` 然后 ``enter`` 它，顺序会反过来——队列（被依赖的一方）
先关，消费者后知道，这正是不想要的。

于是声明一个阶段对（框架没有要求它们怎么配对，``Phase`` 的 ``leave`` 参数就是全部）::

    quiesce = Phase("quiesce")
    serving = Phase("serving", after=start, leave=quiesce)

``enter(root, serving)`` 在整张图 ``@start`` 完成之后推进，``@serving`` 钩子在这里登记
"我开始接活了"；``leave(root, serving)`` 运行 ``@quiesce`` 钩子，本单元在前。

``after=start`` 是一道栅栏：某个单元的 ``@start`` 没跑完就进入 ``serving``，直接
``LifecycleError``，阶段不会被静默跳过。

离开 ``serving`` **不会**动 ``start``：``start`` 是它的前驱，不是它的后继。所以"关闸"之后
整张图仍然是启动着的，``stop()` 照常把 ``@stop`` 跑完。
"""

from canary_framework import Phase, start

#: 停止接受新工作、把在途的做完。``serving`` 的离开阶段。
quiesce = Phase("quiesce")

#: 全图 ``@start`` 完成之后进入：从这一刻起进程对外接活。
serving = Phase("serving", after=start, leave=quiesce)
