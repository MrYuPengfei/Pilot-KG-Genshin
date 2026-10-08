"""知识图谱「带权重的边」与「新类型节点」导入导出测试（v3.9）。

覆盖的三个能力（原先完全缺失，实测 csv-edu 导入结果是 0 节点 / 681 关系全跳过）：

1. **带权重的边**：rel-*.csv 的 ``weight`` 列要能读进 kg_edges 并原样导出；
2. **新类型节点**：``label-ai.csv`` 这类未登记类型的表要能导入（自动注册），
   且 ``label`` 列的中文名不能被误当成类型键、也不能在往返中丢掉；
3. **往返无损**：导出目录整目录回灌后，节点/关系/权重/中文名全部一致。

数据来自仓库内真实 data/csv-edu，一律导入到临时 kg.db（原库只读）。
"""

import csv
import glob
import os

import pytest

from kg_store import (KGStore, DEFAULT_WEIGHT, CN_NAME_KEY, EN_NAME_KEY,
                      register_type, rel_cn, type_cn)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EDU_DIR = os.path.join(ROOT, 'data', 'csv-edu')
GENSHIN_DIR = os.path.join(ROOT, 'data', 'csv')

pytestmark = pytest.mark.skipif(
    not os.path.isdir(EDU_DIR),
    reason='需要 data/csv-edu 样本数据（带权重的边 + 新类型节点）')


@pytest.fixture
def edu(tmp_path):
    """导入了 csv-edu 全部数据的图谱。

    ⚠️ **必须是 function 级**：导入外部图谱会往模块级全局 ``NODE_TYPES``
    注册 ``ai`` / ``education`` 等类型，而 tests/conftest.py 的 autouse
    fixture 会在**每个测试进场前**把该全局恢复成 12 种内置类型（否则
    test_kg_store 的 ``node_files == len(NODE_TYPES)`` 会被污染成 21 而失败，
    且只在全量跑时暴露）。若本fixture 是 module 级，就只在第一个测试前
    注册一次，之后每个测试进场前都被擦掉，本文件里断言
    ``'ai' in NODE_TYPES`` 的用例反而会挂。故改成每次重建。
    """
    store = KGStore(str(tmp_path / 'kg.db'), auto_seed=False)
    store.import_csv(EDU_DIR)
    return store


def csv_entity_count():
    """label-*.csv 的实体行数（**现算**，不写死数字）。

    ⚠️ 这些断言原先硬编码 532 / 681，csv-edu 数据一扩充就全红，
    而失败信息只说「532 != 732」，看不出是数据变了还是功能坏了。
    改成从 CSV 现算：数据更新后测试自动跟着走，仍能守住
    「导入的实体数等于 CSV 里的实体数」这个真正的契约。
    """
    total = 0
    for path in glob.glob(os.path.join(EDU_DIR, 'label-*.csv')):
        with open(path, encoding='utf-8-sig', newline='') as f:
            total += sum(1 for row in csv.DictReader(f)
                         if (row.get('name') or '').strip())
    return total


def csv_rel_count():
    """rel-*.csv 的关系行数（同样现算）。"""
    total = 0
    for path in glob.glob(os.path.join(EDU_DIR, 'rel-*.csv')):
        with open(path, encoding='utf-8-sig', newline='') as f:
            total += sum(1 for row in csv.DictReader(f)
                         if (row.get('rel') or '').strip())
    return total


def csv_count_by_type():
    """各类型的实体数 {类型: 个数}，从 label-*.csv 现算。"""
    counts = {}
    for path in glob.glob(os.path.join(EDU_DIR, 'label-*.csv')):
        ntype = os.path.basename(path)[len('label-'):-len('.csv')]
        with open(path, encoding='utf-8-sig', newline='') as f:
            counts[ntype] = sum(1 for row in csv.DictReader(f)
                                if (row.get('name') or '').strip())
    return counts


def csv_weighted_rel_files():
    """源目录里带 weight 列的关系表数量。

    ⚠️ **不能**用它断言导出报告的 ``weighted_files``：导出按「库里的真实
    方向」重新分组（``rel-<源类型>-<目标类型>.csv``），方向组合数与源文件数
    本来就不相等（实测源目录 6 个表 → 导出 14 个）。两者不是同一个量。
    """
    n = 0
    for path in glob.glob(os.path.join(EDU_DIR, 'rel-*.csv')):
        with open(path, encoding='utf-8-sig', newline='') as f:
            fields = [c.strip().lower() for c in next(csv.reader(f))]
        if any(c in fields for c in ('weight', '权重', '权重值', 'strength', '置信度')):
            n += 1
    return n


