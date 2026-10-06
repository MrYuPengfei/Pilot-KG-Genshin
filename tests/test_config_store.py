"""config_store 配置存储层测试（一律使用临时目录，不碰真实 config.db）。"""

import json
import os

import pytest

from config_store import ConfigStore, DEFAULTS, SCALAR_KEYS

SEED = {
    'audio': True,
    'bg_music': False,
    'img_path': 'png',
    'music_path': 'music',
    'role': '早柚',
    'frame_scale': {'早柚': [60, 0.73], '钟离': [60, 1.0]},
}


@pytest.fixture
def seed_dir(tmp_path):
    """建好出厂种子 data/config.json，返回（根目录, 种子路径）。

    v3.5 起 ConfigStore 运行时**不读**种子文件，它只在显式传 seed_path 时使用
    （构建工具与测试场景）；v3.8 起种子与导入导出**一律是 JSON**。
    """
    data = tmp_path / 'data'
    data.mkdir()
    seed = data / 'config.json'
    seed.write_text(json.dumps(SEED, ensure_ascii=False), encoding='utf-8')
    return tmp_path, seed


@pytest.fixture
def store(seed_dir):
    """带出厂种子的配置库（库在根目录；出厂值由 YAML 构建而来）。"""
    root, seed = seed_dir
    return ConfigStore(str(root), seed_path=str(seed))


def test_db_in_root_seed_not_read_at_runtime(seed_dir):
    """库文件在根目录；v3.5 起运行时不再自动读 YAML（seed_path 缺省即不读）。"""
    root, seed = seed_dir
    store = ConfigStore(str(root))          # 不传 seed_path
    assert os.path.dirname(store.db_path) == str(root)
    assert os.path.basename(store.db_path) == 'config.db'
    assert os.path.isfile(store.db_path)
    assert store.yaml_path is None
    # 没有种子可用 → 退回内置默认值，而不是去读 data/config.yaml
    assert store.get_meta('seeded_from') == 'defaults'
    assert store.load()['role'] == DEFAULTS['role']


def test_db_in_root_with_explicit_seed(seed_dir):
    """显式传 seed_path 时按 YAML 播种（构建出厂 config.db 的路径）。"""
    root, seed = seed_dir
    store = ConfigStore(str(root), seed_path=str(seed))
    assert store.yaml_path == str(seed)
    assert store.load()['role'] == '早柚'
    assert store.get_meta('seeded_from') == str(seed)


def test_seeded_from_yaml(store):
    cfg = store.load()
    assert cfg['role'] == '早柚'
    assert cfg['audio'] is True
    assert cfg['bg_music'] is False
    assert cfg['frame_scale']['早柚'] == [60, 0.73]
    assert set(cfg) == set(DEFAULTS) | {'frame_scale'}


def test_persists_across_instances(seed_dir):
    root, seed = seed_dir
    first = ConfigStore(str(root), seed_path=str(seed))
    first.set('role', '钟离')
    expected = first.load()
    first.close()

    second = ConfigStore(str(root), seed_path=str(seed))
    assert second.load() == expected
    assert second.load()['role'] == '钟离'
    assert second.stats()['roles'] == 2


def test_seed_missing_falls_back_to_defaults(tmp_path):
    """既无库也无种子时用内置默认值，程序仍能启动。"""
    store = ConfigStore(str(tmp_path))
    assert store.load()['role'] == DEFAULTS['role']
    assert store.get_meta('seeded_from') == 'defaults'


def test_broken_seed_does_not_crash(tmp_path):
    """种子文件损坏时静默退回默认值，不能因配置问题让程序起不来。"""
    (tmp_path / 'data').mkdir()
    (tmp_path / 'data' / 'config.json').write_text('{ 这不是合法 JSON',
                                                   encoding='utf-8')
    store = ConfigStore(str(tmp_path))
    assert store.load()['role'] == DEFAULTS['role']


def test_set_and_frame_scale(store):
    store.set('role', '魈')
    store.set('audio', False)
    assert store.load()['role'] == '魈'
    assert store.load()['audio'] is False

    store.set_frame_scale('魈', 80, 1.5)
    assert store.frame_scale('魈') == [80, 1.5]
    assert store.load()['frame_scale']['魈'] == [80, 1.5]


