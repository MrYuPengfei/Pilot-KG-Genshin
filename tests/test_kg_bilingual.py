"""知识图谱「中英双语标签」测试（v3.9.1）。

覆盖三件新做的事：

1. **关系中文名单独成表**（``kg_rel_names``）：随 CSV 走、落盘、往返无损，
   且不与代码里的静态 :data:`REL_NAMES` 打架；
2. **节点标签显示完整英文名 + 中文名**：原先英文名被截到7 字符
   （``reinforcement learning...`` → ``rein…``），等于没显示；
3. **边标签同时给关系中文名与英文名**。

⚠️ 断言一律针对**可见文本**（``toPlainText()``）而不是 HTML 源码：
HTML 里那些 ``<span>``/``font-size`` 只是排版，用户看到的是渲染后的文字。
"""

import csv
import glob
import os

import pytest

from kg_store import KGStore, DEFAULT_WEIGHT, EN_NAME_KEY, REL_NAMES, rel_cn

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EDU_DIR = os.path.join(ROOT, 'data', 'csv-edu')
GENSHIN_DIR = os.path.join(ROOT, 'data', 'csv')

pytestmark = pytest.mark.skipif(
    not os.path.isdir(EDU_DIR),
    reason='需要 data/csv-edu 样本数据（带 rel_cn 列的关系表）')


@pytest.fixture
def edu(tmp_path):
    """导入了 csv-edu 全部数据的图谱。

    ⚠️ **必须是 function 级**：导入会把 ``ai`` / ``education`` 注册进全局
    ``NODE_TYPES``，而 tests/conftest.py 的 autouse fixture 每个测试进场前
    都会把它恢复成 12 种内置类型（不这样，test_kg_store 会被污染）。
    module 级 fixture 只注册一次，之后每测前都被擦掉。
    """
    store = KGStore(str(tmp_path / 'kg.db'), auto_seed=False)
    store.import_csv(EDU_DIR)
    return store


@pytest.fixture(scope='module')
def app():
    pytest.importorskip('PySide6')
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


# ---------- 数据层：rel_cn 列与 kg_rel_names 表 ----------

def test_every_rel_has_chinese_name(edu):
    """csv-edu 里出现的**每个**关系都必须有中文名。

    这是本次改动的根本动机：324 个关系里原先 293 个查不到中文，
    画布上只能显示 ``contrast_with`` 这种生英文。
    """
    missing = [rel for rel, _c, _d, _w in
               [(r, 0, 0, 0) for r in edu._rel_cn]
               if not edu._rel_cn.get(rel)]
    assert not missing, f'有 {len(missing)} 个关系没中文名：{missing[:10]}'
    # 兜底：静态表覆盖不到的关系也必须有中文（即真正做到了「随数据走」）
    only_in_db = {r: c for r, c in edu._rel_cn.items() if r not in REL_NAMES}
    assert len(only_in_db) > 200, \
        f'库里登记的关系只有 {len(only_in_db)} 个，比预期少很多'
    assert all(c and c != r for r, c in only_in_db.items()), \
        '中文名不应为空、也不应等于英文原文'


def test_rel_cn_column_present_in_source_csv():
    """源CSV 的 rel-*.csv 必须真的带 rel_cn 列（表头优化的落点）。"""
    files = glob.glob(os.path.join(EDU_DIR, 'rel-*.csv'))
    assert files, '找不到 rel-*.csv'
    for path in files:
        with open(path, encoding='utf-8', newline='') as f:
            header = [c.strip() for c in next(csv.reader(f))]
        assert 'rel_cn' in header, f'{os.path.basename(path)} 缺 rel_cn 列'
        assert 'rel' in header and 'node1' in header and 'node2' in header
        # rel_cn 紧挨 rel，读起来才顺
        assert abs(header.index('rel_cn') - header.index('rel')) == 1, \
            f'{os.path.basename(path)} 的 rel_cn 应紧跟在 rel 之后'


