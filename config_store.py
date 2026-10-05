"""配置存储层：SQLite 持久化，替代直接读写 config.yaml。

背景：v3.3 及之前配置是 <程序目录>/config.yaml，由程序与素材导入逻辑直接读写。
YAML 文件在多人协作下是合并冲突高发文件（运行时会改写它），且无法像 assets.db /
kg.db 那样统一管理。v3.4 起改为：

- 运行时配置存放在**项目根目录**的 ``config.db``（SQLite），表 ``kv(key, value)``
  存放标量项、``frame_scale`` 表存放人物帧率/缩放；与 ``assets.db``、``kg.db``
  三个库并列在根目录，并随安装包分发（出厂值即包内那份）；

**v3.5：YAML 彻底退出运行时。** ``data/config.yaml`` 不再被程序读取，它只剩两个用途：
① 构建输入——由 ``tools/build_databases.py`` 生成出厂 config.db；② 用户手动导入的
交换格式（面板「导入配置」，也是后续服务器下发的载荷格式）。库为空时直接用内置
默认值播种，再由 :meth:`ConfigStore.ensure_roles` 按 assets.db 补齐人物登记。

对上层只暴露 :meth:`ConfigStore.load`（返回普通 dict，调用方可照旧修改）
与 :meth:`ConfigStore.save`（整体落库），语义与旧的 yaml 读写一致。
"""

import json
import os
import sqlite3

# 内置默认配置：种子文件缺失时的兜底，保证程序总能启动
DEFAULTS = {
    'audio': True,
    'bg_music': False,
    'img_path': 'png',
    'music_path': 'music',
    'role': '七七',
    'frame_scale': {'七七': [60, 1.0]},
}

# 标量型配置项（存 kv 表）；不在此列的键会被忽略，防止脏数据混入
SCALAR_KEYS = ('audio', 'bg_music', 'img_path', 'music_path', 'role')

# 库结构版本：表结构有变更时递增，供客户端判断能否安全接收服务器下发的配置
# （C/S 架构预留——结构版本不匹配时应拒绝导入而非静默出错）
SCHEMA_VERSION = '1'