def test_frame_scale_values_clamped(store):
    """越界值被夹到面板允许的范围，防止 0 间隔导致动画不刷新。"""
    store.set_frame_scale('测试', 5, 99)
    assert store.frame_scale('测试') == [20, 3.0]
    store.set_frame_scale('测试2', 60, 0.001)
    assert store.frame_scale('测试2') == [60, 0.1]


def test_malformed_frame_scale_entry_fallback(store):
    store.save({'frame_scale': {'坏': ['x', 'y']}})
    assert store.frame_scale('坏') == [60, 1.0]


def test_register_role_idempotent(store):
    assert store.register_role('新人物') is True
    store.set_frame_scale('新人物', 90, 1.2)
    assert store.register_role('新人物') is False      # 已存在则不覆盖
    assert store.frame_scale('新人物') == [90, 1.2]
    assert store.unregister_role('新人物') == 1
    assert '新人物' not in store.load()['frame_scale']


def test_ensure_roles_registers_missing_only(store):
    """按资源库补齐人物登记（安装包不带 config.yaml 时的兜底路径）。

    fixture 的 SEED 已登记 早柚 / 钟离，因此只有两个新角色应被补上。
    """
    added = store.ensure_roles(['早柚', '钟离', '七七', '甘雨'])
    assert added == ['七七', '甘雨']
    assert store.frame_scale('七七') == [60, 1.0]
    assert store.frame_scale('早柚') == [60, 0.73]    # 原值不被覆盖
    assert store.frame_scale('钟离') == [60, 1.0]
    # 再调用一次没有新增
    assert store.ensure_roles(['早柚', '钟离', '七七', '甘雨']) == []


def test_ensure_roles_keeps_custom_timing(store):
    store.set_frame_scale('七七', 80, 1.5)
    store.ensure_roles(['七七', '新人物'])
    assert store.frame_scale('七七') == [80, 1.5]
    assert store.frame_scale('新人物') == [60, 1.0]


def test_ensure_roles_empty_input(store):
    assert store.ensure_roles([]) == []
    assert len(store.load()['frame_scale']) == 2


def test_ensure_roles_works_without_seed(tmp_path):
    """无种子（安装包场景）时也能按资源库登记人物。"""
    store = ConfigStore(str(tmp_path))
    assert store.get_meta('seeded_from') == 'defaults'
    # 内置默认只登记了「七七」，其余应全部补上
    added = store.ensure_roles(['七七', 'B', 'C'])
    assert added == ['B', 'C']
    assert set(store.load()['frame_scale']) == {'七七', 'B', 'C'}


def test_save_ignores_unknown_keys(store):
    """脏键不应进库（旧 config.yaml 曾有目录名与人物名不符的脏 key）。"""
    store.save({'role': '钟离', '乱七八糟': 1, 'frame_scale': {'钟离': [60, 1.0]}})
    cfg = store.load()
    assert '乱七八糟' not in cfg
    assert cfg['role'] == '钟离'


def test_save_requires_dict(store):
    with pytest.raises(TypeError):
        store.save(['not', 'a', 'dict'])


# ---------- 导入导出（v3.8 起只有 JSON） ----------

def test_export_import_roundtrip(store, tmp_path):
    store.set('role', '钟离')
    store.set_frame_scale('钟离', 70, 1.1)
    jsn = store.export_json(str(tmp_path / 'out.json'))

    with open(jsn, encoding='utf-8') as f:
        assert json.load(f)['frame_scale']['钟离'] == [70, 1.1]

    target = ConfigStore(str(tmp_path / 'target'))
    report = target.import_file(jsn, replace=True)
    assert report['mode'] == 'replace'
    assert target.load()['role'] == '钟离'
    assert target.frame_scale('钟离') == [70, 1.1]


def test_export_yaml_removed(store, tmp_path):
    """v3.8：export_yaml 已彻底删除，面板上也没有「导出 YAML」了。

    断言「方法不存在」而不是只测JSON 路径——否则将来有人把
    export_yaml 加回来悄悄恢复了旧格式，也不会有测试报警。
    """
    assert not hasattr(ConfigStore, 'export_yaml')


