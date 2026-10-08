"""原神知识图谱存储层：SQLite 持久化 + 内存索引 + CSV 导入导出 + 节点/关系编辑。

数据库（默认 <程序目录>/kg.db，与 assets.db 并列）包含四张表：

- ``kg_nodes(type, name, attrs)``  实体，``attrs`` 为 JSON 字符串，主键 (type, name)；
- ``kg_edges(id, src_type, src_name, rel, dst_type, dst_name, weight)``  有向三元组，
  唯一约束防止重复，同一 (端点, 关系) 的反向重复也只保留一条；
- ``kg_rel_names(rel, cn)``  关系英文名 -> 中文名（**按关系名去重的字典表**）；
- ``kg_meta(key, value)``  播种标记等元信息。

⚠️ 关系中文名单独成表而不是 ``kg_edges`` 加一列：中文名是**关系名**的属性，
而一条关系名在图里往往出现几十次（``drop_from`` 有 2606 条边）。放边上会
把同一个词重复存 2606 遍；放表里则天然唯一，导入导出也只写一次。

首次运行若库为空，自动从 ``data/csv`` 播种（``label-<类型>.csv`` 节点、
``rel-<a>-<b>.csv`` 关系）；此后 CSV 仅作为导入/导出格式，运行时数据以库为准。
播种时沿用历史解析规则：关系两端按名称关联，文件名仅作类型提示
（如 ``rel-country-area.csv`` 中实际方向是 地区→国家），``暂无/无`` 等占位名被过滤。
"""

import colorsys
import csv
import glob
import json
import os
import re
import sqlite3
from collections import defaultdict, Counter

# 类型键 -> (中文名, 节点颜色)
#
# ⚠️ 这是**可增长**的内置类型表，不再是封闭白名单：导入带新类型的图谱
# （如 data/csv-edu 的 ``ai`` / ``education``）会自动注册，见 :func:`register_type`。
# 早期版本把类型写死成 12 项，导致 label-ai.csv 里的实体因类型无法识别
# 而被整表丢弃（实测 0 节点 / 681 条关系全跳过）。
NODE_TYPES = {
    'character': ('人物', '#e74c3c'),
    'weapon':    ('武器', '#8e44ad'),
    'element':   ('神之眼', '#f39c12'),
    'country':   ('国家', '#27ae60'),
    'area':      ('地区', '#16a085'),
    'place':     ('二级地区', '#1abc9c'),
    'material':  ('材料', '#7f8c8d'),
    'instance':  ('副本', '#2c3e50'),
    'npc':       ('NPC', '#3498db'),
    'master':    ('怪物', '#c0392b'),
    'food':      ('料理', '#e67e22'),
    'artifacts': ('圣遗物', '#d4a017'),
}

# 自动注册新类型时轮转取色（HSL 均匀分布的色相角），保证同批导入的类型颜色可区分。
# ⚠️ 这里只存**色相角**，实际颜色由 :func:`_auto_color` 转成 #RRGGBB：
# Qt 的 QColor 不认 CSS 的 hsl() 字符串（isValid() 为 False，会静默变黑）。
_AUTO_HUES = (206, 28, 340, 96, 262, 48, 172, 12, 316, 66, 224, 140)


def _auto_color(index):
    """按序号生成一个明快但不过艳的 #RRGGBB 颜色。

    刻意**不用** CSS ``hsl(...)`` 记法：QColor 解析不了这种字符串，
    ``isValid()`` 返回 False，画布上会渲染成黑点（看着像"类型没颜色"）。
    """
    hue = _AUTO_HUES[index % len(_AUTO_HUES)] / 360.0
    r, g, b = colorsys.hls_to_rgb(hue, 0.48, 0.52)
    return f'#{int(r * 255):02x}{int(g * 255):02x}{int(b * 255):02x}'


# 实体中文名对应的属性键。⚠️ **不能叫 label_cn**——统一表头后CSV 里
# ``label_cn`` 列是**类型**的中文名（``AI领域``），同名会把两个不同语义
# 搅在一起（实测 edu 实体的中文名被写进 label_cn 属性，与类型名撞车）。
# 用 ``name_cn`` 与 CSV 列名对齐，导出时写回该列，往返无损。
CN_NAME_KEY = 'name_cn'

# 英文名对应的属性键：实体表 ``name`` 列（**可为空**——原神实体的官方
# 英文名待补，当前只有 country 有 7 个）。为空就不写该键，详情面板也不会
# 多出一行空的「英文名」。
EN_NAME_KEY = 'name_en'


# 关系英文键 -> 中文名（用户自建关系不在此表中，显示时回退为原文）
REL_NAMES = {
    'part_of': '属于',
    'artifacts_is': '圣遗物',
    'breaking_material_is': '突破材料',
    'come_from': '来自',
    'cultivating_material_is': '培养材料',
    'element_is': '神之眼',
    'special_food': '特殊料理',
    'weapon_is': '武器',
    'ingredient_is': '原料',
    'drop_from': '掉落',
    'locate_in': '位于',
    # --- 教育/AI 领域（data/csv-edu）常见关系 ---
    'derived_from': '衍生自',
    'alternative_to': '可替代为',
    'abbreviation_of': '是……的缩写',
    'variant_of': '变体',
    'instance_of': '实例',
    'component_of': '组成部分',
    'subclass_of': '子类',
    'broader_than': '范围更广',
    'narrower_than': '范围更窄',
    'enables': '使能',
    'supports': '支持',
    'strengthens': '强化',
    'weakens': '削弱',
    'mitigates': '缓解',
    'threatens': '威胁',
    'constrains': '约束',
    'constrains_by': '受限于',
    'determines': '决定',
    'influences': '影响',
    'deepens': '加深',
    'exerts': '施加',
    'underlies': '构成基础',
    'enacts': '践行',
    'reduces': '降低',
    'improves': '改善',
    'negates': '抵消',
    'depends_on': '依赖于',
    'precedes': '先于',
    'succeeds': '后于',
    'successor_of': '后继于',
    'predecessor_of': '先于',
    'contradicts': '矛盾',
    'refines': '细化',
    'extends': '扩展',
    'applies_to': '适用于',
    'measures': '度量',
    'predicts': '预测',
    'explains': '解释',
    'motivates': '激励',
    'regulates': '调节',
    'responds_to': '响应',
    'coexists_with': '共存',
}

# 关系的默认权重：CSV 未给 weight 列时用它。新增关系**不必**登记到此，
# 未登记的用 1.0 即可（面板会原样显示英文关系名）。
DEFAULT_WEIGHT = 1.0

# 权重列可接受的表头别名（csv-edu 用 weight，别的来源可能写 权重/weight值）
_WEIGHT_COLS = ('weight', '权重', '权重值', 'strength', '置信度')

# ⚠️ 关系中文名的列名别名。csv-edu 的 rel-*.csv 原本只有 node1,rel,node2,weight，
# 324 个关系名里有 293 个查不到中文，渲染时只能显示生英文。
# 加一列 ``rel_cn``（或中文别名）后，中文名随数据走，不再依赖代码里的静态字典。
_REL_CN_COLS = ('rel_cn', 'rel-cn', 'relcn', '关系', '关系名', '关系中文名')

# 自动注册新类型时用来起中文名的列：取该列在本表内的**众数**。
# 统一表头后 csv-edu 的 label-ai.csv 用 label_cn（「AI领域」）、
# label-education.csv 亦为「教育领域」，比直接显示类型键 ai / education 可读得多。
# 保留 category / 领域 等旧列名以兼容旧数据。
_TYPE_CN_HINT_COLS = ('label_cn', 'category', '领域', '分类', 'discipline')

# 无意义的占位名称，建图与导入时均过滤
_JUNK_NAMES = {'暂无', '无', '未知', ''}

