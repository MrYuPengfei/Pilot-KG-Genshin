"""知识图谱编辑对话框的回归测试（v3.7）。

修复的崩溃：

    File "kg_editor.py", line 64, in _on_completer_activated
      item = self._model.itemFromIndex(index)
    TypeError: 'QStandardItemModel.itemFromIndex' called with wrong argument types:
    PySide6.QtGui.QStandardItemModel.itemFromIndex(str)

根因：``QCompleter.activated`` 有两个重载（``activated(QString)`` 与
``activated(QModelIndex)``）。Qt 在用户点击候选时发的是**前者**，而 PySide6
在不限定类型时也只会连上这一个——于是把字符串当 QModelIndex 用了。
"""

import os

import pytest

pytest.importorskip('PySide6')

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KG_DB = os.path.join(ROOT, 'kg.db')

pytestmark = pytest.mark.skipif(
    not os.path.isfile(KG_DB),
    reason='需要真实 kg.db（首次运行由 data/csv 播种）')


@pytest.fixture(scope='module')
def app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.fixture
def picker(app):
    """装好 1910 条候选的实体选择器（每次新建，避免相互影响）。"""
    from kg_store import KGStore
    from kg_editor import EntityPicker

    store = KGStore(KG_DB, auto_seed=False)
    p = EntityPicker(store)
    p.refresh()
    yield p
    store.close()


def _first_row_of_type(p, ntype):
    from PySide6.QtCore import Qt
    for row in range(p._model.rowCount()):
        key = p._model.item(row).data(Qt.UserRole)
        if key and key[0] == ntype:
            return row
    return -1


def test_candidates_loaded(picker):
    """前置：补全候选非空。"""
    assert picker._model.rowCount() > 100


def test_activated_with_string_argument_does_not_crash(picker):
    """回归：Qt 传字符串时不能抛 TypeError，且应正确回填类型与名称。"""
    row = _first_row_of_type(picker, 'weapon')
    assert row >= 0
    text = picker._model.item(row).text()          # 形如「护摩之杖 [武器]」
    picker.name_edit.clear()

    picker._on_completer_activated(text)           # 传字符串——正是 Qt 的行为

    key = picker.key()
    assert key is not None and key[0] == 'weapon', f'类型未回填：{key}'
    assert '[' not in picker.name_edit.text(), '名称应去掉「[类型]」后缀'


def test_activated_fills_name(picker):
    """回填的名称应与候选一致。"""
    row = _first_row_of_type(picker, 'character')
    text = picker._model.item(row).text()
    expected = text.split(' [')[0]
    picker.name_edit.clear()
    picker._on_completer_activated(text)
    assert picker.name_edit.text() == expected


def test_highlighted_syncs_type(picker):
    """键盘上下移动候选时也应同步类型（highlighted 同样只有 QString 重载）。"""
    row = _first_row_of_type(picker, 'area')
    text = picker._model.item(row).text()
    picker._on_completer_highlighted(text)
    assert picker.type_combo.currentData() == 'area'


def test_falls_back_to_current_index(picker):
    """文本对不上时退回 currentIndex（键盘导航场景 Qt 会设好它）。"""
    row = _first_row_of_type(picker, 'material')
    picker._completer.setCurrentRow(row)
    picker._on_completer_activated('对不上的文本')   # 触发 currentIndex 回退
    assert picker.type_combo.currentData() == 'material'


@pytest.mark.parametrize('bad', ['', None, '不存在的候选'])
def test_bad_input_is_safe(picker, bad):
    """空/无匹配输入应安静跳过，不抛异常。"""
    picker._on_completer_activated(bad)
    picker._on_completer_highlighted(bad)


def test_typing_new_name_still_supported(picker):
    """直接输入新名字（不选候选）仍应能建新实体。"""
    idx = picker.type_combo.findData('npc')
    picker.type_combo.setCurrentIndex(idx)
    picker.name_edit.setText('全新角色')
    assert picker.key() == ('npc', '全新角色')


def test_placeholder_names_rejected(picker):
    """占位名仍应被 key() 拒绝。"""
    idx = picker.type_combo.findData('npc')
    picker.type_combo.setCurrentIndex(idx)
    for bad in ('暂无', '无', '未知', '   '):
        picker.name_edit.setText(bad)
        assert picker.key() is None, f'{bad!r} 应被拒绝'
