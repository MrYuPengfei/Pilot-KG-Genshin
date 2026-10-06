"""kg_store 知识图谱存储层测试。

数据来自仓库内真实 data/csv，但一律播种到临时 kg.db（原库只读）。
"""

import csv
import os

import pytest

from kg_store import KGStore, NODE_TYPES, REL_NAMES, rel_cn

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, 'data', 'csv')


@pytest.fixture(scope='module')
def kg(tmp_path_factory):
    db = tmp_path_factory.mktemp('kg') / 'kg.db'
    return KGStore(str(db), seed_dir=DATA_DIR)


@pytest.fixture
def empty_kg(tmp_path):
    return KGStore(str(tmp_path / 'kg.db'), auto_seed=False)


# ---------- 播种与查询 ----------

def test_seeded_from_csv(kg):
    s = kg.stats()
    assert s['nodes'] > 1800
    assert s['edges'] > 7000
    assert s['backend'] == 'sqlite'
    for t in NODE_TYPES:
        assert s['by_type'][t] > 0, t


def test_db_persists_across_instances(tmp_path):
    """关闭重开后数据仍在，且不会重复播种。"""
    db = str(tmp_path / 'kg.db')
    first = KGStore(db, seed_dir=DATA_DIR)
    nodes = first.stats()['nodes']
    first.add_node('npc', '持久化测试')
    first.close()

    second = KGStore(db, seed_dir=DATA_DIR)
    assert second.stats()['nodes'] == nodes + 1
    assert second.find('持久化测试') == [('npc', '持久化测试')]


# ---------- 每次改动都落盘（v3.8 锁定） ----------
#
# 需求：「每次修改（增删改）后，将改动保存到 kg.db」。
# 实现上每个写方法都用 `with self._conn:` 包裹（块退出即 commit），
# 下面这些用例**关掉连接重开一个新实例**来验证，避免「内存里有、文件里没有」
# 的假象——只查内存索引是测不出漏提交的。

def test_add_node_persists_immediately(tmp_path):
    """新增实体：不close 直接重开也应能看到。"""
    db = str(tmp_path / 'kg.db')
    KGStore(db, seed_dir=DATA_DIR).add_node('npc', '即时落盘A')
    assert ('npc', '即时落盘A') in KGStore(db, auto_seed=False).nodes


def test_update_node_persists_immediately(tmp_path):
    """改属性/改名：改名会连带迁移关系，重开后都要对得上。"""
    db = str(tmp_path / 'kg.db')
    store = KGStore(db, seed_dir=DATA_DIR)
    store.add_node('npc', '即时落盘B')
    store.update_node(('npc', '即时落盘B'), name='即时落盘B2',
                      attrs={'来源': '单测', '等级': '90'})
    store.close()

    reopened = KGStore(db, auto_seed=False)
    assert ('npc', '即时落盘B2') in reopened.nodes
    assert reopened.node_attrs(('npc', '即时落盘B2')) == {'来源': '单测', '等级': '90'}


def test_delete_node_persists_immediately(tmp_path):
    """删除实体：重开后不应复活（连同其关系一起消失）。"""
    db = str(tmp_path / 'kg.db')
    store = KGStore(db, seed_dir=DATA_DIR)
    store.add_node('npc', '即时落盘C')
    store.add_edge(('npc', '即时落盘C'), 'test_rel', ('character', '钟离'))
    store.delete_node(('npc', '即时落盘C'))
    store.close()

    reopened = KGStore(db, auto_seed=False)
    assert ('npc', '即时落盘C') not in reopened.nodes
    assert not any('即时落盘C' in (e[0][1], e[2][1]) for e in reopened._edges)


def test_add_edge_persists_immediately(tmp_path):
    """新增关系：重开后仍在，且两端类型/名字都对。"""
    db = str(tmp_path / 'kg.db')
    store = KGStore(db, seed_dir=DATA_DIR)
    store.add_node('npc', '即时落盘D')
    store.add_edge(('npc', '即时落盘D'), 'test_rel', ('character', '钟离'))
    store.close()

    reopened = KGStore(db, auto_seed=False)
    # _edges 是 set，元素为 ((源类型,源名), 关系名, (目标类型,目标名))
    assert (('npc', '即时落盘D'), 'test_rel', ('character', '钟离')) in reopened._edges


