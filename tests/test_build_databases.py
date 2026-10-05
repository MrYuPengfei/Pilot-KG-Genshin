"""tools/build_databases.py 测试：由 CSV/YAML 构建 kg.db 与 config.db。

这是 v3.5 的核心链路——安装包里的库由构建工具从 CSV/YAML 生成，
运行时不再读 CSV/YAML。测试全部在临时目录中进行，不碰真实的三个库。
"""

import importlib.util
import os
import sqlite3
import sys

import pytest
import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from config_store import ConfigStore, DEFAULTS   # noqa: E402
from kg_store import KGStore, SCHEMA_VERSION as KG_SCHEMA   # noqa: E402

# 以文件方式加载构建工具：它是发布脚本而非库，import tools.build_databases
# 会在导入期就绑定 ROOT 常量，不利于测试用临时目录。
_spec = importlib.util.spec_from_file_location(
    'build_databases', os.path.join(ROOT, 'tools', 'build_databases.py'))
build_databases = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(build_databases)


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    """把构建工具的路径常量指向临时目录，并造一份最小的 CSV/YAML 输入。"""
    csv_dir = tmp_path / 'data' / 'csv'
    csv_dir.mkdir(parents=True)
    # 实体表：人物 + 神之眼（label 决定类型）
    (csv_dir / 'label-character.csv').write_text(
        'name,label,element\n甲,character,岩\n乙,character,火\n', encoding='utf-8')
    (csv_dir / 'label-element.csv').write_text(
        'name,label\n岩,element\n火,element\n', encoding='utf-8')
    # 关系表
    (csv_dir / 'rel-character-element.csv').write_text(
        'node1,rel,node2\n甲,element_is,岩\n乙,element_is,火\n', encoding='utf-8')

    seed = tmp_path / 'data' / 'config.yaml'
    seed.write_text(yaml.dump({
        'audio': False, 'bg_music': False, 'role': '乙',
        'img_path': 'png', 'music_path': 'music',
        'frame_scale': {'甲': [70, 1.4], '乙': [60, 0.8]},
    }, allow_unicode=True), encoding='utf-8')

    monkeypatch.setattr(build_databases, 'ROOT', str(tmp_path))
    monkeypatch.setattr(build_databases, 'CSV_DIR', str(csv_dir))
    monkeypatch.setattr(build_databases, 'SEED_YAML', str(seed))
    monkeypatch.setattr(build_databases, 'KG_DB', str(tmp_path / 'kg.db'))
    monkeypatch.setattr(build_databases, 'CONFIG_DB', str(tmp_path / 'config.db'))
    return tmp_path


# ---------- kg.db ----------

def test_build_kg_from_csv(workspace):
    report = build_databases.build_kg(verbose=False)
    assert report['nodes'] == 4 and report['edges'] == 2
    db = workspace / 'kg.db'
    assert db.is_file()
    store = KGStore(str(db), auto_seed=False)
    assert ('character', '甲') in store.nodes
    assert ('element', '岩') in store.nodes
    assert store.info()['built_from'] == 'data/csv'
    assert store.info()['schema_version'] == KG_SCHEMA
    store.close()


def test_build_kg_records_app_version(workspace):
    build_databases.build_kg(verbose=False)
    store = KGStore(str(workspace / 'kg.db'), auto_seed=False)
    assert store.info()['app_version']
    store.close()


def test_build_kg_skips_existing(workspace):
    build_databases.build_kg(verbose=False)
    # 第二次应跳过，不报错
    report = build_databases.build_kg(verbose=False)
    assert report['skipped'] is True


def test_build_kg_force_rebuilds(workspace):
    build_databases.build_kg(verbose=False)
    db = KGStore(str(workspace / 'kg.db'), auto_seed=False)
    db.add_node('npc', '临时')
    db.close()
    # 默认跳过 → 临时节点还在
    build_databases.build_kg(verbose=False)
    db = KGStore(str(workspace / 'kg.db'), auto_seed=False)
    assert ('npc', '临时') in db.nodes
    db.close()
    # --force 重建 → 回到 CSV 的内容
    build_databases.build_kg(force=True, verbose=False)
    db = KGStore(str(workspace / 'kg.db'), auto_seed=False)
    assert ('npc', '临时') not in db.nodes
    assert ('character', '甲') in db.nodes
    db.close()


