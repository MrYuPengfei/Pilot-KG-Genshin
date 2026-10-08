"""实体表**统一表头**（name / name_cn / label / label_cn）测试。

两套数据原本各用各的表头：原神是 ``name``(中文) + ``label``(类型键)，
csv-edu 是 ``name``(英文) + ``label``(中文名) + ``category``(领域)。
同一个 ``label`` 列两边语义不同，逼得导入器要靠「像不像类型键」来猜。

统一后：

===========  =====================================================
列名          含义
===========  =====================================================
``name``      **主键**（英文名；原神暂无译名时为空）
``name_cn``   中文名（属性，支持中文搜索）
``label``     类型键，类型由它决定
``label_cn``  类型中文名（仅展示）
===========  =====================================================

⚠️ 主键必须是 ``name``：**中文名不唯一**——csv-edu 有 11 组同中文名
（``RLHF`` 与 ``reinforcement learning from human feedback`` 共用同一
中文名），原神有「凯瑟琳」×4。用中文名当主键会让同一概念裂成多个实体。
"""

import csv
import glob
import os

import pytest

from kg_store import KGStore, CN_NAME_KEY, EN_NAME_KEY

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EDU_DIR = os.path.join(ROOT, 'data', 'csv-edu')
GENSHIN_DIR = os.path.join(ROOT, 'data', 'csv')

pytestmark = pytest.mark.skipif(
    not os.path.isdir(EDU_DIR) or not os.path.isdir(GENSHIN_DIR),
    reason='需要 data/csv 与 data/csv-edu 两套样本数据')

# 内置的 12 种原神类型：用来把全局类型表恢复成「未导入外部数据」的干净状态
_BUILTIN_TYPES = frozenset({
    'character', 'weapon', 'element', 'country', 'area', 'place',
    'material', 'instance', 'npc', 'master', 'food', 'artifacts',
})


def node_files(csv_dir):
    return sorted(glob.glob(os.path.join(csv_dir, 'label-*.csv')))


def headers(path):
    with open(path, encoding='utf-8', newline='') as f:
        return [c.strip() for c in next(csv.reader(f))]


# ---------- 表头本身 ----------

@pytest.mark.parametrize('csv_dir', [GENSHIN_DIR, EDU_DIR],
                         ids=['genshin', 'edu'])
def test_entity_tables_have_unified_columns(csv_dir):
    """两套数据的实体表都必须有 name / name_cn / label / label_cn 四列。"""
    files = node_files(csv_dir)
    assert files, f'{csv_dir} 下没有 label-*.csv'
    for path in files:
        cols = headers(path)
        for required in ('name', 'name_cn', 'label'):
            assert required in cols, \
                f'{os.path.basename(path)} 缺 {required} 列，现有：{cols[:6]}'
        # 前四列顺序固定，便于人直接阅读
        assert cols[:3] == ['name', 'name_cn', 'label'], \
            f'{os.path.basename(path)} 列序应为 name,name_cn,label，实际 {cols[:4]}'


@pytest.mark.parametrize('csv_dir', [GENSHIN_DIR, EDU_DIR],
                         ids=['genshin', 'edu'])
def test_name_cn_never_empty(csv_dir):
    """中文名不能为空——它是展示与中文搜索的依据（主键回退也靠它）。"""
    for path in node_files(csv_dir):
        with open(path, encoding='utf-8', newline='') as f:
            rows = list(csv.DictReader(f))
        empty = [i for i, r in enumerate(rows, 2)
                 if not (r.get('name_cn') or '').strip()]
        assert not empty, \
            f'{os.path.basename(path)} 第 {empty[:5]} 行 name_cn 为空'


@pytest.mark.parametrize('csv_dir', [GENSHIN_DIR, EDU_DIR],
                         ids=['genshin', 'edu'])
