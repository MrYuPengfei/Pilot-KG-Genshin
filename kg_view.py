"""知识图谱可视化画布（QGraphicsView 自我中心网）。

交互：
- 单击节点：选中并发射 nodeSelected(key)；
- 双击节点：以该节点为中心重新展开（发射 nodeExpanded(key)）；
- 滚轮缩放、左键拖拽平移；
- 边中点标注关系名（关系中文名 + 英文名 + 权重）。

**双语标签**：节点标签同时给英文名与中文名，边标签同时给关系中文名与英文名。
两者都用 HTML 富文本拼（深色=英文/中文名，浅灰=副名），而不是截断成
``rein…`` ——csv-edu 的实体名平均 16.7 字符、最长 46，截断等于没显示。

**带权重的边**：关系表带 ``weight`` 列时（如 data/csv-edu 的 1~10 评分），
边的粗细与颜色深浅随权重变化，边标签追加权重值。全默认权重的图谱
（weight = 1.0）渲染结果与早期版本完全一致。

**有向图**：边不再是无向直线，而是带箭头的有向边。
:attr:`KGStore.neighbor_details_directed` 会告诉你每条关系是 ``out``
（本节点 → 对端）还是 ``in``（对端 → 本节点）：

- ``out``（出边）：实线 + 箭头落在**邻居**上；
- ``in``（入边）：虚线 + 箭头落在**中心节点**上。

⚠️ 早期版本用 ``QGraphicsLineItem`` 画直线，只有位置没有方向，
「衍生自 foundation model」和「foundation model 衍生自」长得一模一样。
方向在**数据层一直都有**（``kg_edges`` 存的就是有向三元组），只是画布没画出来。
"""

import html
import math

from PySide6.QtCore import Qt, Signal, QPointF
from PySide6.QtGui import (QColor, QPen, QBrush, QFont, QFontMetricsF, QPainter,
                           QPainterPath)
from PySide6.QtWidgets import (QGraphicsView, QGraphicsScene, QGraphicsEllipseItem,
                               QGraphicsTextItem, QGraphicsPathItem)

from kg_store import NODE_TYPES, DEFAULT_WEIGHT

CENTER_RADIUS = 26
NODE_RADIUS = 15

# 有向边的几何：线不要顶到圆心上，要从圆边出发；箭头占掉末端一段长度。
# 留空隙（gap）避免粗线与节点描边叠在一起显得糊。
ARROW_GAP = 3.0
ARROW_LEN_MIN = 8.0
ARROW_WID_RATIO = 0.55

# 节点标签排版：英文名按词折行，最多 NODE_LABEL_MAX_LINES 行；
# 中文名单行、超长省略。宽度用来估算节点间距（见 show_ego）。
NODE_LABEL_MAX_CHARS = 20
NODE_LABEL_MAX_LINES = 2
CN_LABEL_MAX_CHARS = 12
CENTER_LABEL_MAX_CHARS = 24
CENTER_LABEL_MAX_LINES = 3

# 标签配色：主名深色、副名浅灰（与实体描边同一套色，保持画面统一）
LABEL_MAIN = '#2c3e50'
LABEL_SUB = '#7f8c8d'
# 边的关系标签：关系中文名深色、英文名浅灰，便于一眼分辨主次
EDGE_LABEL_MAIN = '#34495e'
EDGE_LABEL_SUB = '#95a5a6'
# 有向边的文字方向标记（与 edge_label_html 的 direction 参数配套）
EDGE_ARROW_OUT = '→'
EDGE_ARROW_IN = '←'

# 权重 → 视觉映射。csv-edu 用 1~10 整数评分，故上限取 10；
# 超出范围（0~1 的相似度、0~100 的百分比）会被夹到端点，不会画成负宽度。
WEIGHT_MAX = 10.0
EDGE_WIDTH_MIN = 1.2
EDGE_WIDTH_MAX = 6.0
# 无权重边的颜色（沿用早期版本的浅灰）
EDGE_COLOR_BASE = '#b8c2cc'
# 有权重边的两端颜色：低权重偏浅、高权重偏深（蓝灰 → 主蓝）
EDGE_COLOR_LOW = '#c3d0dc'
EDGE_COLOR_HIGH = '#1f6fb2'


def weight_ratio(weight):
    """把权重归一化到 0.0~1.0；缺省/非法值按 0 处理。"""
    try:
        w = float(weight)
    except (TypeError, ValueError):
        return 0.0
    if w <= DEFAULT_WEIGHT:
        # 低于默认权重（0~1 相似度）反向映射，让「弱关系」也可见
        return max(0.0, (w / DEFAULT_WEIGHT) * 0.25) if w > 0 else 0.0
    return min(1.0, (w - DEFAULT_WEIGHT) / (WEIGHT_MAX - DEFAULT_WEIGHT))


