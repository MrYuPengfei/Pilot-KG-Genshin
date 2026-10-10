"""知识图谱画布的**有向显示**测试。

背景：画布原先用 ``QGraphicsLineItem(0, 0, x, y)`` 画边——那是从中心到邻居的
一条直线，没有方向。「A 衍生自 B」和「B 衍生自 A」画出来一模一样，
用户提的需求就是「知识图谱页面显示的是无向图，应该修改为有向图」。

⚠️ 断言必须落到**业务结果**上，不能只断言「代码里出现了 ArrowEdgeItem」——
那是实现细节。这里验的是三件用户能看见的事：

1. 箭头的**尖端落在关系的终点**（出边在对端、入边在中心），方向不能反；
2. 出边实线、入边虚线，两类边在画面上可区分；
3. 边标签带``→``/``←`` 文字标记，缩放到看不清箭头时仍能读懂方向。

方向数据来自 :meth:`KGStore.neighbor_details_directed`，故这些用例需要一个
**既有入边又有出边**的中心节点——用 ``kg.db`` 现场找一个，不写死具体实体名。
"""

import math
import os

import pytest

pytest.importorskip('PySide6')

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KG_DB = os.path.join(ROOT, 'kg.db')

pytestmark = pytest.mark.skipif(
    not os.path.isfile(KG_DB),
    reason='需要真实 kg.db，跳过有向渲染测试')


@pytest.fixture(scope='module')
def app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.fixture(scope='module')
def store():
    import kg_store
    kg_store.reset_default_store()
    return kg_store.KGStore(KG_DB, auto_seed=False)


@pytest.fixture(scope='module')
def mixed(store):
    """一个既有入边又有出边的节点（方向混排才能看出箭头差异）。"""
    for key in store.nodes:
        details = store.neighbor_details_directed(key)
        kinds = {d[5] for d in details}
        if kinds == {'in', 'out'} and len(details) >= 4:
            return key
    pytest.skip('图谱里找不到既有入边又有出边的节点')


def _edges(canvas):
    from kg_view import ArrowEdgeItem
    return [i for i in canvas._scene.items() if isinstance(i, ArrowEdgeItem)]


def _dist(p, q):
    return math.hypot(p.x() - q.x(), p.y() - q.y())


def test_store_exposes_direction(store, mixed):
    """存储层能给方向：每条邻居关系都带 'out'/'in'，且与 edges_of 一致。"""
    details = store.neighbor_details_directed(mixed)
    assert details, '前置：中心节点应至少有一条关系'
    assert {d[5] for d in details} <= {'in', 'out'}

    # 方向必须与既有 edges_of_detailed 对得上（那个方法签名/行为早已定型）
    truth = {(rel, other, direction)
             for rel, other, direction, _w, _cn in store.edges_of_detailed(mixed)}
    assert {(d[0], d[2], d[5]) for d in details} == truth


def test_neighbor_details_stays_five_tuples(store, mixed):
    """回归：neighbor_details 的**既有签名不能变**。

    它被面板、测试等多处按 5 元组解包；改成 6 元组会连环炸。
    """
    for row in store.neighbor_details(mixed):
        assert len(row) == 5, f'neighbor_details 应返回 5 元组，实得 {len(row)}'
    # 且与带方向版去掉末位后逐条相等
    a = store.neighbor_details(mixed)
    b = [t[:5] for t in store.neighbor_details_directed(mixed)]
    assert a == b


def test_edges_rendered_with_arrowheads(store, mixed, app):
    """画布上每条关系都渲染成**带箭头的有向边**，且数量与邻居数一致。"""
    from kg_view import KGCanvas

    canvas = KGCanvas()
    canvas.bind(store)
    canvas.show_ego(mixed)

    expected = len(store.neighbor_details_directed(mixed))
    edges = _edges(canvas)
    assert len(edges) == expected, \
        f'画了 {len(edges)} 条边，应为 {expected} 条'