SCHEMA = """
CREATE TABLE IF NOT EXISTS kv (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS frame_scale (
    role     TEXT PRIMARY KEY,
    interval INTEGER NOT NULL,
    scale    REAL    NOT NULL
);
CREATE TABLE IF NOT EXISTS config_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def _as_bool(value):
    """把配置里的布尔值统一成 bool（YAML 给出的是 True/False，JSON/文本可能是 "true"）。"""
    if isinstance(value, str):
        return value.strip().lower() in ('1', 'true', 'yes', 'on')
    return bool(value)


class ConfigStore:
    """配置读写：v3.5 起**运行时只读 SQLite**，YAML 不再参与。

    库文件放在**项目根目录**（与 assets.db、kg.db 并列）。config.db 随安装包分发
    一份出厂配置；用户改动后即为本机状态，升级安装时由 setup.iss 的
    ``onlyifdoesntexist`` 保护，不会被新版本覆盖。

    ``data/config.yaml`` 仅在两种场合出现：① 构建输入（tools/build_databases.py
    生成出厂 config.db）；② 用户手动导入的交换格式。运行时不再自动读它。

    ``seed_path`` 显式传入时才用作播种来源（构建脚本与测试用）。
    """

    #: 出厂配置：内置默认值 + 人物登记由调用方按 assets.db 补齐（见 ensure_roles）
    DEFAULTS = DEFAULTS

    def __init__(self, base_dir, db_name='config.db', seed_path=None,
                 auto_seed=True):
        self.base_dir = base_dir
        self.db_path = os.path.join(base_dir, db_name)
        # 仅当显式传入 seed_path 时才读 YAML；否则库空则用内置默认值
        self.yaml_path = seed_path
        os.makedirs(base_dir, exist_ok=True)
        # check_same_thread=False：面板与主线程交替读写，均为短事务
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA)
        self._conn.commit()
        if self.get_meta('schema_version') is None:
            self.set_meta('schema_version', SCHEMA_VERSION)
        if auto_seed and self._is_empty():
            self._seed_from_yaml()

    # ---------- 内部 ----------

    def _is_empty(self):
        row = self._conn.execute('SELECT COUNT(*) FROM kv').fetchone()
        return not row or row[0] == 0

    def _seed_from_yaml(self):
        """播种：优先用显式指定的 YAML 种子，否则用内置默认值。

        运行时（未传 seed_path）走的是「内置默认值 + 调用方 ensure_roles 按
        assets.db 补齐人物登记」这条路径，因此不依赖任何 YAML 文件。
        """
        config = self._read_yaml(self.yaml_path) if self.yaml_path else None
        if config is None:
            self.save(dict(DEFAULTS))
            self.set_meta('seeded_from', 'defaults')
        else:
            self.save(config)
            self.set_meta('seeded_from', self.yaml_path)

    @staticmethod
    def _read_yaml(path):
        """读 YAML 配置；文件缺失或解析失败返回 None（不抛异常，交由调用方兜底）。

        yaml.YAMLError 的子类里既有解析错误也有读取错误，这里统一按「无法识别」
        处理——配置是可选输入，为它抛异常只会让程序起不来。
        """
        if not path or not os.path.isfile(path):
            return None
        try:
            import yaml
        except ImportError:
            return None
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f)
        except Exception:      # 含 yaml.YAMLError / OSError / UnicodeDecodeError
            return None
        return data if isinstance(data, dict) and data else None

    def set_meta(self, key, value):
        with self._conn:
            self._conn.execute(
                'INSERT OR REPLACE INTO config_meta (key, value) VALUES (?, ?)',
                (key, str(value)))

    def get_meta(self, key, default=None):
        row = self._conn.execute('SELECT value FROM config_meta WHERE key=?',
                                 (key,)).fetchone()
        return row['value'] if row else default

    # ---------- 读写 ----------

    def load(self):
        """读出完整配置 dict（结构与旧 config.yaml 一致）。"""
        config = {k: DEFAULTS[k] for k in SCALAR_KEYS if k in DEFAULTS}
        for row in self._conn.execute('SELECT key, value FROM kv'):
            try:
                config[row['key']] = json.loads(row['value'])
            except ValueError:
                config[row['key']] = row['value']
        config['frame_scale'] = {
            row['role']: [row['interval'], row['scale']]
            for row in self._conn.execute(
                'SELECT role, interval, scale FROM frame_scale ORDER BY rowid')
        }
        return config

    def save(self, config):
        """整体落库。标量项写 kv，人物帧率/缩放写 frame_scale（整表替换）。"""
        if not isinstance(config, dict):
            raise TypeError('配置必须是 dict')
        with self._conn:
            for key in SCALAR_KEYS:
                if key in config:
                    value = _as_bool(config[key]) if key == 'audio' else config[key]
                    self._conn.execute(
                        'INSERT OR REPLACE INTO kv (key, value) VALUES (?, ?)',
                        (key, json.dumps(value, ensure_ascii=False)))
            self._conn.execute('DELETE FROM frame_scale')
            for role, entry in (config.get('frame_scale') or {}).items():
                interval, scale = self._normalize_entry(role, entry)
                self._conn.execute(
                    'INSERT OR REPLACE INTO frame_scale (role, interval, scale)'
                    ' VALUES (?, ?, ?)', (role, interval, scale))

    @staticmethod
    def _normalize_entry(role, entry):
        """把 frame_scale 的一项规整成 (interval, scale)，非法值退回默认。"""
        try:
            interval = int(entry[0])
            scale = float(entry[1])
        except (TypeError, ValueError, IndexError, KeyError):
            return 60, 1.0
        # 上限与面板输入范围一致，防止手改配置写出 0 间隔导致动画不刷新
        return max(20, min(1000, interval)), max(0.1, min(3.0, scale))

    def get(self, key, default=None):
        row = self._conn.execute('SELECT value FROM kv WHERE key=?', (key,)).fetchone()
        if row is None:
            return default
        try:
            return json.loads(row['value'])
        except ValueError:
            return row['value']

    def set(self, key, value):
        """只更新单个标量项（value 为 bool 时统一存 JSON 布尔）。"""
        if value is None:
            return
        stored = _as_bool(value) if isinstance(value, bool) else value
        with self._conn:
            self._conn.execute('INSERT OR REPLACE INTO kv (key, value) VALUES (?, ?)',
                               (key, json.dumps(stored, ensure_ascii=False)))

    def frame_scale(self, role):
        row = self._conn.execute(
            'SELECT interval, scale FROM frame_scale WHERE role=?', (role,)).fetchone()
        return [row['interval'], row['scale']] if row else [60, 1.0]

    def set_frame_scale(self, role, interval, scale):
        interval, scale = self._normalize_entry(role, [interval, scale])
        with self._conn:
            self._conn.execute(
                'INSERT OR REPLACE INTO frame_scale (role, interval, scale)'
                ' VALUES (?, ?, ?)', (role, interval, scale))

    def register_role(self, role, interval=60, scale=1.0):
        """为新导入的人物登记默认帧率/缩放（已存在则不动）。"""
        row = self._conn.execute('SELECT 1 FROM frame_scale WHERE role=?',
                                 (role,)).fetchone()
        if row:
            return False
        self.set_frame_scale(role, interval, scale)
        return True

    def unregister_role(self, role):
        with self._conn:
            cur = self._conn.execute('DELETE FROM frame_scale WHERE role=?', (role,))
        return cur.rowcount

    def ensure_roles(self, roles, interval=60, scale=1.0):
        """为尚未登记的人物补上默认帧率/缩放，返回新增的角色名列表。

        安装包不带 data/config.yaml 时配置由内置默认值播种，其中只登记了一个
        硬编码角色；这里以资源库（assets.db）中实际存在的人物为准补齐，使人物
        菜单与设置面板在无配置文件时也能正常工作。已登记的不会被覆盖。
        """
        existing = set(self.roles())
        missing = [r for r in roles if r not in existing]
        if not missing:
            return []
        with self._conn:
            for role in missing:
                iv, sc = self._normalize_entry(role, [interval, scale])
                self._conn.execute(
                    'INSERT OR REPLACE INTO frame_scale (role, interval, scale)'
                    ' VALUES (?, ?, ?)', (role, iv, sc))
        return missing

    def roles(self):
        return [r['role'] for r in self._conn.execute(
            'SELECT role FROM frame_scale ORDER BY rowid')]

    def stats(self):
        size_kb = (os.path.getsize(self.db_path) / 1024
                   if os.path.isfile(self.db_path) else 0)
        return {
            'backend': 'sqlite',
            'db_path': self.db_path,
            'db_size_kb': size_kb,
            'scalars': self._conn.execute('SELECT COUNT(*) FROM kv').fetchone()[0],
            'roles': len(self.roles()),
            'seeded_from': self.get_meta('seeded_from', 'unknown'),
        }

    # ---------- 导入 / 导出 ----------

    def export_yaml(self, path):
        """导出为 YAML（与旧 config.yaml 同格式，可直接回灌或人工编辑）。"""
        import yaml
        config = self.load()
        os.makedirs(os.path.dirname(os.path.abspath(path)) or '.', exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            yaml.dump(config, f, default_flow_style=False, allow_unicode=True,
                      sort_keys=False)
        return path

    def export_json(self, path):
        """导出为 JSON。"""
        config = self.load()
        os.makedirs(os.path.dirname(os.path.abspath(path)) or '.', exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
        return path

    def import_file(self, path, replace=True):
        """从 YAML/JSON 配置文件导入，返回报告 dict。

        ``replace=True`` 覆盖现有配置；``False`` 时只补充缺失的人物登记，
        不改动已有标量项（人物/地区资源以 assets.db 为准，配置跟随即可）。
        """
        config = self._load_config_file(path)
        if config is None:
            raise ValueError('配置文件为空或格式无法识别')

        report = {'file': os.path.basename(path), 'mode': 'replace' if replace else 'merge',
                  'scalars': 0, 'roles_added': 0, 'roles_kept': 0, 'unknown_keys': []}
        known = set(SCALAR_KEYS) | {'frame_scale'}
        for key in config:
            if key not in known:
                report['unknown_keys'].append(key)

        current = self.load()
        if replace:
            merged = {k: config.get(k, DEFAULTS.get(k)) for k in SCALAR_KEYS
                      if config.get(k) is not None}
            merged['frame_scale'] = dict(config.get('frame_scale') or {})
            for key in SCALAR_KEYS:
                if key in config:
                    report['scalars'] += 1
        else:
            merged = current
            for key in SCALAR_KEYS:
                if key in config and config[key] is not None:
                    merged[key] = config[key]
                    report['scalars'] += 1

        existing = {r['role'] for r in self._conn.execute('SELECT role FROM frame_scale')}
        for role, entry in (config.get('frame_scale') or {}).items():
            if role in existing:
                report['roles_kept'] += 1
                if not replace:
                    continue        # 合并模式保留已有人物设置
            merged.setdefault('frame_scale', {})[role] = entry
            report['roles_added'] += 1

        self.save(merged)
        return report

    def _load_config_file(self, path):
        """按扩展名与内容嗅探读取 YAML/JSON 配置。

        两种格式都尝试一遍：YAML 是 JSON 的超集，先试 JSON 可避免
        ``.yaml`` 里装着 JSON 时被 YAML 解析成字符串。
        """
        if not os.path.isfile(path):
            raise FileNotFoundError(f'配置文件不存在: {path}')
        ext = os.path.splitext(path)[1].lower()
        if ext == '.json':
            data = self._try_json(path)
            if data is None:
                raise ValueError('JSON 解析失败或内容不是配置对象')
            return data
        data = self._read_yaml(path)
        if data:
            return data
        # 扩展名不可靠时再试一次 JSON（部分用户会改后缀）
        data = self._try_json(path)
        if data:
            return data
        raise ValueError('无法识别的配置文件格式（支持 YAML 或 JSON）')

    @staticmethod
    def _try_json(path):
        """尝试按 JSON 读取；失败返回 None。"""
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except Exception:      # 含 json.JSONDecodeError / OSError / UnicodeDecodeError
            return None
        return data if isinstance(data, dict) and data else None

    def reset_to_seed(self):
        """恢复出厂设置：清库后重新播种。

        v3.5 起出厂配置 = 内置默认值；人物登记由调用方随后调
        :meth:`ensure_roles` 按 assets.db 补齐（面板的「恢复出厂设置」即如此做），
        因此**不需要** data/config.yaml 参与。
        """
        with self._conn:
            self._conn.execute('DELETE FROM kv')
            self._conn.execute('DELETE FROM frame_scale')
        self._seed_from_yaml()
        return self.load()

    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None


_default = None


def get_default_store(base_dir, seed_path=None):
    """懒加载默认配置库（<base_dir>/config.db），全进程共用一份。"""
    global _default
    if _default is None:
        _default = ConfigStore(base_dir, seed_path=seed_path)
    return _default


def reset_default_store():
    """丢弃默认配置库单例（测试与「恢复出厂」用）。"""
    global _default
    if _default is not None:
        _default.close()
    _default = None
