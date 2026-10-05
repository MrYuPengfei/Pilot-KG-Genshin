"""素材导出测试：目录 / zip 导出，以及与导入器的往返对称性。

用临时 sqlite 库（不碰真实 assets.db）构造小型资源库，验证：
  ① 导出目录结构与 asset_importer 的识别规则一致；
  ② 导出内容字节与库中完全相同；
  ③ 导出的目录/zip 能被现有导入器直接并入（**对称性**是本模块的关键契约）。
"""

import os
import sqlite3
import zipfile

import pytest

from asset_exporter import export_assets, FRAME_DIR, MUSIC_DIR, BGM_NAME
from asset_importer import import_assets
from config_store import ConfigStore
from resource_store import ResourceStore

SCHEMA = """
CREATE TABLE assets (
    role TEXT NOT NULL, kind TEXT NOT NULL, name TEXT NOT NULL,
    category TEXT, data BLOB NOT NULL,
    PRIMARY KEY (role, kind, name)
);
"""


@pytest.fixture
def store(tmp_path):
    """构造一个小资源库：2 个角色（含语音）+ 1 个地区 BGM。"""
    db = tmp_path / 'assets.db'
    conn = sqlite3.connect(db)
    conn.executescript(SCHEMA)
    rows = [
        ('七七', 'frame', '0001.png', None, b'PNG-A1'),
        ('七七', 'frame', '0002.png', None, b'PNG-A2'),
        ('七七', 'voice', '早上好.mp3', 'greeting', b'MP3-G1'),
        ('七七', 'voice', '闲聊甲.mp3', 'chat', b'MP3-C1'),
        ('甘雨', 'frame', '0001.png', None, b'PNG-B1'),
        ('璃月', 'bgm', BGM_NAME, None, b'MP3-BGM-LY'),
    ]
    conn.executemany('INSERT INTO assets VALUES (?,?,?,?,?)', rows)
    conn.commit()
    conn.close()
    s = ResourceStore(str(tmp_path))
    yield s
    s.close()


# ---------- 目录导出 ----------

def test_export_dir_layout(store, tmp_path):
    out = tmp_path / 'out'
    report = export_assets(store, str(out))
    assert report['mode'] == 'dir'
    assert report['files'] == 6
    assert report['roles'] == 2 and report['areas'] == 1
    # 布局必须与导入器一致
    assert (out / FRAME_DIR / '七七' / '0001.png').is_file()
    assert (out / MUSIC_DIR / '七七' / '早上好.mp3').is_file()
    assert (out / MUSIC_DIR / '璃月' / BGM_NAME).is_file()
    assert not (out / MUSIC_DIR / '璃月' / '早上好.mp3').exists(), 'BGM 目录混入语音'


def test_export_bytes_identical(store, tmp_path):
    out = tmp_path / 'out'
    export_assets(store, str(out))
    assert (out / FRAME_DIR / '七七' / '0001.png').read_bytes() == b'PNG-A1'
    assert (out / MUSIC_DIR / '璃月' / BGM_NAME).read_bytes() == b'MP3-BGM-LY'


def test_export_filter_roles_and_areas(store, tmp_path):
    out = tmp_path / 'out'
    report = export_assets(store, str(out), roles=['七七'], areas=[])
    assert report['files'] == 4          # 2 帧 + 2 语音
    assert (out / FRAME_DIR / '七七').is_dir()
    assert not (out / FRAME_DIR / '甘雨').exists(), '角色筛选失效'
    assert not (out / MUSIC_DIR / '璃月').exists(), '地区未被排除'


def test_export_progress_callback(store, tmp_path):
    seen = []
    export_assets(store, str(tmp_path / 'out'),
                  progress=lambda d, t, l: seen.append((d, t)))
    assert [d for d, _ in seen] == [1, 2, 3, 4, 5, 6]
    assert all(t == 6 for _, t in seen)


# ---------- zip 导出 ----------

def test_export_zip(store, tmp_path):
    zpath = tmp_path / 'assets.zip'
    report = export_assets(store, str(zpath), as_zip=True)
    assert report['mode'] == 'zip'
    assert zipfile.is_zipfile(zpath)
    with zipfile.ZipFile(zpath) as zf:
        names = set(zf.namelist())
        assert f'{FRAME_DIR}/七七/0001.png' in names
        assert f'{MUSIC_DIR}/璃月/{BGM_NAME}' in names
        assert zf.read(f'{FRAME_DIR}/七七/0001.png') == b'PNG-A1'


def test_export_empty_raises(store, tmp_path):
    with pytest.raises(ValueError, match='没有可导出的素材'):
        export_assets(store, str(tmp_path / 'out'), roles=[], areas=[])


# ---------- 与导入器对称（关键契约） ----------

def test_exported_dir_can_be_reimported(store, tmp_path):
    """导出的目录能被现有导入器直接识别并并入。"""
    out = tmp_path / 'out'
    export_assets(store, str(out))
    target = tmp_path / 'target'
    target.mkdir()
    cfg = ConfigStore(str(target), auto_seed=False)
    report = import_assets(str(out), str(target / 'assets.db'), cfg)
    assert report['frames'] == 3
    assert report['voices'] == 2
    assert report['bgms'] == 1
    assert report['roles'] == ['七七', '甘雨']
    assert report['areas'] == ['璃月']
    # 新角色已被登记进配置库
    assert '甘雨' in cfg.load()['frame_scale']


def test_exported_zip_can_be_reimported(store, tmp_path):
    """导出的 zip 同样能被导入器识别。"""
    zpath = tmp_path / 'assets.zip'
    export_assets(store, str(zpath), as_zip=True)
    target = tmp_path / 'target'
    target.mkdir()
    cfg = ConfigStore(str(target), auto_seed=False)
    report = import_assets(str(zpath), str(target / 'assets.db'), cfg)
    assert report['frames'] == 3 and report['bgms'] == 1


def test_roundtrip_preserves_everything(store, tmp_path):
    """导出→导入→再导出，文件数与内容应完全一致（幂等）。"""
    first = tmp_path / 'first'
    export_assets(store, str(first))
    target = tmp_path / 'target'
    target.mkdir()
    cfg = ConfigStore(str(target), auto_seed=False)
    import_assets(str(first), str(target / 'assets.db'), cfg)
    re_store = ResourceStore(str(target))
    second = tmp_path / 'second'
    export_assets(re_store, str(second))
    re_store.close()
    files_first = {os.path.relpath(os.path.join(r, f), first)
                   for r, _d, fs in os.walk(first) for f in fs}
    files_second = {os.path.relpath(os.path.join(r, f), second)
                    for r, _d, fs in os.walk(second) for f in fs}
    assert files_first == files_second
    assert len(files_first) == 6