def test_update_and_delete_edge_persist_immediately(tmp_path):
    """改关系名 / 换对端 / 删关系，三种都要落盘。

    这条走的是 ``*_edge_touching`` 包装（面板的可视化用的是它），
    它本身不碰数据库、只委托给 ``update_edge`` / ``delete_edge``——
    一旦委托链断了，改动就只留在内存里，故单独锁一次。
    """
    db = str(tmp_path / 'kg.db')
    store = KGStore(db, seed_dir=DATA_DIR)
    store.add_node('npc', '即时落盘E')
    store.add_edge(('npc', '即时落盘E'), '旧关系', ('character', '钟离'))

    src, dst = ('npc', '即时落盘E'), ('character', '钟离')
    store.update_edge_touching(src, '旧关系', dst, new_rel='新关系')
    store.close()
    reopened = KGStore(db, auto_seed=False)
    assert (src, '新关系', dst) in reopened._edges
    assert (src, '旧关系', dst) not in reopened._edges
    reopened.close()

    store = KGStore(db, auto_seed=False)
    store.delete_edge_touching(src, '新关系', dst)
    store.close()
    reopened = KGStore(db, auto_seed=False)
    assert (src, '新关系', dst) not in reopened._edges
    assert src in reopened.nodes      # 只删关系，实体仍在


def test_import_csv_persists_immediately(tmp_path):
    """整目录导入 CSV 同样要落盘（面板的「导入图谱 CSV」走这条）。"""
    db = str(tmp_path / 'kg.db')
    store = KGStore(db, auto_seed=False)
    csv_dir = tmp_path / 'csv'
    csv_dir.mkdir()
    (csv_dir / 'label-character.csv').write_text(
        'name,label,element\n甲,character,岩\n乙,character,火\n', encoding='utf-8')
    (csv_dir / 'rel-character-element.csv').write_text(
        'node1,rel,node2\n甲,element_is,岩\n乙,element_is,火\n', encoding='utf-8')
    store.import_csv(str(csv_dir), replace=True)
    store.close()

    reopened = KGStore(db, auto_seed=False)
    # 关系表里的「岩」「火」会被自动建为 element 实体，故是 2 人物 + 2 元素
    assert reopened.stats()['nodes'] == 4
    assert reopened.stats()['edges'] == 2


def test_kg_db_is_not_overwritten_on_upgrade():
    """**升级安装不得覆盖用户的 kg.db**。

    图谱编辑就写在安装目录的 kg.db 里。若安装脚本跟着 recursesubdirs
    无条件复制，每次升级都会把用户的编辑清空——表现为「明明存了，
    升级后就没了」。config.db 同理，两者都必须 onlyifdoesntexist。
    """
    iss = open(os.path.join(ROOT, 'setup.iss'), encoding='utf-8').read()
    assert 'Excludes: "config.db,kg.db"' in iss, \
        '批量复制必须排除 config.db 与 kg.db'
    for db in ('config.db', 'kg.db'):
        assert f'_internal\\{db}"; DestDir: "{{app}}\\_internal"; Flags: onlyifdoesntexist' in iss, \
            f'{db} 应用 onlyifdoesntexist 安装，否则升级会清空用户数据'


def test_find_and_neighbors(kg):
    keys = kg.find('阿贝多')
    assert keys == [('character', '阿贝多')]
    neighbors = kg.neighbors(keys[0])
    rels = {rel for rel, _, _ in neighbors}
    assert {'element_is', 'come_from', 'weapon_is'} <= rels
    targets = {other[1] for _, _, other in neighbors}
    assert '蒙德' in targets and '岩' in targets


