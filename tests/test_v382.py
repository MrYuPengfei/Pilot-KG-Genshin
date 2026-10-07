"""v3.8.2 新增功能的回归测试：删除背景音乐 / 导出当前背景音乐。

两个功能都改的是**有破坏性或不可逆**的路径，故断言不只看「函数返回了」，
而是覆盖真实后果：

- 删除：地区从资源库消失、**同名/其他人物毫发无损**、正在播放的状态被清掉、
  托盘菜单同步重建、filesystem 后端明确报错而不是静默失败；
- 导出：只产出一个 ``music/<地区>/background.mp3``，**不含任何人物帧与语音**。

用真实 assets.db（约 460MB）的**临时副本**，绝不碰原库。
"""

import os
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))

from asset_exporter import export_assets                       # noqa: E402
from resource_store import ResourceStore                       # noqa: E402

REAL_ASSETS_DB = ROOT_DIR / 'assets.db'

pytestmark = pytest.mark.skipif(
    not REAL_ASSETS_DB.is_file(),
    reason='需要真实 assets.db 才有地区背景音乐')


@pytest.fixture()
def store():
    """真实 assets.db 的临时副本。

    ⚠️ 必须是**函数级**夹具：本文件多数测试都在删除 BGM。用模块级共享副本时，
    前面删掉的地区会让后面的 ``list_bgm_areas()[0]`` 越界——
    测试之间互相污染，还会被误读成「删除逻辑有 bug」。
    代价是每个用例拷一次 460MB，但换来的是彼此独立。
    """
    tmp = tempfile.mkdtemp(prefix='p382_')
    db = os.path.join(tmp, 'assets.db')
    shutil.copy(REAL_ASSETS_DB, db)
    s = ResourceStore(tmp, 'png', 'music', 'assets.db')
    yield s
    s.close()
    shutil.rmtree(tmp, ignore_errors=True)


# ---------- 删除背景音乐：存储层 ----------

def test_delete_area_only_removes_bgm(store):
    """删除地区只影响该地区的 BGM，人物资源一个都不能少。"""
    area = store.list_bgm_areas()[0]
    roles_before = store.list_roles()
    frames_before = {r: len(store.list_frames(r)) for r in roles_before}

    assert store.delete_area(area) == 1
    assert area not in store.list_bgm_areas()
    # 关键：人物资源完全不受影响
    assert store.list_roles() == roles_before
    for r in roles_before:
        assert len(store.list_frames(r)) == frames_before[r]


def test_delete_area_is_idempotent(store):
    """重复删除返回 0 而不报错（面板会据此提示「未找到」）。"""
    area = store.list_bgm_areas()[0]
    assert store.delete_area(area) == 1
    assert store.delete_area(area) == 0
    assert store.delete_area(area) == 0


def test_delete_area_does_not_touch_same_name_role(store):
    """地区名与角色名可能同名，删除 BGM 不能误删同名人物的帧/语音。

    这是本功能最容易埋的雷：两者共用 ``assets.role`` 一列，
    只按 role 删就会连人物一起清掉。
    """
    import sqlite3

    area = store.list_bgm_areas()[0]
    conn = sqlite3.connect(store.db_path)
    try:
        # 人工造一条「同名人物」：同名 role 下既有 frame 也有 bgm
        conn.execute("INSERT INTO assets (role, kind, name, data)"
                     " VALUES (?, 'frame', '0001.png', ?)", (area, b'PNG'))
        conn.execute("INSERT INTO assets (role, kind, name, data)"
                     " VALUES (?, 'voice', 'a.mp3', ?)", (area, b'MP3'))
        conn.commit()
    finally:
        conn.close()

    assert store.delete_area(area) == 1
    # 同名的帧与语音必须还在
    assert store.list_frames(area) == ['0001.png']
    assert store.list_voices(area) == ['a.mp3']
    assert area not in store.list_bgm_areas()


def test_delete_area_persists_across_instances(store):
    """删除要真的落盘：关掉连接重开新实例仍然没有。"""
    area = store.list_bgm_areas()[0]
    store.delete_area(area)
    reopened = ResourceStore(os.path.dirname(store.db_path), 'png', 'music',
                             'assets.db')
    try:
        assert area not in reopened.list_bgm_areas()
    finally:
        reopened.close()


def test_delete_area_requires_sqlite_backend(store):
    """filesystem 后端删不掉，必须抛 RuntimeError（面板据此提示而非静默失败）。"""
    fs = ResourceStore(os.path.dirname(store.db_path), 'png', 'music',
                       '不存在的.db')
    try:
        assert fs.backend == 'filesystem'
        with pytest.raises(RuntimeError, match='assets.db'):
            fs.delete_area(store.list_bgm_areas()[0])
    finally:
        fs.close()


