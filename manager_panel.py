"""管理面板：人物管理 / 音乐管理 / 素材管理 / 知识图谱 / 窗口与状态 / 帮助文档六个标签页。

从托盘菜单「管理面板」打开。面板通过 Pilot 暴露的方法操作，
所有变更即时生效并与托盘菜单状态保持同步。

**v3.8：面板由 QDialog 改为 QMainWindow**，并新增「窗口与状态」标签页：

1. **任务栏有独立图标**。原先作为 ``Pilot`` 的子弹窗运行时，Windows 会把它
   并进伙伴那个「无边框置顶」窗口的任务栏分组里，用户在任务栏上找不到它。
   改成主窗口并显式声明 ``Qt.Window`` 后，任务栏出现独立条目，
   可以像普通程序那样最小化、最大化、还原。
2. **窗口命令有落脚处**。原先面板没有任何窗口状态入口。
   现放在「窗口与状态」页：最小化、最大化 / 还原、全屏 / 退出全屏、
   隐藏面板、显示桌面上的伙伴，同页还有当前窗口状态与版本等信息。
3. **关闭 = 隐藏**。点关闭按钮或 Alt+F4 只是隐藏到托盘，伙伴继续运行；
   再从托盘「管理面板」唤出即可，不必重建面板（重建会丢失已填的表单状态）。

**不用菜单栏**：面板的全部功能都挂在标签页上，窗口命令也有专门的标签页，
再加一层菜单只会让「换页」与「做事」分散在两处。
"""

import html
import os

from PySide6.QtCore import Qt, QStringListModel, QEvent
from PySide6.QtGui import QIcon, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                               QListWidget, QLabel, QPushButton, QSpinBox, QDoubleSpinBox,
                               QCheckBox, QMessageBox, QFileDialog, QGroupBox, QFormLayout,
                               QTextBrowser, QLineEdit, QCompleter, QSplitter,
                               QComboBox, QProgressDialog, QApplication, QDialog,
                               QTabWidget)

from asset_exporter import export_assets, _human_size
from kg_store import (NODE_TYPES, get_default_store, reset_default_store,
                      rel_cn, type_cn)
from kg_editor import NodeEditDialog, EdgeEditDialog
from kg_view import KGCanvas

APP_VERSION = '3.8'
REPO_URL = 'https://github.com/MrYuPengfei/Pilot-KG-Genshin.git'

# 全局按钮尺寸：管理面板**所有页**的按钮一律用这个尺寸，保证视觉一致。
# 必须显式 setFixedSize——同一行的 QPushButton 默认 sizePolicy 会被拉伸成等宽，
# 文字长短仍会让观感不一致（v3.7 逐页统一时踩过）。
BTN_W: int = 132
BTN_H: int = 32
REPO_PAGE = 'https://github.com/MrYuPengfei/'

# 帮助文档文件名（v3.8 起 HTML 独立成文件，不再硬编码在本模块里）
HELP_FILE = 'help.html'


def app_icon(base_dir, fallback_pixmap=None):
    """取应用图标：优先用磁盘上的 ``icon256.ico``，否则退回伙伴当前帧。

    **为什么任务栏图标要用这个**：面板在任务栏有独立条目后，
    任务栏显示的就是这个图标。若不给``setWindowIcon``，Windows 会拿
    exe 的图标（PyInstaller 已嵌入，但在开发态是PySide6 默认图标）。
    """
    here = os.path.dirname(os.path.abspath(__file__))
    for path in (os.path.join(base_dir, 'icon256.ico'),
                 os.path.join(here, 'icon256.ico'),
                 os.path.join(base_dir, '_internal', 'icon256.ico')):
        if os.path.isfile(path):
            icon = QIcon(path)
            if not icon.isNull():
                return icon
    return QIcon(fallback_pixmap) if fallback_pixmap is not None else QIcon()


def help_file_candidates(base_dir):
    """返回可能的帮助文件路径（按优先级）。

    v3.8 起帮助页是独立文件 ``res/help.html``，随安装包进 ``_internal``：

    - 打包后 ``base_dir`` 就是 ``_internal``（pilot.py 的 BASE_DIR 指向那里），
      故第一条命中；
    - 从源码运行时 ``base_dir`` 是项目根，文件在 ``res/`` 子目录下，
      故第二条命中——**注意是 here/res 而不是 here 的父目录/res**，
      写错成父目录会导致开发态永远读不到帮助文件（且因为有兜底提示，
      不报错、只是帮助页变空白，很难发现）。
    """
    here = os.path.dirname(os.path.abspath(__file__))
    return [
        os.path.join(base_dir, HELP_FILE),
        os.path.join(here, HELP_FILE),
        os.path.join(here, 'res', HELP_FILE),
    ]


def load_help_html(base_dir, app_version=APP_VERSION, repo_url=REPO_URL,
                   repo_page=REPO_PAGE):
    """读取帮助文档 HTML 并填入版本等占位符；读不到时返回兜底提示页。

    文件里的占位符写成 ``{{APP_VERSION}}`` 这种**双花括号**形式——
    若沿用单花括号，HTML 里的 CSS（如 ``body { margin: 0 }``）
    会在替换时把内容吃掉。

    **不抛异常**：帮助页读不到只是文档缺失，不能因此让程序起不来。
    """
    candidates = help_file_candidates(base_dir)
    path = next((p for p in candidates if os.path.isfile(p)), None)
    if path is None:
        content = (f'<h2>原神桌面伙伴 v{app_version} · 帮助文档</h2>'
                   f'<p style="color:#c0392b"><b>未能载入帮助文件 '
                   f'{HELP_FILE}</b></p>'
                   f'<p>帮助文档随程序一起安装在 <code>_internal</code> 目录下。'
                   f'若该文件缺失，可重新安装程序；源码位于仓库的 '
                   f'<code>res/{HELP_FILE}</code>。</p>')
    else:
        try:
            with open(path, 'r', encoding='utf-8') as f:
                content = f.read()
        except OSError as e:
            content = (f'<h2>原神桌面伙伴 v{app_version} · 帮助文档</h2>'
                       f'<p style="color:#c0392b">帮助文件读取失败：'
                       f'{html.escape(str(e))}</p>')
    return (content
            .replace('{{APP_VERSION}}', app_version)
            .replace('{{REPO_URL}}', repo_url)
            .replace('{{REPO_PAGE}}', repo_page))