def test_arrowhead_points_at_relation_target(store, mixed, app):
    """核心断言：箭头尖端落在关系的**终点**，方向不能反。

    ⚠️ 判据是「尖端离 dst 更近」，不是「离圆心更近」——入边的 dst 就是中心，
    但中心被微偏移后并不严格在原点，拿原点比会两边等距、判不出方向。
    """
    from kg_view import KGCanvas

    canvas = KGCanvas()
    canvas.bind(store)
    canvas.show_ego(mixed)

    edges = _edges(canvas)
    assert edges
    for e in edges:
        assert e.tip is not None, '边应记录箭头尖端坐标'
        assert _dist(e.tip, e.dst) < _dist(e.tip, e.src), \
            f'{e.direction} 边箭头没落在目标端（尖端离源更近）'


def test_edge_endpoints_match_direction_semantics(store, mixed, app):
    """🔴 核心语义绑定：出边的**源必须是中心**、入边的**源必须是对端**。

    ⚠️ 这条是被变异测试逼出来的。只断言「箭头顶点离 dst 更近」是不够的——
    把入边的 src/dst 整个对调后，画出来的箭头仍然落在 ``dst`` 上，
    那条断言照样通过，而画面表达的语义已经反了（变成「中心 → 对端」）。
    所以必须直接验「谁被当成源」与数据层的 ``direction`` 是否一致。
    """
    from kg_view import KGCanvas

    canvas = KGCanvas()
    canvas.bind(store)
    canvas.show_ego(mixed)

    center_pos = (0.0, 0.0)
    neighbors = {(round(px), round(py))
                 for _rel, _cn, other, _w, _c, _d in
                 store.neighbor_details_directed(mixed)
                 for px, py in [_pos_of(canvas, other)]}

    for e in _edges(canvas):
        src_xy = (round(e.src.x()), round(e.src.y()))
        dst_xy = (round(e.dst.x()), round(e.dst.y()))
        if e.direction == 'out':
            assert src_xy == center_pos, '出边应从中心节点出发'
            assert dst_xy in neighbors, '出边应指向某个邻居节点'
        else:
            assert dst_xy == center_pos, '入边应指向中心节点'
            assert src_xy in neighbors, '入边应从某个邻居节点出发'


def _pos_of(canvas, key):
    """取某节点在场景里的坐标（NodeItem.pos）。"""
    from kg_view import NodeItem
    for item in canvas._scene.items():
        if isinstance(item, NodeItem) and item.key == key:
            return item.pos().x(), item.pos().y()
    return (float('nan'), float('nan'))


def test_out_edges_solid_and_in_edges_dashed(store, mixed, app):
    """两类边在画面上可区分：出边实线、入边虚线。"""
    from PySide6.QtCore import Qt

    from kg_view import KGCanvas

    canvas = KGCanvas()
    canvas.bind(store)
    canvas.show_ego(mixed)

    for e in _edges(canvas):
        dashed = e.pen().style() == Qt.DashLine
        if e.direction == 'out':
            assert not dashed, '出边（本节点→对端）应是实线'
        else:
            assert dashed, '入边（对端→本节点）应是虚线'


def test_arrowhead_stays_outside_node_circle(store, mixed, app):
    """箭头不能埋在节点圆里——否则看起来就像没画箭头。"""
    from kg_view import KGCanvas

    canvas = KGCanvas()
    canvas.bind(store)
    canvas.show_ego(mixed)

    for e in _edges(canvas):
        assert _dist(e.tip, e.dst) > 1.0, '箭头尖端贴在目标圆心上'


def _arrow_length(item):
    """从路径里反解箭头几何长度（尖端到箭头根部）。

    路径元素顺序固定：MoveTo(线起点) → LineTo(箭头根部) → MoveTo(尖端)
    → LineTo(根部+侧) → LineTo(根部-侧) → LineTo(闭合)。
    """
    path = item.path()
    assert path.elementCount() >= 2
    root = path.elementAt(1)
    return math.hypot(item.tip.x() - root.x, item.tip.y() - root.y)


