"""知识图谱画布的悬空对象回归测试（v3.7）。

复现的崩溃：

    Error calling Python override of QGraphicsEllipseItem::mouseDoubleClickEvent():
    RuntimeError: libshiboken: Internal C++ object (NodeItem) already deleted.

成因是**事件重入**：双击节点 → ``nodeExpanded`` 信号同步触发 ``show_ego()``
→ 里面 ``self._scene.clear()`` 把**正在处理这个事件的节点本身**销毁；控制流回到
``super().mouseDoubleClickEvent(event)`` 时 C++ 对象已不存在。

而 ``NodeItem.canvas`` 这条 Python 引用会让包装对象继续存活，于是 Qt 仍可能把
事件投递到已销毁的 C++ 对象上——所以除了调整调用顺序，还需要 ``_alive`` 标记兜底。

这些都需要真实的 QApplication 与 QGraphicsScene，故用离屏 Qt 跑真实画布。
素材库很重，故只在真实 assets.db 存在时运行。
"""

import os

import pytest

pytest.importorskip('PySide6')

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('SDL_AUDIODRIVER', 'dummy')

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS_DB = os.path.join(ROOT, 'assets.db')

pytestmark = pytest.mark.skipif(
    not os.path.isfile(ASSETS_DB),
    reason='需要真实 assets.db（约 460MB），跳过画布行为测试')

CENTER = ('character', '钟离')


@pytest.fixture(scope='module')
def app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.fixture(scope='module')
def canvas(app):
    """加载了钟离自我中心网的真实画布。"""
    import kg_store
    from kg_view import KGCanvas

    kg_store.reset_default_store()
    store = kg_store.KGStore(os.path.join(ROOT, 'kg.db'), auto_seed=False)
    c = KGCanvas()
    c.bind(store)
    c.show_ego(CENTER)
    assert c.center_key == CENTER
    return c


def _nodes(c):
    from kg_view import NodeItem
    return [i for i in c._scene.items() if isinstance(i, NodeItem)]


def _event(kind):
    """构造 QGraphicsSceneMouseEvent（QGraphicsItem 只接受这一种事件）。"""
    from PySide6.QtCore import Qt, QPointF
    from PySide6.QtWidgets import QGraphicsSceneMouseEvent

    e = QGraphicsSceneMouseEvent(kind)
    e.setScenePos(QPointF(0, 0))
    e.setButton(Qt.LeftButton)
    e.setButtons(Qt.LeftButton)
    return e


def test_scene_has_nodes(canvas):
    """前置：画布上确实有多个节点可点。"""
    assert len(_nodes(canvas)) >= 2


def test_double_click_expands_without_error(canvas):
    """回归：双击节点应发出**该节点**的 nodeExpanded，且**不抛 RuntimeError**。

    这是原崩溃点：emit 同步触发面板 `show_ego()` → `scene.clear()` 销毁 self，
    随后 `super().mouseDoubleClickEvent(event)` 访问已删的 C++ 对象。
    """
    from PySide6.QtWidgets import QGraphicsSceneMouseEvent

    emitted = []
    canvas.nodeExpanded.connect(emitted.append)
    try:
        target = _nodes(canvas)[1]
        expected = target.key
        assert expected != CENTER
        target.mouseDoubleClickEvent(
            _event(QGraphicsSceneMouseEvent.MouseButtonDblClick))
        assert emitted == [expected], 'nodeExpanded 应携带被双击的节点'
    finally:
        try:
            canvas.nodeExpanded.disconnect()
        except (RuntimeError, TypeError):
            pass


def test_repeated_double_click_is_safe(canvas):
    """回归：连续双击（每次都重建场景）不应报错。"""
    from PySide6.QtWidgets import QGraphicsSceneMouseEvent

    for _ in range(3):
        nodes = _nodes(canvas)
        if len(nodes) < 2:
            pytest.skip('邻居不足，无法双击')
        nodes[1].mouseDoubleClickEvent(
            _event(QGraphicsSceneMouseEvent.MouseButtonDblClick))
    assert canvas.center_key is not None