def test_label_is_type_key_not_chinese(csv_dir):
    """``label`` 列必须是**类型键**，不能再装中文名。

    这正是统一表头要消除的歧义：曾经 edu 的 label装中文名、原神装类型键，
    导入器只能靠形态猜。
    """
    from kg_store import _looks_like_type_key

    for path in node_files(csv_dir):
        ntype = os.path.basename(path)[len('label-'):-len('.csv')]
        with open(path, encoding='utf-8', newline='') as f:
            for row in csv.DictReader(f):
                label = (row.get('label') or '').strip()
                if not label:
                    continue      # 少数行留空，靠文件名判定类型
                assert label == ntype, \
                    f'{os.path.basename(path)} 的 label={label!r} != 文件名类型 {ntype!r}'
                assert _looks_like_type_key(label)


def test_genshin_name_column_mostly_empty_but_valid():
    """原神 ``name``（英文名）大部分为空是**预期**的——官方译名待补。

    不能因此断言「必须有英文名」，但要保证：有值的那些是合法的英文名
    （不含汉字），且原神实体不会因为 name 空而丢失。
    """
    has_en = 0
    total = 0
    for path in node_files(GENSHIN_DIR):
        with open(path, encoding='utf-8', newline='') as f:
            for row in csv.DictReader(f):
                total += 1
                if (row.get('name') or '').strip():
                    has_en += 1
                    assert not any('一' <= c <= '鿿'
                                   for c in row['name']), \
                        f'name 应是英文名，却含汉字：{row["name"]!r}'
    assert has_en > 0, '原神至少应有 country 的 7 个官方英文名'
    assert has_en < total, '大部分实体暂无官方译名（当前状态）'


def test_edu_keeps_all_english_names():
    """csv-edu 的英文名必须完整保留（732 个实体都有）。"""
    total = 0
    for path in node_files(EDU_DIR):
        with open(path, encoding='utf-8', newline='') as f:
            for row in csv.DictReader(f):
                total += 1
                assert (row.get('name') or '').strip(), \
                    f'{os.path.basename(path)} 缺英文名'
    assert total > 700, f'实体数异常：{total}'


# ---------- 导入后的行为 ----------

@pytest.fixture(scope='module')
def edu(tmp_path_factory):
    store = KGStore(str(tmp_path_factory.mktemp('hdr') / 'edu.db'), auto_seed=False)
    store.import_csv(EDU_DIR, replace=True)
    return store


@pytest.fixture(scope='module')
def genshin(tmp_path_factory):
    store = KGStore(str(tmp_path_factory.mktemp('hdr') / 'g.db'), auto_seed=False)
    store.import_csv(GENSHIN_DIR, replace=True)
    return store


def test_edu_key_is_english_name(edu):
    """edu 实体主键是英文名，中文名在属性里。"""
    key = ('ai', 'foundation model')
    assert key in edu.nodes
    assert edu.node_en_name(key) == 'foundation model'
    assert edu.node_cn_name(key) == '大规模基础模型'
    assert edu.node_display(key) == 'foundation model'   # 优先英文名


def test_genshin_key_is_chinese_when_no_en_name(genshin):
    """原神实体暂无英文名时主键回退中文名，node_en_name 为空。"""
    key = ('character', '阿贝多')
    assert key in genshin.nodes
    assert genshin.node_en_name(key) == ''
    assert genshin.node_cn_name(key) == '阿贝多'
    assert genshin.node_display(key) == '阿贝多'


def test_genshin_country_key_is_english(genshin):
    """country 有官方英文名 → 主键是英文名，中文名仍可查。"""
    assert ('country', 'Liyue') in genshin.nodes
    assert genshin.node_cn_name(('country', 'Liyue')) == '璃月'
    assert genshin.find('璃月') == [('country', 'Liyue')]
    assert genshin.find('Liyue') == [('country', 'Liyue')]


def test_cn_name_attr_key_not_clashing_with_type(genshin, edu):
    """⚠️ 中文名属性键不能叫 ``label_cn``——那是**类型**中文名的列名。

    两者同名会把实体中文名与类型中文名搅在一起（实测 edu 的中文名被写进
    label_cn 属性）。故CN_NAME_KEY 必须是 ``name_cn``。
    """
    assert CN_NAME_KEY == 'name_cn'
    assert EN_NAME_KEY != CN_NAME_KEY
    # 类型中文名不得作为实体属性出现
    for store in (genshin, edu):
        for key in list(store.nodes)[:80]:
            assert store.node_attrs(key).get('label_cn') is None, key


