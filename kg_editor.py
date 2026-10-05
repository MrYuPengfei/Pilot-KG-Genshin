"""知识图谱编辑对话框：实体（节点）与关系的增删改。

两个对话框都是「先在内存里改字段，点确定后由调用方落库」的模式：
- :class:`NodeEditDialog` 编辑类型、名称与任意键值属性（属性表格可增删行）；
- :class:`EdgeEditDialog` 编辑两端实体与关系名，支持方向翻转。

实体选择统一用 :class:`EntityPicker`：可输入的搜索框 + 补全列表，
既可选已有实体，也可直接输入新名字（此时按所选类型新建）。
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
                               QLabel, QLineEdit, QComboBox, QPushButton,
                               QDialogButtonBox, QTableWidget, QTableWidgetItem,
                               QHeaderView, QWidget, QCompleter, QAbstractItemView)
from PySide6.QtGui import QStandardItemModel, QStandardItem

from kg_store import NODE_TYPES, REL_NAMES, type_cn

MAX_ATTR_ROWS = 64


class EntityPicker(QWidget):
    """实体选择器：类型下拉 + 可搜索的名称框（支持输入新实体名）。"""

    def __init__(self, kg, parent=None):
        super().__init__(parent)
        self.kg = kg
        self.setObjectName('EntityPicker')

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        self.type_combo = QComboBox()
        for key, (cn, _color) in NODE_TYPES.items():
            self.type_combo.addItem(cn, key)
        self.type_combo.setFixedWidth(96)
        row.addWidget(self.type_combo)

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText('输入实体名称，可搜索已有实体')
        row.addWidget(self.name_edit, 1)

        # 补全：显示「名称 [类型]」，userData 存 (type, name)
        self._model = QStandardItemModel(self)
        self._completer = QCompleter(self._model, self)
        self._completer.setCaseSensitivity(Qt.CaseInsensitive)
        self._completer.setFilterMode(Qt.MatchContains)
        self._completer.setCompletionMode(QCompleter.PopupCompletion)
        # activated / highlighted 都只接 QString 重载（见 _on_completer_activated
        # 的说明），真实索引一律从 completer.currentIndex() 取。
        self._completer.activated.connect(self._on_completer_activated)
        self._completer.highlighted.connect(self._on_completer_highlighted)
        self.name_edit.setCompleter(self._completer)

    def refresh(self):
        """重建补全候选（导入/删除实体后调用）。"""
        self._model.clear()
        for key, node in sorted(self.kg.nodes.items(), key=lambda kv: kv[0][1]):
            item = QStandardItem(f'{node["name"]} [{type_cn(key[0])}]')
            item.setData(key, Qt.UserRole)
            self._model.appendRow(item)
        # 过滤模式 MatchContains 时补全需自行处理前缀，交给默认匹配即可
        self.name_edit.setCompleter(self._completer)

    def _on_completer_activated(self, text):
        """点击补全候选时回填类型（与候选一致），避免同名跨类型歧义。

        ⚠️ ``QCompleter.activated`` 有**两个重载**：``activated(QString)`` 与
        ``activated(QModelIndex)``。Qt 在用户点击候选时发的是**前者**，而 PySide6
        在不限定类型时也只会连上这一个——于是旧代码把字符串当 QModelIndex 传给
        ``itemFromIndex()``，直接抛 ``TypeError: ...itemFromIndex(str)``。

        修法：不再把信号参数当索引用，而是**拿候选文本反查行**（文本即
        ``refresh()`` 里拼的「名称 [类型]」，与模型一一对应），并辅以
        ``currentIndex()``（键盘导航时 Qt 会设好它）作为次选。
        """
        self._sync_type(text)

    def _on_completer_highlighted(self, text):
        """键盘上下移动候选时同步类型，让「所见即所选」。

        纯视觉辅助：即使同步失败也不影响输入框里的名称。
        """
        self._sync_type(text)

    def _find_candidate_row(self, text):
        """按候选文本定位模型行号；找不到返回 -1。

        ``text`` 是补全框里的显示文本（形如「钟离 [人物]」）。
        """
        if not text:
            return -1
        for row in range(self._model.rowCount()):
            if self._model.item(row).text() == text:
                return row
        return -1

    def _sync_type(self, text):
        """把选中候选的类型回填到类型下拉，并去掉名称里的「[类型]」后缀。"""
        row = self._find_candidate_row(text)
        if row < 0:
            # 文本对不上（如用户输入了新名字）时退回 currentIndex
            index = self._completer.currentIndex()
            if not index.isValid():
                return
            row = index.row()
        item = self._model.item(row)
        if item is None:
            return
        key = item.data(Qt.UserRole)
        if key:
            idx = self.type_combo.findData(key[0])
            if idx >= 0:
                self.type_combo.setCurrentIndex(idx)
        self.name_edit.setText(item.text().split(' [')[0])

    def key(self):
        """返回 (type, name)；名称为空或为占位名时返回 None。"""
        name = self.name_edit.text().strip()
        if not name or name in ('暂无', '无', '未知'):
            return None
        return (self.type_combo.currentData(), name)

    def set_key(self, key):
        """回填已有实体；同名跨类型时按 key 的类型精确选中。"""
        if not key:
            return
        idx = self.type_combo.findData(key[0])
        if idx >= 0:
            self.type_combo.setCurrentIndex(idx)
        self.name_edit.setText(key[1])

    def text(self):
        return self.name_edit.text().strip()


class NodeEditDialog(QDialog):
    """实体编辑对话框：类型、名称、属性键值表。key 为 None 时是新增。"""

    def __init__(self, kg, key=None, parent=None):
        super().__init__(parent)
        self.kg = kg
        self.key = key            # 原始键（新增时为 None）
        self.setWindowTitle('编辑实体' if key else '新增实体')
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        self.resize(520, 420)

        form = QFormLayout()
        self.type_combo = QComboBox()
        for k, (cn, _c) in NODE_TYPES.items():
            self.type_combo.addItem(cn, k)
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText('实体名称')
        form.addRow('类型:', self.type_combo)
        form.addRow('名称:', self.name_edit)

        attr_hint = QLabel('属性（键值对，可增删行；长文本请勿超过 2000 字）')
        attr_hint.setStyleSheet('color: #7f8c8d;')
        self.attr_table = QTableWidget(0, 2)
        self.attr_table.setHorizontalHeaderLabels(['属性名', '属性值'])
        self.attr_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.Stretch)
        self.attr_table.verticalHeader().setVisible(False)
        self.attr_table.setSelectionBehavior(QAbstractItemView.SelectRows)

        row = QHBoxLayout()
        add_btn = QPushButton('添加属性')
        add_btn.clicked.connect(lambda: self._add_attr_row())
        del_btn = QPushButton('删除选中')
        del_btn.clicked.connect(self._del_attr_rows)
        row.addWidget(add_btn)
        row.addWidget(del_btn)
        row.addStretch(1)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self._on_accept)
        btns.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(attr_hint)
        layout.addWidget(self.attr_table, 1)
        layout.addLayout(row)
        layout.addWidget(btns)

        if key:
            self.type_combo.setCurrentIndex(self.type_combo.findData(key[0]))
            self.name_edit.setText(key[1])
            for k, v in self.kg.node_attrs(key).items():
                self._add_attr_row(k, v)
        else:
            self.type_combo.setCurrentIndex(
                max(0, self.type_combo.findData('npc')))
            self._add_attr_row()

    def _add_attr_row(self, k='', v=''):
        row = self.attr_table.rowCount()
        if row >= MAX_ATTR_ROWS:
            return
        self.attr_table.insertRow(row)
        self.attr_table.setItem(row, 0, QTableWidgetItem(str(k)))
        self.attr_table.setItem(row, 1, QTableWidgetItem(str(v)))

    def _del_attr_rows(self):
        for idx in sorted({i.row() for i in self.attr_table.selectedIndexes()},
                          reverse=True):
            self.attr_table.removeRow(idx)

    def _on_accept(self):
        name = self.name_edit.text().strip()
        if not name or name in ('暂无', '无', '未知'):
            return
        self.accept()

    def values(self):
        """返回 (type, name, attrs_dict)。"""
        attrs = {}
        for row in range(self.attr_table.rowCount()):
            k_item = self.attr_table.item(row, 0)
            v_item = self.attr_table.item(row, 1)
            k = (k_item.text() if k_item else '').strip()
            v = (v_item.text() if v_item else '').strip()
            if k:
                attrs[k] = v
        return self.type_combo.currentData(), self.name_edit.text().strip(), attrs


class EdgeEditDialog(QDialog):
    """关系编辑对话框：源实体、关系名、目标实体。edge 为 None 时是新增。

    ``anchor`` 为当前选中的实体，新增时预置为源端；``exclude`` 列出不可选的对端
    （新增时为当前实体自身，避免自环）。
    """

    def __init__(self, kg, edge=None, anchor=None, exclude=(), parent=None):
        super().__init__(parent)
        self.kg = kg
        self.edge = edge            # (src_key, rel, dst_key)
        self.anchor = anchor
        self.setWindowTitle('编辑关系' if edge else '新增关系')
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        self.resize(560, 220)

        src_picker = EntityPicker(kg)
        dst_picker = EntityPicker(kg)
        src_picker.refresh()
        dst_picker.refresh()
        self.src, self.dst = src_picker, dst_picker

        self.rel_edit = QLineEdit()
        self.rel_edit.setPlaceholderText('关系名，如 element_is / part_of')
        completer = QCompleter(sorted({*REL_NAMES, *REL_NAMES.values()}), self)
        completer.setCaseSensitivity(Qt.CaseInsensitive)
        completer.setFilterMode(Qt.MatchContains)
        self.rel_edit.setCompleter(completer)

        self.rel_hint = QLabel('')
        self.rel_hint.setStyleSheet('color: #27ae60;')
        self.rel_edit.textChanged.connect(self._update_hint)

        swap_btn = QPushButton('⇄  交换两端')
        swap_btn.clicked.connect(self._swap)

        form = QFormLayout()
        form.addRow('源实体:', self.src)
        form.addRow('目标实体:', self.dst)
        rel_row = QHBoxLayout()
        rel_row.addWidget(self.rel_edit, 1)
        rel_row.addWidget(swap_btn)
        form.addRow('关系:', rel_row)
        form.addRow('', self.rel_hint)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self._on_accept)
        btns.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(btns)

        if edge:
            s_key, rel, d_key = edge
            self.src.set_key(s_key)
            self.dst.set_key(d_key)
            self.rel_edit.setText(rel)
        else:
            if anchor:
                self.src.set_key(anchor)
            if exclude:
                other = list(exclude)[0]
                self.dst.set_key(other)
        self._update_hint(self.rel_edit.text())

    def _update_hint(self, text):
        text = (text or '').strip()
        if text:
            cn = REL_NAMES.get(text)
            self.rel_hint.setText(f'显示为「{cn}」' if cn else '自定义关系名（无中文映射）')
        else:
            self.rel_hint.setText('')

    def _swap(self):
        a, b = self.src.type_combo.currentData(), self.src.text()
        self.src.set_key((self.dst.type_combo.currentData(), self.dst.text()))
        self.dst.set_key((a, b))

    def _on_accept(self):
        if not self.values()[1]:
            return
        self.accept()

    def values(self):
        """返回 (src_key, rel, dst_key)，任一端为空则为 None。"""
        return self.src.key(), self.rel_edit.text().strip(), self.dst.key()