def test_single_click_is_safe(canvas):
    """单击同样会重绘详情，不能报错。"""
    from PySide6.QtWidgets import QGraphicsSceneMouseEvent

    target = _nodes(canvas)[1]
    target.mousePressEvent(_event(QGraphicsSceneMouseEvent.MouseButtonPress))
    assert canvas.center_key is not None


def test_stale_node_event_short_circuits(canvas):
    """回归：场景重绘后，旧节点再收到滞后事件应安全短路。"""
    from PySide6.QtWidgets import QGraphicsSceneMouseEvent

    victim = _nodes(canvas)[1]
    canvas.show_ego(('character', '七七'))       # 场景重建，victim 的 C++ 已销毁
    assert victim._alive is False, '重绘后旧节点应被标记为已销毁'
    # 之前这里会抛「Internal C++ object (NodeItem) already deleted」
    victim.mouseDoubleClickEvent(
        _event(QGraphicsSceneMouseEvent.MouseButtonDblClick))
    victim.mousePressEvent(_event(QGraphicsSceneMouseEvent.MouseButtonPress))


def test_retire_marks_all_previous_nodes(canvas):
    """_retire_items 应把场景内所有 NodeItem 标记掉。"""
    before = _nodes(canvas)
    assert before and all(n._alive for n in before)
    canvas.show_ego(('character', '甘雨'))
    assert all(n._alive is False for n in before), '旧节点未全部标记'


def test_clear_marks_nodes(canvas):
    """clear() 同样要标记，避免删除实体后残留悬空对象。"""
    nodes = _nodes(canvas)
    canvas.clear()
    assert all(n._alive is False for n in nodes)
    assert canvas.center_key is None
    canvas.show_ego(CENTER)      # 复原供后续测试使用


def test_double_click_via_panel_repaint(app):
    """端到端：连上真实面板的双击链路（nodeExpanded → show_ego）不应崩溃。

    单测里画布没有面板连接，`nodeExpanded` 只是个空信号；这里接入真实的
    `ManagerPanel._on_kg_node_expanded`，复现用户实际点击的完整路径——
    正是这条路径在 v3.7 之前抛「Internal C++ object already deleted」。
    """
    import tempfile

    from PySide6.QtWidgets import QGraphicsSceneMouseEvent, QWidget

    import kg_store
    from manager_panel import ManagerPanel

    class _Store:
        base_dir = ROOT

        def list_roles(self):
            return ['钟离']

        def list_bgm_areas(self):
            return ['璃月']

        def list_frames(self, role):
            return ['0001.png']

        def list_voices(self, role, category=None):
            return ['早上好.mp3']

        def read_frame(self, role, name):
            return b''

        def read_voice(self, role, name):
            return b''

        def read_bgm(self, area):
            return b''

        def stats(self):
            return {'backend': 'sqlite', 'roles': 1, 'areas': 1, 'frames': 1,
                    'voices': 1, 'bgms': 1, 'db_size_mb': 1.0}

    class _Pilot(QWidget):
        """pilot 桩：必须是 QWidget。

        v3.8 起ManagerPanel 是独立的 QMainWindow，**不再**把 pilot 当作 Qt
        父窗口传入（那会让面板被并进伙伴的任务栏分组）。但面板仍要读取
        pilot 的 store / config_store / _frames 等属性，故这些成员不能省。
        成员清单与 tools/smoke_kg_panel.py 的 FakePilot 保持一致。
        """

        def __init__(self):
            super().__init__()
            from config_store import ConfigStore
            self.store = _Store()
            self.config_store = ConfigStore(tempfile.mkdtemp(), auto_seed=False)
            self.role_name = '钟离'
            self.audio_player = False
            self._frames = []
            self.index = 0

        def set_voice_enabled(self, enabled):
            pass

        def stop_bgm(self):
            pass

        def play_area_bgm(self, area):
            pass

        def set_role_timing(self, role, interval, scale):
            pass

        def reshow(self, name):
            self.role_name = name

        def _rebuild_role_menu(self):
            pass

        def set_visible(self, visible):
            self.setWindowOpacity(1.0 if visible else 0.0)

        def quit(self):
            """面板菜单「退出程序」会调用；桩件里什么都不做。"""

        def _rebuild_bgm_menu(self):
            pass

        def save_config(self):
            pass

    store = kg_store.KGStore(os.path.join(ROOT, 'kg.db'), auto_seed=False)
    pilot_stub = _Pilot()
    panel = ManagerPanel(pilot_stub, {'frame_scale': {}, 'bg_music': None,
                                      'audio': False, 'role': '钟离'})
    try:
        panel._ensure_kg_loaded()
        panel.kg_canvas.kg = store
        panel.kg_canvas.show_ego(CENTER)
        for _ in range(3):
            nodes = _nodes(panel.kg_canvas)
            assert len(nodes) >= 2
            nodes[1].mouseDoubleClickEvent(
                _event(QGraphicsSceneMouseEvent.MouseButtonDblClick))
            # 经面板后画布确实以被点节点重绘了
            assert panel.kg_canvas.center_key is not None
    finally:
        panel.deleteLater()
        pilot_stub.deleteLater()


