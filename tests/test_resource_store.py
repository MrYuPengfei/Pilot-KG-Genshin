"""ResourceStore 与 assets.db 构建脚本的测试。

使用临时目录构造迷你资源树，同时验证文件系统回退和 SQLite 两种后端行为一致。
"""

import sys
from pathlib import Path

import pytest

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))
sys.path.insert(0, str(ROOT_DIR / 'tools'))

from build_assets_db import build_db, classify_voice  # noqa: E402
from resource_store import ResourceStore  # noqa: E402


@pytest.fixture()
def mini_tree(tmp_path):
    """构造一个最小资源目录：1 个角色（2 帧 + 4 语音）+ 1 个区域 BGM。"""
    png_dir = tmp_path / 'png' / '测试角色'
    png_dir.mkdir(parents=True)
    (png_dir / '0001.png').write_bytes(b'PNG1')
    (png_dir / '0002.png').write_bytes(b'PNG2')

    music_dir = tmp_path / 'music' / '测试角色'
    music_dir.mkdir(parents=True)
    (music_dir / '早上好.mp3').write_bytes(b'MP3-MORNING')
    (music_dir / '闲聊测试.mp3').write_bytes(b'MP3-CHAT')
    (music_dir / '想要了解测试其一.mp3').write_bytes(b'MP3-KNOW')
    (music_dir / '晚安.mp3').write_bytes(b'MP3-NIGHT')

    bgm_dir = tmp_path / 'music' / '蒙德'
    bgm_dir.mkdir(parents=True)
    (bgm_dir / 'background.mp3').write_bytes(b'MP3-BGM')
    return tmp_path


def test_classify_voice():
    assert classify_voice('早上好.mp3') == 'greeting'
    assert classify_voice('晚安.mp3') == 'greeting'
    assert classify_voice('闲聊雪国故土.mp3') == 'chat'
    assert classify_voice('想要了解达达利亚其一.mp3') == 'know'
    assert classify_voice('其他.mp3') is None


def test_filesystem_backend(mini_tree):
    store = ResourceStore(str(mini_tree))
    assert store.backend == 'filesystem'
    assert store.list_frames('测试角色') == ['0001.png', '0002.png']
    assert store.read_frame('测试角色', '0001.png') == b'PNG1'
    assert store.list_voices('测试角色', 'chat') == ['闲聊测试.mp3']
    assert store.list_voices('测试角色', 'know') == ['想要了解测试其一.mp3']
    assert sorted(store.list_voices('测试角色', 'greeting')) == ['早上好.mp3', '晚安.mp3']
    assert store.read_voice('测试角色', '闲聊测试.mp3') == b'MP3-CHAT'
    assert store.read_bgm('蒙德') == b'MP3-BGM'
    assert store.list_roles() == ['测试角色']


def test_sqlite_backend_matches_filesystem(mini_tree):
    count = build_db(str(mini_tree), str(mini_tree / 'assets.db'))
    assert count == 7  # 2 帧 + 4 语音 + 1 BGM

    fs = ResourceStore(str(mini_tree), db_name='不存在.db')
    db = ResourceStore(str(mini_tree))
    assert db.backend == 'sqlite'

    assert db.list_frames('测试角色') == fs.list_frames('测试角色')
    assert db.read_frame('测试角色', '0002.png') == fs.read_frame('测试角色', '0002.png')
    assert db.list_voices('测试角色', 'chat') == fs.list_voices('测试角色', 'chat')
    assert db.list_voices('测试角色', 'know') == fs.list_voices('测试角色', 'know')
    assert db.list_voices('测试角色', 'greeting') == fs.list_voices('测试角色', 'greeting')
    assert db.read_voice('测试角色', '晚安.mp3') == fs.read_voice('测试角色', '晚安.mp3')
    assert db.read_bgm('蒙德') == fs.read_bgm('蒙德')
    assert db.list_roles() == fs.list_roles()

    with pytest.raises(FileNotFoundError):
        db.read_frame('测试角色', '9999.png')
    db.close()


def test_stats(mini_tree):
    build_db(str(mini_tree), str(mini_tree / 'assets.db'))
    db = ResourceStore(str(mini_tree))
    s = db.stats()
    assert s['backend'] == 'sqlite'
    assert s['roles'] == 1
    assert s['areas'] == 1
    assert s['frames'] == 2
    assert s['voices'] == 4
    assert s['bgms'] == 1
    assert s['db_size_mb'] > 0
    db.close()


def test_delete_role_and_area(mini_tree):
    build_db(str(mini_tree), str(mini_tree / 'assets.db'))
    db = ResourceStore(str(mini_tree))

    removed = db.delete_role('测试角色')
    assert removed == 6  # 2 帧 + 4 语音
    assert db.list_frames('测试角色') == []
    assert db.list_roles() == []
    # 地区不受影响
    assert db.read_bgm('蒙德') == b'MP3-BGM'

    removed = db.delete_area('蒙德')
    assert removed == 1
    assert db.list_bgm_areas() == []
    db.close()


def test_delete_requires_sqlite_backend(mini_tree):
    fs = ResourceStore(str(mini_tree), db_name='不存在.db')
    assert fs.backend == 'filesystem'
    with pytest.raises(RuntimeError, match='assets.db'):
        fs.delete_role('测试角色')
    with pytest.raises(RuntimeError, match='assets.db'):
        fs.delete_area('蒙德')