# ---------- 导入：新类型 + 带权重的边 ----------

def test_edu_nodes_imported(edu):
    """前置：csv-edu 的实体必须真的进库。

    这是本次修复的核心回归——早期版本把类型表写成封闭的 12 项，
    ``label-ai.csv`` / ``label-education.csv`` 的类型（ai / education）无法识别，
    整表被丢弃，进而 681 条关系全部因端点不存在而跳过。
    """
    stats = edu.stats()
    assert stats['nodes'] == csv_entity_count()
    assert stats['edges'] == csv_rel_count()
    # 每种类型的实体数合计应等于实体总数。
    # ⚠️ 不能逐类型断言「by_type[X] == label-X.csv 行数」：关系表里出现、
    # 但实体表没收录的端点会**自动补桩**（如 ArangoDB / JanusGraph 等
    # 图数据库名各补 1 个），于是 database 的 187 行会变成 181+6 个桩。
    # 桩是既有设计（见 _import_endpoint），不是丢数据，故只断言总数守恒。
    assert sum(stats['by_type'].values()) == stats['nodes']
    # CSV 里声明的类型必须都在（不能被静默丢弃）
    assert set(csv_count_by_type()) <= set(stats['by_type'])


def test_new_types_registered(edu):
    """未登记的类型应自动注册，且从 category 列取到可读的中文名。"""
    from kg_store import NODE_TYPES
    assert 'ai' in NODE_TYPES and 'education' in NODE_TYPES
    # csv-edu 的 category 众数分别是「AI领域」「教育领域」，
    # 比直接显示 ai / education 可读（画布图例与关系列表都显示这个）
    assert type_cn('ai') == 'AI领域'
    assert type_cn('education') == '教育领域'
    # 注册是幂等的：重复注册不覆盖既有配色
    before = NODE_TYPES['ai']
    assert register_type('ai') == before


def test_name_cn_column_kept(edu):
    """统一表头后``name_cn`` 是中文名、``name`` 是主键（英文名）。

    早期版本里csv-edu 的 ``label`` 列装的是中文名，且要靠
    「像不像类型键」来猜——统一表头后语义明确，不再需要猜。
    """
    key = ('ai', 'foundation model')
    assert key in edu.nodes
    assert edu.node_cn_name(key) == '大规模基础模型'
    assert edu.node_en_name(key) == 'foundation model'
    # 类型中文名（原category/label_cn 列）不得污染成实体属性：它是类型级信息
    assert edu.node_attrs(key).get('label_cn') is None


def test_search_finds_by_chinese_name(edu):
    """实体名是英文时，按中文名也要能搜到。"""
    keys = edu.search('大语言模型')
    assert ('ai', 'large language model') in keys
    assert ('ai', 'LLM') in keys


def test_edu_edges_have_weights(edu):
    """关系表里的 weight 列必须读进来（而不是被当成普通属性丢掉）。"""
    stats = edu.stats()
    assert stats['edges'] == csv_rel_count()
    assert stats['weighted_edges'] == stats['edges']   # 全部带权重
    # 方向无关地取权重：UI 只知道「A — 关系 — B」
    assert edu.edge_weight(('ai', 'instruction tuning'), 'derived_from',
                           ('ai', 'foundation model')) == 8.0
    assert edu.edge_weight(('ai', 'foundation model'), 'derived_from',
                           ('ai', 'instruction tuning')) == 8.0
    # 关系名有中文映射，渲染时不再是生英文
    assert rel_cn('derived_from') == '衍生自'


def test_weight_persists_across_instances(tmp_path):
    """权重必须落盘：关掉连接重开新实例仍在（只查内存会漏提交）。"""
    db = str(tmp_path / 'kg.db')
    store = KGStore(db, auto_seed=False)
    store.import_csv(EDU_DIR)
    store.close()

    reopened = KGStore(db, auto_seed=False)
    assert reopened.stats()['weighted_edges'] == csv_rel_count()
    assert reopened.edge_weight(('ai', 'RLHF'), 'part_of',
                                ('ai', 'post-training')) == 9.0


