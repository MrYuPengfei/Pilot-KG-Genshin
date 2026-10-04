"""资源访问抽象层：优先从 assets.db（SQLite）读取，数据库不存在时回退文件系统。

对上层（desktoppet.py）只暴露字节流和名称列表，不关心底层存储形态。
"""

import os
import sqlite3

BGM_AREAS = ('蒙德', '璃月', '稻妻')
GREETING_FILES = ('早上好.mp3', '中午好.mp3', '晚上好.mp3', '晚安.mp3')


def _classify_voice(filename):
    stem = os.path.splitext(filename)[0]
    if stem in ('早上好', '中午好', '晚上好', '晚安'):
        return 'greeting'
    if stem.startswith('闲聊'):
        return 'chat'
    if stem.startswith('想要了解'):
        return 'know'
    return None


class ResourceStore:
    """统一资源入口。backend 为 'sqlite' 或 'filesystem'。"""

    def __init__(self, base_dir, img_dir='png', music_dir='music', db_name='assets.db'):
        self.base_dir = base_dir
        self.img_dir = img_dir
        self.music_dir = music_dir
        self.db_path = os.path.join(base_dir, db_name)
        self._conn = None
        if os.path.isfile(self.db_path):
            # check_same_thread=False 以便在 Qt 信号回调线程中查询；只读使用是安全的
            self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
            self.backend = 'sqlite'
        else:
            self.backend = 'filesystem'

    # ---------- 帧图片 ----------

    def list_frames(self, role):
        """返回角色全部帧文件名（已排序）。"""
        if self._conn:
            rows = self._conn.execute(
                "SELECT name FROM assets WHERE role=? AND kind='frame' ORDER BY name",
                (role,),
            ).fetchall()
            return [r[0] for r in rows]
        role_dir = os.path.join(self.base_dir, self.img_dir, role)
        return sorted(n for n in os.listdir(role_dir) if n.lower().endswith('.png'))

    def read_frame(self, role, name):
        if self._conn:
            row = self._conn.execute(
                "SELECT data FROM assets WHERE role=? AND kind='frame' AND name=?",
                (role, name),
            ).fetchone()
            if row is None:
                raise FileNotFoundError(f'assets.db 中不存在帧: {role}/{name}')
            return row[0]
        with open(os.path.join(self.base_dir, self.img_dir, role, name), 'rb') as f:
            return f.read()

    # ---------- 角色语音 ----------

    def list_voices(self, role, category=None):
        """返回角色语音文件名列表；category 可取 'greeting'/'chat'/'know' 或 None（全部）。"""
        if self._conn:
            if category is None:
                rows = self._conn.execute(
                    "SELECT name FROM assets WHERE role=? AND kind='voice' ORDER BY name",
                    (role,),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT name FROM assets WHERE role=? AND kind='voice' AND category=? ORDER BY name",
                    (role, category),
                ).fetchall()
            return [r[0] for r in rows]
        role_dir = os.path.join(self.base_dir, self.music_dir, role)
        names = sorted(n for n in os.listdir(role_dir) if n.lower().endswith('.mp3'))
        if category is None:
            return names
        return [n for n in names if _classify_voice(n) == category]

    def read_voice(self, role, name):
        if self._conn:
            row = self._conn.execute(
                "SELECT data FROM assets WHERE role=? AND kind='voice' AND name=?",
                (role, name),
            ).fetchone()
            if row is None:
                raise FileNotFoundError(f'assets.db 中不存在语音: {role}/{name}')
            return row[0]
        with open(os.path.join(self.base_dir, self.music_dir, role, name), 'rb') as f:
            return f.read()

    # ---------- 背景音乐 ----------

    def read_bgm(self, area):
        """读取区域背景音乐（蒙德/璃月/稻妻）。"""
        if self._conn:
            row = self._conn.execute(
                "SELECT data FROM assets WHERE role=? AND kind='bgm' AND name='background.mp3'",
                (area,),
            ).fetchone()
            if row is None:
                raise FileNotFoundError(f'assets.db 中不存在背景音乐: {area}')
            return row[0]
        with open(os.path.join(self.base_dir, self.music_dir, area, 'background.mp3'), 'rb') as f:
            return f.read()

    # ---------- 元信息 ----------

    def list_bgm_areas(self):
        """返回全部有背景音乐的地区名。"""
        if self._conn:
            rows = self._conn.execute(
                "SELECT DISTINCT role FROM assets WHERE kind='bgm' ORDER BY role"
            ).fetchall()
            return [r[0] for r in rows]
        music_root = os.path.join(self.base_dir, self.music_dir)
        areas = []
        for d in os.listdir(music_root):
            dpath = os.path.join(music_root, d)
            if os.path.isdir(dpath) and os.path.isfile(os.path.join(dpath, 'background.mp3')):
                areas.append(d)
        return sorted(areas)

    def list_roles(self):
        """返回全部有帧资源的角色名。"""
        if self._conn:
            rows = self._conn.execute(
                "SELECT DISTINCT role FROM assets WHERE kind='frame' ORDER BY role"
            ).fetchall()
            return [r[0] for r in rows]
        png_root = os.path.join(self.base_dir, self.img_dir)
        return sorted(d for d in os.listdir(png_root) if os.path.isdir(os.path.join(png_root, d)))

    # ---------- 管理（统计/删除） ----------

    def stats(self):
        """资源统计，供管理面板展示。"""
        if self._conn:
            counts = dict(self._conn.execute(
                'SELECT kind, COUNT(*) FROM assets GROUP BY kind').fetchall())
            size_mb = os.path.getsize(self.db_path) / 1024 / 1024
        else:
            counts = {
                'frame': sum(len(self.list_frames(r)) for r in self.list_roles()),
                'voice': sum(len(self.list_voices(r)) for r in self.list_roles()
                             if os.path.isdir(os.path.join(self.base_dir, self.music_dir, r))),
                'bgm': len(self.list_bgm_areas()),
            }
            size_mb = None
        return {
            'backend': self.backend,
            'roles': len(self.list_roles()),
            'areas': len(self.list_bgm_areas()),
            'frames': counts.get('frame', 0),
            'voices': counts.get('voice', 0),
            'bgms': counts.get('bgm', 0),
            'db_size_mb': size_mb,
        }

    def delete_role(self, role):
        """删除角色的全部帧与语音（仅 sqlite 后端）。返回删除行数。"""
        if not self._conn:
            raise RuntimeError('仅 assets.db 后端支持删除操作')
        with self._conn:
            cur = self._conn.execute(
                "DELETE FROM assets WHERE role=? AND kind IN ('frame', 'voice')", (role,))
        return cur.rowcount

    def delete_area(self, area):
        """删除地区背景音乐（仅 sqlite 后端）。返回删除行数。"""
        if not self._conn:
            raise RuntimeError('仅 assets.db 后端支持删除操作')
        with self._conn:
            cur = self._conn.execute(
                "DELETE FROM assets WHERE role=? AND kind='bgm'", (area,))
        return cur.rowcount

    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None
