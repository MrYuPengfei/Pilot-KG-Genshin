"""知识图谱可视化画布（QGraphicsView 自我中心网）。

交互：
- 单击节点：选中并发射 nodeSelected(key)；
- 双击节点：以该节点为中心重新展开（发射 nodeExpanded(key)）；
- 滚轮缩放、左键拖拽平移；
- 边中点标注关系名（仅中心节点的边，避免文字堆叠）。
"""

import math

from PySide6.QtCore import Qt, Signal, QPointF
from PySide6.QtGui import QColor, QPen, QBrush, QFont, QPainter
from PySide6.QtWidgets import (QGraphicsView, QGraphicsScene, QGraphicsEllipseItem,
                               QGraphicsTextItem, QGraphicsLineItem)

from kg_store import NODE_TYPES

CENTER_RADIUS = 26
NODE_RADIUS = 15


class NodeItem(QGraphicsEllipseItem):
    """图谱节点：圆形 + 下方名称标签。"""

    def __init__(self, key, radius, canvas):
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
        self.setToolTip(f'{NODE_TYPES.get(ntype, (ntype,))[0]} · {name}')

        label = QGraphicsTextItem(self._short_name(name), self)
        font = QFont()
        font.setPointSize(9)
        label.setFont(font)
        label.setDefaultTextColor(QColor('#2c3e50'))
        br = label.boundingRect()
        label.setPos(-br.width() / 2, radius - 2)
        label.setZValue(3)

    @staticmethod
    def _short_name(name, limit=7):
        return name if len(name) <= limit else name[:limit - 1] + '…'

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
        """以 key 为中心绘制一跳自我中心网。"""
        if self.kg is None or key not in self.kg.nodes:
            return
        self.center_key = key
        self._retire_items()     # 必须在 clear 之前置标记
        self._scene.clear()

        neighbors = self.kg.neighbors(key)   # 已按关系分组排序
        n = len(neighbors)
        # 半径保证邻居间距不小于 ~44px
        radius = max(200.0, n * 44.0 / (2 * math.pi))

        # 先画边（置于节点下层）
        for i, (rel, rel_cn, other) in enumerate(neighbors):
            angle = 2 * math.pi * i / max(n, 1) - math.pi / 2
            x, y = radius * math.cos(angle), radius * math.sin(angle)
            line = QGraphicsLineItem(0, 0, x, y)
            line.setPen(QPen(QColor('#b8c2cc'), 1.2))
            line.setZValue(0)
            self._scene.addItem(line)
            # 关系标签放在 60% 处
            text = QGraphicsTextItem(rel_cn)
            font = QFont()
            font.setPointSize(8)
            text.setFont(font)
            text.setDefaultTextColor(QColor('#7f8c8d'))
            br = text.boundingRect()
            text.setPos(x * 0.55 - br.width() / 2, y * 0.55 - br.height() / 2)
            text.setZValue(1)
            self._scene.addItem(text)

        # 中心节点
        center = NodeItem(key, CENTER_RADIUS, self)
        center.setPos(QPointF(0, 0))
        center.setPen(QPen(QColor('#2c3e50'), 2.5))
        self._scene.addItem(center)

        # 邻居节点
        for i, (rel, rel_cn, other) in enumerate(neighbors):
            angle = 2 * math.pi * i / max(n, 1) - math.pi / 2
            item = NodeItem(other, NODE_RADIUS, self)
            item.setPos(QPointF(radius * math.cos(angle), radius * math.sin(angle)))
            self._scene.addItem(item)

        self._scene.setSceneRect(self._scene.itemsBoundingRect().adjusted(-80, -80, 80, 80))
        self.fitInView(self._scene.sceneRect(), Qt.KeepAspectRatio)
        self.nodeSelected.emit(key)

    # ---------- 交互 ----------

    def wheelEvent(self, event):
        factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        self.scale(factor, factor)
