"""素材导出：把 assets.db 中的资源还原为原始目录布局或 zip 包。

与 :mod:`asset_importer` 严格对称——导出的包可以直接再导入：

    <导出目录>/
      png/<角色>/*.png                 角色帧
      music/<角色>/*.mp3              角色语音
      music/<地区>/background.mp3     地区背景音乐

用途：
  * 备份/归档完整素材（数据库里只有二进制，导出后才是可读的文件树）；
  * 手工编辑后回导（如替换某一帧、重命名语音）；
  * 分享给 others——导出的包符合素材包格式，可直接用「导入素材」并入。
"""

import os
import zipfile

# 与 asset_importer.iter_assets 的识别规则保持一致
FRAME_DIR = 'png'
MUSIC_DIR = 'music'
BGM_NAME = 'background.mp3'
# 语音分类由文件名约定（见 resource_store._classify_voice），无需额外记录
FRAME_EXT = '.png'
VOICE_EXT = '.mp3'


def _ensure_dir(path):
    os.makedirs(path, exist_ok=True)
    return path


def export_assets(store, out_dir, roles=None, areas=None, as_zip=False,
                  progress=None):
    """导出素材，返回报告 dict。

    :param store: :class:`resource_store.ResourceStore` 实例
    :param out_dir: 输出目录（``as_zip=True`` 时为 zip 文件路径）
    :param roles: 限定只导出这些角色；``None`` 表示全部
    :param areas: 限定只导出这些地区；``None`` 表示全部
    :param as_zip: ``True`` 打成单个 zip，``False`` 写成目录树
    :param progress: 可选回调 ``progress(done, total, label)``，用于界面反馈
    """
    all_roles = store.list_roles()
    all_areas = store.list_bgm_areas()
    roles = list(roles) if roles is not None else all_roles
    areas = list(areas) if areas is not None else all_areas

    # 先把要导出的条目收集齐，才能给 zip 报进度
    items = []   # (归档内相对路径, 读取字节的函数, 分类)
    for role in roles:
        for name in store.list_frames(role):
            items.append((f'{FRAME_DIR}/{role}/{name}', 'frame', role, name))
        for name in store.list_voices(role):
            items.append((f'{MUSIC_DIR}/{role}/{name}', 'voice', role, name))
    for area in areas:
        items.append((f'{MUSIC_DIR}/{area}/{BGM_NAME}', 'bgm', area, BGM_NAME))

    if not items:
        raise ValueError('没有可导出的素材（资源库为空或筛选条件无匹配）')

    readers = {
        'frame': lambda r, n: store.read_frame(r, n),
        'voice': lambda r, n: store.read_voice(r, n),
        'bgm': lambda r, n: store.read_bgm(r),
    }
    report = {'roles': len(roles), 'areas': len(areas), 'files': len(items),
              'bytes': 0, 'mode': 'zip' if as_zip else 'dir',
              'path': os.path.abspath(out_dir)}
    total = len(items)

    if as_zip:
        parent = os.path.dirname(os.path.abspath(out_dir))
        _ensure_dir(parent)
        with zipfile.ZipFile(out_dir, 'w', zipfile.ZIP_DEFLATED,
                             compresslevel=6) as zf:
            for i, (arc, kind, role, name) in enumerate(items, 1):
                data = readers[kind](role, name)
                # PNG/MP3 本身已压缩，改用 ZIP_STORED 可省 CPU 且几乎不增体积
                zf.writestr(arc, data, zipfile.ZIP_STORED)
                report['bytes'] += len(data)
                if progress:
                    progress(i, total, arc)
    else:
        base = _ensure_dir(out_dir)
        for i, (arc, kind, role, name) in enumerate(items, 1):
            data = readers[kind](role, name)
            target = os.path.join(base, *arc.split('/'))
            _ensure_dir(os.path.dirname(target))
            with open(target, 'wb') as f:
                f.write(data)
            report['bytes'] += len(data)
            if progress:
                progress(i, total, arc)

    return report


def _human_size(n):
    # 显式转 float：n 可能是 int（初值 0）或统计累加结果，
    # 直接用格式说明符在类型检查器下会报「不支持格式规范」
    n = float(n)
    if n >= 1024 * 1024 * 1024:
        return f'{n / 1024 / 1024 / 1024:.2f} GB'
    if n >= 1024 * 1024:
        return f'{n / 1024 / 1024:.1f} MB'
    return f'{n / 1024:.0f} KB'