class ManagerPanel(QMainWindow):
    """管理面板主窗口（v3.8 起由 QDialog 升级而来）。

    任务栏行为的关键是构造时的 ``super().__init__(None)`` 加显式
    ``Qt.Window``：把 pilot 作为 parent 会让 Windows 把面板并进伙伴那个
    无边框窗口的任务栏分组，导致任务栏上看不到独立图标。
    伙伴（pilot）改由 :attr:`pilot` 属性引用，不再是 Qt 父子关系。
    """

    def __init__(self, pilot, config):
        super().__init__(None)      # 不设 parent：见类文档的说明
        self.pilot = pilot
        self.store = pilot.store
        self.config = config
        # v3.4：配置以 SQLite 为准（config.db），config dict 是其内存副本
        self.config_store = pilot.config_store
        self.setWindowTitle(f'原神桌面伙伴 v{APP_VERSION} · 管理面板')
        self.setWindowIcon(self._app_icon())

        # 显式声明标准窗口：带标题栏与最小化/最大化/关闭按钮，
        # 并在任务栏占一个独立条目（不写这一句，任务栏上会找不到面板）
        self.setWindowFlags(Qt.Window | Qt.WindowCloseButtonHint
                            | Qt.WindowMinimizeButtonHint
                            | Qt.WindowMaximizeButtonHint)
        self.setAttribute(Qt.WA_DeleteOnClose, False)   # 关闭只隐藏，不销毁
        self.resize(960, 620)
        self.setMinimumSize(720, 480)

        # 标签页放在中央控件里（QMainWindow 的标准结构）
        central = QWidget(self)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(8, 6, 8, 6)
        self.tabs = QTabWidget(central)
        layout.addWidget(self.tabs)
        self.setCentralWidget(central)

        self._build_roles_tab()
        self._build_music_tab()
        self._build_assets_tab()
        self._build_kg_tab()
        self._build_window_tab()
        self._build_help_tab()
        self._build_shortcuts()
        # 知识图谱页首次被打开时才加载数据（1900+ 节点，避免拖慢面板启动）
        self.tabs.currentChanged.connect(self._on_tab_changed)
        self.refresh()

    def _app_icon(self):
        """面板图标：磁盘上的 icon256.ico 优先，缺文件时退回当前伙伴帧。

        不依赖资源库：打包后ico 在 ``_internal`` 里，
        而开发时资源又在 assets.db 中，两条路径都可能取不到。
        """
        return app_icon(getattr(self.store, 'base_dir', os.curdir),
                        self.pilot._frames[self.pilot.index][0]
                        if getattr(self.pilot, '_frames', None) else None)

    def _build_shortcuts(self):
        """给六个标签页各绑一个 Ctrl+数字 快捷键。

        面板没有菜单栏，标签页就是唯一的导航入口；但逐个点标签
        在宽屏上有点来回。用 <code>Ctrl+1</code> ~ <code>Ctrl+6</code>
        直接跳过去，比菜单快捷键更省一次鼠标移动。

        ⚠️ 必须在**所有标签页建好之后**调用：快捷键要按索引定位，
        少建一个就会绑到错位的页面上。
        """
        for index in range(self.tabs.count()):
            QShortcut(QKeySequence(f'Ctrl+{index + 1}'), self.tabs,
                      lambda _checked=False, i=index: self.tabs.setCurrentIndex(i))

    # ---------- 窗口与状态 ----------

    def _build_window_tab(self):
        """构建「窗口与状态」标签页。

        v3.8 新增：原先面板没有任何窗口状态入口（不能最小化、不能最大化），
        而为这几条命令单开一个菜单栏又多一层层级，故直接做成一个标签页：
        上半部分是窗口命令，下半部分是当前状态。
        """
        tab = QWidget()
        root = QVBoxLayout(tab)

        # ① 窗口操作：按钮文案随当前状态变化（_sync_window_state 负责同步）
        win_box = QGroupBox('窗口操作')
        win_layout = QVBoxLayout(win_box)

        self.btn_min = QPushButton('最小化')
        self.btn_min.setToolTip('把面板缩到任务栏，托盘图标仍在运行')
        self.btn_min.clicked.connect(self.showMinimized)
        self.btn_max = QPushButton('最大化')
        self.btn_max.clicked.connect(self._toggle_maximized)
        self.btn_full = QPushButton('全屏')
        self.btn_full.setToolTip('全屏后按 Esc 可退出（按钮会变成「退出全屏」）')
        self.btn_full.clicked.connect(self._toggle_fullscreen)
        win_row1 = QHBoxLayout()
        for btn in (self.btn_min, self.btn_max, self.btn_full):
            btn.setFixedSize(BTN_W, BTN_H)   # 全局统一尺寸，见 BTN_W/BTN_H
            win_row1.addWidget(btn)
        win_row1.addStretch(1)   # 按钮保持自身尺寸，不被拉伸填满整行
        win_layout.addLayout(win_row1)

        self.btn_hide = QPushButton('隐藏面板')
        self.btn_hide.setToolTip('隐藏面板但伙伴继续在桌面运行，可从托盘再次唤出')
        self.btn_hide.clicked.connect(self.hide)
        self.btn_hide.setFixedSize(BTN_W, BTN_H)
        win_row2 = QHBoxLayout()
        win_row2.addWidget(self.btn_hide)
        win_row2.addStretch(1)
        win_layout.addLayout(win_row2)

        # 伙伴显隐用勾选框而非按钮：它是**状态**而非**动作**，
        # 勾选框能同时表达「当前状态」与「点击切换」
        self.show_pilot_check = QCheckBox('显示桌面上的伙伴')
        self.show_pilot_check.setToolTip(
            '取消勾选即把伙伴设为透明（同托盘菜单的「隐藏」）')
        self.show_pilot_check.toggled.connect(self._toggle_pilot_visible)
        win_layout.addWidget(self.show_pilot_check)
        root.addWidget(win_box)

        # ② 当前状态
        info_box = QGroupBox('当前状态')
        info_form = QFormLayout(info_box)
        self.win_state_label = QLabel('-')
        self.cur_role_label = QLabel('-')
        self.store_label = QLabel('-')
        self.version_label = QLabel(f'原神桌面伙伴 v{APP_VERSION}')
        info_form.addRow('窗口状态:', self.win_state_label)
        info_form.addRow('当前伙伴:', self.cur_role_label)
        info_form.addRow('资源库:', self.store_label)
        info_form.addRow('版本:', self.version_label)
        root.addWidget(info_box)

        hint = QLabel('提示：面板只关闭不退出程序——彻底结束请用托盘菜单的「退出」。'
                      '伙伴本体只在系统托盘有图标，不占用任务栏。')
        hint.setStyleSheet('color: #7f8c8d;')
        hint.setWordWrap(True)
        root.addWidget(hint)
        root.addStretch(1)

        self.tabs.addTab(tab, '窗口与状态')

    def _toggle_maximized(self):
        """最大化 / 还原切换。"""
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()

    def _toggle_fullscreen(self):
        """全屏 / 退出全屏切换。

        全屏会盖住整个屏幕，因此除了按钮，还要允许 Esc 键退出
        （见 :meth:`keyPressEvent`）——否则用户会被困在全屏里。
        """
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()

    def _toggle_pilot_visible(self, checked):
        """显示 / 隐藏桌面上的伙伴（勾选 = 显示）。

        走 :meth:`Pilot.set_visible` 而不是直接设透明度：那样才能让托盘
        造成的显隐变化同步回本勾选框的状态。
        """
        self.pilot.set_visible(checked)

    def _window_state_text(self):
        """返回窗口状态的可读名称（多个状态同时置位时按优先级取）。"""
        if self.isFullScreen():
            return '全屏'
        if self.isMinimized():
            return '最小化'
        if self.isMaximized():
            return '最大化'
        return '正常'

    def _sync_window_state(self):
        """按当前状态更新「窗口与状态」页的按钮文字、勾选与状态标签。

        窗口状态变化（最小化 / 最大化 / 全屏）时由 changeEvent 调用；
        :meth:`Pilot.set_visible` 在托盘侧改变显隐时也回调这里。
        """
        if not hasattr(self, 'btn_max'):     # 标签页尚未建好（构造早期）
            return
        maximized = self.isMaximized()
        self.btn_max.setText('还原' if maximized else '最大化')
        full = self.isFullScreen()
        self.btn_full.setText('退出全屏' if full else '全屏')

        # 伙伴本体是「透明隐藏」，故用 opacity 判断可见性而不是 isVisible
        visible = self.pilot.windowOpacity() > 0
        if visible != self.show_pilot_check.isChecked():
            self.show_pilot_check.blockSignals(True)   # 避免程序性勾选触发回调
            self.show_pilot_check.setChecked(visible)
            self.show_pilot_check.blockSignals(False)

        self.win_state_label.setText(self._window_state_text())

    def changeEvent(self, event):
        """窗口状态变化时刷新「窗口与状态」页。

        必须调 ``super().changeEvent(event)``：QMainWindow 靠这个事件
        维护自身状态（如 QLabel 的尺寸 hint），漏掉会导致界面显示异常。
        """
        super().changeEvent(event)
        if event.type() == QEvent.Type.WindowStateChange:
            self._sync_window_state()

    def keyPressEvent(self, event):
        """Esc 退出全屏。

        全屏时标签页与标题栏控件都可能被盖住，若没有这个 Esc 退出路径，
        用户就得靠 Alt+Tab 切出去才能恢复——这是全屏最常见的坑。
        """
        if event.key() == Qt.Key.Key_Escape and self.isFullScreen():
            self.showNormal()
            return
        super().keyPressEvent(event)

    def _on_tab_changed(self, index):
        """切到知识图谱页时才加载图谱数据（大库首次加载约 0.7 秒）。"""
        if self.tabs.tabText(index) == '知识图谱':
            self._ensure_kg_loaded()

    # ================= 知识图谱 =================

    def _build_kg_tab(self):
        tab = QWidget()
        root = QVBoxLayout(tab)

        # 顶部：搜索栏 + 数据操作
        top = QHBoxLayout()
        self.kg_search = QLineEdit()
        self.kg_search.setPlaceholderText('搜索实体（人物/武器/材料/副本/料理…），回车定位')
        self.kg_search.setMaximumWidth(320)
        self.kg_completer = QCompleter(self)
        self.kg_completer.setCaseSensitivity(Qt.CaseInsensitive)
        self.kg_completer.setFilterMode(Qt.MatchContains)
        self.kg_search.setCompleter(self.kg_completer)
        self.kg_search.returnPressed.connect(self._on_kg_search)
        top.addWidget(self.kg_search)
        search_btn = QPushButton('定位')
        search_btn.setFixedSize(BTN_W, BTN_H)
        search_btn.clicked.connect(self._on_kg_search)
        top.addWidget(search_btn)
        top.addStretch(1)
        # 说明：CSV 导入/导出/重新载入已移到「素材管理」页（与素材的导入导出放一起）
        tip = QLabel('数据导入导出见「素材管理」页')
        tip.setStyleSheet('color: #7f8c8d;')
        top.addWidget(tip)
        root.addLayout(top)

        # 中部：画布 + 详情/关系/操作
        splitter = QSplitter(Qt.Horizontal)
        self.kg_canvas = KGCanvas()
        splitter.addWidget(self.kg_canvas)

        side = QWidget()
        side_layout = QVBoxLayout(side)
        side_layout.setContentsMargins(0, 0, 0, 0)

        self.kg_detail = QTextBrowser()
        self.kg_detail.setMaximumHeight(230)
        side_layout.addWidget(self.kg_detail)

        self.kg_rel_list = QListWidget()
        self.kg_rel_list.setToolTip('当前实体的关系，选中后可编辑或删除')
        self.kg_rel_list.currentRowChanged.connect(
            lambda _i: self._sync_kg_buttons())
        side_layout.addWidget(self.kg_rel_list, 1)

        # 实体与关系操作按钮
        node_row = QHBoxLayout()
        self.kg_add_node_btn = QPushButton('新增实体')
        self.kg_add_node_btn.clicked.connect(self._on_kg_add_node)
        self.kg_edit_node_btn = QPushButton('编辑实体')
        self.kg_edit_node_btn.clicked.connect(self._on_kg_edit_node)
        self.kg_del_node_btn = QPushButton('删除实体')
        self.kg_del_node_btn.clicked.connect(self._on_kg_delete_node)
        for btn in (self.kg_add_node_btn, self.kg_edit_node_btn, self.kg_del_node_btn):
            btn.setFixedSize(BTN_W-40, BTN_H)
            node_row.addWidget(btn)
        node_row.addStretch(1)
        side_layout.addLayout(node_row)

        rel_row = QHBoxLayout()
        self.kg_add_rel_btn = QPushButton('新增关系')
        self.kg_add_rel_btn.clicked.connect(self._on_kg_add_edge)
        self.kg_edit_rel_btn = QPushButton('编辑关系')
        self.kg_edit_rel_btn.clicked.connect(self._on_kg_edit_edge)
        self.kg_del_rel_btn = QPushButton('删除关系')
        self.kg_del_rel_btn.clicked.connect(self._on_kg_delete_edge)
        for btn in (self.kg_add_rel_btn, self.kg_edit_rel_btn, self.kg_del_rel_btn):
            btn.setFixedSize(BTN_W-40, BTN_H)
            rel_row.addWidget(btn)
        rel_row.addStretch(1)
        side_layout.addLayout(rel_row)

        side.setMaximumWidth(320)
        splitter.addWidget(side)
        splitter.setStretchFactor(0, 1)
        root.addWidget(splitter, 1)

        self.kg_status = QLabel('')
        self.kg_status.setStyleSheet('color: #7f8c8d;')
        root.addWidget(self.kg_status)

        legend = QLabel('　'.join(
            f'<font color="{color}">●</font>{cn}'
            for cn, color in NODE_TYPES.values()))
        legend.setTextFormat(Qt.RichText)
        legend.setStyleSheet('color: #7f8c8d;')
        root.addWidget(legend)

        hint = QLabel('单击节点查看详情，双击节点以其为中心展开，滚轮缩放、拖拽平移；'
                      '右侧可编辑实体与关系')
        hint.setStyleSheet('color: #7f8c8d;')
        root.addWidget(hint)

        self.kg_canvas.nodeSelected.connect(self._on_kg_node_selected)
        self.kg_canvas.nodeExpanded.connect(self._on_kg_node_expanded)
        self.tabs.addTab(tab, '知识图谱')

        self._kg_ready = False   # 图谱数据较大，首次切换到本页时再加载
        self._kg_current = None  # 当前选中实体键
        self._kg_rel_edges = []  # 与关系列表一一对应的 (rel, 对端键, 方向)

    def _ensure_kg_loaded(self):
        if self._kg_ready:
            return True
        try:
            self.kg = get_default_store(self.store.base_dir)
        except Exception as e:
            # 错误信息可能是多行（如 kg.db 缺失时的操作指引），逐行转义后换行显示
            detail = '<br>'.join(html.escape(line) for line in str(e).splitlines())
            self.kg_detail.setHtml(
                f'<p style="color:#c0392b"><b>知识图谱数据加载失败</b></p>'
                f'<p style="color:#7f8c8d">{detail}</p>'
                f'<p>知识图谱以 <code>kg.db</code> 随安装包分发（不含 CSV）。'
                f'若库文件缺失，可重新安装，或点上方「导入 CSV」'
                f'从 CSV 导入——CSV 既可由本地 <code>data/csv</code> 提供，'
                f'也可由服务器下发（格式完全相同）。</p>')
            return False
        self.kg_canvas.bind(self.kg)
        self._kg_refresh_completer()
        self._kg_update_status()
        self.kg_detail.setHtml(
            '<h3>原神知识图谱</h3>'
            '<p>在上方搜索框输入实体名称开始探索，例如：钟离、蒙德、护摩之杖。</p>'
            '<p>也可直接新增实体与关系，或用「导入 CSV」合并外部图谱数据。</p>')
        self._kg_ready = True
        self._sync_kg_buttons()
        self._update_kg_stat()      # 素材管理页的图谱统计随之更新
        return True

    def _kg_refresh_completer(self):
        self.kg_completer.setModel(QStringListModel(self.kg.all_names()))

    def _update_kg_stat(self):
        """素材管理页「知识图谱数据」分组的统计文本（图谱未载入时只提示位置）。"""
        if not hasattr(self, 'stat_kg'):
            return
        if getattr(self, '_kg_ready', False) and getattr(self, 'kg', None) is not None:
            ks = self.kg.stats()
            self.stat_kg.setText(
                f"SQLite (kg.db) · {ks['nodes']} 实体 / {ks['edges']} 关系")
        else:
            self.stat_kg.setText('SQLite (kg.db) · 打开「知识图谱」页后载入')

    def _kg_update_status(self):
        s = self.kg.stats()
        # db_size_mb 的类型是 float | None（文件后端时没有库文件），
        # 必须先判空再格式化，否则类型检查器报「不支持格式规范」
        size_mb = s['db_size_mb']
        size = f' · 库 {float(size_mb):.1f} MB' if size_mb is not None else ''
        # 附带数据来源（构建来源 / 版本），既是构建追溯，也便于将来核对服务器下发
        info = self.kg.info() if hasattr(self.kg, 'info') else {}
        origin = info.get('built_from', 'unknown')
        app_v = info.get('app_version', '')
        tail = f' · 来源 {origin}' + (f' v{app_v}' if app_v and app_v != 'unknown' else '')
        self.kg_status.setText(
            f'实体 {s["nodes"]} 个 · 关系 {s["edges"]} 条 · 存储 SQLite (kg.db){size}{tail}')
        self._update_kg_stat()      # 图谱变化后素材管理页的统计同步

    def _on_kg_search(self):
        if not self._ensure_kg_loaded():
            return
        text = self.kg_search.text().strip()
        if not text:
            return
        keys = self.kg.find(text)
        if not keys:
            keys = self.kg.search(text, limit=1)
        if not keys:
            self.kg_detail.setHtml(f'<p>未找到与「{text}」相关的实体。</p>')
            return
        self.kg_canvas.show_ego(keys[0])

    def _on_kg_node_selected(self, key):
        if not getattr(self, '_kg_ready', False):
            return
        node = self.kg.nodes.get(key)
        if node is None:
            return
        self._kg_current = key
        cn_type = NODE_TYPES.get(key[0], (key[0],))[0]
        parts = [f'<h3>{key[1]} <small style="color:#7f8c8d">[{cn_type}]</small></h3>']
        if node['attrs']:
            parts.append('<table border="0" cellspacing="0" cellpadding="2">')
            for k, v in node['attrs'].items():
                v = v.replace('<', '&lt;')
                if len(v) > 300:
                    v = v[:300] + '…'
                parts.append(f'<tr><td><b>{k}</b></td><td>{v}</td></tr>')
            parts.append('</table>')
        else:
            parts.append('<p style="color:#7f8c8d">（无属性）</p>')
        self.kg_detail.setHtml(''.join(parts))
        self._kg_fill_relations(key)
        self._sync_kg_buttons()

    def _kg_fill_relations(self, key):
        """把当前实体有向关系填进列表：出边显示「关系 → 对端」，入边显示「对端 → 关系」。"""
        self.kg_rel_list.blockSignals(True)
        self.kg_rel_list.clear()
        self._kg_rel_edges = []
        for rel, other, direction in self.kg.edges_of(key):
            o_type = NODE_TYPES.get(other[0], (other[0],))[0]
            arrow = '→' if direction == 'out' else '←'
            self.kg_rel_list.addItem(f'{rel_cn(rel)} {arrow} {other[1]}  [{o_type}]')
            self._kg_rel_edges.append((rel, other, direction))
        self.kg_rel_list.blockSignals(False)
        if not self._kg_rel_edges:
            self.kg_rel_list.addItem('（暂无关系）')
            self.kg_rel_list.setEnabled(False)
        else:
            self.kg_rel_list.setEnabled(True)

    def _on_kg_node_expanded(self, key):
        self.kg_canvas.show_ego(key)

    # ---------- 知识图谱：实体编辑 ----------

    def _sync_kg_buttons(self):
        """按当前选中实体与关系列表选中项启用/禁用按钮。"""
        has_node = getattr(self, '_kg_current', None) is not None
        has_rel = bool(getattr(self, '_kg_rel_edges', [])) and \
            self.kg_rel_list.currentRow() >= 0
        for btn in (self.kg_edit_node_btn, self.kg_del_node_btn):
            btn.setEnabled(has_node)
        for btn in (self.kg_add_rel_btn, self.kg_edit_rel_btn, self.kg_del_rel_btn):
            btn.setEnabled(has_node)
        self.kg_edit_rel_btn.setEnabled(has_rel)
        self.kg_del_rel_btn.setEnabled(has_rel)

    def _kg_selected_edge(self):
        """返回关系列表当前选中项 (rel, 对端键, 方向)，未选中返回 None。"""
        row = self.kg_rel_list.currentRow()
        if 0 <= row < len(getattr(self, '_kg_rel_edges', [])):
            return self._kg_rel_edges[row]
        return None

    def _kg_after_change(self, keep_key=None, keep_edge=None):
        """编辑/导入后统一刷新：索引、自动补全、状态、画布与详情。"""
        self._kg_refresh_completer()
        self._kg_update_status()
        key = keep_key or self._kg_current
        if key is not None and key not in self.kg.nodes:
            key = None
        if key is None:
            self._kg_current = None
            self.kg_canvas.clear()
            self.kg_rel_list.clear()
            self._kg_rel_edges = []
            self.kg_detail.setHtml('<p style="color:#7f8c8d">'
                                   '当前实体已不存在，请重新搜索定位。</p>')
            self._sync_kg_buttons()
            return
        self.kg_canvas.show_ego(key)
        if keep_edge is not None:
            # 关系列表重建后按关系名+对端重新定位，保持选中
            for i, (rel, other, _d) in enumerate(self._kg_rel_edges):
                if rel == keep_edge[0] and other == keep_edge[1]:
                    self.kg_rel_list.setCurrentRow(i)
                    break
        self._sync_kg_buttons()

    def _on_kg_add_node(self):
        if not self._ensure_kg_loaded():
            return
        dlg = NodeEditDialog(self.kg, None, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        ntype, name, attrs = dlg.values()
        try:
            created = self.kg.add_node(ntype, name, attrs, overwrite=False)
        except ValueError as e:
            QMessageBox.warning(self, '新增失败', str(e))
            return
        if not created:
            QMessageBox.information(
                self, '已存在',
                f'「{type_cn(ntype)} · {name}」已存在。'
                '如需修改其属性，请使用「编辑实体」。')
            return
        self._kg_after_change(keep_key=(ntype, name))

    def _on_kg_edit_node(self):
        key = getattr(self, '_kg_current', None)
        if key is None or not self._ensure_kg_loaded():
            return
        dlg = NodeEditDialog(self.kg, key, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        ntype, name, attrs = dlg.values()
        try:
            new_key = self.kg.update_node(key, name=name, ntype=ntype, attrs=attrs)
        except (ValueError, KeyError) as e:
            QMessageBox.warning(self, '保存失败', str(e).strip("'"))
            return
        self._kg_after_change(keep_key=new_key)

    def _on_kg_delete_node(self):
        key = getattr(self, '_kg_current', None)
        if key is None or not self._ensure_kg_loaded():
            return
        n_rel = len(self.kg.edges_of(key))
        ret = QMessageBox.question(
            self, '确认删除',
            f'确定删除实体「{key[1]}」吗？\n其关联的 {n_rel} 条关系也会一并删除。')
        if ret != QMessageBox.StandardButton.Yes:
            return
        nodes, edges = self.kg.delete_node(key)
        self._kg_current = None
        self._kg_after_change()
        QMessageBox.information(
            self, '已删除', f'已删除实体 {nodes} 个、关联关系 {edges} 条。')

    # ---------- 知识图谱：关系编辑 ----------

    def _on_kg_add_edge(self):
        anchor = getattr(self, '_kg_current', None)
        if not self._ensure_kg_loaded():
            return
        dlg = EdgeEditDialog(self.kg, None, anchor=anchor,
                             exclude=[anchor] if anchor else (), parent=self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        src, rel, dst = dlg.values()
        missing = [n for n, k in (('源', src), ('目标', dst)) if k is None]
        if missing or not rel:
            QMessageBox.warning(self, '信息不完整', '请填写关系名与两端实体。')
            return
        try:
            for key in (src, dst):
                if key not in self.kg.nodes:      # 对话框允许直接输入新实体名
                    self.kg.add_node(key[0], key[1], {}, overwrite=False)
            created = self.kg.add_edge(src, rel, dst, overwrite=False)
        except (ValueError, KeyError) as e:
            QMessageBox.warning(self, '新增失败', str(e).strip("'"))
            return
        if not created:
            QMessageBox.information(self, '已存在', '这两者之间已存在同名关系。')
            return
        self._kg_after_change(keep_edge=(rel, dst))

    def _on_kg_edit_edge(self):
        anchor = getattr(self, '_kg_current', None)
        selected = self._kg_selected_edge()
        if anchor is None or selected is None or not self._ensure_kg_loaded():
            return
        rel, other, direction = selected
        # 统一以当前实体为源端构造有向三元组，方向由列表给出
        edge = (anchor, rel, other) if direction == 'out' else (other, rel, anchor)
        dlg = EdgeEditDialog(self.kg, edge=edge, anchor=anchor, parent=self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        src, new_rel, dst = dlg.values()
        missing = [n for n, k in (('源', src), ('目标', dst)) if k is None]
        if missing or not new_rel:
            QMessageBox.warning(self, '信息不完整', '请填写关系名与两端实体。')
            return
        try:
            for key in (src, dst):
                if key not in self.kg.nodes:
                    self.kg.add_node(key[0], key[1], {}, overwrite=False)
            self.kg.update_edge(edge, (src, new_rel, dst))
        except (ValueError, KeyError) as e:
            QMessageBox.warning(self, '保存失败', str(e).strip("'"))
            return
        self._kg_after_change(keep_edge=(new_rel, dst))

    def _on_kg_delete_edge(self):
        anchor = getattr(self, '_kg_current', None)
        selected = self._kg_selected_edge()
        if anchor is None or selected is None or not self._ensure_kg_loaded():
            return
        rel, other, _direction = selected
        ret = QMessageBox.question(
            self, '确认删除',
            f'确定删除关系「{rel_cn(rel)}」吗？\n{anchor[1]} — {rel_cn(rel)} — {other[1]}')
        if ret != QMessageBox.StandardButton.Yes:
            return
        self.kg.delete_edge_touching(anchor, rel, other)
        self._kg_after_change()

    # ---------- 知识图谱：导入 / 导出 / 重载 ----------

    def _on_kg_import(self):
        """导入 CSV：选来源类型（目录 / 单文件），再选合并或覆盖。

        对话框只有**一层**——选定来源后紧接着问合并/覆盖，导出结果
        用同一套标准按钮呈现。原先这里先弹一个自建的三按钮 QMessageBox、
        再弹一个 Yes/No/Cancel，语义混乱（"确定" 到底是选哪个？）且容易
        在取消后仍往下走。
        """
        if not self._ensure_kg_loaded():
            return
        box = QMessageBox(self)
        box.setWindowTitle('导入知识图谱')
        box.setIcon(QMessageBox.Icon.Question)
        box.setText('请选择要导入的内容：')
        box.setInformativeText(
            '• CSV 目录：含 label-*.csv 与 rel-*.csv，是知识图谱的完整原始布局\n'
            '• 单个 CSV：只导入一张表（实体表或关系表），用于补充零散数据')
        dir_btn = box.addButton('CSV 目录…', QMessageBox.ButtonRole.AcceptRole)
        file_btn = box.addButton('单个 CSV 文件…', QMessageBox.ButtonRole.AcceptRole)
        box.addButton(QMessageBox.StandardButton.Cancel)
        box.setDefaultButton(QMessageBox.StandardButton.Cancel)
        box.exec()
        clicked = box.clickedButton()
        if clicked is dir_btn:
            path = QFileDialog.getExistingDirectory(
                self, '选择知识图谱 CSV 目录')
        elif clicked is file_btn:
            path, _ = QFileDialog.getOpenFileName(
                self, '选择知识图谱 CSV（实体表或关系表）', '', 'CSV 文件 (*.csv)')
        else:
            return                      # 取消或直接关窗：什么都不做
        if not path:
            return                      # 在文件对话框里取消
        self._kg_do_import(path)

    def _kg_do_import(self, path):
        """导入前确认合并 / 覆盖（覆盖会清空现有图谱），取消则不执行。"""
        s = self.kg.stats()
        box = QMessageBox(self)
        box.setWindowTitle('导入知识图谱')
        box.setIcon(QMessageBox.Icon.Warning)
        box.setText(f'确定把「{os.path.basename(path)}」导入当前图谱吗？')
        box.setInformativeText(
            f'当前库：实体 {s["nodes"]} 个、关系 {s["edges"]} 条。\n\n'
            f'合并：保留现有内容，同名实体的属性被导入值覆盖\n'
            f'覆盖：先清空当前图谱再导入（原内容将丢失）')
        merge_btn = box.addButton('合并', QMessageBox.ButtonRole.AcceptRole)
        replace_btn = box.addButton('覆盖', QMessageBox.ButtonRole.DestructiveRole)
        box.addButton(QMessageBox.StandardButton.Cancel)
        box.setDefaultButton(merge_btn)     # 默认走安全的那条路
        box.exec()
        clicked = box.clickedButton()
        if clicked is merge_btn:
            replace = False
        elif clicked is replace_btn:
            replace = True
        else:
            return                          # 取消 / 关窗：不导入
        try:
            report = self.kg.import_csv(path, replace=replace)
        except Exception as e:
            QMessageBox.warning(self, '导入失败', str(e))
            return
        self._kg_current = None
        self._kg_after_change()
        msg = (f'实体：新增 {report["nodes_added"]}，更新 {report["nodes_updated"]}\n'
               f'关系：新增 {report["edges_added"]}，跳过 {report["edges_skipped"]}')
        if report['stubs']:
            msg += f'\n自动补建实体 {report["stubs"]} 个'
        if report['ignored_files']:
            msg += f'\n忽略无法识别的文件：{", ".join(report["ignored_files"])}'
        QMessageBox.information(self, '导入完成', msg)

    def _on_kg_export(self):
        if not self._ensure_kg_loaded():
            return
        path = QFileDialog.getExistingDirectory(self, '选择导出目录')
        if not path:
            return
        try:
            report = self.kg.export_csv(path)
        except Exception as e:
            QMessageBox.warning(self, '导出失败', str(e))
            return
        QMessageBox.information(
            self, '导出完成',
            f'实体表 {report["node_files"]} 个（{report["node_rows"]} 行）\n'
            f'关系表 {report["edge_files"]} 个（{report["edge_rows"]} 行）\n\n'
            f'已导出到：{report["dir"]}\n'
            f'该目录可被「导入 CSV」整目录回灌。')

    def _on_kg_reload(self):
        """重置单例并重新打开数据库，丢弃内存中的未落库改动。"""
        if not self._ensure_kg_loaded():
            return
        reset_default_store()
        self._kg_ready = False
        self._kg_current = None
        if self._ensure_kg_loaded():
            self._kg_after_change()
        QMessageBox.information(self, '已重新载入', '知识图谱已从 kg.db 重新读入。')


    # ================= 帮助文档 =================

    def _build_help_tab(self):
        tab = QWidget()
        root = QVBoxLayout(tab)
        browser = QTextBrowser()
        # v3.8：HTML 独立成 res/help.html，程序启动时动态读取，
        # 不再把大段帮助文案硬编码在 manager_panel.py 里
        browser.setHtml(load_help_html(getattr(self.store, 'base_dir', os.curdir)))
        browser.setOpenExternalLinks(True)  # 链接交给系统浏览器打开
        root.addWidget(browser)
        self.tabs.addTab(tab, '帮助文档')

    # ================= 人物管理 =================

    def _build_roles_tab(self):
        tab = QWidget()
        root = QHBoxLayout(tab)

        self.role_list = QListWidget()
        self.role_list.setMaximumWidth(200)
        self.role_list.currentTextChanged.connect(self._on_role_selected)
        root.addWidget(self.role_list)

        right = QVBoxLayout()

        preview_row = QHBoxLayout()
        self.preview = QLabel('（无预览）')
        self.preview.setFixedSize(180, 180)
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setStyleSheet('border: 1px solid #ccc; background: transparent;')
        preview_row.addWidget(self.preview)

        info_box = QGroupBox('信息')
        info_form = QFormLayout(info_box)
        self.role_frames_label = QLabel('-')
        self.role_voices_label = QLabel('-')
        self.role_status_label = QLabel('-')
        info_form.addRow('帧数量:', self.role_frames_label)
        info_form.addRow('语音数量:', self.role_voices_label)
        info_form.addRow('状态:', self.role_status_label)
        preview_row.addWidget(info_box, stretch=1)
        right.addLayout(preview_row)

        setting_box = QGroupBox('播放设置（对该人物生效）')
        setting_form = QFormLayout(setting_box)
        self.interval_spin = QSpinBox()
        self.interval_spin.setRange(20, 1000)
        self.interval_spin.setSuffix(' ms')
        self.scale_spin = QDoubleSpinBox()
        self.scale_spin.setRange(0.1, 3.0)
        self.scale_spin.setSingleStep(0.05)
        self.scale_spin.setDecimals(2)
        setting_form.addRow('帧间隔:', self.interval_spin)
        setting_form.addRow('缩放比例:', self.scale_spin)
        right.addWidget(setting_box)

        btn_row = QHBoxLayout()
        self.apply_btn = QPushButton('应用设置')
        self.apply_btn.clicked.connect(self._apply_role_settings)
        self.set_current_btn = QPushButton('设为当前伙伴')
        self.set_current_btn.clicked.connect(self._set_current_role)
        self.delete_btn = QPushButton('删除此人物')
        self.delete_btn.clicked.connect(self._delete_role)
        for btn in (self.apply_btn, self.set_current_btn, self.delete_btn):
            btn.setFixedSize(BTN_W, BTN_H)   # 全局统一尺寸，见 BTN_W/BTN_H
            btn_row.addWidget(btn)
        btn_row.addStretch(1)
        right.addLayout(btn_row)
        right.addStretch(1)

        root.addLayout(right, stretch=1)
        self.tabs.addTab(tab, '人物管理')

    def _on_role_selected(self, role):
        if not role:
            return
        frames = self.store.list_frames(role)
        voices = self.store.list_voices(role)
        self.role_frames_label.setText(str(len(frames)))
        self.role_voices_label.setText(str(len(voices)))
        self.role_status_label.setText('当前伙伴' if role == self.pilot.role_name else '未使用')
        self.role_status_label.setStyleSheet(
            'color: #d33; font-weight: bold;' if role == self.pilot.role_name else '')

        if frames:
            pm = QPixmap()
            pm.loadFromData(self.store.read_frame(role, frames[0]))
            self.preview.setPixmap(pm.scaled(
                self.preview.size(), Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation))
        else:
            self.preview.setPixmap(QPixmap())
            self.preview.setText('（无帧）')

        interval, scale = self.config['frame_scale'].get(role, [60, 1.0])
        self.interval_spin.setValue(int(interval))
        self.scale_spin.setValue(float(scale))

    def _selected_role(self):
        item = self.role_list.currentItem()
        return item.text() if item else None

    def _apply_role_settings(self):
        role = self._selected_role()
        if not role:
            return
        self.pilot.set_role_timing(role, self.interval_spin.value(), self.scale_spin.value())
        QMessageBox.information(self, '已应用', f'「{role}」的播放设置已保存。')

    def _set_current_role(self):
        role = self._selected_role()
        if not role or role == self.pilot.role_name:
            return
        self.pilot.reshow(role)
        self._on_role_selected(role)
        self.pilot.save_config()

    def _delete_role(self):
        role = self._selected_role()
        if not role:
            return
        roles = self.store.list_roles()
        if len(roles) <= 1:
            QMessageBox.warning(self, '无法删除', '至少需要保留一个人物。')
            return
        ret = QMessageBox.question(
            self, '确认删除',
            f'确定删除「{role}」的全部帧和语音吗？此操作不可恢复。')
        if ret != QMessageBox.StandardButton.Yes:
            return
        try:
            self.store.delete_role(role)
        except RuntimeError as e:
            QMessageBox.warning(self, '无法删除', str(e))
            return
        self.config['frame_scale'].pop(role, None)
        if role == self.pilot.role_name:
            self.pilot.reshow(self.store.list_roles()[0])
        self.pilot._rebuild_role_menu()
        self.pilot.save_config()
        self.refresh()

    # ================= 音乐管理 =================

    def _build_music_tab(self):
        tab = QWidget()
        root = QHBoxLayout(tab)

        self.area_list = QListWidget()
        self.area_list.setMaximumWidth(200)
        root.addWidget(self.area_list)

        right = QVBoxLayout()
        bgm_box = QGroupBox('背景音乐')
        bgm_row = QHBoxLayout(bgm_box)
        self.play_bgm_btn = QPushButton('播放选中地区')
        self.play_bgm_btn.clicked.connect(self._play_selected_area)
        self.stop_bgm_btn = QPushButton('停止背景音乐')
        self.stop_bgm_btn.clicked.connect(self._stop_bgm)
        for btn in (self.play_bgm_btn, self.stop_bgm_btn):
            btn.setFixedSize(BTN_W, BTN_H)
            bgm_row.addWidget(btn)
        bgm_row.addStretch(1)
        right.addWidget(bgm_box)

        self.bgm_state_label = QLabel('-')
        right.addWidget(self.bgm_state_label)

        voice_box = QGroupBox('人物语音')
        voice_layout = QVBoxLayout(voice_box)
        self.voice_checkbox = QCheckBox('启用人物语音（问候 / 闲聊 / 了解）')
        self.voice_checkbox.toggled.connect(self.pilot.set_voice_enabled)
        voice_layout.addWidget(self.voice_checkbox)
        right.addWidget(voice_box)

        self.mute_all_btn = QPushButton('关闭所有声音')
        self.mute_all_btn.setFixedSize(BTN_W, BTN_H)
        self.mute_all_btn.clicked.connect(self._mute_all)
        right.addWidget(self.mute_all_btn)
        right.addStretch(1)

        root.addLayout(right, stretch=1)
        self.tabs.addTab(tab, '音乐管理')

    def _play_selected_area(self):
        item = self.area_list.currentItem()
        if not item:
            return
        self.pilot.play_area_bgm(item.text())
        self._refresh_music_state()

    def _stop_bgm(self):
        self.pilot.stop_bgm()
        self._refresh_music_state()

    def _mute_all(self):
        self.pilot.set_voice_enabled(False)
        self.pilot.stop_bgm()
        self._refresh_music_state()

    def _refresh_music_state(self):
        current = self.config.get('bg_music')
        self.bgm_state_label.setText(
            f'正在播放: {current}' if current else '背景音乐: 未播放')
        self.voice_checkbox.blockSignals(True)
        self.voice_checkbox.setChecked(self.pilot.audio_player)
        self.voice_checkbox.blockSignals(False)

    # ================= 素材管理 =================

    def _build_assets_tab(self):
        tab = QWidget()
        root = QVBoxLayout(tab)

        stats_box = QGroupBox('资源统计')
        stats_form = QFormLayout(stats_box)
        self.stat_backend = QLabel('-')
        self.stat_roles = QLabel('-')
        self.stat_areas = QLabel('-')
        self.stat_frames = QLabel('-')
        self.stat_voices = QLabel('-')
        self.stat_size = QLabel('-')
        stats_form.addRow('存储后端:', self.stat_backend)
        stats_form.addRow('人物数量:', self.stat_roles)
        stats_form.addRow('地区数量:', self.stat_areas)
        stats_form.addRow('帧总数:', self.stat_frames)
        stats_form.addRow('语音总数:', self.stat_voices)
        stats_form.addRow('数据库大小:', self.stat_size)
        root.addWidget(stats_box)

        # 导入与导出是**两个独立模块**（各自分组），但按钮尺寸保持一致——
        # 尺寸由模块级常量 BTN_W/BTN_H 统一设定，五个页面全部共用。
        import_box = QGroupBox('导入素材（新人物 / 新地区，导入后立即出现在菜单中）')
        import_row = QHBoxLayout(import_box)
        import_zip_btn = QPushButton('导入 zip 素材包')
        import_zip_btn.setToolTip('从 zip 素材包导入人物帧、语音与地区背景音乐')
        import_zip_btn.clicked.connect(self._import_zip)
        import_dir_btn = QPushButton('导入素材目录')
        import_dir_btn.setToolTip('从 png/ 与 music/ 目录树导入')
        import_dir_btn.clicked.connect(self._import_dir)
        refresh_btn = QPushButton('刷新统计')
        refresh_btn.setToolTip('重新读取资源库并刷新上方统计')
        refresh_btn.clicked.connect(self.refresh)
        for btn in (import_zip_btn, import_dir_btn, refresh_btn):
            btn.setFixedSize(BTN_W, BTN_H)
            import_row.addWidget(btn)
        import_row.addStretch(1)   # 按钮保持自身尺寸，不被拉伸填满整行
        root.addWidget(import_box)

        export_box = QGroupBox('导出素材（还原为 png/ 与 music/ 目录，可直接再导入或分享）')
        export_row = QHBoxLayout(export_box)
        # 范围选择放在按钮之前：先限定范围再点导出，符合「先选后做」的顺序
        self.export_scope_combo = QComboBox()
        self.export_scope_combo.addItem('全部素材', None)
        self.export_scope_combo.addItem('仅当前人物', 'current')
        self.export_scope_combo.setToolTip('「仅当前人物」只导出该角色的帧与语音，不含地区背景音乐')
        self.export_scope_combo.setFixedSize(BTN_W, BTN_H)
        export_dir_btn = QPushButton('导出为目录')
        export_dir_btn.setToolTip('写出 png/<角色>、music/<角色>、music/<地区> 目录树')
        export_dir_btn.clicked.connect(lambda: self._export_assets(as_zip=False))
        export_zip_btn = QPushButton('导出为 zip')
        export_zip_btn.setToolTip('打包成单个 zip，体积不变但便于传输')
        export_zip_btn.clicked.connect(lambda: self._export_assets(as_zip=True))
        export_row.addWidget(self.export_scope_combo)
        for btn in (export_dir_btn, export_zip_btn):
            btn.setFixedSize(BTN_W, BTN_H)
            export_row.addWidget(btn)
        export_row.addStretch(1)
        root.addWidget(export_box)

        # 配置导入导出（v3.4：配置改由 config.db 管理）
        cfg_box = QGroupBox('配置文件（存于 config.db，可导出 JSON 备份或迁移到其他机器）')
        cfg_layout = QVBoxLayout(cfg_box)
        cfg_form = QFormLayout()
        self.stat_config = QLabel('-')
        self.stat_config_roles = QLabel('-')
        cfg_form.addRow('配置存储:', self.stat_config)
        cfg_form.addRow('已登记人物:', self.stat_config_roles)
        cfg_layout.addLayout(cfg_form)

        cfg_row = QHBoxLayout()
        # v3.8：配置导入导出一律用 JSON，不再提供 YAML
        export_json_btn = QPushButton('导出 JSON')
        export_json_btn.setToolTip('把当前配置导出为 JSON 文件，便于备份与迁移')
        export_json_btn.clicked.connect(lambda: self._export_config('json'))
        import_cfg_btn = QPushButton('导入配置')
        import_cfg_btn.setToolTip('从 JSON 配置文件导入，可选覆盖或合并')
        import_cfg_btn.clicked.connect(self._import_config)
        # v3.6：移除「恢复出厂设置」——它会清空用户调好的缩放/帧率，风险大于便利。
        # 需要恢复出厂值时删掉 config.db 后重新安装即可（见帮助页说明）。
        # 与导入/导出按钮共用同一尺寸常量，三组按钮外观完全一致
        for btn in (export_json_btn, import_cfg_btn):
            btn.setFixedSize(BTN_W, BTN_H)
            cfg_row.addWidget(btn)
        cfg_row.addStretch(1)   # 按钮保持自身尺寸，不被拉伸填满整行
        cfg_layout.addLayout(cfg_row)
        root.addWidget(cfg_box)

        # 知识图谱数据（v3.7 从「知识图谱」页迁来，与素材的导入导出放在一起）
        kg_box = QGroupBox('知识图谱数据（存于 kg.db，可导入 / 导出 CSV 备份或迁移）')
        kg_layout = QVBoxLayout(kg_box)
        kg_form = QFormLayout()
        self.stat_kg = QLabel('-')
        kg_form.addRow('图谱存储:', self.stat_kg)
        kg_layout.addLayout(kg_form)

        kg_row = QHBoxLayout()
        kg_import_btn = QPushButton('导入图谱 CSV')
        kg_import_btn.setToolTip('从 CSV 目录或单个 CSV 文件导入图谱数据（可选合并 / 覆盖）')
        kg_import_btn.clicked.connect(self._on_kg_import)
        kg_export_btn = QPushButton('导出图谱 CSV')
        kg_export_btn.setToolTip('把当前图谱导出为 CSV 目录，可整目录回灌')
        kg_export_btn.clicked.connect(self._on_kg_export)
        kg_reload_btn = QPushButton('重新载入图谱')
        kg_reload_btn.setToolTip('重新打开 kg.db，刷新图谱页显示')
        kg_reload_btn.clicked.connect(self._on_kg_reload)
        for btn in (kg_import_btn, kg_export_btn, kg_reload_btn):
            btn.setFixedSize(BTN_W, BTN_H)
            kg_row.addWidget(btn)
        kg_row.addStretch(1)
        kg_layout.addLayout(kg_row)
        root.addWidget(kg_box)

        root.addStretch(1)

        self.tabs.addTab(tab, '素材管理')

    def _export_assets(self, as_zip=False):
        """导出素材：按所选范围与格式导出全部帧/语音/BGM。

        素材库约 460MB，导出会耗时，故用带进度条的模态对话框；期间界面冻结属
        正常现象（读写都是顺序 IO），对话框上的「取消」可在完成后生效。
        """
        scope = self.export_scope_combo.currentData()
        roles = [self._selected_role()] if scope == 'current' else None
        areas = None
        if scope == 'current':
            if not roles[0]:
                QMessageBox.information(
                    self, '请先选择人物',
                    '「仅当前人物」需要先在「人物管理」里选中一个角色。')
                return
            # 「仅当前人物」只导该人物，不导地区背景音乐——它们与人物无关，
            # 全量带上会平白多出几 MB 且与选项名不符。
            areas = []

        if as_zip:
            default = '桌面伙伴素材.zip'
            path, _ = QFileDialog.getSaveFileName(
                self, '导出素材为 zip', default, 'Zip 压缩包 (*.zip)')
            if not path:
                return
            out_path = path
        else:
            out_dir = QFileDialog.getExistingDirectory(self, '选择导出目录')
            if not out_dir:
                return
            out_path = os.path.join(out_dir, '桌面伙伴素材')

        dlg = QProgressDialog('正在导出素材…', '取消', 0, 100, self)
        dlg.setWindowTitle('导出素材')
        dlg.setWindowModality(Qt.WindowModal)
        dlg.setMinimumDuration(300)   # 300ms 内完成就不闪一下
        dlg.setAutoClose(False)
        dlg.setAutoReset(False)

        def on_progress(done, total, label):
            dlg.setMaximum(total)
            dlg.setValue(done)
            dlg.setLabelText(f'正在导出 {done}/{total}\n{os.path.basename(label)}')
            QApplication.processEvents()

        try:
            report = export_assets(self.store, out_path, roles=roles, areas=areas,
                                   as_zip=as_zip, progress=on_progress)
        except Exception as e:
            dlg.close()
            QMessageBox.warning(self, '导出失败', str(e))
            return
        finally:
            dlg.close()

        size = _human_size(report['bytes'])
        QMessageBox.information(
            self, '导出完成',
            f'文件 {report["files"]} 个（{size}）\n'
            f'人物 {report["roles"]} 个 · 地区 {report["areas"]} 个\n\n'
            f'已导出到：{report["path"]}\n\n'
            f'导出结果符合素材包格式，可用「导入素材」直接并入。')

    def _export_config(self, fmt='json'):
        """导出配置到用户选择的路径（v3.8 起只有 JSON）。

        保留 ``fmt`` 参数是为了兼容旧调用方；任何非 json 的取值都会
        退回 JSON，避免留下「导出 YAML」的死路径。
        """
        try:
            path, _ = QFileDialog.getSaveFileName(
                self, '导出配置为 JSON', 'pilot_config.json',
                'JSON 配置 (*.json)')
            if not path:
                return
            self.config_store.export_json(path)
        except Exception as e:
            QMessageBox.warning(self, '导出失败', str(e))
            return
        QMessageBox.information(self, '导出完成', f'配置已导出到：\n{path}')

    def _import_config(self):
        """导入 JSON 配置文件，先确认覆盖或合并。"""
        path, _ = QFileDialog.getOpenFileName(
            self, '选择配置文件', '', 'JSON 配置 (*.json)')
        if not path:
            return
        ret = QMessageBox.question(
            self, '导入配置',
            f'将导入：{os.path.basename(path)}\n\n'
            f'确定 = 覆盖（当前设置全部替换）\n'
            f'取消 = 合并（只补充缺失的人物登记，保留现有设置）\n',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            | QMessageBox.StandardButton.Cancel)
        if ret == QMessageBox.StandardButton.Cancel:
            return
        replace = ret == QMessageBox.StandardButton.Yes
        try:
            report = self.config_store.import_file(path, replace=replace)
        except Exception as e:
            QMessageBox.warning(self, '导入失败', str(e))
            return
        # 覆盖可能换掉当前人物/语音开关/背景音乐，需重载并重建界面
        self.pilot.reload_config()
        self.config.clear()
        self.config.update(self.pilot.config)
        self._after_config_change()
        msg = (f'设置项 {report["scalars"]} 个已更新\n'
               f'人物登记：新增 {report["roles_added"]}，保留 {report["roles_kept"]}')
        if report['unknown_keys']:
            msg += f'\n忽略无法识别的键：{", ".join(report["unknown_keys"])}'
        if report['mode'] == 'replace':
            msg += '\n\n当前伙伴与音频开关已按导入的配置切换。'
        QMessageBox.information(self, '导入完成', msg)

    def _after_config_change(self):
        """配置被导入后刷新面板与托盘菜单。"""
        self.refresh()
        self.pilot.reshow(self.pilot.role_name)
        self.pilot._rebuild_role_menu()
        self.pilot._rebuild_bgm_menu()

    def _do_import(self, path):
        try:
            report = self.pilot.import_from_path(path)
        except Exception as e:
            QMessageBox.warning(self, '导入失败', str(e))
            return
        self.refresh()
        QMessageBox.information(
            self, '导入完成',
            f"帧 {report['frames']} / 语音 {report['voices']} / BGM {report['bgms']}\n"
            f"新角色: {', '.join(report['new_roles']) or '无'}\n"
            f"地区: {', '.join(report['areas']) or '无'}")

    def _import_zip(self):
        path, _ = QFileDialog.getOpenFileName(self, '选择素材包（zip）', '', 'Zip 素材包 (*.zip)')
        if path:
            self._do_import(path)

    def _import_dir(self):
        path = QFileDialog.getExistingDirectory(self, '选择素材包目录')
        if path:
            self._do_import(path)

    # ================= 通用刷新 =================

    def refresh(self):
        """重新加载人物/地区列表与统计，保持当前选中项。"""
        current_role = self._selected_role()
        self.role_list.blockSignals(True)
        self.role_list.clear()
        self.role_list.addItems(self.store.list_roles())
        self.role_list.blockSignals(False)
        target = current_role or self.pilot.role_name
        matches = self.role_list.findItems(target, Qt.MatchFlag.MatchExactly)
        if matches:
            self.role_list.setCurrentItem(matches[0])
        elif self.role_list.count():
            self.role_list.setCurrentRow(0)

        self.area_list.clear()
        self.area_list.addItems(self.store.list_bgm_areas())
        self._refresh_music_state()

        s = self.store.stats()
        self.stat_backend.setText('SQLite (assets.db)' if s['backend'] == 'sqlite' else '文件系统目录')
        self.stat_roles.setText(str(s['roles']))
        self.stat_areas.setText(str(s['areas']))
        self.stat_frames.setText(str(s['frames']))
        self.stat_voices.setText(str(s['voices']))
        # db_size_mb 是 float | None（文件后端无库文件），先判空再格式化
        size_mb = s['db_size_mb']
        self.stat_size.setText(f'{float(size_mb):.1f} MB' if size_mb is not None else '-')

        cs = self.config_store.stats()
        # 同理：db_size_kb 也显式转 float，避免联合类型触发格式规范警告
        self.stat_config.setText(
            f"SQLite ({os.path.basename(cs['db_path'])}) · {float(cs['db_size_kb']):.0f} KB")
        self.stat_config_roles.setText(str(cs['roles']))

        # 知识图谱：未加载时只提示位置，不强制打开（大库首次加载约 0.7 秒）
        self._update_kg_stat()
        # v3.8：「窗口与状态」页的当前伙伴 / 资源库 / 窗口状态
        self._sync_window_state()
        self.cur_role_label.setText(self.pilot.role_name)
        self.store_label.setText(
            f'SQLite (assets.db) · {float(s["db_size_mb"]):.1f} MB'
            if s.get('db_size_mb') is not None
            else f'文件系统目录 · {s["roles"]} 人')

    def closeEvent(self, event):
        """关闭 = 隐藏到托盘，而不是销毁面板。

        v3.8 之前这里直接销毁：用户点一次关闭，下次打开就要重建整个面板
        （丢失已填的表单、图谱也要重新加载）。现在只隐藏，
        托盘「管理面板」可以原样唤回。

        **不要在这里把 Pilot 的 ``_panel`` 置空**——那会导致下次打开时新建一个面板，
        旧实例连同已加载的图谱一起泄漏。关闭只隐藏，实例继续由 Pilot 持有、
        供 ``open_manager()`` 复用（见 pilot.py 中对应的注释）。
        真正销毁只发生在 ``Pilot.quit()``。

        伙伴本体（pilot）不作为 Qt 父窗口，本面板关闭不影响它继续运行。
        """
        event.ignore()      # 阻止真的关闭
        self.hide()