def edge_pen(weight):
    """按权重生成边的画笔：越粗越深。"""
    if weight is None or weight == DEFAULT_WEIGHT:
        return QPen(QColor(EDGE_COLOR_BASE), EDGE_WIDTH_MIN)
    r = weight_ratio(weight)
    color = QColor(EDGE_COLOR_LOW)
    target = QColor(EDGE_COLOR_HIGH)
    color.setRed(int(color.red() + (target.red() - color.red()) * r))
    color.setGreen(int(color.green() + (target.green() - color.green()) * r))
    color.setBlue(int(color.blue() + (target.blue() - color.blue()) * r))
    width = EDGE_WIDTH_MIN + (EDGE_WIDTH_MAX - EDGE_WIDTH_MIN) * r
    pen = QPen(color, width)
    pen.setCapStyle(Qt.RoundCap)
    return pen


def weight_text(weight):
    """边标签里的权重后缀；默认权重不显示（避免给无权重图谱平添噪声）。"""
    if weight is None or weight == DEFAULT_WEIGHT:
        return ''
    return f' {int(weight)}' if float(weight).is_integer() else f' {weight:.2f}'


def shorten(text, limit):
    """超长文本截断并加省略号（按**字符**数，中英文都适用）。"""
    text = text or ''
    return text if len(text) <= limit else text[:max(1, limit - 1)] + '…'


def wrap_label(text, limit, max_lines):
    """按词折行，超出 max_lines 行则截断并加省略号。

    ⚠️ 英文名按长度硬切会把词劈开（``reinforce / ment``），
    所以优先在空格处折行；单词本身超长才硬切。
    """
    words = (text or '').split()
    if not words:
        return ['']
    lines, cur = [], ''
    for w in words:
        cand = f'{cur} {w}' if cur else w
        if len(cand) <= limit:
            cur = cand
            continue
        if cur:
            lines.append(cur)
        # 单个词就超长（无空格的极长名）→ 硬切，别让它把行撑爆
        while len(w) > limit:
            lines.append(w[:limit])
            w = w[limit:]
        cur = w
    if cur:
        lines.append(cur)
    if len(lines) > max_lines:
        # 放不下：保留前 max_lines 行，末行留一个位置给省略号。
        # ⚠️ 别用 shorten()再拼一个「…」——末行被硬切过就可能已有省略号，
        # 拼出来会变成「……」。这里直接按长度切片，末尾只加一个。
        kept = lines[:max_lines]
        last = kept[-1]
        if len(last) >= limit:
            last = last[:limit - 1]
        kept[-1] = last + '…'
        return kept
    return lines


def measure_text(text, point_size, bold=False):
    """量一段文本的像素宽度（用于按标签宽度决定节点间距）。"""
    font = QFont()
    font.setPointSize(point_size)
    font.setBold(bold)
    return QFontMetricsF(font).horizontalAdvance(text or '')


def node_label_html(name, cn_name, center=False):
    """节点标签的 HTML：英文名（可折行）+ 中文名（灰色小字）。

    ⚠️ 名字来自 CSV，必须转义——``<``/``&`` 未转义会让 Qt 把标签当HTML
    解析，轻则丢字重则整段不显示。
    """
    limit = CENTER_LABEL_MAX_CHARS if center else NODE_LABEL_MAX_CHARS
    max_lines = CENTER_LABEL_MAX_LINES if center else NODE_LABEL_MAX_LINES
    size = 11 if center else 9
    sub_size = 9 if center else 7.5
    # ⚠️ 主名与中文名相同时**只显示一次**。原神实体的主键就是中文名
    # （暂无官方译名），若不去重，标签会变成「阿贝多 / 阿贝多」两行重复。
    show_cn = bool(cn_name) and cn_name != name
    parts = [f'<div style="color:{LABEL_MAIN}; font-size:{size}px;">']
    for i, line in enumerate(wrap_label(name, limit, max_lines)):
        if i:
            parts.append('<br/>')
        parts.append(html.escape(line))
    parts.append('</div>')
    if show_cn:
        parts.append(f'<div style="color:{LABEL_SUB}; '
                     f'font-size:{sub_size}px;">'
                     f'{html.escape(shorten(cn_name, CN_LABEL_MAX_CHARS))}</div>')
    return ''.join(parts)