def test_rel_cn_survives_reopen(tmp_path):
    """关系中文名必须落盘：关掉连接重开新实例仍在（只查内存会漏提交）。"""
    db = str(tmp_path / 'kg.db')
    store = KGStore(db, auto_seed=False)
    store.import_csv(EDU_DIR)
    before = dict(store._rel_cn)
    store.close()

    reopened = KGStore(db, auto_seed=False)
    assert reopened._rel_cn == before
    assert reopened.rel_cn_of('contrast_with') == '与……对比'


def test_set_rel_cn_does_not_overwrite_by_default(tmp_path):
    """默认不覆盖已有登记：先导入的数据优先，后来的缺列表不能抹掉它。"""
    store = KGStore(str(tmp_path / 'kg.db'), auto_seed=False)
    assert store.set_rel_cn('foo', '甲') is True
    assert store.set_rel_cn('foo', '乙') is False
    assert store.rel_cn_of('foo') == '甲'
    # 显式 overwrite 才改
    assert store.set_rel_cn('foo', '乙', overwrite=True) is True
    assert store.rel_cn_of('foo') == '乙'
    # 空值不登记（否则会把英文原文写成「中文名」）
    assert store.set_rel_cn('bar', '') is False
    assert store.set_rel_cn('', '丙') is False


def test_rel_cn_of_falls_back_to_static_table(tmp_path):
    """库里没登记的关系回退静态表，再回退英文原文。"""
    store = KGStore(str(tmp_path / 'kg.db'), auto_seed=False)
    assert store.rel_cn_of('part_of') == REL_NAMES['part_of']   # 静态表兜底
    assert store.rel_cn_of('完全没见过的关系') == '完全没见过的关系'


def test_csv_data_overrides_static_table(tmp_path):
    """同一关系在静态表与 CSV 里都有中文名时，**以 CSV 为准**。

    静态表只是「数据没给中文名时的兜底」；用户在自己维护的图谱里把
    ``part_of`` 译成别的，不该被代码里的旧译名盖回去。
    （反向保障见 test_genshin_export_has_no_rel_cn_column：原神 CSV 没有
    rel_cn 列，故一个关系都不登记，导出仍是三列。）
    """
    csv_path = tmp_path / 'rel-npc-npc.csv'
    csv_path.write_text(
        'node1,rel,node2,rel_cn\n甲,part_of,乙,自定义译名\n',
        encoding='utf-8')
    store = KGStore(str(tmp_path / 'kg.db'), auto_seed=False)
    store.add_node('npc', '甲')
    store.add_node('npc', '乙')
    store.import_csv(str(csv_path))
    assert store.rel_cn_of('part_of') == '自定义译名'
    # 静态表本身没被改动（它只是不再优先）
    assert rel_cn('part_of') == '属于'


def test_export_writes_rel_cn_and_roundtrips(edu, tmp_path):
    """导出带 rel_cn 列，回灌后中文名与节点/关系数完全一致。"""
    out = str(tmp_path / 'out')
    edu.export_csv(out)

    path = os.path.join(out, 'rel-ai-ai.csv')
    with open(path, encoding='utf-8-sig') as f:
        rows = list(csv.DictReader(f))
    assert rows[0].keys() >= {'node1', 'rel', 'node2', 'weight', 'rel_cn'}
    # ⚠️ 别假设行序：导出按实体名排序，derived_from 不在第一行
    by_rel = {}
    for r in rows:
        by_rel.setdefault(r['rel'], r['rel_cn'])
    assert by_rel['derived_from'] == '衍生自'
    # 不能出现「英文原文被当成中文名写回」的情况
    assert all(r['rel_cn'] != r['rel'] for r in rows if r['rel_cn'])

    clone = KGStore(str(tmp_path / 'clone.db'), auto_seed=False)
    rep = clone.import_csv(out, replace=True)
    assert rep['rel_cn_added'] == len(edu._rel_cn)
    assert clone.rel_cn_of('contrast_with') == '与……对比'
    assert clone.stats()['nodes'] == edu.stats()['nodes']
    assert clone.stats()['edges'] == edu.stats()['edges']


