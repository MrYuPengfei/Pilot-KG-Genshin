"""原神知识图谱存储层：SQLite 持久化 + 内存索引 + CSV 导入导出 + 节点/关系编辑。

数据库（默认 <程序目录>/kg.db，与 assets.db 并列）包含三张表：

- ``kg_nodes(type, name, attrs)``  实体，``attrs`` 为 JSON 字符串，主键 (type, name)；
- ``kg_edges(id, src_type, src_name, rel, dst_type, dst_name)``  有向三元组，
  唯一约束防止重复，同一 (端点, 关系) 的反向重复也只保留一条；
- ``kg_meta(key, value)``  播种标记等元信息。

首次运行若库为空，自动从 ``data/csv`` 播种（``label-<类型>.csv`` 节点、
``rel-<a>-<b>.csv`` 关系）；此后 CSV 仅作为导入/导出格式，运行时数据以库为准。
播种时沿用历史解析规则：关系两端按名称关联，文件名仅作类型提示
（如 ``rel-country-area.csv`` 中实际方向是 地区→国家），``暂无/无`` 等占位名被过滤。
"""

import csv
import glob
import json
import os
import sqlite3
from collections import defaultdict

# 类型键 -> (中文名, 节点颜色)
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
}

# 无意义的占位名称，建图与导入时均过滤
_JUNK_NAMES = {'暂无', '无', '未知', ''}