def edge_label_html(rel_cn, rel_en, weight, direction=None):
    """边标签的 HTML：方向箭头 + 关系中文名 + 英文名（灰色）+ 权重。

    中英同名（如用户自建关系名恰好等于中文）时不重复显示。

    ``direction`` 为 ``'out'``/``'in'`` 时在标签前加 ``→``/``←``，
    这是有向图的**文字兜底**：箭头图形之外，标签本身也说明关系指向，
    缩放得很小看不清箭头时仍能读懂。``None``（默认）表示不标方向，
    供不需要方向的旧调用保持原样。
    """
    if direction == 'out':
        arrow = f'<b>{EDGE_ARROW_OUT}</b> '
    elif direction == 'in':
        arrow = f'<b>{EDGE_ARROW_IN}</b> '
    else:
        arrow = ''
    parts = [f'{arrow}<span style="color:{EDGE_LABEL_MAIN};">'
             f'{html.escape(rel_cn)}</span>']
    if rel_en and rel_en != rel_cn:
        parts.append(f' <span style="color:{EDGE_LABEL_SUB}; '
                     f'font-size:7pt;">{html.escape(rel_en)}</span>')
    wt = weight_text(weight).strip()
    if wt:
        parts.append(f' <b>{html.escape(wt)}</b>')
    return ''.join(parts)


class NodeItem(QGraphicsEllipseItem):
    """图谱节点：圆形 + 下方双语名称标签（英文名 + 中文名）。"""

    def __init__(self, key, radius, canvas, cn_name='', center=False):
        super().__init__(-radius, -radius, radius * 2, radius * 2)
        self.key = key
        self.canvas = canvas
        # 场景重绘（show_ego/clear）会销毁本节点的 C++ 对象，但 Python 包装
        # 仍可能被 Qt 投递悬空事件。置此标记后，事件处理可据此安全短路。
        self._alive = True
        ntype, name = key
        color = QColor(NODE_TYPES.get(ntype, ('', '#95a5a6'))[1])
        self.setBrush(QBrush(color))
        self.setPen(QPen(color.darker(130), 1.5))
        self.setZValue(2)
        self.setAcceptHoverEvents(True)
        # 提示框给全名（标签是折行显示的，完整名字放提示里）
        type_label = NODE_TYPES.get(ntype, (ntype,))[0]
        tip = f'{type_label} · {name}'
        # 中文名与主名相同时不重复（原神实体主键即中文名）
        if cn_name and cn_name != name:
            tip += f'\n{cn_name}'
        self.setToolTip(tip)

        label = QGraphicsTextItem(self)
        label.setHtml(node_label_html(name, cn_name, center=center))
        label.setTextWidth(-1)          # 不自动换行：折行由 wrap_label 决定
        label.setDefaultTextColor(QColor(LABEL_MAIN))
        br = label.boundingRect()
        # 标签在圆下方：圆半径 + 一点留白
        label.setPos(-br.width() / 2, radius + 2)
        label.setZValue(3)
        self.label = label

    def mousePressEvent(self, event):
        """单击节点：选中并通知画布。

        ⚠️ 这里**不调用** ``super().mousePressEvent()``。QGraphicsItem 的默认实现会
        ``grabMouse()`` 接管后续事件，而双击时本对象会在 ``nodeExpanded`` 槽里被
        ``scene.clear()`` 销毁——Qt 于是在松手时找不到 grabber，打印
        ``QGraphicsItem::ungrabMouse: not a mouse grabber``。
        节点只需响应「按下」这一瞬，拖拽平移由 QGraphicsView 的
        ScrollHandDrag 负责，因此直接 accept 事件即可。
        """
        if not self._alive:
            return          # C++ 对象已被场景重绘销毁，不再触碰
        if event.button() != Qt.LeftButton:
            event.ignore()
            return
        event.accept()
        # 事件处理期间本对象可能已被销毁（show_ego() 会 scene.clear()），
        # 因此先取出引用再发射信号。
        self.canvas.nodeSelected.emit(self.key)

    def mouseDoubleClickEvent(self, event):
        """双击节点：以它为中心重新展开。

        同样不调 ``super()``（理由见 mousePressEvent），并**先 accept 再发射信号**：
        发射后本对象可能已被场景重绘销毁，之后不再触碰 self。
        """
        if not self._alive:
            return
        if event.button() != Qt.LeftButton:
            event.ignore()
            return
        event.accept()
        key, canvas = self.key, self.canvas
        canvas.nodeExpanded.emit(key)

    def hoverEnterEvent(self, event):
        # 悬停事件同样可能落在已被销毁的对象上，安静跳过。
        # 不调 super()：QGraphicsItem 的默认悬停实现会 grabMouse/hover grab，
        # 在场景重绘后容易留下悬空 grab 状态。
        if not self._alive:
            return
        event.accept()


