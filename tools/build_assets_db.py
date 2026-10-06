"""把零散的图片/音频资源打包进单个 SQLite 数据库（assets.db）。

用法：
    python tools/build_assets_db.py                     # 使用默认路径
    python tools/build_assets_db.py --src . --output assets.db -v

目录约定（相对 --src）：
    png/<角色>/*.png                 -> kind='frame'
    music/<角色>/*.mp3               -> kind='voice'，按文件名前缀归类 category
    music/<区域>/background.mp3      -> kind='bgm'（区域：蒙德/璃月/稻妻）

category 取值：greeting（早/中/晚/晚安）、chat（闲聊*）、know（想要了解*）。
"""

import argparse
import os
import sqlite3
import sys

BGM_AREAS = ('蒙德', '璃月', '稻妻')
GREETING_NAMES = ('早上好', '中午好', '晚上好', '晚安')

SCHEMA = """
CREATE TABLE assets (
    role     TEXT NOT NULL,
    kind     TEXT NOT NULL,
    name     TEXT NOT NULL,
    category TEXT,
    data     BLOB NOT NULL,
    PRIMARY KEY (role, kind, name)
);
CREATE INDEX idx_assets_role_kind ON assets(role, kind);
"""


def classify_voice(filename):
    """根据语音文件名推断分类。"""
    stem = os.path.splitext(filename)[0]
    if stem in GREETING_NAMES:
        return 'greeting'
    if stem.startswith('闲聊'):
        return 'chat'
    if stem.startswith('想要了解'):
        return 'know'
    return None


def iter_assets(src_root, img_dir='png', music_dir='music'):
    """遍历资源目录，产出 (role, kind, name, category, abs_path)。"""
    png_root = os.path.join(src_root, img_dir)
    if os.path.isdir(png_root):
        for role in sorted(os.listdir(png_root)):
            role_dir = os.path.join(png_root, role)
            if not os.path.isdir(role_dir):
                continue
            for name in sorted(os.listdir(role_dir)):
                if name.lower().endswith('.png'):
                    yield role, 'frame', name, None, os.path.join(role_dir, name)

    music_root = os.path.join(src_root, music_dir)
    if os.path.isdir(music_root):
        for role in sorted(os.listdir(music_root)):
            role_dir = os.path.join(music_root, role)
            if not os.path.isdir(role_dir):
                continue
            # 含 background.mp3 的目录视为地区 BGM（兼容第三方自定义地区，如 须弥）
            if role in BGM_AREAS or os.path.isfile(os.path.join(role_dir, 'background.mp3')):
                bgm_path = os.path.join(role_dir, 'background.mp3')
                if os.path.isfile(bgm_path):
                    yield role, 'bgm', 'background.mp3', None, bgm_path
                continue
            for name in sorted(os.listdir(role_dir)):
                if name.lower().endswith('.mp3'):
                    yield role, 'voice', name, classify_voice(name), os.path.join(role_dir, name)


def build_db(src_root, output, img_dir='png', music_dir='music', verbose=False):
    """构建 assets.db，返回写入的记录数。"""
    if os.path.exists(output):
        os.remove(output)
    conn = sqlite3.connect(output)
    try:
        conn.executescript(SCHEMA)
        count = 0
        with conn:
            for role, kind, name, category, path in iter_assets(src_root, img_dir, music_dir):
                with open(path, 'rb') as f:
                    data = f.read()
                conn.execute(
                    'INSERT INTO assets (role, kind, name, category, data) VALUES (?, ?, ?, ?, ?)',
                    (role, kind, name, category, data),
                )
                count += 1
                if verbose and count % 500 == 0:
                    print(f'  已导入 {count} 条...', flush=True)
        conn.execute('PRAGMA optimize')
        return count
    finally:
        conn.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description='把桌宠资源打包进 SQLite 数据库')
    parser.add_argument('--src', default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        help='项目根目录（默认取脚本上一级）')
    parser.add_argument('--output', default=None, help='输出数据库路径（默认 <src>/assets.db）')
    parser.add_argument('--img-dir', default='png', help='帧图片目录名（默认 png）')
    parser.add_argument('--music-dir', default='music', help='音频目录名（默认 music）')
    parser.add_argument('-v', '--verbose', action='store_true', help='打印导入进度')
    args = parser.parse_args(argv)

    output = args.output or os.path.join(args.src, 'assets.db')
    count = build_db(args.src, output, args.img_dir, args.music_dir, args.verbose)
    size_mb = os.path.getsize(output) / 1024 / 1024
    print(f'完成：{count} 条资源 -> {output}（{size_mb:.1f} MB）')
    return 0


if __name__ == '__main__':
    sys.exit(main())