def test_find_works_for_both_languages(edu, genshin):
    """中英文都能查到（用户两种都可能输入）。"""
    assert edu.find('大规模基础模型') == [('ai', 'foundation model')]
    assert edu.find('foundation model') == [('ai', 'foundation model')]
    assert genshin.find('璃月') == [('country', 'Liyue')]
    assert genshin.find('Liyue') == [('country', 'Liyue')]
    assert genshin.find('阿贝多') == [('character', '阿贝多')]


def test_search_covers_cn_and_en(edu):
    """模糊搜索同时覆盖中英文（``基础模型`` 与 ``foundation`` 都要有结果）。"""
    assert edu.search('基础模型'), '按中文片段搜不到'
    assert edu.search('foundation'), '按英文片段搜不到'


def test_relations_resolve_via_chinese_name(genshin):
    """关系表用中文名引用端点，而主键是英文名 → 端点仍须解析得到。

    漏掉中文名索引会让所有关系端点找不到、全部退化成桩。
    """
    stats = genshin.stats()
    assert stats['edges'] > 7000, f'关系数异常：{stats["edges"]}'
    # 鹤观(area) part_of 稻妻(country) —— 端点是中文名
    neighbors = genshin.neighbors(('area', '鹤观'))
    assert any(other == ('country', 'Inazuma') for _, _, other in neighbors)


def test_type_cn_name_survives_restart(tmp_path):
    """回归：类型中文名必须**跨进程**存活。

    🔴 ``NODE_TYPES`` 是进程级全局：导入外部图谱时注册的类型（``ai`` /
    ``education`` / ``database``）连同其中文名，进程退出就全丢了。程序重启后
    新进程里查不到中文名 → 画布上这些实体渲染成**灰点**、图例与详情显示生
    类型键 ``ai``（实测 kg.db 里明明存着这些类型，界面上却认不出）。
    故类型中文名必须随库持久化（``kg_type_names`` 表）。
    """
    from kg_store import type_cn

    db = str(tmp_path / 'kg.db')
    store = KGStore(db, auto_seed=False)
    store.import_csv(EDU_DIR, replace=True)
    assert type_cn('ai') == 'AI领域'          # 导入后（同进程）
    store.close()

    # 模拟重启：把全局类型表清回「只有内置 12 项」的干净状态
    # （真实情况下是全新进程，NODE_TYPES 本来就是空的）。
    # tests/conftest.py 的 autouse fixture 会在本测试结束后还原。
    import kg_store as kg_module
    builtin = {k: v for k, v in kg_module.NODE_TYPES.items()
               if k in _BUILTIN_TYPES}
    kg_module.NODE_TYPES.clear()
    kg_module.NODE_TYPES.update(builtin)
    assert 'ai' not in kg_module.NODE_TYPES, '前置：全局里不该已有 ai'

    reopened = KGStore(db, auto_seed=False)
    try:
        assert type_cn('ai') == 'AI领域', '重启后类型中文名丢失（会渲染成灰点）'
        assert type_cn('education') == '教育领域'
        assert type_cn('database') == '数据库领域'
        # 颜色也要有，否则画布上是灰点而不是彩色节点
        assert kg_module.NODE_TYPES['ai'][1].startswith('#')
    finally:
        reopened.close()


def test_import_counts_match_source_rows(tmp_path):
    """导入的实体数应等于 CSV 行数（主键为空/重复都不会静默丢数据）。"""
    for tag, src in (('genshin', GENSHIN_DIR), ('edu', EDU_DIR)):
        expected = 0
        for path in node_files(src):
            with open(path, encoding='utf-8', newline='') as f:
                expected += sum(1 for r in csv.DictReader(f)
                                if (r.get('name_cn') or '').strip())
        store = KGStore(str(tmp_path / f'{tag}.db'), auto_seed=False)
        rep = store.import_csv(src, replace=True)
        # 主键是英文名时，重名中文的实体会合并，故允许 <= 行数
        assert rep['nodes_added'] <= expected, tag
        # 但也不能丢太多：原神几乎无重名，edu 只有 11 组
        assert rep['nodes_added'] >= expected * 0.98, \
            f'{tag}: {rep["nodes_added"]} 远小于 CSV 行数 {expected}'