def test_rel_direction_resolved(kg):
    """rel-country-area.csv 实际方向是 地区→国家，两端类型须正确解析。"""
    assert ('area', '鹤观') in kg.find('鹤观')
    assert any(rel == 'part_of' and other == ('country', '稻妻')
               for rel, _, other in kg.neighbors(('area', '鹤观')))


def test_junk_nodes_filtered(kg):
    assert not kg.find('暂无')
    assert ('country', '暂无') not in kg.nodes
    aloy = kg.find('埃洛伊')
    assert all(t[1] != '暂无' for _, _, t in kg.neighbors(aloy[0]))


def test_artifacts_type_kept(kg):
    """label-artifacts.csv 自带 type 列（圣遗物部位），不能据此改判实体类型。"""
    node = kg.nodes.get(('artifacts', '魔女的炎之花'))
    assert node is not None
    assert node['attrs'].get('type')    # 部位仍作为普通属性保留


def test_search(kg):
    assert kg.search('钟离')[0] == ('character', '钟离')
    assert any(k[1] == '护摩之杖' for k in kg.search('护摩'))
    assert kg.search('') == []


def test_ego_network(kg):
    nodes, edges = kg.ego_network(('character', '钟离'), hops=1)
    assert ('character', '钟离') in nodes
    assert ('country', '璃月') in nodes
    expected = {('character', '钟离')} | {o for _, _, o in kg.neighbors(('character', '钟离'))}
    assert nodes == expected
    for k1, rel, k2 in edges:
        assert k1 in nodes and k2 in nodes
        assert rel_cn(rel) == rel or rel in REL_NAMES


def test_missing_seed_dir_raises(tmp_path):
    """首次运行且初始数据目录缺失时应报错，而不是静默得到空图谱。"""
    with pytest.raises(FileNotFoundError):
        KGStore(str(tmp_path / 'x.db'), seed_dir='不存在的目录')


# ---------- 节点增删改 ----------

def test_add_node_and_dup(empty_kg):
    assert empty_kg.add_node('npc', '测试NPC', {'note': 'hi'}) is True
    assert empty_kg.find('测试NPC') == [('npc', '测试NPC')]
    assert empty_kg.node_attrs(('npc', '测试NPC')) == {'note': 'hi'}
    # overwrite=False 时同名不再新建
    assert empty_kg.add_node('npc', '测试NPC', {}, overwrite=False) is False
    # 默认覆盖属性
    empty_kg.add_node('npc', '测试NPC', {'note': 'new'})
    assert empty_kg.node_attrs(('npc', '测试NPC')) == {'note': 'new'}


def test_add_node_validation(empty_kg):
    with pytest.raises(ValueError):
        empty_kg.add_node('unknown', 'x')
    with pytest.raises(ValueError):
        empty_kg.add_node('npc', '暂无')      # 占位名
    with pytest.raises(ValueError):
        empty_kg.add_node('npc', '   ')


def test_update_node_rename_migrates_edges(empty_kg):
    empty_kg.add_node('npc', '旧名')
    empty_kg.add_node('character', '钟离')
    empty_kg.add_edge(('character', '钟离'), 'knows', ('npc', '旧名'))

    new_key = empty_kg.update_node(('npc', '旧名'), name='新名')
    assert new_key == ('npc', '新名')
    assert ('npc', '旧名') not in empty_kg.nodes
    # 关系端点随改名迁移
    assert empty_kg.edges_of(('npc', '新名')) == [('knows', ('character', '钟离'), 'in')]
    assert empty_kg.find('旧名') == []


def test_update_node_change_type(kg):
    """改类型同样迁移关系；用完即还原，避免污染模块级图谱。"""
    key = ('material', '凛风奔狼的始龀')
    assert kg.node_attrs(key), '前置数据缺失：凛风奔狼的始龀'
    rel_before = len(kg.edges_of(key))
    assert rel_before > 0

    kg.update_node(key, ntype='food')
    assert ('food', '凛风奔狼的始龀') in kg.nodes
    assert key not in kg.nodes
    assert len(kg.edges_of(('food', '凛风奔狼的始龀'))) == rel_before

    kg.update_node(('food', '凛风奔狼的始龀'), ntype='material')
    assert key in kg.nodes
    assert len(kg.edges_of(key)) == rel_before