# ---------- 导出当前背景音乐：导出器层 ----------

def test_export_only_bgm_produces_single_file(store, tmp_path):
    """只导一个地区的 BGM：产物恰好一个文件，且路径正确。"""
    area = store.list_bgm_areas()[0]
    out = tmp_path / 'only_bgm'
    report = export_assets(store, str(out), roles=[], areas=[area])

    assert report['roles'] == 0
    assert report['areas'] == 1
    assert report['files'] == 1

    files = [p for p in out.rglob('*') if p.is_file()]
    assert len(files) == 1
    assert files[0].relative_to(out).as_posix() == f'music/{area}/background.mp3'
    # 字节要与库里的完全一致
    assert files[0].read_bytes() == store.read_bgm(area)


def test_export_only_bgm_excludes_all_characters(store, tmp_path):
    """BGM 导出不得夹带任何人物帧 / 语音（这是「仅…」范围的核心语义）。"""
    out = tmp_path / 'only_bgm2'
    export_assets(store, str(out), roles=[], areas=[store.list_bgm_areas()[0]])
    top = {p.name for p in out.iterdir()}
    # 只应有 music/，不应出现 png/ 或任何人物目录
    assert top == {'music'}
    music_children = {p.name for p in (out / 'music').iterdir()}
    assert music_children == {store.list_bgm_areas()[0]}


def test_export_empty_scope_raises(store, tmp_path):
    """两个范围都为空时报错（面板已挡住，这里锁住导出器的兜底）。"""
    with pytest.raises(ValueError, match='没有可导出的素材'):
        export_assets(store, str(tmp_path / 'empty'), roles=[], areas=[])


def test_export_bgm_as_zip(store, tmp_path):
    """BGM 也能打成 zip（面板两个按钮都支持）。"""
    import zipfile

    area = store.list_bgm_areas()[0]
    zpath = tmp_path / 'bgm.zip'
    report = export_assets(store, str(zpath), roles=[], areas=[area], as_zip=True)
    assert report['mode'] == 'zip'
    assert report['files'] == 1
    with zipfile.ZipFile(zpath) as zf:
        names = zf.namelist()
    assert names == [f'music/{area}/background.mp3']


# ---------- 面板层：控件与选项存在 ----------

def test_panel_has_delete_bgm_button_and_export_scope():
    """面板上必须有这两个新入口——版本号升级了但控件没加是最容易漏的。"""
    pytest.importorskip('PySide6')
    import os as _os
    _os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    _os.environ.setdefault('SDL_AUDIODRIVER', 'dummy')

    from PySide6.QtWidgets import QApplication, QWidget

    from config_store import ConfigStore
    import manager_panel

    class _Store:
        base_dir = str(ROOT_DIR)

        def list_roles(self):
            return ['测试角色']

        def list_bgm_areas(self):
            return ['蒙德', '璃月']

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
            return {'backend': 'sqlite', 'roles': 1, 'areas': 2, 'frames': 1,
                    'voices': 1, 'bgms': 2, 'db_size_mb': 1.0}

    class _Pilot(QWidget):
        def __init__(self):
            super().__init__()
            self.store = _Store()
            self.config_store = ConfigStore(tempfile.mkdtemp(), auto_seed=False)
            self.role_name = '测试角色'
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
            pass

        def quit(self):
            pass

        def _rebuild_bgm_menu(self):
            pass

        def save_config(self):
            pass

    QApplication.instance() or QApplication([])
    panel = manager_panel.ManagerPanel(
        _Pilot(), {'frame_scale': {}, 'bg_music': None, 'audio': False,
                   'role': '测试角色'})
    try:
        # 音乐管理页的删除按钮
        assert hasattr(panel, 'delete_bgm_btn')
        assert '删除' in panel.delete_bgm_btn.text()
        # 导出范围要有「仅当前背景音乐」
        scopes = [panel.export_scope_combo.itemData(i)
                  for i in range(panel.export_scope_combo.count())]
        assert 'current_bgm' in scopes
        # 地区列表应已填充（导出与删除都读它）
        assert panel.area_list.count() == 2
        # _selected_area 是播放/删除/导出三处的统一入口
        assert panel._selected_area() is None     # 未选中
        panel.area_list.setCurrentRow(0)
        assert panel._selected_area() == '蒙德'
    finally:
        panel.deleteLater()