def test_export_keeps_english_name_as_primary_key(tmp_path):
    """回归：英文名恰好等于主键时，导出**不能**把它丢掉。

    这条盯的是真丢过的数据：``country`` 的英文名（Liyue/璃月）就是主键，
    而英文名等于主键时**不存成属性**（避免与主键重复）。若导出时只查
    属性判断「有没有英文名」，就会误判为无、导出时把英文名列省掉——
    回灌后中文名变成主键，同一个国家裂成两个节点（实测 1910→1915）。
    """
    d = tmp_path / 'd'
    d.mkdir()
    (d / 'label-country.csv').write_text(
        'name,name_cn,label,label_cn\nLiyue,璃月,country,国家\n',
        encoding='utf-8')
    store = KGStore(str(tmp_path / 'kg.db'), auto_seed=False)
    store.import_csv(str(d), replace=True)
    # 英文名等于主键 → 属性里没有，但 node_en_name 要能算出来
    key = ('country', 'Liyue')
    assert store.node_en_name(key) == 'Liyue'
    assert EN_NAME_KEY not in store.node_attrs(key)

    out = str(tmp_path / 'out')
    store.export_csv(out)
    with open(os.path.join(out, 'label-country.csv'), encoding='utf-8-sig') as f:
        row = next(csv.DictReader(f))
    assert row['name'] == 'Liyue' and row['name_cn'] == '璃月'

    # 往返后仍是同一个节点，不裂成两个
    clone = KGStore(str(tmp_path / 'clone.db'), auto_seed=False)
    clone.import_csv(out, replace=True)
    assert ('country', 'Liyue') in clone.nodes
    assert ('country', '璃月') not in clone.nodes
    assert clone.stats()['nodes'] == 1


def test_roundtrip_preserves_node_count_both_datasets(tmp_path):
    """两套数据导出再回灌，节点/关系数必须一模一样。"""
    for tag, src in (('genshin', GENSHIN_DIR), ('edu', EDU_DIR)):
        if not os.path.isdir(src):
            pytest.skip(f'缺少 {src}')
        store = KGStore(str(tmp_path / f'{tag}.db'), auto_seed=False)
        store.import_csv(src, replace=True)
        out = str(tmp_path / f'{tag}_out')
        store.export_csv(out)
        clone = KGStore(str(tmp_path / f'{tag}_c.db'), auto_seed=False)
        clone.import_csv(out, replace=True)
        assert clone.stats()['nodes'] == store.stats()['nodes'], tag
        assert clone.stats()['edges'] == store.stats()['edges'], tag


def test_genshin_export_has_no_rel_cn_column(tmp_path):
    """原神图谱的关系全走静态表，导出**不应**多出 rel_cn 列。

    多了这列，下游（Excel 打开、脚本解析）会以为原神图谱也有数据自带的中文名；
    且无登记时写出英文原文当「中文名」，回灌方会把英文当真。
    """
    genshin = os.path.join(ROOT, 'data', 'csv')
    if not os.path.isdir(genshin):
        pytest.skip('需要 data/csv 样本')
    store = KGStore(str(tmp_path / 'g.db'), seed_dir=genshin)
    out = str(tmp_path / 'g_out')
    store.export_csv(out)
    for path in glob.glob(os.path.join(out, 'rel-*.csv')):
        with open(path, encoding='utf-8-sig') as f:
            header = f.readline().strip()
        assert 'rel_cn' not in header, \
            f'{os.path.basename(path)} 不该有 rel_cn 列：{header}'


def test_replace_import_clears_stale_rel_cn(tmp_path):
    """replace 导入要清掉旧的关系中文名，否则残留旧数据。"""
    db = str(tmp_path / 'kg.db')
    store = KGStore(db, auto_seed=False)
    store.set_rel_cn('stale_relation', '旧关系')
    # 造一份只含新关系的 CSV
    d = tmp_path / 'd'
    d.mkdir()
    (d / 'label-npc.csv').write_text('name,label\n甲,npc\n乙,npc\n',
                                     encoding='utf-8')
    (d / 'rel-npc-npc.csv').write_text(
        'node1,rel,node2,rel_cn\n甲,fresh_relation,乙,新关系\n', encoding='utf-8')
    store.import_csv(str(d), replace=True)
    assert store.rel_cn_of('fresh_relation') == '新关系'
    assert 'stale_relation' not in store._rel_cn, 'replace 后不该残留旧关系中文名'