class ArrowEdgeItem(QGraphicsPathItem):
    """有向边：从源点画一条线到目标点，并在**目标端**画箭头。

    ⚠️ 早期版本用 ``QGraphicsLineItem(0, 0, x, y)`` 画边——那只是条直线，
    从中心到邻居，看起来完全对称，方向信息全丢。这里改用
    ``QGraphicsPathItem``：线段 + 目标端三角箭头合成一条路径，
    用同一支笔刷既描边又填充（线段子路径面积为 0，填充无副作用）。

    端点会**按节点半径内缩**：线从圆的边缘出发而不是圆心，
    否则箭头会埋在圆形里、看着像没画箭头。
    """

    def __init__(self, src, dst, src_radius, dst_radius, weight,
                 direction='out', pen=None):
        super().__init__()
        self.direction = direction
        self.weight = weight
        self.src = QPointF(*src)
        self.dst = QPointF(*dst)
        self.src_radius = src_radius
        self.dst_radius = dst_radius
        # 用调用方给的笔（通常按权重算好、入边再改虚线），没有则按权重现算一支。
        self.setPen(pen if pen is not None else edge_pen(weight))
        self.setBrush(QBrush(self.pen().color()))
        self.setZValue(0)
        # 箭头尖端留在属性里：QPainterPath 不暴露 subpaths()，外部（测试、
        # 悬停命中）想确认「箭头指哪」时直接读这个点，不用去解析路径元素。
        self.tip = None
        self.tail = None
        self._build()

    def _build(self):
        """按当前端点与两端半径重建路径（重算偏移后要再调一次）。"""
        dx = self.dst.x() - self.src.x()
        dy = self.dst.y() - self.src.y()
        length = math.hypot(dx, dy)
        if length < 1e-6:
            self.setPath(QPainterPath())
            self.tip = None
            self.tail = None
            return
        ux, uy = dx / length, dy / length
        # 起点从源圆边缘往外推，终点停在目标圆边缘外
        sx = self.src.x() + ux * (self.src_radius + ARROW_GAP)
        sy = self.src.y() + uy * (self.src_radius + ARROW_GAP)
        ex = self.dst.x() - ux * (self.dst_radius + ARROW_GAP)
        ey = self.dst.y() - uy * (self.dst_radius + ARROW_GAP)

        pen_w = self.pen().widthF() or 1.0
        # 箭头随线宽变粗，但有下限——太细的边配太小的箭头会看不见。
        # ⚠️ 同时要**相对线长封顶**：高权重边线宽可达 6px，箭头按比例会长到
        # 18px，在密集图里会盖住邻居的标签；线本身很短时更会喧宾夺主。
        usable = max(0.0, length - self.src_radius - self.dst_radius - 2 * ARROW_GAP)
        arrow_len = max(ARROW_LEN_MIN, pen_w * 3.0)
        arrow_len = min(arrow_len, usable * 0.4)
        arrow_w = arrow_len * ARROW_WID_RATIO
        bx = ex - ux * arrow_len
        by = ey - uy * arrow_len
        # 垂直于线方向的单位向量，用来张箭头两侧
        px, py = -uy, ux

        path = QPainterPath(QPointF(sx, sy))
        path.lineTo(bx, by)
        path.moveTo(ex, ey)
        path.lineTo(bx + px * arrow_w / 2, by + py * arrow_w / 2)
        path.lineTo(bx - px * arrow_w / 2, by - py * arrow_w / 2)
        path.closeSubpath()
        self.setPath(path)
        self.tip = QPointF(ex, ey)
        self.tail = QPointF(sx, sy)