def test_weight_parsing_variants(tmp_path):
    """权重列的各种写法都要能解析：整数/小数/分式/空/非法。"""
    from kg_store import _parse_weight

    assert _parse_weight('8') == 8.0
    assert _parse_weight(' 0.85 ') == 0.85
    assert _parse_weight('8/10') == 0.8          # 分式按比例归一
    assert _parse_weight('8,5') == 8.5           # 逗号当小数点
    assert _parse_weight('1,000') == 1000.0      # 千分位
    assert _parse_weight('') == DEFAULT_WEIGHT   # 空 → 默认
    assert _parse_weight(None) == DEFAULT_WEIGHT
    assert _parse_weight('强') == DEFAULT_WEIGHT  # 非法 → 默认而非抛异常


def test_weight_column_alias(tmp_path):
    """权重列的中文别名（权重）也要认。

    端点先建成实体：同类型关系表（rel-npc-npc）里两端不会互相补桩，
    这是「同一行两端不取同类型桩」的既有规则，故这里不依赖自动补建。
    """
    store = KGStore(str(tmp_path / 'kg.db'), auto_seed=False)
    for name in ('甲', '乙', '丙', '丁'):
        store.add_node('npc', name)
    csv_path = tmp_path / 'rel-npc-npc.csv'
    csv_path.write_text(
        'node1,rel,node2,权重\n甲,knows,乙,7\n丙,knows,丁,\n', encoding='utf-8')
    rep = store.import_csv(str(csv_path))
    assert rep['edges_added'] == 2
    assert rep['edges_weighted'] == 1
    # 空权重用默认值，不丢关系
    assert store.edge_weight(('npc', '甲'), 'knows', ('npc', '乙')) == 7.0
    assert store.edge_weight(('npc', '丙'), 'knows', ('npc', '丁')) == DEFAULT_WEIGHT


# ---------- 导出 + 往返 ----------

def test_edu_export_roundtrip_lossless(edu, tmp_path):
    """导出后整目录回灌：节点/关系/权重/中文名全部一致。"""
    out = str(tmp_path / 'edu_out')
    report = edu.export_csv(out)
    assert report['node_rows'] == csv_entity_count()
    assert report['edge_rows'] == csv_rel_count()
    # csv-edu 的关系全部带权重，故导出的每个 rel 表都该有 weight 列，
    # 且带权重的行数 = 关系总数（分组后的文件数与源文件数无关，见上面的说明）
    assert report['weighted_rows'] == csv_rel_count()
    exported_rel = glob.glob(os.path.join(out, 'rel-*.csv'))
    assert report['weighted_files'] == len(exported_rel)
    for path in exported_rel:
        with open(path, encoding='utf-8-sig') as f:
            header = f.readline()
        assert 'weight' in header, f'{os.path.basename(path)} 缺 weight 列'

    clone = KGStore(str(tmp_path / 'clone.db'), auto_seed=False)
    rep = clone.import_csv(out, replace=True)
    assert rep['nodes_added'] == csv_entity_count()
    assert rep['edges_added'] == csv_rel_count()
    assert rep['edges_skipped'] == 0
    assert clone.stats()['nodes'] == edu.stats()['nodes']
    assert clone.stats()['edges'] == edu.stats()['edges']
    # 权重与中文名都在往返中保住
    assert clone.edge_weight(('ai', 'instruction tuning'), 'derived_from',
                             ('ai', 'foundation model')) == 8.0
    assert clone.node_cn_name(('ai', 'foundation model')) == '大规模基础模型'
    # 边标签里的权重也要能整体对上
    assert {(r, o[1], w) for r, o, _d, w, _c in
            clone.edges_of_detailed(('ai', 'instruction tuning'))} >= {
        ('part_of', 'post-training', 9.0),
        ('derived_from', 'foundation model', 8.0)}


def test_export_writes_weight_column(edu, tmp_path):
    """带权重的关系表要有 weight 列，且整数权重不带小数尾巴。"""
    out = str(tmp_path / 'edu_out2')
    edu.export_csv(out)
    path = os.path.join(out, 'rel-ai-ai.csv')
    with open(path, encoding='utf-8-sig') as f:
        rows = list(csv.DictReader(f))
    assert rows[0].keys() >= {'node1', 'rel', 'node2', 'weight'}
    weights = {r['weight'] for r in rows}
    assert all(w == '' or '.' not in w for w in weights), \
        f'整数权重不应写成小数：{sorted(weights)[:5]}'


def test_export_writes_unified_columns(edu, tmp_path):
    """导出用统一表头：name(英文) / name_cn(中文) / label(类型键)。"""
    out = str(tmp_path / 'edu_out3')
    edu.export_csv(out)
    with open(os.path.join(out, 'label-ai.csv'), encoding='utf-8-sig') as f:
        rows = {r['name_cn']: r for r in csv.DictReader(f)}
    row = rows['大规模基础模型']
    assert row['name'] == 'foundation model'   # 英文名
    assert row['label'] == 'ai'                # 类型键，不再装中文名
    # 中文名只出现在 name_cn 一列，不该再有第二个「中文名列」
    # （CN_NAME_KEY 即'name_cn'，与 CSV 列名对齐）
    assert CN_NAME_KEY == 'name_cn'
    assert EN_NAME_KEY not in row