def test_v2_db_gets_rel_names_table(tmp_path):
    """v2 老库（无kg_rel_names 表）打开时应自动建表，而不是查询报错。"""
    import sqlite3

    db = str(tmp_path / 'old.db')
    conn = sqlite3.connect(db)
    conn.executescript(
        'CREATE TABLE kg_nodes (type TEXT NOT NULL, name TEXT NOT NULL,'
        ' attrs TEXT NOT NULL DEFAULT \'{}\', PRIMARY KEY (type, name));'
        'CREATE TABLE kg_edges (id INTEGER PRIMARY KEY AUTOINCREMENT,'
        ' src_type TEXT NOT NULL, src_name TEXT NOT NULL, rel TEXT NOT NULL,'
        ' dst_type TEXT NOT NULL, dst_name TEXT NOT NULL,'
        ' UNIQUE (src_type, src_name, rel, dst_type, dst_name));'
        'CREATE TABLE kg_meta (key TEXT PRIMARY KEY, value TEXT);')
    conn.execute('INSERT INTO kg_nodes VALUES (?,?,?)', ('npc', '老角色', '{}'))
    conn.commit()
    conn.close()

    store = KGStore(db, auto_seed=False)
    cols = {r['name'] for r in store._conn.execute(
        'PRAGMA table_info(kg_rel_names)')}
    assert cols == {'rel', 'cn'}, '老库打开后应建好 kg_rel_names 表'
    # 老库没有关系中文名，回退静态表即可
    assert store.rel_cn_of('part_of') == '属于'


def test_rel_names_merges_static_and_db(tmp_path):
    """自动完成用的关系表 = 静态表 + 库里登记，且库里的优先。"""
    store = KGStore(str(tmp_path / 'kg.db'), auto_seed=False)
    store.set_rel_cn('contrast_with', '与……对比')
    names = store.rel_names()
    assert names['part_of'] == '属于'                 # 静态表也在
    assert names['contrast_with'] == '与……对比'       # 库里的进来了


# ---------- 渲染层：双语标签 ----------

def test_wrap_label_wraps_on_spaces():
    """英文名按词折行，不把单词劈开。"""
    from kg_view import wrap_label

    lines = wrap_label('reinforcement learning from verifiable rewards', 20, 2)
    assert lines == ['reinforcement', 'learning from…']
    assert all(len(line) <= 20 for line in lines)
    # 无空格的超长名才硬切，且不能出现两个省略号
    hard = wrap_label('x' * 50, 20, 2)
    assert all(len(line) <= 20 for line in hard)
    assert not any(line.endswith('……') for line in hard)
    assert hard[-1].endswith('…')
    # 短名原样返回，不加省略号
    assert wrap_label('LLM', 20, 2) == ['LLM']


def test_node_label_shows_full_english_and_chinese(app):
    """节点标签要给出**完整**英文名 + 中文名。

    ⚠️ 这条盯的是旧缺陷：英文名曾被截到 7 字符，
    ``reinforcement learning from verifiable rewards`` 只剩``rein…``。
    """
    from PySide6.QtWidgets import QGraphicsTextItem

    from kg_view import node_label_html

    item = QGraphicsTextItem()
    item.setHtml(node_label_html('reinforcement learning from verifiable rewards',
                                 '可验证奖励强化学习'))
    text = item.toPlainText()
    assert 'reinforcement' in text          # 词首在
    assert '强化学习' in text               # 中文名在
    # 至少能看到名里的多个词，而不是只剩一个残词
    assert text.split()[1] == 'learning'


def test_node_label_escapes_html(app):
    """名字里的 ``<``/``&`` 必须转义，否则 Qt 会当HTML 解析而丢字。"""
    from PySide6.QtWidgets import QGraphicsTextItem

    from kg_view import node_label_html

    item = QGraphicsTextItem()
    item.setHtml(node_label_html('a<b>&c', '中<文&名'))
    assert item.toPlainText() == 'a<b>&c\n中<文&名'