def test_build_kg_missing_csv_dir(workspace, monkeypatch):
    monkeypatch.setattr(build_databases, 'CSV_DIR', str(workspace / 'nope'))
    with pytest.raises(FileNotFoundError, match='构建输入'):
        build_databases.build_kg(verbose=False)


def test_build_kg_leaves_no_partial_db(workspace, monkeypatch):
    """构建失败时不应留下半成品 .building 文件。"""
    bad = workspace / 'data' / 'csv' / 'label-broken.csv'
    bad.write_text('not,a,node\n1,2,3\n', encoding='utf-8')   # 无 name 列 → 空结果
    monkeypatch.setattr(build_databases, 'CSV_DIR', str(workspace / 'missing'))
    with pytest.raises(FileNotFoundError):
        build_databases.build_kg(verbose=False)
    assert not (workspace / 'kg.db.building').exists()


# ---------- config.db ----------

def test_build_config_from_yaml(workspace):
    report = build_databases.build_config(verbose=False)
    assert report['roles'] == 2 and report['role'] == '乙'
    store = ConfigStore(str(workspace), auto_seed=False)
    cfg = store.load()
    assert cfg['role'] == '乙'
    assert cfg['frame_scale']['甲'] == [70, 1.4]      # 精确保留出厂值
    assert store.get_meta('seeded_from') == 'data/config.yaml'
    store.close()


def test_build_config_force(workspace):
    build_databases.build_config(verbose=False)
    store = ConfigStore(str(workspace), auto_seed=False)
    store.set('role', '甲')
    store.close()
    build_databases.build_config(force=True, verbose=False)
    store = ConfigStore(str(workspace), auto_seed=False)
    assert store.load()['role'] == '乙'                 # 回到出厂值
    store.close()


def test_build_config_missing_seed_still_builds(workspace, monkeypatch):
    """没有 YAML 也能构建：出厂配置退化为内置默认值。"""
    monkeypatch.setattr(build_databases, 'SEED_YAML', str(workspace / 'nope.yaml'))
    report = build_databases.build_config(verbose=False)
    assert report['role'] == DEFAULTS['role']
    store = ConfigStore(str(workspace), auto_seed=False)
    assert store.get_meta('seeded_from') == 'defaults'
    store.close()


# ---------- 整体 ----------

def test_build_all(workspace):
    results = build_databases.build(verbose=False)
    assert (workspace / 'kg.db').is_file()
    assert (workspace / 'config.db').is_file()
    assert set(results) == {'kg', 'config'}


def test_check_mode_writes_nothing(workspace):
    results = build_databases.build(check_only=True, verbose=False)
    assert not (workspace / 'kg.db').exists()
    assert not (workspace / 'config.db').exists()
    assert results['kg']['csv_files'] == 3


def test_built_db_is_valid_sqlite(workspace):
    """产物必须是标准 SQLite 文件（安装包直接分发它）。"""
    build_databases.build(verbose=False)
    # 能连上且能查到表即为合法 SQLite 库
    kg_tables = {r[0] for r in sqlite3.connect(str(workspace / 'kg.db')).execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert {'kg_nodes', 'kg_edges', 'kg_meta'} <= kg_tables
    cfg_tables = {r[0] for r in sqlite3.connect(str(workspace / 'config.db')).execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert {'kv', 'frame_scale', 'config_meta'} <= cfg_tables


def test_runtime_does_not_need_csv(workspace):
    """v3.5 核心保证：只有库、没有 CSV/YAML 时，get_default_store 仍能打开。"""
    import kg_store
    build_databases.build(verbose=False)
    # 删掉所有 CSV/YAML，模拟安装包环境
    import shutil
    shutil.rmtree(workspace / 'data')
    kg_store.reset_default_store()
    store = kg_store.get_default_store(str(workspace))
    assert len(store.nodes) == 4
    store.close()
    kg_store.reset_default_store()

    cfg = ConfigStore(str(workspace), auto_seed=False)
    assert cfg.load()['role'] == '乙'
    cfg.close()