# 详情展示时跳过的属性列（实体自身字段与长 URL，避免与名称重复或撑爆详情面板）。
# ``name_cn`` / ``label`` / ``label_cn`` 是结构列：中文名与类型中文名分别在
# 标题里单独显示，不该再作为业务属性重复出现。
# ⚠️ 中文名属性 CN_NAME_KEY（``name_cn``）虽被跳过，但导入时会**显式**写回
# ``attrs[CN_NAME_KEY]``，所以跳过只影响「从 CSV 列自动收集」这一步，不会丢名。
_SKIP_ATTRS = {'mhy_id', 'id', 'name', 'label', 'label_cn', 'icon',
               CN_NAME_KEY, EN_NAME_KEY}

# 关系文件名可识别的别名（除 label-*.csv / rel-*.csv 约定外的友好命名）
_NODE_ALIASES = {'nodes.csv', 'node.csv', '实体.csv', '节点.csv'}
_REL_ALIASES = {'relations.csv', 'relation.csv', 'edges.csv', 'edge.csv',
                'rels.csv', 'rel.csv', '关系.csv'}

SCHEMA = """
CREATE TABLE IF NOT EXISTS kg_nodes (
    type  TEXT NOT NULL,
    name  TEXT NOT NULL,
    attrs TEXT NOT NULL DEFAULT '{}',
    PRIMARY KEY (type, name)
);
CREATE TABLE IF NOT EXISTS kg_edges (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    src_type TEXT NOT NULL,
    src_name TEXT NOT NULL,
    rel      TEXT NOT NULL,
    dst_type TEXT NOT NULL,
    dst_name TEXT NOT NULL,
    weight   REAL,
    UNIQUE (src_type, src_name, rel, dst_type, dst_name)
);
CREATE INDEX IF NOT EXISTS idx_kg_edges_src ON kg_edges(src_type, src_name);
CREATE INDEX IF NOT EXISTS idx_kg_edges_dst ON kg_edges(dst_type, dst_name);
CREATE TABLE IF NOT EXISTS kg_rel_names (
    rel TEXT PRIMARY KEY,
    cn  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS kg_type_names (
    type TEXT PRIMARY KEY,
    cn   TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS kg_meta (key TEXT PRIMARY KEY, value TEXT);
"""

SEED_VERSION = '1'

# 库结构版本：表结构有变更时递增，供客户端判断能否安全接收服务器下发的数据
# （C/S 架构预留——服务端与客户端结构版本不匹配时应拒绝导入而非静默出错）
# v2：kg_edges 增 weight 列（带权重边）
# v3：新增 kg_rel_names 表（关系中文名）
SCHEMA_VERSION = '3'


def _key(ntype, name):
    return (ntype, name)


def register_type(ntype, cn=None, color=None):
    """注册一个新的节点类型，返回 (中文名, 颜色)。

    导入外部图谱时，CSV 里出现未知类型（``label-ai.csv`` → ``ai``）会自动
    调用本函数。**幂等**：已存在则原样返回，不覆盖用户/内置的既有配色。
    中文名优先取 ``category`` 之类的展示列，取不到就用类型键本身。
    """
    ntype = (ntype or '').strip()
    if not ntype:
        return None
    existing = NODE_TYPES.get(ntype)
    if existing is not None:
        return existing
    if not color:
        # 按已注册类型数轮转取色，保证同一批导入的类型之间颜色可区分
        color = _auto_color(len(NODE_TYPES))
    entry = ((cn or ntype).strip() or ntype, color)
    NODE_TYPES[ntype] = entry
    return entry


def _clean_name(name):
    """规整实体名：去空白；空值/占位名返回 None。"""
    name = (name or '').strip()
    return None if name in _JUNK_NAMES else name


def _clean_attrs(row, skip=_SKIP_ATTRS):
    """从 CSV 行提取展示属性：跳过内部字段与空值。"""
    return {k: (v or '').strip() for k, v in row.items()
            if k and k not in skip and (v or '').strip()}


def _parse_weight(raw, default=DEFAULT_WEIGHT):
    """把 CSV 里的权重值转成 float；空值/非法值退回默认权重。

    支持 ``8``、``0.85``、``8/10``、``8,5``（逗号小数）等写法——
    外部数据源的这几种写法都出现过，直接 float() 会把后两种变成 8.0 / 85.0。
    """
    if raw is None:
        return default
    text = str(raw).strip().replace('，', ',').replace('：', ':')
    if not text:
        return default
    # "8/10" → 取分子并按分母归一；"1-9" 这类区间不处理（权重不是区间语义）
    if '/' in text:
        head, _, tail = text.partition('/')
        try:
            num, den = float(head), float(tail)
            if den:
                return num / den
        except ValueError:
            return default
    # 千分位逗号（1,000）先去掉；纯逗号小数（8,5）再换成点
    if ',' in text:
        text = text.replace(',', '') if text.count(',') == 1 and len(
            text.split(',')[1]) == 3 else text.replace(',', '.')
    try:
        return float(text)
    except ValueError:
        return default


def rel_cn(rel):
    """关系键 -> 中文名（未登记则返回原文）。

    这是**静态兜底表**（:data:`REL_NAMES`）的查询。库里登记过的中文名优先，
    由 :meth:`KGStore.rel_cn_of` 处理——渲染层应调它而不是本函数。
    """
    return REL_NAMES.get(rel, rel)


def type_cn(ntype):
    """类型键 -> 中文名（未登记则返回原文）。"""
    entry = NODE_TYPES.get(ntype)
    return entry[0] if entry else ntype


def _is_cn_text(text):
    """判断字符串是否含中日文字符。

    用于「实体主键是英文名还是中文名」的判定：统一表头后主键优先取英文名，
    原神实体因暂无官方译名而回退成中文名。判据是**有无汉字**——
    英文名里混中文标点不算中文名。
    """
    return any('一' <= ch <= '鿿' for ch in (text or ''))


def _looks_like_type_key(text):
    """判断一个字符串能否充当实体类型键。

    用于区分 label 列的两种语义：``character`` 是类型键，
    ``大规模基础模型`` 是中文名。判据是**形态**而非白名单——
    外部图谱的类型（``ai``、``education``、``LLM_concept``）不在内置表里，
    但形态上仍是合法标识符。中文名几乎不可能通过这个判据。
    """
    text = (text or '').strip()
    if not text or len(text) > 40:
        return False
    if not re.match(r'^[A-Za-z][A-Za-z0-9_]*$', text):
        return False
    return True




