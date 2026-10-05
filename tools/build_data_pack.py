"""打包「数据包」：把 data/ 打成独立压缩包，供非 git 渠道发布。

背景：安装包自 v3.4.1 起只带「程序 + assets.db + kg.db + 图标」，**不带 data 文件夹**——
知识图谱 CSV（data/csv，27 个）与配置种子（data/config.yaml）体积小但更新频率低，
改为随源码分发、或用本脚本打成数据包单独发布。

生成两个文件（默认输出到 dist_data/）：

- ``pilot_data_<版本>.zip``    —— 完整数据包，解压到程序目录即生效（含 config.yaml）
- ``pilot_kg_csv_<版本>.zip``  —— 仅知识图谱 CSV，供已安装用户单独补图谱数据

用法::

    uv run python tools/build_data_pack.py                 # 打两个包
    uv run python tools/build_data_pack.py --only kg       # 只打知识图谱 CSV
    uv run python tools/build_data_pack.py --out D:\\发布   # 指定输出目录

说明：数据缺失时程序不会崩——配置退回内置默认并按 assets.db 补齐人物登记，
知识图谱页面则提示需要补充 CSV（见 kg_store 的播种逻辑）。
"""

import argparse
import os
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def _version():
    """从 pyproject.toml 读版本号；读不到时回退为 0.0.0。"""
    try:
        import tomllib
        with open(os.path.join(ROOT, 'pyproject.toml'), 'rb') as f:
            return tomllib.load(f)['project']['version']
    except Exception:
        return '0.0.0'


def _collect(dirpath, exts):
    """收集目录下指定后缀的文件（相对路径排序，保证包内容稳定）。"""
    files = []
    for base, _dirs, names in os.walk(dirpath):
        for name in names:
            if not exts or os.path.splitext(name)[1].lower() in exts:
                full = os.path.join(base, name)
                rel = os.path.relpath(full, ROOT).replace('\\', '/')
                files.append((full, rel))
    return sorted(files, key=lambda x: x[1])


def _make_zip(target, entries):
    """把 (绝对路径, 归档内路径) 列表打进 zip。"""
    with zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for full, arc in entries:
            zf.write(full, arc)
    size_kb = os.path.getsize(target) / 1024
    print(f'  已生成 {os.path.basename(target)}  ({len(entries)} 个文件, {size_kb:.0f} KB)')
    return target


def build(out_dir, only=None):
    version = _version()
    os.makedirs(out_dir, exist_ok=True)
    csv_dir = os.path.join(ROOT, 'data', 'csv')
    seed = os.path.join(ROOT, 'data', 'config.yaml')

    if not os.path.isdir(csv_dir):
        print(f'警告：{csv_dir} 不存在，知识图谱数据包将为空包。', file=sys.stderr)
    csv_files = _collect(csv_dir, {'.csv'}) if os.path.isdir(csv_dir) else []

    made = []
    if only in (None, 'all', 'kg'):
        target = os.path.join(out_dir, f'pilot_kg_csv_{version}.zip')
        made.append(_make_zip(target, csv_files))
    if only in (None, 'all', 'data'):
        entries = list(csv_files)
        if os.path.isfile(seed):
            entries.append((seed, 'data/config.yaml'))
        else:
            print(f'警告：{seed} 不存在，数据包将不含配置种子。', file=sys.stderr)
        target = os.path.join(out_dir, f'pilot_data_{version}.zip')
        made.append(_make_zip(target, entries))

    print('\n发布说明可附在数据包中：把压缩包解压到程序安装目录'
          '（与 原神桌面伙伴.exe 同级的 _internal 目录）即生效。')
    return made


def main(argv=None):
    parser = argparse.ArgumentParser(description='打包 data/ 供非 git 渠道发布')
    parser.add_argument('--out', default=os.path.join(ROOT, 'dist_data'),
                        help='输出目录（默认 dist_data/）')
    parser.add_argument('--only', choices=['all', 'kg', 'data'], default='all',
                        help='只打知识图谱 CSV(kg) / 完整数据包(data) / 全部(all)')
    args = parser.parse_args(argv)
    build(args.out, args.only)
    return 0


if __name__ == '__main__':
    sys.exit(main())