# 详情展示时跳过的属性列（实体自身字段与长 URL，避免与名称重复或撑爆详情面板）
_SKIP_ATTRS = {'mhy_id', 'id', 'name', 'label', 'icon'}

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
    UNIQUE (src_type, src_name, rel, dst_type, dst_name)
);
CREATE INDEX IF NOT EXISTS idx_kg_edges_src ON kg_edges(src_type, src_name);
CREATE INDEX IF NOT EXISTS idx_kg_edges_dst ON kg_edges(dst_type, dst_name);
CREATE TABLE IF NOT EXISTS kg_meta (key TEXT PRIMARY KEY, value TEXT);
"""

SEED_VERSION = '1'

# 库结构版本：表结构有变更时递增，供客户端判断能否安全接收服务器下发的数据
# （C/S 架构预留——服务端与客户端结构版本不匹配时应拒绝导入而非静默出错）
SCHEMA_VERSION = '1'


def _key(ntype, name):
    return (ntype, name)


def _clean_name(name):
    """规整实体名：去空白；空值/占位名返回 None。"""
    name = (name or '').strip()
    return None if name in _JUNK_NAMES else name


def _clean_attrs(row, skip=_SKIP_ATTRS):
    """从 CSV 行提取展示属性：跳过内部字段与空值。"""
    return {k: (v or '').strip() for k, v in row.items()
            if k and k not in skip and (v or '').strip()}


def rel_cn(rel):
    """关系键 -> 中文名（未登记则返回原文）。"""
    return REL_NAMES.get(rel, rel)


def type_cn(ntype):
    """类型键 -> 中文名（未登记则返回原文）。"""
    entry = NODE_TYPES.get(ntype)
    return entry[0] if entry else ntype


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
        # 记录库结构版本（新建库时写入；已存在的老库不覆盖）
        if self.get_meta('schema_version') is None:
            self.set_meta('schema_version', SCHEMA_VERSION)

        self.nodes = {}                      # (type, name) -> {'type','name','attrs'}
        self._name_index = defaultdict(list)  # name -> [(type, name), ...]
        self.adj = defaultdict(list)         # (type, name) -> [(rel, (type, name)), ...]
        self._edges = set()                  # 有向三元组 {(k1, rel, k2), ...}
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

    def _reindex(self):
        """从数据库全量重建内存索引（写入后调用；1900 节点/7500 边耗时毫秒级）。"""
        self.nodes.clear()
        self._name_index.clear()
        self.adj.clear()
        self._edges.clear()

        for row in self._conn.execute('SELECT type, name, attrs FROM kg_nodes'):
            try:
                attrs = json.loads(row['attrs']) or {}
            except (TypeError, ValueError):
                attrs = {}
            key = _key(row['type'], row['name'])
            self.nodes[key] = {'type': key[0], 'name': key[1], 'attrs': attrs}
            self._name_index[key[1]].append(key)

        seen_und = set()   # 同一关系的正反向只建一条邻接，避免可视化出现重复边
        for row in self._conn.execute(
                'SELECT src_type, src_name, rel, dst_type, dst_name FROM kg_edges'):
            k1 = _key(row['src_type'], row['src_name'])
            k2 = _key(row['dst_type'], row['dst_name'])
            if k1 == k2 or k1 not in self.nodes or k2 not in self.nodes:
                continue
            rel = row['rel']
            self._edges.add((k1, rel, k2))
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
        return {
            'backend': 'sqlite',
            'db_path': self.db_path,
            'db_size_mb': size_mb,
            'nodes': len(self.nodes),
            'edges': len(self._edges),
            'by_type': {t: sum(1 for k in self.nodes if k[0] == t)
                        for t in NODE_TYPES},
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
        """精确查找名称对应的节点键列表。"""
        return list(self._name_index.get((name or '').strip(), []))

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
        """子串模糊搜索，优先前缀匹配，返回 [(type, name), ...]。"""
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
        return (prefix + substr)[:limit]

    def neighbors(self, key):
        """节点的全部邻居：[(rel英文, rel中文, 邻居键), ...]，按关系分组排序。"""
        result = [(rel, rel_cn(rel), other) for rel, other in self.adj.get(key, [])]
        result.sort(key=lambda x: (x[0], x[2][0], x[2][1]))
        return result

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
        """新增实体。名称重复时 overwrite=True 覆盖属性、False 直接返回 False。"""
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

    def add_edge(self, src_key, rel, dst_key, overwrite=True):
        """新增有向关系，返回 True 表示新建、False 表示已存在。"""
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
        with self._conn:
            self._conn.execute(
                'INSERT OR REPLACE INTO kg_edges'
                ' (src_type, src_name, rel, dst_type, dst_name) VALUES (?, ?, ?, ?, ?)',
                (src_key[0], src_key[1], rel, dst_key[0], dst_key[1]))
        self._reindex()
        return not exists

    def update_edge(self, old, new):
        """修改关系：old/new 均为 (源实体键, 关系名, 目标实体键)。"""
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
        with self._conn:
            self._conn.execute(
                'UPDATE OR REPLACE kg_edges SET src_type=?, src_name=?, rel=?,'
                ' dst_type=?, dst_name=?'
                ' WHERE src_type=? AND src_name=? AND rel=? AND dst_type=? AND dst_name=?',
                (src_key[0], src_key[1], rel, dst_key[0], dst_key[1],
                 old[0][0], old[0][1], old[1], old[2][0], old[2][1]))
        self._reindex()
        return True

    def update_edge_touching(self, key, rel, other_key, new_rel=None, new_other=None):
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
        self.update_edge(directed, triple)
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
    def _parse_node_file(path, default_type=None):
        """解析节点 CSV，产出 (type, name, attrs)。

        实体类型列的优先级为 ``label`` → 文件名类型（label-*.csv）→ ``type``。
        不能让 ``type`` 优先：``label-artifacts.csv`` 自带 type 列（圣遗物部位：
        花/羽/沙/杯/冠），若按它归类会丢掉全部 189 个圣遗物实体。
        """
        rows = []
        with open(path, 'r', encoding='utf-8-sig', newline='') as f:
            for raw in csv.DictReader(f):
                name = _clean_name(raw.get('name'))
                if not name:
                    continue
                ntype = ''
                for cand in (raw.get('label'), default_type, raw.get('type')):
                    cand = (cand or '').strip()
                    if cand in NODE_TYPES:
                        ntype = cand
                        break
                if not ntype:
                    continue
                rows.append((ntype, name, _clean_attrs(raw)))
        return rows

    @staticmethod
    def _parse_rel_file(path, hint_types=()):
        """解析关系 CSV，产出 (端点1, 关系, 端点2, 类型提示集合)。"""
        rows = []
        hints = tuple(t for t in hint_types if t in NODE_TYPES)
        with open(path, 'r', encoding='utf-8-sig', newline='') as f:
            for raw in csv.DictReader(f):
                n1 = _clean_name(raw.get('node1'))
                rel = (raw.get('rel') or '').strip()
                n2 = _clean_name(raw.get('node2'))
                if not n1 or not rel or not n2:
                    continue
                rows.append((n1, rel, n2, hints))
        return rows

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

        node_rows, rel_rows, ignored = [], [], []
        for f in files:
            base = os.path.basename(f).lower()
            if base.startswith('label-') and base.endswith('.csv'):
                ntype = base[len('label-'):-len('.csv')]
                node_rows.extend(self._parse_node_file(f, ntype))
                continue
            if base.startswith('rel-') and base.endswith('.csv'):
                hints = base[len('rel-'):-len('.csv')].split('-')
                rel_rows.extend(self._parse_rel_file(f, hints))
                continue
            cols = {c.lower() for c in self._read_header(f)}
            if {'node1', 'rel', 'node2'} <= cols or base in _REL_ALIASES:
                rel_rows.extend(self._parse_rel_file(f))
            elif 'name' in cols and (cols & {'label', 'type'}) or base in _NODE_ALIASES:
                node_rows.extend(self._parse_node_file(f))
            else:
                ignored.append(os.path.basename(f))

        if not node_rows and not rel_rows:
            raise ValueError('未找到可导入的实体表或关系表'
                             '（需要 label-*.csv / rel-*.csv，或含 name+type、node1+rel+node2 表头的 CSV）')

        report = {'mode': 'replace' if replace else 'merge', 'files': len(files),
                  'ignored_files': ignored,
                  'nodes_added': 0, 'nodes_updated': 0,
                  'edges_added': 0, 'edges_skipped': 0, 'stubs': 0}
        # 事务内自建名称索引：新插入的实体必须立即能被后续关系解析到
        name_index = defaultdict(list)
        with self._conn:
            if replace:
                self._conn.execute('DELETE FROM kg_edges')
                self._conn.execute('DELETE FROM kg_nodes')
            else:
                for key in self.nodes:
                    name_index[key[1]].append(key)

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

            for n1, rel, n2, hints in rel_rows:
                k1 = self._import_endpoint(n1, hints, name_index, report)
                # 同一行两端不取同类型桩：rel-character-element.csv 的两个未知实体
                # 应分别落为 人物/元素，而不是都被建成人物
                used = {k1[0]} if k1 else set()
                k2 = self._import_endpoint(n2, hints, name_index, report,
                                           avoid=used)
                if k1 is None or k2 is None or k1 == k2:
                    report['edges_skipped'] += 1
                    continue
                cur = self._conn.execute(
                    'INSERT OR IGNORE INTO kg_edges'
                    ' (src_type, src_name, rel, dst_type, dst_name) VALUES (?, ?, ?, ?, ?)',
                    (k1[0], k1[1], rel, k2[0], k2[1]))
                if cur.rowcount:
                    report['edges_added'] += 1
                else:
                    report['edges_skipped'] += 1
            self._conn.execute('INSERT OR REPLACE INTO kg_meta (key, value) VALUES (?, ?)',
                               ('seed_version', SEED_VERSION))
        self._reindex()
        return report

    def _import_endpoint(self, name, hint_types, name_index, report, avoid=()):
        """解析导入关系的端点：命中已有实体则复用，否则按类型提示建桩实体。

        ``avoid`` 是同一行已占用的类型（来自另一端），用于避免两端建成同类桩。
        """
        candidates = name_index.get(name, [])
        if len(candidates) == 1:
            return candidates[0]
        if candidates:
            for key in candidates:      # 多义名按文件名类型提示消歧
                if key[0] in hint_types:
                    return key
            return candidates[0]
        # 实体表中不存在（多为爬虫未收录的实体）：按提示建桩
        for ntype in hint_types:
            if ntype in NODE_TYPES and ntype not in avoid:
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

    def export_csv(self, out_dir, only_types=None):
        """导出为项目原始 CSV 布局：``label-<类型>.csv`` + ``rel-<a>-<b>.csv``。

        关系按真实方向写入文件名（如 地区→国家 导出为 ``rel-area-country.csv``），
        导出目录可直接被 :meth:`import_csv` 整目录回灌。返回导出报告。
        """
        os.makedirs(out_dir, exist_ok=True)
        types = [t for t in NODE_TYPES if not only_types or t in only_types]
        node_files, node_rows, edge_files, edge_rows = 0, 0, 0, 0

        for ntype in types:
            rows = [n for n in self.nodes.values() if n['type'] == ntype]
            if not rows:
                continue
            # 属性列取该类型全部实体的并集，顺序按首次出现，保持导出稳定
            columns = []
            for n in rows:
                for k in n['attrs']:
                    if k not in columns:
                        columns.append(k)
            path = os.path.join(out_dir, f'label-{ntype}.csv')
            with open(path, 'w', encoding='utf-8-sig', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(['name', 'label'] + columns)
                for n in sorted(rows, key=lambda x: x['name']):
                    writer.writerow([n['name'], ntype]
                                    + [n['attrs'].get(c, '') for c in columns])
            node_files += 1
            node_rows += len(rows)

        groups = defaultdict(list)
        for k1, rel, k2 in sorted(self._edges, key=lambda e: (e[0], e[1], e[2])):
            groups[(k1[0], k2[0])].append((k1[1], rel, k2[1]))
        for (st, dt), triples in sorted(groups.items()):
            path = os.path.join(out_dir, f'rel-{st}-{dt}.csv')
            with open(path, 'w', encoding='utf-8-sig', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(['node1', 'rel', 'node2'])
                writer.writerows(triples)
            edge_files += 1
            edge_rows += len(triples)

        return {'dir': out_dir, 'node_files': node_files, 'node_rows': node_rows,
                'edge_files': edge_files, 'edge_rows': edge_rows}

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