class KGStore:
    """知识图谱存储：SQLite 为准，内存维护节点表与邻接表以加速查询。"""

    def __init__(self, db_path, seed_dir=None, auto_seed=True):
        self.db_path = os.path.abspath(db_path)
        self.seed_dir = seed_dir
        parent = os.path.dirname(self.db_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        # check_same_thread=False 以便在 Qt 信号回调线程中读写；全部操作均为短事务
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA)
        self._conn.commit()
        self._migrate()
        # 记录库结构版本（新建库时写入；已存在的老库不覆盖）
        if self.get_meta('schema_version') is None:
            self.set_meta('schema_version', SCHEMA_VERSION)

        self.nodes = {}                      # (type, name) -> {'type','name','attrs'}
        self._name_index = defaultdict(list)  # name -> [(type, name), ...]
        # 中文名 -> 节点键。⚠️ 主键是英文名，中文名在属性里，故中文查询
        # 必须另建索引，否则 find('大规模基础模型') 一无所获。
        self._cn_index = defaultdict(list)
        self.adj = defaultdict(list)         # (type, name) -> [(rel, (type, name)), ...]
        self._edges = set()                  # 有向三元组 {(k1, rel, k2), ...}
        self._weights = {}                   # (k1, rel, k2) -> float
        self._rel_cn = {}                    # rel英文 -> 中文名
        self._reindex()

        if auto_seed and not self.nodes and seed_dir:
            # 仅当显式给了 seed_dir 才播种（开发/测试/手工重建场景）。
            # v3.5 起安装包携带 kg.db，正常运行不会走到这里。
            if not os.path.isdir(seed_dir):
                raise FileNotFoundError(
                    f'知识图谱初始数据目录不存在：{seed_dir}\n'
                    '该目录是构建输入，不随安装包分发。可用 '
                    'tools/build_databases.py 由 CSV 重建 kg.db，'
                    '或用管理面板「知识图谱 → 导入 CSV」导入。')
            self.import_csv(seed_dir, replace=True, _quiet=True)
        elif auto_seed and not self.nodes and not seed_dir:
            # 库为空且无 CSV 可播种：明确报错，而不是留一个空白图谱页
            raise FileNotFoundError(
                f'知识图谱数据库为空：{self.db_path}\n'
                '本版本的知识图谱随安装包以 kg.db 形式分发，不含 CSV。\n'
                '若库文件缺失，请重新安装，或用管理面板「知识图谱 → 导入 CSV」'
                '从 CSV 导入（CSV 可由 data/csv 或服务器下发获得）。')

    # ---------- 索引 ----------

    def _migrate(self):
        """老库结构迁移：给 v1 的 kg_edges 补 weight 列；给 v2 补 kg_rel_names 表。

        ``CREATE TABLE IF NOT EXISTS`` 对已存在的表**不会**加列，
        所以升级安装（kg.db 由 onlyifdoesntexist 保留）后必须显式 ALTER。
        迁移是加列而非改列，老数据读出来 weight 为 NULL，渲染按默认权重处理。

        ``kg_rel_names`` 是**新表**（不是新列），``executescript`` 里的
        ``CREATE TABLE IF NOT EXISTS`` 已经会建好，无需额外处理；
        老库的关系中文名沿用静态兜底表 :data:`REL_NAMES`。

        🔴 末尾的「补注册库里的类型」必须**无条件**执行，不能只放在补weight
        列的分支里：``NODE_TYPES`` 是**进程级全局**，导入外部图谱时注册的类型
        不随数据库持久化。程序重启后新进程里它又是空的，于是 edu 的
        ``ai`` / ``education`` / ``database`` 全部查不到中文名与配色——
        节点在画布上渲染成**灰点**、详情与图例显示生类型键（实测 kg.db 里
        明明存着这些类型，界面上却认不出）。故每次打开库都按库里的实际
        类型补一遍注册。
        """
        cols = {row['name'] for row in
                self._conn.execute('PRAGMA table_info(kg_edges)')}
        if 'weight' not in cols:
            with self._conn:
                self._conn.execute('ALTER TABLE kg_edges ADD COLUMN weight REAL')
            self.set_meta('schema_version', SCHEMA_VERSION)
        elif self.get_meta('schema_version') != SCHEMA_VERSION:
            # v2→v3 只新增了 kg_rel_names 表（executescript 已建好），
            # 但版本号要跟上——否则「检查更新」会以为库结构还是 v2。
            # 放在 weight 分支之外：v2 库**有** weight 列，只补版本号即可。
            self.set_meta('schema_version', SCHEMA_VERSION)

        # 库里的类型补注册（幂等）：库可能来自旧版导入，或由用户导入外部图谱
        # 而来，这些类型当初是靠 import_csv 的内存副作用注册的，进程退出即丢。
        # 中文名与配色优先取库里的登记（kg_type_names），这样重启后
        # ``ai`` 仍显示「AI领域」而不是生类型键 ``ai``。
        saved_cn = {row['type']: row['cn'] for row in
                    self._conn.execute('SELECT type, cn FROM kg_type_names')
                    if row['type'] and row['cn']}
        for row in self._conn.execute('SELECT DISTINCT type FROM kg_nodes'):
            register_type(row['type'], cn=saved_cn.get(row['type']))

    def _reindex(self):
        """从数据库全量重建内存索引（写入后调用；1900 节点/7500 边耗时毫秒级）。"""
        self.nodes.clear()
        self._name_index.clear()
        self._cn_index.clear()
        self.adj.clear()
        self._edges.clear()
        self._weights.clear()
        self._rel_cn.clear()

        # 库里登记的关系中文名优先于静态兜底表
        for row in self._conn.execute('SELECT rel, cn FROM kg_rel_names'):
            if row['rel'] and row['cn']:
                self._rel_cn[row['rel']] = row['cn']

        for row in self._conn.execute('SELECT type, name, attrs FROM kg_nodes'):
            try:
                attrs = json.loads(row['attrs']) or {}
            except (TypeError, ValueError):
                attrs = {}
            key = _key(row['type'], row['name'])
            self.nodes[key] = {'type': key[0], 'name': key[1], 'attrs': attrs}
            self._name_index[key[1]].append(key)
            cn = attrs.get(CN_NAME_KEY)
            if cn:
                self._cn_index[cn].append(key)

        seen_und = set()   # 同一关系的正反向只建一条邻接，避免可视化出现重复边
        for row in self._conn.execute(
                'SELECT src_type, src_name, rel, dst_type, dst_name, weight'
                ' FROM kg_edges'):
            k1 = _key(row['src_type'], row['src_name'])
            k2 = _key(row['dst_type'], row['dst_name'])
            if k1 == k2 or k1 not in self.nodes or k2 not in self.nodes:
                continue
            rel = row['rel']
            self._edges.add((k1, rel, k2))
            self._weights[(k1, rel, k2)] = (DEFAULT_WEIGHT if row['weight'] is None
                                            else float(row['weight']))
            und = (k1, rel, k2) if k1 <= k2 else (k2, rel, k1)
            if und in seen_und:
                continue
            seen_und.add(und)
            self.adj[k1].append((rel, k2))
            self.adj[k2].append((rel, k1))


    # ---------- 查询 ----------

    def stats(self):
        size_mb = None
        if os.path.isfile(self.db_path):
            size_mb = os.path.getsize(self.db_path) / 1024 / 1024
        # 只统计库里真实存在的类型：NODE_TYPES 是全局可增长的注册表，
        # 别人的库导入过新类型时，直接遍历 NODE_TYPES 会多出一堆 0 项。
        by_type = {}
        for key in self.nodes:
            by_type[key[0]] = by_type.get(key[0], 0) + 1
        return {
            'backend': 'sqlite',
            'db_path': self.db_path,
            'db_size_mb': size_mb,
            'nodes': len(self.nodes),
            'edges': len(self._edges),
            'weighted_edges': sum(1 for w in self._weights.values()
                                  if w != DEFAULT_WEIGHT),
            'by_type': by_type,
        }


    def all_names(self):
        return sorted(self._name_index.keys())

    # ---------- 元信息（供构建工具与后续服务器下发使用） ----------

    def set_meta(self, key, value):
        with self._conn:
            self._conn.execute('INSERT OR REPLACE INTO kg_meta (key, value) VALUES (?, ?)',
                               (key, str(value)))

    def get_meta(self, key, default=None):
        row = self._conn.execute('SELECT value FROM kg_meta WHERE key=?',
                                 (key,)).fetchone()
        return row['value'] if row else default

    def info(self):
        """库的来源与版本信息（面板「重载」与将来「检查更新」用）。"""
        return {'schema_version': SCHEMA_VERSION, 'db_path': self.db_path,
                'built_from': self.get_meta('built_from', 'unknown'),
                'app_version': self.get_meta('app_version', 'unknown'),
                'nodes': len(self.nodes), 'edges': len(self._edges)}

    def find(self, name):
        """精确查找名称对应的节点键列表。

        **中英文都能查到**：主键是英文名，但用户很可能输入中文名
        （如「璃月」找璃月、「大规模基础模型」找 foundation model），
        故中文名另建索引一并查。
        """
        text = (name or '').strip()
        keys = list(self._name_index.get(text, []))
        if keys:
            return keys
        keys = self._cn_index.get(text, [])
        if keys:
            return list(keys)
        return self._find_by_en_name(text)

    def _find_by_en_name(self, text):
        """按英文名精确查找（:attr:`EN_NAME_KEY` 属性）。

        英文名恰好等于主键时不会存成属性，故这里还要扫主键。
        """
        if not text:
            return []
        found = [key for key, node in self.nodes.items()
                 if node['attrs'].get(EN_NAME_KEY) == text]
        if not found:
            found = [key for key in self.nodes
                     if key[1] == text and not _is_cn_text(text)]
        return found

    def resolve(self, name, prefer_types=()):
        """按名称解析唯一节点键；多义名按 prefer_types 消歧；无解返回 None。"""
        candidates = self._name_index.get((name or '').strip(), [])
        if not candidates:
            return None
        if len(candidates) == 1:
            return candidates[0]
        for key in candidates:
            if key[0] in prefer_types:
                return key
        return candidates[0]

    def search(self, text, limit=50):
        """子串模糊搜索，优先前缀匹配，返回 [(type, name), ...]。

        **三个字段都搜**：中文名（主键）、英文名（``name_en``）、
        类型中文名（``label_cn``）。前者保证中文输入能找到实体，
        后两者让「按英文名」「按领域词」也能搜到——否则用户输入
        ``Liyue`` 或 ``AI领域`` 会一无所获。
        """
        text = (text or '').strip()
        if not text:
            return []
        prefix, substr = [], []
        for name in self._name_index:
            for key in self._name_index[name]:
                if name.startswith(text):
                    prefix.append(key)
                elif text in name:
                    substr.append(key)
        if len(prefix) + len(substr) < limit:
            for key in self._search_by_attr(text, (CN_NAME_KEY, EN_NAME_KEY),
                                            limit):
                if key not in prefix and key not in substr:
                    prefix.append(key)
        return (prefix + substr)[:limit]

    def _search_by_attr(self, text, keys, limit):
        """按若干属性键做子串匹配，前缀命中排前面。"""
        found = []
        for attr in keys:
            for key, node in self.nodes.items():
                val = node['attrs'].get(attr) or ''
                if not val:
                    continue
                if val.startswith(text):
                    found.insert(0, key)
                elif text in val:
                    found.append(key)
                if len(found) >= limit:
                    break
        return found

    def neighbors(self, key):
        """节点的全部邻居：[(rel英文, rel中文, 邻居键), ...]，按关系分组排序。"""
        result = [(rel, self.rel_cn_of(rel), other)
                  for rel, other in self.adj.get(key, [])]
        result.sort(key=lambda x: (x[0], x[2][0], x[2][1]))
        return result

    def neighbor_details(self, key):
        """带权重与中文名的邻居列表，渲染层用这个（neighbors 保持原签名不动）。

        返回 [(rel, rel中文, 对端键, 权重, 对端中文名), ...]。
        权重按大到小排，让强关系在放射布局里排在前面、视觉上更靠上。
        """
        result = []
        for rel, other in self.adj.get(key, []):
            triple = self._directed(key, rel, other)
            weight = self._weights.get(triple, DEFAULT_WEIGHT) if triple else DEFAULT_WEIGHT
            cn = self.nodes.get(other, {}).get('attrs', {}).get(CN_NAME_KEY) or ''
            result.append((rel, self.rel_cn_of(rel), other, weight, cn))
        result.sort(key=lambda x: (-x[3], x[0], x[2][0], x[2][1]))
        return result

    def edge_weight(self, key, rel, other_key):
        """方向无关地取关系权重；不存在返回默认权重。"""
        directed = self._directed(key, rel, other_key)
        if directed is None:
            return DEFAULT_WEIGHT
        return self._weights.get(directed, DEFAULT_WEIGHT)


    def edges_of(self, key):
        """节点关联的有向关系：[(rel, 对端键, 'out'|'in')]，按关系与对端排序。"""
        result = []
        for k1, rel, k2 in self._edges:
            if k1 == key:
                result.append((rel, k2, 'out'))
            elif k2 == key:
                result.append((rel, k1, 'in'))
        result.sort(key=lambda x: (x[0], x[1][0], x[1][1]))
        return result

    def edges_of_detailed(self, key):
        """带权重与对端中文名的关系列表，面板关系列表用这个。

        返回 [(rel, 对端键, 方向, 权重, 对端中文名), ...]。
        ``edges_of`` 保持 3 元组不变——它被多处既有逻辑按位置解包。
        """
        result = []
        for rel, other, direction in self.edges_of(key):
            weight = self._weights.get((key, rel, other) if direction == 'out'
                                       else (other, rel, key), DEFAULT_WEIGHT)
            cn = self.nodes.get(other, {}).get('attrs', {}).get(CN_NAME_KEY) or ''
            result.append((rel, other, direction, weight, cn))
        return result

    def node_cn_name(self, key):
        """节点的中文名（无则返回空串）。

        ⚠️ 中文名**恰好等于主键**时不会存成属性（避免与主键重复），
        故这里要回退：主键含汉字即它本身就是中文名。
        否则原神实体（主键是中文名）会一律返回空串。
        """
        node = self.nodes.get(key)
        if node is None:
            return ''
        cn = node['attrs'].get(CN_NAME_KEY)
        if cn:
            return cn
        return key[1] if _is_cn_text(key[1]) else ''

    def node_en_name(self, key):
        """节点的英文名（无则返回空串）。

        ⚠️ 统一表头后**实体主键就是英文名**，故主键非中文时才把它当英文名；
        原神实体主键是中文（暂无译名，回退到 name_cn），返回空串。
        不要只看 :attr:`EN_NAME_KEY` 属性——英文名恰好等于主键时不会
        存成属性（避免与主键重复），那样查属性会误报「没有英文名」。
        """
        node = self.nodes.get(key)
        if node is None:
            return ''
        en = node['attrs'].get(EN_NAME_KEY)
        if en:
            return en
        # 主键是英文名（edu 侧）：含非中日文字符即视为英文名
        name = key[1]
        return '' if _is_cn_text(name) else name

    def node_display(self, key):
        """节点该优先显示的名字：有英文名用英文名，否则用中文名。

        画布节点标签用它——这样 csv-edu（英文名齐全）显示英文，
        原神（暂无英文名）自动退回中文，不会出现空标签。
        """
        return self.node_en_name(key) or self.node_cn_name(key) or key[1]

    # ---------- 关系中文名 ----------

    def rel_cn_of(self, rel):
        """关系的中文名：库里的登记优先，回退静态表，都没有则返回英文原文。

        渲染层（画布边标签、面板关系列表、编辑器提示）统一走这里，
        不要直接用模块级 :func:`rel_cn`——后者看不到库里的登记。
        """
        cn = self._rel_cn.get(rel)
        return cn or rel_cn(rel)

    def set_rel_cn(self, rel, cn, overwrite=False):
        """登记关系中文名，返回 True 表示新建/改写。

        ``overwrite=False``（默认）时已有登记不覆盖：先导入的数据优先，
        避免后来一份缺列的 CSV 把已有中文名抹掉。
        """
        rel = (rel or '').strip()
        cn = (cn or '').strip()
        if not rel or not cn:
            return False
        if not overwrite and rel in self._rel_cn:
            return False
        with self._conn:
            self._conn.execute('INSERT OR REPLACE INTO kg_rel_names (rel, cn)'
                               ' VALUES (?, ?)', (rel, cn))
        self._rel_cn[rel] = cn
        return True

    def rel_names(self):
        """全部关系中文名映射（供编辑器做自动完成）。"""
        merged = dict(REL_NAMES)
        merged.update(self._rel_cn)
        return merged


    def ego_network(self, key, hops=1):
        """自我中心网：返回 (节点键集合, 边列表[(k1, rel, k2)])。"""
        nodes = {key}
        frontier = {key}
        edges = []
        seen_edges = set()
        for _ in range(max(1, hops)):
            nxt = set()
            for k in frontier:
                for rel, other in self.adj.get(k, []):
                    ekey = (k, rel, other) if k <= other else (other, rel, k)
                    if ekey not in seen_edges:
                        seen_edges.add(ekey)
                        edges.append((k, rel, other))
                    if other not in nodes:
                        nxt.add(other)
                    nodes.add(other)
            frontier = nxt
            if not frontier:
                break
        return nodes, edges

    # ---------- 节点编辑 ----------

    def node_attrs(self, key):
        node = self.nodes.get(key)
        return dict(node['attrs']) if node else {}

    def add_node(self, ntype, name, attrs=None, overwrite=True):
        """新增实体。名称重复时 overwrite=True 覆盖属性、False 直接返回 False。

        未知类型**报错**而非自动注册：这是手工/面板路径，类型键打错字
        （如 'character' 误写成 'charater'）应当当场被拦下。
        导入路径另有自动注册（见 :func:`register_type`），两类入口语义不同。
        """
        name = _clean_name(name)
        if not name:
            raise ValueError('实体名称不能为空')
        if ntype not in NODE_TYPES:
            raise ValueError(f'未知实体类型: {ntype}')
        key = _key(ntype, name)
        exists = key in self.nodes
        if exists and not overwrite:
            return False
        payload = json.dumps(attrs or {}, ensure_ascii=False)
        with self._conn:
            self._conn.execute(
                'INSERT OR REPLACE INTO kg_nodes (type, name, attrs) VALUES (?, ?, ?)',
                (ntype, name, payload))
        self._reindex()
        return not exists   # True 表示新建



    def update_node(self, key, name=None, ntype=None, attrs=None):
        """修改实体的名称/类型/属性；改名或改类型会同步迁移其全部关系。返回新键。"""
        if key not in self.nodes:
            raise KeyError(f'实体不存在: {key}')
        new_name = _clean_name(name) if name is not None else key[1]
        if not new_name:
            raise ValueError('实体名称不能为空')
        new_type = ntype if ntype is not None else key[0]
        if new_type not in NODE_TYPES:
            raise ValueError(f'未知实体类型: {new_type}')
        new_key = _key(new_type, new_name)
        if new_key != key and new_key in self.nodes:
            raise ValueError(f'同名实体已存在: {type_cn(new_type)} · {new_name}')

        if attrs is None:
            payload = json.dumps(self.nodes[key]['attrs'], ensure_ascii=False)
        else:
            payload = json.dumps({k: v for k, v in attrs.items() if k and k != 'name'},
                                 ensure_ascii=False)
        with self._conn:
            self._conn.execute('UPDATE kg_nodes SET type=?, name=?, attrs=?'
                               ' WHERE type=? AND name=?',
                               (new_type, new_name, payload, key[0], key[1]))
            if new_key != key:
                self._conn.execute('UPDATE kg_edges SET src_type=?, src_name=?'
                                   ' WHERE src_type=? AND src_name=?',
                                   (new_type, new_name, key[0], key[1]))
                self._conn.execute('UPDATE kg_edges SET dst_type=?, dst_name=?'
                                   ' WHERE dst_type=? AND dst_name=?',
                                   (new_type, new_name, key[0], key[1]))
        self._reindex()
        return new_key

    def delete_node(self, key):
        """删除实体及其全部关系，返回 (删除节点数, 删除关系数)。"""
        if key not in self.nodes:
            return 0, 0
        with self._conn:
            cur = self._conn.execute('DELETE FROM kg_edges'
                                     ' WHERE (src_type=? AND src_name=?)'
                                     '    OR (dst_type=? AND dst_name=?)',
                                     (key[0], key[1], key[0], key[1]))
            removed_edges = cur.rowcount
            cur = self._conn.execute('DELETE FROM kg_nodes WHERE type=? AND name=?',
                                     (key[0], key[1]))
            removed_nodes = cur.rowcount
        self._reindex()
        return removed_nodes, removed_edges

    # ---------- 关系编辑 ----------

    def add_edge(self, src_key, rel, dst_key, overwrite=True, weight=None):
        """新增有向关系，返回 True 表示新建、False 表示已存在。

        ``weight`` 省略时用 :data:`DEFAULT_WEIGHT`（等价于「无权重」）。
        """
        rel = (rel or '').strip()
        if not rel:
            raise ValueError('关系名不能为空')
        if src_key == dst_key:
            raise ValueError('关系的两端不能是同一实体')
        for k in (src_key, dst_key):
            if k not in self.nodes:
                raise KeyError(f'实体不存在: {k}')
        exists = (src_key, rel, dst_key) in self._edges
        if exists and not overwrite:
            return False
        w = DEFAULT_WEIGHT if weight is None else _parse_weight(weight)
        with self._conn:
            self._conn.execute(
                'INSERT OR REPLACE INTO kg_edges'
                ' (src_type, src_name, rel, dst_type, dst_name, weight)'
                ' VALUES (?, ?, ?, ?, ?, ?)',
                (src_key[0], src_key[1], rel, dst_key[0], dst_key[1], w))
        self._reindex()
        return not exists

    def update_edge(self, old, new, weight=None):
        """修改关系：old/new 均为 (源实体键, 关系名, 目标实体键)。

        ``weight`` 省略表示**沿用原权重**——UI 改关系名/对端时不该把权重清掉。
        """
        if tuple(old) not in self._edges:
            raise KeyError(f'关系不存在: {old}')
        src_key, rel, dst_key = new[0], new[1], new[2]
        rel = (rel or '').strip()
        if not rel:
            raise ValueError('关系名不能为空')
        if src_key == dst_key:
            raise ValueError('关系的两端不能是同一实体')
        for k in (src_key, dst_key):
            if k not in self.nodes:
                raise KeyError(f'实体不存在: {k}')
        if (src_key, rel, dst_key) != tuple(old) and (src_key, rel, dst_key) in self._edges:
            raise ValueError('目标关系已存在')
        w = (self._weights.get(tuple(old), DEFAULT_WEIGHT) if weight is None
             else _parse_weight(weight))
        with self._conn:
            self._conn.execute(
                'UPDATE OR REPLACE kg_edges SET src_type=?, src_name=?, rel=?,'
                ' dst_type=?, dst_name=?, weight=?'
                ' WHERE src_type=? AND src_name=? AND rel=? AND dst_type=? AND dst_name=?',
                (src_key[0], src_key[1], rel, dst_key[0], dst_key[1], w,
                 old[0][0], old[0][1], old[1], old[2][0], old[2][1]))
        self._reindex()
        return True

    def update_edge_touching(self, key, rel, other_key, new_rel=None, new_other=None,
                             weight=None):
        """以 key 为锚点修改关系，自动识别实际存储方向。

        可视化按无向遍历展示关系，UI 只知道「某实体 — 关系 — 另一实体」，
        不应要求调用方判断三元组方向。``new_other`` 省略时保持原对端。
        返回修改后的有向三元组。
        """
        directed = self._directed(key, rel, other_key)
        if directed is None:
            raise KeyError(f'关系不存在: {key} - {rel} - {other_key}')
        src, old_rel, dst = directed
        if new_other is None:
            # 只改关系名：两端保持原位置
            new_src, new_dst = src, dst
        elif src == key:
            # 锚点作源端：新对端接在后面
            new_src, new_dst = src, new_other
        else:
            # 锚点作目标端：新对端接在前面
            new_src, new_dst = new_other, dst
        triple = (new_src, (new_rel or old_rel).strip(), new_dst)
        self.update_edge(directed, triple, weight=weight)
        return triple

    def _directed(self, key, rel, other_key):
        """返回 (源, 关系, 目标) 形式的实际存储方向；不存在返回 None。"""
        for k1, r, k2 in self._edges:
            if r == rel and ((k1 == key and k2 == other_key) or (k2 == key and k1 == other_key)):
                return (k1, r, k2)
        return None

    def delete_edge_touching(self, key, rel, other_key):
        """方向无关地删除关系，返回删除行数（0 表示不存在）。"""
        directed = self._directed(key, rel, other_key)
        if directed is None:
            return 0
        return self.delete_edge(*directed)

    def delete_edge(self, src_key, rel, dst_key):
        """删除一条有向关系，返回删除行数（0 表示不存在）。"""
        with self._conn:
            cur = self._conn.execute(
                'DELETE FROM kg_edges WHERE src_type=? AND src_name=? AND rel=?'
                ' AND dst_type=? AND dst_name=?',
                (src_key[0], src_key[1], rel, dst_key[0], dst_key[1]))
        if cur.rowcount:
            self._reindex()
        return cur.rowcount

    # ---------- CSV 导入 ----------

    @staticmethod
    def _read_header(path):
        with open(path, 'r', encoding='utf-8-sig', newline='') as f:
            try:
                return [c.strip() for c in next(csv.reader(f))]
            except StopIteration:
                return []

    @staticmethod
    def _weight_column(fieldnames):
        """找出权重列名；没有则返回 None（表示该表不带权重）。"""
        if not fieldnames:
            return None
        lowered = {c.strip().lower(): c for c in fieldnames if c}
        for cand in _WEIGHT_COLS:
            if cand in lowered:
                return lowered[cand]
        return None

    @staticmethod
    def _rel_cn_column(fieldnames):
        """找出关系中文名列名；没有则返回 None。"""
        if not fieldnames:
            return None
        lowered = {c.strip().lower(): c for c in fieldnames if c}
        for cand in _REL_CN_COLS:
            if cand in lowered:
                return lowered[cand]
        return None

    @classmethod
    def _parse_node_file(cls, path, default_type=None):
        """解析节点 CSV，产出 (type, name, attrs)。

        实体类型的判定顺序为 ``label``（是已知/可注册的类型键时）→
        文件名类型（label-*.csv）→ ``type`` 列。

        三个容易踩的点：

        1. **不能让 ``type`` 列优先**：``label-artifacts.csv`` 自带 type 列
           （圣遗物部位：花/羽/沙/杯/冠），若按它归类会丢掉全部 189 个圣遗物。
        2. **主键取 ``name``（英文名），空时回退 ``name_cn``**：中文名
           **不唯一**——csv-edu 有 11 组同中文名（``RLHF`` 与
           ``reinforcement learning from human feedback`` 共用同一中文名），
           原神也有「凯瑟琳」×4。拿中文名当主键会让同一概念裂成多个实体
           （实测节点 732→1392、关系 1063→784）。英文名则唯一。
           而原神实体的 ``name`` 目前**多为空**（官方译名待补，仅 country
           有 7 个），故必须能回退到中文名，否则整表被丢弃。
        3. **未知类型要自动注册**：``label-ai.csv`` / ``label-education.csv``
           的类型不在内置 12 项里，早期版本因此把整表丢弃。

        **兼容旧表头**：没有 ``name_cn`` 列时（旧数据把中文名放在 ``label`` 列）
        仍按老规则猜——``label`` 像类型键就当类型，否则当中文名。
        """
        rows = []
        # 收集每个类型下 label_cn/category/领域 列的取值分布，用于给新类型起中文名
        pending_types = {}    # ntype -> Counter()
        with open(path, 'r', encoding='utf-8-sig', newline='') as f:
            reader = csv.DictReader(f)
            unified = 'name_cn' in (reader.fieldnames or [])
            for raw in reader:
                label = (raw.get('label') or '').strip()
                ntype, cn_name, en_name = '', '', ''
                if unified:
                    # 新表头：语义明确，无需猜测
                    en_name = (raw.get('name') or '').strip()
                    cn_name = (raw.get('name_cn') or '').strip()
                    ntype = label
                else:
                    # 旧表头：name 就是主键；label 可能是类型键，也可能是中文名
                    en_name = (raw.get('name') or '').strip()
                    if label:
                        if label in NODE_TYPES or _looks_like_type_key(label):
                            ntype = label
                        else:
                            cn_name = label
                for cand in (default_type, raw.get('type')):
                    if ntype:
                        break
                    cand = (cand or '').strip()
                    if cand and (cand in NODE_TYPES or _looks_like_type_key(cand)):
                        ntype = cand
                if not ntype:
                    continue
                # 主键 = 英文名；原神暂无译名时回退中文名（否则整表丢弃）
                key_name = _clean_name(en_name) or _clean_name(cn_name)
                if not key_name:
                    continue
                attrs = _clean_attrs(raw)
                # 中文名/英文名各有独立属性位，导出时写回，往返不丢
                if cn_name and cn_name != key_name:
                    attrs[CN_NAME_KEY] = cn_name
                if en_name and en_name != key_name:
                    attrs[EN_NAME_KEY] = en_name
                rows.append((ntype, key_name, attrs))
                if ntype not in NODE_TYPES:
                    bucket = pending_types.setdefault(ntype, Counter())
                    for col in _TYPE_CN_HINT_COLS:
                        val = (raw.get(col) or '').strip()
                        if val and not _looks_like_type_key(val):
                            bucket[val] += 1
                            break
        # 类型注册放在循环外：需要整表统计后才能取到众数（如 AI领域 / 教育领域）
        type_cn_map = {}
        for ntype, counter in pending_types.items():
            top = counter.most_common(1)
            cn = top[0][0] if top else None
            register_type(ntype, cn=cn)
            if cn:
                type_cn_map[ntype] = cn
        return rows, type_cn_map

    @classmethod
    def _parse_rel_file(cls, path, hint_types=()):
        """解析关系 CSV，产出 (端点1, 关系, 端点2, 类型提示集合, 权重)，
        并返回该表出现过的 ``{关系名: 中文名}``（无 rel_cn 列时为空 dict）。

        ``weight`` 可选：无该列时用 :data:`DEFAULT_WEIGHT`；列存在但单元格
        为空/非数字时同样退回默认值（宁可标成默认权重，也不要把关系丢掉）。

        ⚠️ 关系中文名是**按关系名去重**的：同一个 ``derived_from`` 可能在表里
        出现 20 次，中文名只登记一次（见 :meth:`set_rel_cn`），既省空间也避免
        同一关系因不同行填了不同中文名而产生分歧。
        """
        rows = []
        hints = tuple(t for t in hint_types
                      if t in NODE_TYPES or _looks_like_type_key(t))
        cn_map = {}
        with open(path, 'r', encoding='utf-8-sig', newline='') as f:
            reader = csv.DictReader(f)
            wcol = cls._weight_column(reader.fieldnames)
            ccol = cls._rel_cn_column(reader.fieldnames)
            for raw in reader:
                n1 = _clean_name(raw.get('node1'))
                rel = (raw.get('rel') or '').strip()
                n2 = _clean_name(raw.get('node2'))
                if not n1 or not rel or not n2:
                    continue
                weight = _parse_weight(raw.get(wcol)) if wcol else DEFAULT_WEIGHT
                rows.append((n1, rel, n2, hints, weight))
                cn = (raw.get(ccol) or '').strip() if ccol else ''
                if cn and rel not in cn_map:
                    cn_map[rel] = cn
        return rows, cn_map

    def import_csv(self, path, replace=False, _quiet=False):
        """从 CSV 文件或目录导入图谱，返回导入报告。

        支持三种形态：
        1. 目录：``label-<类型>.csv`` + ``rel-<a>-<b>.csv``（项目原始布局，可整目录回灌）；
        2. 单个关系表：表头含 ``node1,rel,node2``（或 relations.csv 等别名）；
        3. 单个实体表：表头含 ``name`` 且含 ``label``/``type``（或 nodes.csv 等别名）。

        ``replace=True`` 先清空库再导入；否则与现有数据合并（同名实体覆盖属性）。
        """
        if os.path.isdir(path):
            files = sorted(glob.glob(os.path.join(path, '*.csv')))
            if not files:
                raise FileNotFoundError(f'目录中没有 CSV 文件: {path}')
        elif os.path.isfile(path):
            files = [path]
        else:
            raise FileNotFoundError(f'导入路径不存在: {path}')

        # 导入前快照类型表，事后取差集即本次自动新增的类型（面板据此提示）
        known_types = set(NODE_TYPES)
        node_rows, rel_rows, ignored = [], [], []
        rel_cn_map = {}       # 本次导入发现的关系中文名 {rel: cn}
        type_cn_map = {}      # 本次导入发现的类型中文名 {type: cn}
        for f in files:
            base = os.path.basename(f).lower()
            if base.startswith('label-') and base.endswith('.csv'):
                ntype = base[len('label-'):-len('.csv')]
                # 文件名类型合法才作为类型（label-ai-notes.csv 之类的备注表不该建实体）。
                # 注册交给 _parse_node_file：它要统计整表才能给新类型起中文名。
                if _looks_like_type_key(ntype):
                    rows, cn_map = self._parse_node_file(f, ntype)
                    node_rows.extend(rows)
                    for t, cn in cn_map.items():
                        type_cn_map.setdefault(t, cn)
                else:
                    ignored.append(os.path.basename(f))
                continue
            if base.startswith('rel-') and base.endswith('.csv'):
                hints = [h for h in base[len('rel-'):-len('.csv')].split('-')
                         if _looks_like_type_key(h)]
                rows, cn_map = self._parse_rel_file(f, hints)
                rel_rows.extend(rows)
                for rel, cn in cn_map.items():
                    rel_cn_map.setdefault(rel, cn)
                continue
            cols = {c.lower() for c in self._read_header(f)}
            if {'node1', 'rel', 'node2'} <= cols or base in _REL_ALIASES:
                rows, cn_map = self._parse_rel_file(f)
                rel_rows.extend(rows)
                for rel, cn in cn_map.items():
                    rel_cn_map.setdefault(rel, cn)
            elif 'name' in cols and (cols & {'label', 'type'}) or base in _NODE_ALIASES:
                rows, cn_map = self._parse_node_file(f)
                node_rows.extend(rows)
                for t, cn in cn_map.items():
                    type_cn_map.setdefault(t, cn)
            else:
                ignored.append(os.path.basename(f))

        if not node_rows and not rel_rows:
            raise ValueError('未找到可导入的实体表或关系表'
                             '（需要 label-*.csv / rel-*.csv，或含 name+type、node1+rel+node2 表头的 CSV）')

        report = {'mode': 'replace' if replace else 'merge', 'files': len(files),
                  'ignored_files': ignored,
                  'nodes_added': 0, 'nodes_updated': 0,
                  'edges_added': 0, 'edges_skipped': 0, 'stubs': 0,
                  'edges_weighted': 0, 'new_types': [],
                  'rel_cn_added': 0}
        # 事务内自建名称索引：新插入的实体必须立即能被后续关系解析到。
        # ⚠️ **同时索引中文名**：实体主键是英文名，而 ``rel-*.csv`` 引用的是
        # 中文名（``璃月``、``可莉``），故中文名也必须进索引才能解析到端点。
        # 否则所有关系都会因端点找不到而变成桩（实测关系数 1063→784）。
        name_index = defaultdict(list)
        cn_index = defaultdict(list)
        with self._conn:
            if replace:
                self._conn.execute('DELETE FROM kg_edges')
                self._conn.execute('DELETE FROM kg_nodes')
                # 关系中文名同属图谱数据：replace 语义是「清空后重建」，
                # 留着旧登记会让本次没带 rel_cn 的表仍显示陈旧中文名
                self._conn.execute('DELETE FROM kg_rel_names')
                self._rel_cn.clear()
                # 类型中文名同属图谱数据：replace 语义是「清空后重建」
                self._conn.execute('DELETE FROM kg_type_names')
            else:
                for key in self.nodes:
                    name_index[key[1]].append(key)
                    cn = self.nodes[key]['attrs'].get(CN_NAME_KEY)
                    if cn:
                        cn_index[cn].append(key)

            for ntype, name, attrs in node_rows:
                key = _key(ntype, name)
                # replace 模式下库已被清空，一律计为新增；合并时按是否已存在区分
                if replace or key not in self.nodes:
                    report['nodes_added'] += 1
                else:
                    report['nodes_updated'] += 1
                self._conn.execute(
                    'INSERT OR REPLACE INTO kg_nodes (type, name, attrs) VALUES (?, ?, ?)',
                    (ntype, name, json.dumps(attrs, ensure_ascii=False)))
                if key not in name_index[name]:
                    name_index[name].append(key)
                cn = attrs.get(CN_NAME_KEY)
                if cn and key not in cn_index[cn]:
                    cn_index[cn].append(key)

            # 关系中文名与节点/关系同在一个事务里落库：
            # 中途失败不会留下「有边没中文名」的半成品。
            # ⚠️ **数据优先于代码**：CSV 里给了中文名就登记，哪怕静态表里也有。
            # 静态表是「无数据时的兜底」，而 CSV 是用户实际维护的那份真相——
            # 用户在自己的图谱里把 part_of 译成别的，不该被代码里的旧译名盖回去。
            # （原神图谱的 CSV 没有 rel_cn 列，故一个关系都不会登记，
            #  导出仍是三列，这个约定不受影响。）
            for rel, cn in rel_cn_map.items():
                if rel in self._rel_cn:
                    continue      # 先导入的表优先，不被后来的覆盖
                self._conn.execute(
                    'INSERT OR REPLACE INTO kg_rel_names (rel, cn) VALUES (?, ?)',
                    (rel, cn))
                self._rel_cn[rel] = cn
                report['rel_cn_added'] += 1

            # 类型中文名同样落库：否则重启后新进程的NODE_TYPES 是空的，
            # 补注册只能拿到生类型键，画布上edu 节点变灰点、图例显示「ai」。
            for ntype, cn in type_cn_map.items():
                self._conn.execute(
                    'INSERT OR REPLACE INTO kg_type_names (type, cn) VALUES (?, ?)',
                    (ntype, cn))

            for n1, rel, n2, hints, weight in rel_rows:
                k1 = self._import_endpoint(n1, hints, name_index, report,
                                          cn_index=cn_index)
                # 同一行两端不取同类型桩：rel-character-element.csv 的两个未知实体
                # 应分别落为 人物/元素，而不是都被建成人物
                used = {k1[0]} if k1 else set()
                k2 = self._import_endpoint(n2, hints, name_index, report,
                                           avoid=used, cn_index=cn_index)
                if k1 is None or k2 is None or k1 == k2:
                    report['edges_skipped'] += 1
                    continue
                cur = self._conn.execute(
                    'INSERT OR IGNORE INTO kg_edges'
                    ' (src_type, src_name, rel, dst_type, dst_name, weight)'
                    ' VALUES (?, ?, ?, ?, ?, ?)',
                    (k1[0], k1[1], rel, k2[0], k2[1], weight))
                if cur.rowcount:
                    report['edges_added'] += 1
                    if weight != DEFAULT_WEIGHT:
                        report['edges_weighted'] += 1
                else:
                    report['edges_skipped'] += 1
            self._conn.execute('INSERT OR REPLACE INTO kg_meta (key, value) VALUES (?, ?)',
                               ('seed_version', SEED_VERSION))
        self._reindex()
        # 本次导入新出现的类型（面板据此提示「已自动新增 N 种实体类型」）
        report['new_types'] = [(t, NODE_TYPES[t][0])
                               for t in sorted(set(NODE_TYPES) - known_types)]
        return report

    def _import_endpoint(self, name, hint_types, name_index, report, avoid=(),
                         cn_index=None):
        """解析导入关系的端点：命中已有实体则复用，否则按类型提示建桩实体。

        ``avoid`` 是同一行已占用的类型（来自另一端），用于避免两端建成同类桩。

        ⚠️ **按中文名也能命中**：实体主键是英文名，而 ``rel-*.csv`` 引用的是
        中文名（``璃月``、``可莉``），故先查英文名索引、再查中文名索引。
        缺了后者，所有关系端点都解析不到、全部退化成桩（实测关系 1063→784）。
        """
        candidates = list(name_index.get(name, []))
        if not candidates and cn_index:
            candidates = list(cn_index.get(name, []))
        if len(candidates) == 1:
            return candidates[0]
        if candidates:
            for key in candidates:      # 多义名按文件名类型提示消歧
                if key[0] in hint_types:
                    return key
            return candidates[0]
        # 实体表中不存在（多为爬虫未收录的实体）：按提示建桩
        for ntype in hint_types:
            if ntype in avoid:
                continue
            if ntype not in NODE_TYPES:
                # 关系文件名里的类型同样可能是新类型（rel-ai-education.csv）
                if not _looks_like_type_key(ntype):
                    continue
                register_type(ntype)
            self._conn.execute(
                'INSERT OR IGNORE INTO kg_nodes (type, name, attrs) VALUES (?, ?, ?)',
                (ntype, name, '{}'))
            key = _key(ntype, name)
            name_index[name].append(key)
            report['stubs'] += 1
            return key
        return None

    def seed_from_csv(self, data_dir):
        """从项目 CSV 目录重新播种（清空后导入），返回导入报告。"""
        return self.import_csv(data_dir, replace=True, _quiet=True)

    # ---------- CSV 导出 ----------

    @staticmethod
    def _fmt_weight(value):
        """权重写回 CSV 的格式：整数不带小数点，其余保留两位。

        csv-edu 用的是 1~10 的整数评分，写成 ``8.0`` 虽能被自己读回来，
        但人再打开看就多了一层无意义的噪声。
        """
        if value == DEFAULT_WEIGHT:
            return ''
        return str(int(value)) if float(value).is_integer() else f'{value:.2f}'

    def export_csv(self, out_dir, only_types=None):
        """导出为项目原始 CSV 布局：``label-<类型>.csv`` + ``rel-<a>-<b>.csv``。

        - 关系按真实方向写入文件名（如 地区→国家 导出为 ``rel-area-country.csv``）；
        - 实体表用**统一表头** ``name_cn``(中文) / ``label``(类型键)，
          有英文名时额外写 ``name`` 列；与 data/csv、data/csv-edu 的
          布局一致，导出目录可直接整目录回灌；
        - **带权重的关系表会多写一列 weight**（全部是默认权重时不写，保持与
          旧版导出逐字节一致，不给下游 diff 制造噪声）；
        - **库里有登记的关系表会多写一列 rel_cn**（同样按需出现），
          使关系中文名随数据往返，而不是只能来自代码里的静态字典；
        - 实体表 label 列写中文名（若有）而非类型键——这正是 csv-edu 的形态，
          写类型键会丢掉全部中文名；无中文名时仍写类型键，兼容原神数据。
        - 动态注册的类型（``ai`` / ``education`` 等）与内置类型一视同仁导出。

        导出目录可直接被 :meth:`import_csv` 整目录回灌，往返无损。
        """
        os.makedirs(out_dir, exist_ok=True)
        # 只导出库里真实存在的类型：NODE_TYPES 是全局注册表，可能含别的库
        # 注册过的类型，照单全收会产出一堆空表。
        present = {key[0] for key in self.nodes}
        types = [t for t in NODE_TYPES
                 if t in present and (not only_types or t in only_types)]
        node_files, node_rows, edge_files, edge_rows = 0, 0, 0, 0
        weighted_files, weighted_rows = 0, 0

        for ntype in types:
            rows = [n for n in self.nodes.values() if n['type'] == ntype]
            if not rows:
                continue
            # 属性列取该类型全部实体的并集，顺序按首次出现，保持导出稳定。
            # 名称类属性（中文名/英文名）不作为独立列——它们已归位到
            # name_cn / name 两列，与实体表统一表头一致。
            columns = []
            for n in rows:
                for k in n['attrs']:
                    if k not in (CN_NAME_KEY, EN_NAME_KEY) and k not in columns:
                        columns.append(k)
            path = os.path.join(out_dir, f'label-{ntype}.csv')
            # 与实体表统一表头：name_cn(中文) / label(类型键)，有英文名时
            # 额外写name 列。⚠️ 判「有没有英文名」必须用 :meth:`node_en_name`
            # 而不是只看 EN_NAME_KEY 属性——英文名恰好等于主键时（country
            # 的Liyue/璃月）不会存成属性，只看属性会误判为「无英文名」，
            # 导出时把英文名丢了，回灌就退化成中文名主键、同一国家裂成两个节点。
            has_en = any(self.node_en_name(_key(ntype, n['name']))
                         for n in rows)
            header = ['name_cn', 'label']
            if has_en:
                header.insert(0, 'name')
            with open(path, 'w', encoding='utf-8-sig', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(header + columns)
                for n in sorted(rows, key=lambda x: x['name']):
                    key = _key(ntype, n['name'])
                    cn = self.node_cn_name(key) or n['name']
                    row = [cn, n['type']]
                    if has_en:
                        row.insert(0, self.node_en_name(key))
                    writer.writerow(row + [n['attrs'].get(c, '')
                                           for c in columns])
            node_files += 1
            node_rows += len(rows)

        groups = defaultdict(list)
        for k1, rel, k2 in sorted(self._edges, key=lambda e: (e[0], e[1], e[2])):
            groups[(k1[0], k2[0])].append((k1[1], rel, k2[1],
                                           self._weights.get((k1, rel, k2),
                                                             DEFAULT_WEIGHT)))
        for (st, dt), triples in sorted(groups.items()):
            path = os.path.join(out_dir, f'rel-{st}-{dt}.csv')
            # 只有该表内存在非默认权重时才加 weight 列
            has_weight = any(w != DEFAULT_WEIGHT for _, _, _, w in triples)
            # 同理，关系中文名只在**库里真的登记过**时才写。
            # ⚠️ 不能对所有关系都写中文名：无登记时写出英文原文当「中文名」，
            # 会让回灌方以为那串英文就是中文，反而污染数据。
            # 也因此，原神图谱（全部关系走静态 REL_NAMES）导出仍是三列。
            # ⚠️ triples 的元素顺序是 (名1, 关系, 名2, 权重)——关系在**下标 1**，
            # 取错位置会拿节点名去查字典（恒查不到，导出就少一列）。
            cn_of = {rel for _n1, rel, _n2, _w in triples if rel in self._rel_cn}
            with open(path, 'w', encoding='utf-8-sig', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(['node1', 'rel', 'node2']
                                + (['weight'] if has_weight else [])
                                + (['rel_cn'] if cn_of else []))
                for n1, rel, n2, w in triples:
                    row = [n1, rel, n2]
                    if has_weight:
                        row.append(self._fmt_weight(w))
                    if cn_of:
                        row.append(self._rel_cn.get(rel, ''))
                    writer.writerow(row)
            edge_files += 1
            edge_rows += len(triples)
            if has_weight:
                weighted_files += 1
                weighted_rows += sum(1 for _, _, _, w in triples
                                     if w != DEFAULT_WEIGHT)

        return {'dir': out_dir, 'node_files': node_files, 'node_rows': node_rows,
                'edge_files': edge_files, 'edge_rows': edge_rows,
                'weighted_files': weighted_files, 'weighted_rows': weighted_rows}

    # ---------- 生命周期 ----------

    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None


_default = None


def get_default_store(base_dir=None, seed_dir=None, reset=False):
    """懒加载默认图谱（<base_dir>/kg.db），供面板共用一份数据。

    v3.5 起**运行时不再读 CSV**：kg.db 随安装包分发，CSV 只是构建输入
    （见 tools/build_databases.py）。``seed_dir`` 仅供开发/测试显式指定时使用；
    库为空且未给 seed_dir 时抛错，提示用构建工具或导入功能补数据。
    """
    global _default
    if _default is not None and not reset:
        return _default
    if base_dir is None:
        base_dir = os.path.dirname(os.path.abspath(__file__))
    _default = KGStore(os.path.join(base_dir, 'kg.db'), seed_dir=seed_dir)
    return _default


def reset_default_store():
    """丢弃默认图谱单例（测试与「重载」用）。"""
    global _default
    if _default is not None:
        _default.close()
    _default = None