class KGCanvas(QGraphicsView):
    """自我中心网画布：中心节点 + 邻居放射布局。"""

    nodeSelected = Signal(object)   # (type, name)
    nodeExpanded = Signal(object)   # (type, name)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self.setRenderHint(QPainter.Antialiasing)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setBackgroundBrush(QBrush(QColor('#fafbfc')))
        self.kg = None
        self.center_key = None

    def bind(self, kg_store):
        self.kg = kg_store

    def clear(self):
        """清空画布（删除当前实体后调用）。"""
        self.center_key = None
        self._retire_items()
        self._scene.clear()

    def _retire_items(self):
        """把场景内所有 NodeItem 标记为已销毁。

        ``QGraphicsScene.clear()`` 只销毁 C++ 侧对象，Python 包装可能仍存活
        （``NodeItem.canvas`` 持有引用），此时 Qt 若再投递事件就会命中悬空对象。
        先置 ``_alive = False`` 让事件处理安全短路。
        """
        for item in self._scene.items():
            if isinstance(item, NodeItem):
                item._alive = False

    # ---------- 绘图 ----------

    def show_ego(self, key):
        """以key 为中心绘制一跳自我中心网。

        邻居按权重从大到小排（:meth:`KGStore.neighbor_details_directed`），强关系
        排在前面、线也更粗，形成可读的强弱层次。

        边标签给「方向 + 关系中文名 + 英文名 + 权重」，节点标签给「英文名 + 中文名」，
        两者都用 HTML 富文本，深浅两色区分主次。

        **有向显示**：``out``（本节点 → 对端）画实线、箭头落在对端；
        ``in``（对端 → 本节点）画虚线、箭头落在中心。
        """
        if self.kg is None or key not in self.kg.nodes:
            return
        self.center_key = key
        self._retire_items()     # 必须在 clear 之前置标记
        self._scene.clear()

        # (rel, rel_cn, 对端键, 权重, 对端中文名, 'out'|'in')
        neighbors = self.kg.neighbor_details_directed(key)
        n = len(neighbors)

        # 半径要放得下标签：按最长标签宽度估算每个节点需要的弧长，
        # 否则标签宽而节点密的图（如「foundation model」）会互相压字。
        widest = 0.0
        for _rel, _rel_cn, other, _weight, cn, _dir in neighbors:
            w = measure_text(other[1], 9)
            if cn:
                w = max(w, measure_text(shorten(cn, CN_LABEL_MAX_CHARS), 7.5))
            widest = max(widest, w)
        # 弧长至少是最宽标签的 1.6 倍才不压字；中心节点自身也占地方
        radius = max(220.0, 220.0 + n * 12,
                     n * widest * 1.6 / (2 * math.pi))

        def place(i):
            angle = 2 * math.pi * i / max(n, 1) - math.pi / 2
            return radius * math.cos(angle), radius * math.sin(angle)

        # 先画边（置于节点下层）
        for i, (rel, rel_cn, other, weight, _cn, direction) in enumerate(neighbors):
            x, y = place(i)
            # ⚠️ 同一对端出现多次时**不需要**额外偏移：放射布局按条目逐个
            # 分配角度槽位，那几条边本来就指向不同位置、不会重叠。
            # （曾在这里加过垂直微偏移，结果反而让边不再正对节点中心。）
            if direction == 'out':
                src, dst = (0.0, 0.0), (x, y)
                src_r, dst_r = CENTER_RADIUS, NODE_RADIUS
            else:
                # 入边：源在对端、目标在中心，箭头指回中心节点
                src, dst = (x, y), (0.0, 0.0)
                src_r, dst_r = NODE_RADIUS, CENTER_RADIUS
            pen = edge_pen(weight)
            if direction == 'in':
                pen.setStyle(Qt.DashLine)
            edge = ArrowEdgeItem(src, dst, src_r, dst_r, weight,
                                 direction=direction, pen=pen)
            self._scene.addItem(edge)
            # 关系标签放在 55% 处：方向 + 中英关系名 + 权重
            text = QGraphicsTextItem()
            text.setHtml(edge_label_html(rel_cn, rel, weight, direction))
            text.setTextWidth(-1)
            br = text.boundingRect()
            text.setPos(x * 0.55 - br.width() / 2, y * 0.55 - br.height() / 2)
            text.setZValue(1)
            self._scene.addItem(text)

        # 中心节点
        center = NodeItem(key, CENTER_RADIUS, self,
                          self.kg.node_cn_name(key) if self.kg else '',
                          center=True)
        center.setPos(QPointF(0, 0))
        center.setPen(QPen(QColor('#2c3e50'), 2.5))
        self._scene.addItem(center)

        # 邻居节点
        for i, (rel, rel_cn, other, weight, cn, _dir) in enumerate(neighbors):
            x, y = place(i)
            item = NodeItem(other, NODE_RADIUS, self, cn)
            item.setPos(QPointF(x, y))
            self._scene.addItem(item)

        self._scene.setSceneRect(self._scene.itemsBoundingRect().adjusted(-80, -80, 80, 80))
        self.fitInView(self._scene.sceneRect(), Qt.KeepAspectRatio)
        self.nodeSelected.emit(key)

    # ---------- 交互 ----------

    def wheelEvent(self, event):
        factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        self.scale(factor, factor)
