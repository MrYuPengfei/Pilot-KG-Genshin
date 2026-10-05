"""第三方素材包导入模块：把自定义人物/地区资源并入 assets.db，并登记配置。

素材包可以是目录或 zip 文件，内部布局与项目一致：

    素材包/
      png/<角色>/*.png                 -> 角色帧（可选）
      music/<角色>/*.mp3               -> 角色语音（可选，命名遵循 早上好/闲聊*/想要了解* 约定自动分类）
      music/<地区>/background.mp3      -> 地区背景音乐（目录含 background.mp3 即识别为地区）

png/ 与 music/ 可只提供其一；已有资源同名覆盖，新增资源直接并入。
新角色会自动在配置库（config.db）的 frame_scale 中登记默认值 [60, 1.0]。
"""

import os
import sqlite3
import tempfile
import zipfile

from tools.build_assets_db import iter_assets

ENSURE_SCHEMA = """
CREATE TABLE IF NOT EXISTS assets (
    role     TEXT NOT NULL,
    kind     TEXT NOT NULL,
    name     TEXT NOT NULL,
    category TEXT,
    data     BLOB NOT NULL,
    PRIMARY KEY (role, kind, name)
);
CREATE INDEX IF NOT EXISTS idx_assets_role_kind ON assets(role, kind);
"""

DEFAULT_FRAME_SCALE = [60, 1.0]


def _extract_if_zip(src):
    """zip 解压到临时目录，返回 (实际目录, 临时目录对象或 None)。"""
    if zipfile.is_zipfile(src):
        tmp = tempfile.TemporaryDirectory(prefix='pet_asset_pack_')
        with zipfile.ZipFile(src) as zf:
            zf.extractall(tmp.name)
        # 兼容 zip 内多套一层同名目录的情况
        entries = os.listdir(tmp.name)
        if len(entries) == 1 and os.path.isdir(os.path.join(tmp.name, entries[0])):
            inner = os.path.join(tmp.name, entries[0])
            if os.path.isdir(os.path.join(inner, 'png')) or os.path.isdir(os.path.join(inner, 'music')):
                return inner, tmp
        return tmp.name, tmp
    if os.path.isdir(src):
        return src, None
    raise FileNotFoundError(f'素材包不存在或格式不支持: {src}')


def import_assets(src, db_path, config_store=None, img_dir='png', music_dir='music'):
    """导入素材包，返回导入报告 dict。

    ``config_store`` 为 :class:`config_store.ConfigStore` 实例（v3.4 起配置走
    SQLite）；传入时会为新角色登记默认帧率/缩放。

    report = {
        'frames': 新增/更新帧数, 'voices': ..., 'bgms': ...,
        'roles':  [涉及的角色], 'areas': [涉及的地区],
        'new_roles': [本次新出现的角色],
    }
    """
    src_dir, tmp = _extract_if_zip(src)
    try:
        conn = sqlite3.connect(db_path)
        try:
            conn.executescript(ENSURE_SCHEMA)
            report = {'frames': 0, 'voices': 0, 'bgms': 0,
                      'roles': set(), 'areas': set(), 'new_roles': set()}
            existing_roles = {r[0] for r in conn.execute(
                "SELECT DISTINCT role FROM assets WHERE kind='frame'")}
            with conn:
                for role, kind, name, category, path in iter_assets(src_dir, img_dir, music_dir):
                    with open(path, 'rb') as f:
                        data = f.read()
                    conn.execute(
                        'INSERT OR REPLACE INTO assets (role, kind, name, category, data)'
                        ' VALUES (?, ?, ?, ?, ?)',
                        (role, kind, name, category, data),
                    )
                    if kind == 'frame':
                        report['frames'] += 1
                        report['roles'].add(role)
                        if role not in existing_roles:
                            report['new_roles'].add(role)
                    elif kind == 'voice':
                        report['voices'] += 1
                        report['roles'].add(role)
                    elif kind == 'bgm':
                        report['bgms'] += 1
                        report['areas'].add(role)
        finally:
            conn.close()
    finally:
        if tmp is not None:
            tmp.cleanup()

    total = report['frames'] + report['voices'] + report['bgms']
    if total == 0:
        raise ValueError(f'素材包中未找到可导入的资源（需要 png/ 或 music/ 目录）: {src_dir}')

    if config_store is not None and report['roles']:
        for role in report['roles']:
            config_store.register_role(role, *DEFAULT_FRAME_SCALE)

    report['roles'] = sorted(report['roles'])
    report['areas'] = sorted(report['areas'])
    report['new_roles'] = sorted(report['new_roles'])
    return report


def _register_roles_in_config(config_path, roles):
    """（已废弃）v3.3 及之前直接改写 config.yaml 的登记逻辑。

    v3.4 起配置改由 ConfigStore（SQLite）管理，请改用
    ``config_store.register_role(role, interval, scale)``。
    """