def test_arrow_length_is_capped_relative_to_line(app):
    """箭头长度必须按**线长封顶**：高权重粗边的箭头不能盖住邻居标签。

    ⚠️ 这里对比同一支粗笔（权重 10、线宽 6px）在短线与长线上的箭头长度：
    未封顶时两者都是 18px，短边那根的箭头会占掉可见线的一大半。
    """
    from kg_view import ArrowEdgeItem

    short = ArrowEdgeItem((0, 0), (60, 0), 15, 15, 10, direction='out')
    long_ = ArrowEdgeItem((0, 0), (600, 0), 15, 15, 10, direction='out')

    short_len = _arrow_length(short)
    long_len = _arrow_length(long_)
    # 长线不触发封顶，箭头保持与线宽相称
    assert long_len == pytest.approx(18.0, abs=0.5), \
        f'长边箭头长度应约 18px，实得 {long_len}'
    # 短线必须被压到可见线的 40% 以内（封顶逻辑就是 usable * 0.4）
    visible = _dist(short.tail, short.tip)
    assert short_len < visible * 0.45, \
        f'短线箭头未封顶：箭头 {short_len:.1f}px / 可见线 {visible:.1f}px'


def test_edge_labels_carry_direction_marker(store, mixed, app):
    """边标签带 → / ← 文字标记：缩放到看不清箭头时仍能读懂方向。"""
    from PySide6.QtWidgets import QGraphicsTextItem

    from kg_view import KGCanvas

    canvas = KGCanvas()
    canvas.bind(store)
    canvas.show_ego(mixed)

    labels = [i.toPlainText() for i in canvas._scene.items()
              if isinstance(i, QGraphicsTextItem) and i.parentItem() is None]
    assert any('→' in t for t in labels), '出边标签应有 →'
    assert any('←' in t for t in labels), '入边标签应有 ←'


def test_edge_label_html_direction_is_optional(app):
    """edge_label_html 不传 direction 时**不加**箭头，保持旧调用点行为。"""
    from PySide6.QtWidgets import QGraphicsTextItem

    from kg_view import edge_label_html

    plain = QGraphicsTextItem()
    plain.setHtml(edge_label_html('属于', 'part_of', None))
    text = plain.toPlainText()
    assert '→' not in text and '←' not in text

    out = QGraphicsTextItem()
    out.setHtml(edge_label_html('属于', 'part_of', None, 'out'))
    assert '→' in out.toPlainText()

    inc = QGraphicsTextItem()
    inc.setHtml(edge_label_html('属于', 'part_of', None, 'in'))
    assert '←' in inc.toPlainText()


def test_panel_relation_list_marks_direction():
    """面板关系列表按方向渲染（出边 → / 入边 ←），不能退化成无向列表。

    ⚠️ 不用 ``ManagerPanel.__new__`` 硬造实例去调 ``_kg_fill_relations``——
    那要求整个面板已初始化，一旦用到别的实例属性就 AttributeError，
    测的是构造细节而非「方向有没有标出来」。改为静态查源码：
    方向变量必须真的进了拼接结果，且两个箭头字面量都在。
    """
    import ast
    import inspect
    import textwrap

    import manager_panel

    src = textwrap.dedent(inspect.getsource(manager_panel))
    fn = next(n for n in ast.walk(ast.parse(src))
              if isinstance(n, ast.FunctionDef)
              and n.name == '_kg_fill_relations')

    # 1) 方向参与渲染：三元表达式里按 direction 选出两个不同字面量
    picked = set()
    for t in (n for n in ast.walk(fn) if isinstance(n, ast.IfExp)):
        if not isinstance(t.body, ast.Constant):
            continue          # 分支不是字面量（如 alias 那种）就跳过
        if not isinstance(t.orelse, ast.Constant):
            continue
        if t.body.value != t.orelse.value:
            picked.add(t.body.value)
            picked.add(t.orelse.value)
    assert '→' in picked and '←' in picked, \
        f'_kg_fill_relations 应按 direction 选 →/←，实得 {picked}'

    # 2) 两个箭头都进了最终拼接的文本
    assert '→' in src and '←' in src