def test_genshin_export_unchanged(tmp_path):
    """无权重图谱的导出格式必须与旧版一致：不写 weight 列，label 写类型键。

    少了这个约束，给 csv-edu 加权重会把所有下游消费方（Excel 打开、脚本解析）
    的表头都改掉。
    """
    store = KGStore(str(tmp_path / 'g.db'), seed_dir=GENSHIN_DIR)
    out = str(tmp_path / 'g_out')
    report = store.export_csv(out)
    assert report['weighted_files'] == 0
    assert report['weighted_rows'] == 0
    with open(os.path.join(out, 'rel-character-element.csv'), encoding='utf-8-sig') as f:
        header = f.readline().strip()
    assert header == 'node1,rel,node2'
    with open(os.path.join(out, 'label-character.csv'), encoding='utf-8-sig') as f:
        rows = list(csv.DictReader(f))
    # ⚠️ 别假设行序：导出按实体名排序
    assert all(r['label'] == 'character' for r in rows)
    assert all(r['name_cn'] for r in rows), '中文名应在name_cn 列'
    assert {'name_cn', 'label'} <= set(rows[0])


# ---------- 渲染：权重与中文名 ----------

def test_edge_pen_and_label_scale_with_weight():
    """边的粗细与标签随权重变化；默认权重不显示权重文字。"""
    pytest.importorskip('PySide6')
    from kg_view import edge_pen, weight_text, weight_ratio

    assert weight_text(DEFAULT_WEIGHT) == ''
    assert weight_text(8.0) == ' 8'
    assert weight_text(0.85) == ' 0.85'
    # 权重越大越粗
    assert edge_pen(9).widthF() > edge_pen(3).widthF() > edge_pen(DEFAULT_WEIGHT).widthF()
    # 越界不产生负宽度/爆表
    assert edge_pen(0).widthF() > 0
    assert edge_pen(9999).widthF() <= 10
    assert 0.0 <= weight_ratio(0) <= weight_ratio(10) <= 1.0


def test_canvas_renders_weighted_ego(edu):
    """端到端：带权重的自我中心网能画出来，边标签带权重。"""
    pytest.importorskip('PySide6')
    import os as _os
    _os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from PySide6.QtWidgets import QApplication, QGraphicsTextItem
    from kg_view import KGCanvas, NodeItem

    QApplication.instance() or QApplication([])
    canvas = KGCanvas()
    canvas.bind(edu)
    center = ('ai', 'instruction tuning')
    canvas.show_ego(center)
    assert canvas.center_key == center
    assert len([i for i in canvas._scene.items() if isinstance(i, NodeItem)]) >= 3
    # 边标签里出现权重数字
    labels = [i.toPlainText() for i in canvas._scene.items()
              if isinstance(i, QGraphicsTextItem)]
    assert any(lbl.strip().endswith('8') for lbl in labels), labels[:8]


def test_neighbor_details_sorted_by_weight(edu):
    """邻居按权重降序：强关系排在前面，渲染时视觉上更靠上。"""
    details = edu.neighbor_details(('ai', 'instruction tuning'))
    weights = [d[3] for d in details]
    assert weights == sorted(weights, reverse=True)
    assert len(details) == len(edu.neighbors(('ai', 'instruction tuning')))


def test_new_type_nodes_render_with_color(edu):
    """新类型实体在画布上应有专属颜色，而不是退化成灰点或黑点。

    ⚠️ 这条曾经抓到一个真 bug：自动配色曾用 CSS 的 ``hsl(...)`` 记法，
    而 **QColor 解析不了这种字符串**（``isValid()`` 为 False），
    于是所有新类型节点都渲染成黑色。故这里必须断言颜色**有效**。
    """
    pytest.importorskip('PySide6')
    import os as _os
    _os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QColor
    from kg_view import NodeItem, KGCanvas

    QApplication.instance() or QApplication([])
    canvas = KGCanvas()
    canvas.bind(edu)
    canvas.show_ego(('ai', 'instruction tuning'))
    item = next(i for i in canvas._scene.items()
                if isinstance(i, NodeItem) and i.key[0] == 'ai')
    color = item.brush().color()
    assert color.isValid(), f'新类型节点颜色无效（会渲染成黑点）：{color.name()}'
    # 灰色兜底是 #95a5a6，黑色是 #000000，两者都说明配色没生效
    assert color != QColor('#95a5a6')
    assert color != QColor('#000000')