def test_update_node_conflict(kg):
    with pytest.raises(ValueError):
        kg.update_node(('element', '岩'), ntype='element', name='冰')
    with pytest.raises(KeyError):
        kg.update_node(('element', '不存在的元素'), name='x')


def test_delete_node_cascades(kg):
    key = ('material', '临时删除材料')
    kg.add_node('material', '临时删除材料')
    kg.add_edge(key, 'drop_from', ('master', '丘丘人'))
    nodes, edges = kg.delete_node(key)
    assert nodes == 1 and edges == 1
    assert key not in kg.nodes
    assert kg.edges_of(('master', '丘丘人')) is not None
    # 再删一次返回 0，不报错
    assert kg.delete_node(key) == (0, 0)


# ---------- 关系增删改 ----------

def test_add_edge(kg):
    src, dst = ('character', '刻晴'), ('element', '雷')
    assert (src, 'smoke_rel', dst) not in kg.edges_of(src)
    assert kg.add_edge(src, 'smoke_rel', dst) is True
    assert ('smoke_rel', dst, 'out') in kg.edges_of(src)
    assert kg.add_edge(src, 'smoke_rel', dst, overwrite=False) is False
    kg.delete_edge_touching(src, 'smoke_rel', dst)


def test_add_edge_validation(kg):
    with pytest.raises(ValueError):
        kg.add_edge(('element', '岩'), 'x', ('element', '岩'))      # 自环
    with pytest.raises(ValueError):
        kg.add_edge(('element', '岩'), '  ', ('element', '水'))      # 空关系名
    with pytest.raises(KeyError):
        kg.add_edge(('element', '不存在'), 'x', ('element', '水'))    # 端点缺失


def test_update_edge_touching_direction_agnostic(empty_kg):
    """UI 只知道「某实体—关系—另一实体」，改关系名不应要求判断方向。"""
    empty_kg.add_node('character', 'A')
    empty_kg.add_node('character', 'B')
    empty_kg.add_node('character', 'C')
    empty_kg.add_edge(('character', 'A'), 'r1', ('character', 'B'))

    # 锚点 B 在库中是目标端，rename 后方向应保持
    triple = empty_kg.update_edge_touching(('character', 'B'), 'r1',
                                           ('character', 'A'), new_rel='r2')
    assert triple == (('character', 'A'), 'r2', ('character', 'B'))
    assert empty_kg.edges_of(('character', 'B')) == [('r2', ('character', 'A'), 'in')]

    # 换对端：锚点 A 为源端，新对端接在后面
    triple = empty_kg.update_edge_touching(('character', 'A'), 'r2',
                                           ('character', 'B'),
                                           new_other=('character', 'C'))
    assert triple == (('character', 'A'), 'r2', ('character', 'C'))


def test_delete_edge_touching(kg):
    src, dst = ('character', '刻晴'), ('npc', '临时关系对端')
    kg.add_node('npc', '临时关系对端')
    kg.add_edge(src, 'tmp', dst)
    assert kg.delete_edge_touching(dst, 'tmp', src) == 1     # 从目标端删
    assert kg.delete_edge_touching(dst, 'tmp', src) == 0     # 幂等
    kg.delete_node(dst)


# ---------- CSV 导入导出 ----------

def test_export_then_reimport_roundtrip(kg, tmp_path):
    out = str(tmp_path / 'kg_out')
    report = kg.export_csv(out)
    assert report['node_files'] == len(NODE_TYPES)
    assert report['node_rows'] == kg.stats()['nodes']
    assert report['edge_rows'] == kg.stats()['edges']

    clone = KGStore(str(tmp_path / 'clone.db'), auto_seed=False)
    rep = clone.import_csv(out, replace=True)
    assert rep['nodes_added'] == report['node_rows']
    assert rep['edges_added'] == report['edge_rows']
    assert clone.stats()['nodes'] == kg.stats()['nodes']
    assert clone.stats()['edges'] == kg.stats()['edges']
    # 关键关系在往返后保持
    assert any(rel == 'part_of' and other == ('country', '稻妻')
               for rel, _, other in clone.neighbors(('area', '鹤观')))
    clone.close()