def test_import_merge_keeps_existing(store, tmp_path):
    src = tmp_path / 'src.json'
    src.write_text(json.dumps(
        {'role': '魈', 'frame_scale': {'早柚': [99, 2.0], '新角色': [60, 1.0]}},
        ensure_ascii=False), encoding='utf-8')
    report = store.import_file(str(src), replace=False)
    assert report['mode'] == 'merge'
    # 合并模式：标量被更新，但已有人物设置保留
    assert store.load()['role'] == '魈'
    assert store.frame_scale('早柚') == [60, 0.73]
    assert store.frame_scale('新角色') == [60, 1.0]


def test_import_replace_overwrites(store, tmp_path):
    src = tmp_path / 'src.json'
    src.write_text(json.dumps({'role': '魈', 'frame_scale': {'魈': [60, 1.0]}},
                              ensure_ascii=False), encoding='utf-8')
    store.import_file(str(src), replace=True)
    assert store.load()['role'] == '魈'
    # 覆盖模式：早柚不在新配置里，应被移除
    assert '早柚' not in store.load()['frame_scale']


def test_import_reports_unknown_keys(store, tmp_path):
    src = tmp_path / 'src.json'
    src.write_text(json.dumps({'role': '魈', '脏键': 1}, ensure_ascii=False),
                   encoding='utf-8')
    report = store.import_file(str(src), replace=True)
    assert report['unknown_keys'] == ['脏键']
    assert '脏键' not in store.load()


def test_import_json_content_with_other_suffix(store, tmp_path):
    """后缀不是 .json 也照样按 JSON 读（有人会把配置存成 .txt/.conf）。"""
    src = tmp_path / 'conf.txt'
    src.write_text(json.dumps({'role': '魈', 'frame_scale': {}}, ensure_ascii=False),
                   encoding='utf-8')
    store.import_file(str(src), replace=True)
    assert store.load()['role'] == '魈'


@pytest.mark.parametrize('name', ['old.yaml', 'old.yml'])
def test_import_yaml_is_rejected(store, tmp_path, name):
    """v3.8：YAML 不再支持，且必须**明确报错**而不是静默按 JSON 读。

    静默兼容一个已退役的格式是危险的：YAML 长得像 JSON 的超集，
    真按 JSON 解析多半直接报「格式无法识别」，但若文件碰巧是
    JSON 合法 YAML，用户会以为导入了 YAML 却被改写成 JSON——
    所以这里要求给出**明确的**、提到 JSON 的错误信息。
    """
    src = tmp_path / name
    src.write_text('role: 魈\nframe_scale: {}\n', encoding='utf-8')
    with pytest.raises(ValueError) as exc:
        store.import_file(str(src))
    assert 'YAML' in str(exc.value) and 'JSON' in str(exc.value)


def test_import_errors(store, tmp_path):
    with pytest.raises(FileNotFoundError):
        store.import_file(str(tmp_path / 'nope.json'))
    bad_json = tmp_path / 'bad.json'
    bad_json.write_text('{oops', encoding='utf-8')
    with pytest.raises(ValueError):
        store.import_file(str(bad_json))
    empty = tmp_path / 'empty.json'
    empty.write_text('', encoding='utf-8')
    with pytest.raises(ValueError):
        store.import_file(str(empty))
    # 内容是合法 JSON 但不是配置对象（这里是数组）也要拒绝
    not_obj = tmp_path / 'arr.json'
    not_obj.write_text('[1, 2]', encoding='utf-8')
    with pytest.raises(ValueError):
        store.import_file(str(not_obj))


def test_reset_to_seed(store):
    store.set('role', '魈')
    store.set_frame_scale('早柚', 200, 2.0)
    cfg = store.reset_to_seed()
    assert cfg['role'] == '早柚'
    assert cfg['frame_scale']['早柚'] == [60, 0.73]
    assert '魈' not in cfg['frame_scale']


def test_stats(store):
    s = store.stats()
    assert s['backend'] == 'sqlite'
    assert s['roles'] == 2
    assert s['scalars'] == len(SCALAR_KEYS)
    assert s['db_size_kb'] >= 0
    assert s['db_path'].endswith('config.db')
