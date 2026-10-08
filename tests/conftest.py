"""测试全局状态隔离。

⚠️ 背景：``kg_store.NODE_TYPES`` 是**可增长**的模块级全局注册表，导入外部
图谱（data/csv-edu 的 ``ai`` / ``education`` 等）会调 :func:`register_type`
往里加键，而这个副作用**不随临时库销毁**。

于是同进程跑全量测试会串味：``test_kg_store`` 断言
``node_files == len(NODE_TYPES)``、并遍历 ``NODE_TYPES`` 检查
``by_type[t] > 0``，被前面的文件注册成 21 项后立刻失败——而**单独跑那个
文件是通过的**，只在全量跑时暴露。这不是新加测试造成的：
``test_kg_weighted`` 的 module 级 ``edu`` fixture 在播种时就会污染它。

⚠️ 关键：还原必须发生在**每个测试进场前**，而不是上一个测试结束后。
module 级 fixture（如 ``edu``）在首个测试之前就建好，那一刻的污染连
「结束后还原」也拦不住——必须在它被创建前就把注册表擦干净。
"""

import sys
from pathlib import Path

import pytest

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))

# 会话初始的干净类型表。模块导入期就取一次快照（那时还没任何测试跑过），
# 之后每个测试进场前都恢复成这份。
_PRISTINE_NODE_TYPES = None


def _capture_pristine():
    global _PRISTINE_NODE_TYPES
    if _PRISTINE_NODE_TYPES is None:
        from kg_store import NODE_TYPES
        _PRISTINE_NODE_TYPES = dict(NODE_TYPES)
    return _PRISTINE_NODE_TYPES


@pytest.fixture(scope='session', autouse=True)
def _pristine_node_types():
    """会话开始时快照（务必早于任何 fixture 建库），结束时还原。"""
    saved = _capture_pristine()
    yield
    from kg_store import NODE_TYPES
    NODE_TYPES.clear()
    NODE_TYPES.update(saved)


@pytest.fixture(autouse=True)
def _isolate_node_types(_pristine_node_types):
    """每个测试**进场前**恢复注册表，保证「原神图谱」类测试互不干扰。

    ⚠️ 只在**进场前**恢复、**不在出场后**清空：导入外部图谱的测试
    （test_kg_weighted / test_kg_bilingual）本身要断言 ``ai`` / ``education``
    已注册，若出场后清掉，它们自己就失败了。
    于是形成「谁污染、谁负责用到，轮到下一批测试时先擦干净」的秩序：
    外部图谱测试可以放心注册类型，原神测试永远只看到 12 种内置类型。
    """
    from kg_store import NODE_TYPES
    saved = _capture_pristine()
    NODE_TYPES.clear()
    NODE_TYPES.update(saved)
    yield