def test_export_edge_direction_in_filename(kg, tmp_path):
    """关系按真实方向命名（原数据里 rel-country-area 方向与文件名相反）。"""
    out = str(tmp_path / 'kg_dir')
    kg.export_csv(out)
    assert os.path.isfile(os.path.join(out, 'rel-area-country.csv'))
    with open(os.path.join(out, 'rel-area-country.csv'), encoding='utf-8-sig') as f:
        rows = list(csv.DictReader(f))
    assert any(r['node1'] == '鹤观' and r['node2'] == '稻妻' for r in rows)


def test_import_single_rel_file(empty_kg, tmp_path):
    empty_kg.add_node('character', '刻晴')
    empty_kg.add_node('element', '雷')
    path = tmp_path / 'relations.csv'
    with open(path, 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.writer(f)
        w.writerow(['node1', 'rel', 'node2'])
        w.writerow(['刻晴', 'element_is', '雷'])
        w.writerow(['刻晴', 'bad_rel', ''])       # 缺列，应跳过
    rep = empty_kg.import_csv(str(path))
    assert rep['edges_added'] == 1
    assert ('element_is', ('element', '雷'), 'out') in empty_kg.edges_of(('character', '刻晴'))


def test_import_single_node_file(empty_kg, tmp_path):
    path = tmp_path / 'nodes.csv'
    with open(path, 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.writer(f)
        w.writerow(['name', 'label', 'title'])
        w.writerow(['某NPC', 'npc', '旅人'])
        w.writerow(['暂无', 'npc', '占位应被过滤'])
    rep = empty_kg.import_csv(str(path))
    assert rep['nodes_added'] == 1
    assert empty_kg.node_attrs(('npc', '某NPC')) == {'title': '旅人'}


def test_import_stub_endpoint(empty_kg, tmp_path):
    """关系端点不在实体表中时按文件名类型提示建桩。"""
    path = tmp_path / 'rel-character-element.csv'
    with open(path, 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.writer(f)
        w.writerow(['node1', 'rel', 'node2'])
        w.writerow(['无名角色', 'element_is', '火'])
    rep = empty_kg.import_csv(str(path))
    assert rep['stubs'] == 2
    assert ('character', '无名角色') in empty_kg.nodes
    assert ('element', '火') in empty_kg.nodes
    assert rep['edges_added'] == 1


def test_import_merge_vs_replace(kg, tmp_path):
    path = tmp_path / 'extra.csv'
    with open(path, 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.writer(f)
        w.writerow(['name', 'label', 'note'])
        w.writerow(['合并测试实体', 'npc', 'v1'])

    before = kg.stats()['nodes']
    rep = kg.import_csv(str(path))                 # 合并
    assert rep['nodes_added'] == 1
    assert kg.stats()['nodes'] == before + 1
    assert kg.node_attrs(('npc', '合并测试实体')) == {'note': 'v1'}

    kg.import_csv(str(path))                       # 再次合并 → 更新
    assert kg.stats()['nodes'] == before + 1

    kg.delete_node(('npc', '合并测试实体'))
    assert kg.stats()['nodes'] == before


def test_import_errors(empty_kg, tmp_path):
    with pytest.raises(FileNotFoundError):
        empty_kg.import_csv(str(tmp_path / '不存在.csv'))
    empty_dir = tmp_path / 'emptydir'
    empty_dir.mkdir()
    with pytest.raises(FileNotFoundError):
        empty_kg.import_csv(str(empty_dir))
    bad = tmp_path / 'bad.csv'
    bad.write_text('foo,bar\n1,2\n', encoding='utf-8')
    with pytest.raises(ValueError):
        empty_kg.import_csv(str(bad))