def test_edge_label_has_cn_and_en(app):
    """边标签同时给关系中文名与英文名，默认权重不添噪声。"""
    from PySide6.QtWidgets import QGraphicsTextItem

    from kg_view import edge_label_html

    item = QGraphicsTextItem()
    item.setHtml(edge_label_html('与……对比', 'contrast_with', 8))
    text = item.toPlainText()
    assert '与……对比' in text and 'contrast_with' in text
    assert text.strip().endswith('8')

    # 默认权重不显示数字
    plain = QGraphicsTextItem()
    plain.setHtml(edge_label_html('属于', 'part_of', DEFAULT_WEIGHT))
    assert '1' not in plain.toPlainText()

    # 中英相同不重复显示
    same = QGraphicsTextItem()
    same.setHtml(edge_label_html('自造关系', '自造关系', 5))
    assert same.toPlainText().count('自造关系') == 1


def test_canvas_renders_bilingual_labels(edu, app):
    """端到端：画布上节点标签有中文名、边标签有关系中文名。"""
    from PySide6.QtWidgets import QGraphicsTextItem

    from kg_view import KGCanvas, NodeItem

    canvas = KGCanvas()
    canvas.bind(edu)
    canvas.show_ego(('ai', 'foundation model'))

    node_labels = [i.label.toPlainText() for i in canvas._scene.items()
                   if isinstance(i, NodeItem)]
    cn_labels = [t for t in node_labels if any(
        '一' <= ch <= '鿿' for ch in t)]
    assert cn_labels, '节点标签里应出现中文名'

    edge_labels = [i.toPlainText() for i in canvas._scene.items()
                   if isinstance(i, QGraphicsTextItem) and i.parentItem() is None]
    assert any('衍生自' in t and 'derived_from' in t for t in edge_labels), \
        f'边标签应同时含中英关系名，实际：{edge_labels}'


def test_label_not_duplicated_when_cn_equals_key(app):
    """回归：中文名与主键相同时，标签/提示**不得**重复显示两遍。

    原神实体暂无官方英文名，主键就是中文名（如「阿贝多」），而
    ``node_cn_name`` 会回退返回主键——两者相同却都渲染出来时，
    标签就成了「阿贝多 / 阿贝多」两行重复。
    """
    from kg_view import NodeItem, node_label_html

    from PySide6.QtGui import QTextDocument
    text = QTextDocument()
    text.setHtml(node_label_html('阿贝多', '阿贝多'))
    assert text.toPlainText().strip() == '阿贝多'

    from PySide6.QtWidgets import QGraphicsScene
    scene = QGraphicsScene()
    canvas = _FakeCanvas()
    item = NodeItem(('character', '阿贝多'), 15, canvas, '阿贝多')
    scene.addItem(item)
    assert item.label.toPlainText().strip() == '阿贝多'
    assert item.toolTip().count('阿贝多') == 1


class _FakeCanvas:
    """NodeItem 只需要一个带 nodeSelected/nodeExpanded 信号的画布。"""

    def __init__(self):
        from PySide6.QtCore import Signal
        self.nodeSelected = Signal(object)
        self.nodeExpanded = Signal(object)


def test_dense_ego_labels_do_not_overlap(edu, app):
    """最拥挤的自我中心网（度数最大的实体）标签也不该互相压字。

    半径按最长标签宽度估算弧长，故这里断言「相邻节点的标签框不相交」。
    """
    from kg_view import KGCanvas, NodeItem

    canvas = KGCanvas()
    canvas.bind(edu)
    center = max(edu.nodes, key=lambda k: len(edu.adj.get(k, [])))
    canvas.show_ego(center)

    boxes = []
    for item in canvas._scene.items():
        if isinstance(item, NodeItem) and item.key != center:
            rect = item.label.boundingRect().translated(item.pos())
            boxes.append((item.key[1], rect))
    assert len(boxes) >= 10, '前置：应挑一个度数够大的节点来测'
    overlaps = [(a[0], b[0]) for i, a in enumerate(boxes)
                for b in boxes[i + 1:] if a[1].intersects(b[1])]
    assert not overlaps, f'标签重叠：{overlaps[:5]}'