def test_tray_icon_set_before_tray_shown(app):
    """回归（v3.7）：托盘必须在**设置图标之后**才 show()。

    原顺序是 `tray()` → `init_window()`，而 `tray()` 内部会 `self.tp.show()`，
    此时图标还没设，Qt 打印「QSystemTrayIcon::setVisible: No Icon set」。
    """
    import inspect

    import pilot as pilot_mod

    src = inspect.getsource(pilot_mod.Pilot.__init__)
    i_init = src.index('self.init_window()')
    i_tray = src.index('self.tray()')
    assert i_init < i_tray, 'init_window()（设图标）必须早于 tray()（显示托盘）'


def test_mouse_handlers_do_not_call_super(canvas):
    """回归（v3.7）：节点的鼠标处理**不得调用 super()**。

    QGraphicsItem 的默认实现会 ``grabMouse()``，而节点在双击时会被
    ``scene.clear()`` 销毁，Qt 于是在松手时找不到 grabber，打印
    「QGraphicsItem::ungrabMouse: not a mouse grabber」。
    用 AST 判定（而非字符串匹配，docstring 里也会出现 super() 字样）。
    """
    import ast
    import inspect
    import textwrap

    from kg_view import NodeItem

    for name in ('mousePressEvent', 'mouseDoubleClickEvent', 'hoverEnterEvent'):
        tree = ast.parse(textwrap.dedent(inspect.getsource(getattr(NodeItem, name))))
        calls = [n for n in ast.walk(tree)
                 if isinstance(n, ast.Call)
                 and isinstance(n.func, ast.Attribute)
                 and n.func.attr.startswith('__')]
        assert not calls, f'{name} 不应调用 super()（会 grabMouse），实际有 {calls}'


def test_mouse_sequence_has_no_grab_warning(canvas, capsys):
    """按「按下 → 释放 → 双击 → 再交互」走一遍，不应出现 ungrabMouse 警告。"""
    import io
    from contextlib import redirect_stderr

    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtWidgets import QGraphicsSceneMouseEvent

    def mk(kind):
        e = QGraphicsSceneMouseEvent(kind)
        e.setScenePos(QPointF(0, 0))
        e.setButton(Qt.LeftButton)
        e.setButtons(Qt.LeftButton)
        return e

    PRS = QGraphicsSceneMouseEvent.MouseButtonPress
    REL = QGraphicsSceneMouseEvent.MouseButtonRelease
    DBL = QGraphicsSceneMouseEvent.MouseButtonDblClick

    canvas.show_ego(CENTER)
    buf = io.StringIO()
    with redirect_stderr(buf):
        n = _nodes(canvas)[1]
        n.mousePressEvent(mk(PRS))
        n.mouseReleaseEvent(mk(REL))
        n.mouseReleaseEvent(mk(REL))       # Qt 的双击序列
        n2 = _nodes(canvas)[1]
        n2.mouseDoubleClickEvent(mk(DBL))  # 场景重绘，旧节点销毁
        n3 = _nodes(canvas)[1]
        n3.mousePressEvent(mk(PRS))
        n3.mouseReleaseEvent(mk(REL))
    err = buf.getvalue()
    assert 'ungrabMouse' not in err, f'仍出现 grab 警告：{err.strip()}'