def test_all_auto_colors_are_qt_parseable():
    """自动生成的颜色必须是 QColor 认得的 #RRGGBB，不能是 CSS hsl() 记法。"""
    pytest.importorskip('PySide6')
    from PySide6.QtGui import QColor

    from kg_store import _AUTO_HUES, _auto_color

    seen = set()
    for i in range(len(_AUTO_HUES)):
        c = QColor(_auto_color(i))
        assert c.isValid(), f'第 {i} 个自动颜色无效：{_auto_color(i)}'
        seen.add(c.name())
    # 轮转一圈后颜色应互不相同（相邻类型不能撞色）
    assert len(seen) == len(_AUTO_HUES)


# ---------- 老库迁移 ----------

def test_v1_db_gets_weight_column(tmp_path):
    """v1 老库（无 weight 列）打开时应自动 ALTER 补列，而不是查询报错。

    安装升级会保留用户的 kg.db（onlyifdoesntexist），所以老库必然存在。
    """
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
    conn.execute('INSERT INTO kg_edges (src_type,src_name,rel,dst_type,dst_name)'
                 ' VALUES (?,?,?,?,?)', ('npc', '老角色', 'knows', 'npc', '老朋友'))
    conn.commit()
    conn.close()

    store = KGStore(db, auto_seed=False)     # 迁移在 __init__ 里发生
    assert ('npc', '老角色') in store.nodes
    # 老数据没有权重，按默认处理且不报错
    assert store.edge_weight(('npc', '老角色'), 'knows', ('npc', '老朋友')) \
        == DEFAULT_WEIGHT
    cols = {r['name'] for r in store._conn.execute('PRAGMA table_info(kg_edges)')}
    assert 'weight' in cols


# ---------- 编辑路径：权重可改、且不被误清 ----------

def test_update_edge_preserves_weight_when_not_given(tmp_path):
    """改关系名/对端时若不传权重，应沿用原权重（UI 改个名不该把权重清掉）。"""
    store = KGStore(str(tmp_path / 'kg.db'), auto_seed=False)
    store.add_node('npc', '甲')
    store.add_node('npc', '乙')
    store.add_node('npc', '丙')
    store.add_edge(('npc', '甲'), 'knows', ('npc', '乙'), weight=8)

    store.update_edge_touching(('npc', '甲'), 'knows', ('npc', '乙'),
                               new_rel='了解')
    assert store.edge_weight(('npc', '甲'), '了解', ('npc', '乙')) == 8.0

    # 显式传权重才覆盖
    store.update_edge_touching(('npc', '甲'), '了解', ('npc', '乙'), weight=3)
    assert store.edge_weight(('npc', '甲'), '了解', ('npc', '乙')) == 3.0


def test_add_edge_with_weight(tmp_path):
    store = KGStore(str(tmp_path / 'kg.db'), auto_seed=False)
    store.add_node('npc', '甲')
    store.add_node('npc', '乙')
    assert store.add_edge(('npc', '甲'), 'r', ('npc', '乙'), weight='7/10') is True
    assert store.edge_weight(('npc', '甲'), 'r', ('npc', '乙')) == 0.7


# ---------- 常量表卫生 ----------

def test_no_duplicate_keys_in_literal_tables():
    """NODE_TYPES / REL_NAMES 等字面量字典**不得有重复键**。

    重复键在 Python 里是合法语法（后者静默覆盖前者），不报错也不报警告，
    只会让先写的那条映射悄悄失效。给「衍生自」补关系名时就踩过一次：
    ``part_of`` 在改动前后各出现一次，diff 看着像新增、实际是原地重复。
    用 AST 判定（而非字符串计数，注释与文档里也会出现这些词）。
    """
    import ast
    import collections
    import inspect

    import kg_editor
    import kg_store
    import kg_view

    for mod in (kg_store, kg_view, kg_editor):
        tree = ast.parse(inspect.getsource(mod))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Dict):
                continue
            keys = [k.value for k in node.keys
                    if isinstance(k, ast.Constant) and isinstance(k.value, str)]
            dupes = [k for k, c in collections.Counter(keys).items() if c > 1]
            assert not dupes, f'{mod.__name__} 第 {node.lineno} 行字面量有重复键: {dupes}'
