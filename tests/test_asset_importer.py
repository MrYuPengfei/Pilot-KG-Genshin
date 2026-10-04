"""第三方素材包导入模块的测试：目录导入、zip 导入、幂等性、config 登记、自定义地区。"""

import os
import sys
import zipfile
from pathlib import Path

import pytest
import yaml

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))

from asset_importer import import_assets  # noqa: E402
from resource_store import ResourceStore  # noqa: E402


@pytest.fixture()
def pack_dir(tmp_path):
    """构造一个第三方素材包：1 个新角色（帧+语音）+ 1 个自定义地区 BGM。"""
    pack = tmp_path / '我的素材包'
    frames = pack / 'png' / '自定义角色'
    frames.mkdir(parents=True)
    (frames / '0001.png').write_bytes(b'PNG-A')
    (frames / '0002.png').write_bytes(b'PNG-B')

    voices = pack / 'music' / '自定义角色'
    voices.mkdir(parents=True)
    (voices / '早上好.mp3').write_bytes(b'MP3-GREET')
    (voices / '闲聊自定义.mp3').write_bytes(b'MP3-CHAT')

    area = pack / 'music' / '须弥'
    area.mkdir(parents=True)
    (area / 'background.mp3').write_bytes(b'MP3-SUMERU-BGM')
    return pack


@pytest.fixture()
def config_file(tmp_path):
    cfg = tmp_path / 'config.yaml'
    cfg.write_text(yaml.dump({
        'audio': True, 'bg_music': False, 'role': '达达利亚',
        'frame_scale': {'达达利亚': [60, 1.0]},
        'img_path': 'png', 'music_path': 'music',
    }, allow_unicode=True), encoding='utf-8')
    return cfg


def test_import_from_directory(pack_dir, config_file, tmp_path):
    db = tmp_path / 'assets.db'
    report = import_assets(str(pack_dir), str(db), str(config_file))

    assert report['frames'] == 2
    assert report['voices'] == 2
    assert report['bgms'] == 1
    assert report['new_roles'] == ['自定义角色']
    assert report['areas'] == ['须弥']

    # 导入后可直接被 ResourceStore 读取
    store = ResourceStore(str(tmp_path))
    assert store.backend == 'sqlite'
    assert store.list_frames('自定义角色') == ['0001.png', '0002.png']
    assert store.read_frame('自定义角色', '0001.png') == b'PNG-A'
    assert store.list_voices('自定义角色', 'chat') == ['闲聊自定义.mp3']
    assert store.list_voices('自定义角色', 'greeting') == ['早上好.mp3']
    assert store.list_bgm_areas() == ['须弥']
    assert store.read_bgm('须弥') == b'MP3-SUMERU-BGM'
    store.close()

    # 新角色已登记 frame_scale 默认值，且原有配置未被破坏
    cfg = yaml.safe_load(config_file.read_text(encoding='utf-8'))
    assert cfg['frame_scale']['自定义角色'] == [60, 1.0]
    assert cfg['frame_scale']['达达利亚'] == [60, 1.0]
    assert cfg['role'] == '达达利亚'


def test_import_from_zip(pack_dir, config_file, tmp_path):
    zip_path = tmp_path / 'pack.zip'
    with zipfile.ZipFile(zip_path, 'w') as zf:
        for path in pack_dir.rglob('*'):
            if path.is_file():
                # zip 内多套一层目录，验证自动下探
                zf.write(path, Path('我的素材包') / path.relative_to(pack_dir))

    db = tmp_path / 'assets.db'
    report = import_assets(str(zip_path), str(db), str(config_file))
    assert report['frames'] == 2
    assert report['areas'] == ['须弥']


def test_import_is_idempotent_and_supports_update(pack_dir, config_file, tmp_path):
    db = tmp_path / 'assets.db'
    import_assets(str(pack_dir), str(db), str(config_file))
    # 修改包内一帧后重复导入：覆盖更新，不产生重复记录
    (pack_dir / 'png' / '自定义角色' / '0001.png').write_bytes(b'PNG-A-V2')
    report = import_assets(str(pack_dir), str(db), str(config_file))
    assert report['new_roles'] == []  # 已存在，不算新角色

    store = ResourceStore(str(tmp_path))
    assert store.read_frame('自定义角色', '0001.png') == b'PNG-A-V2'
    assert len(store.list_frames('自定义角色')) == 2
    store.close()


def test_import_empty_pack_raises(tmp_path, config_file):
    empty = tmp_path / '空包'
    empty.mkdir()
    with pytest.raises(ValueError, match='未找到可导入的资源'):
        import_assets(str(empty), str(tmp_path / 'assets.db'), str(config_file))


def test_import_missing_path_raises(tmp_path, config_file):
    with pytest.raises(FileNotFoundError):
        import_assets(str(tmp_path / '不存在'), str(tmp_path / 'assets.db'), str(config_file))
