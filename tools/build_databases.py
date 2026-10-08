"""由 CSV / JSON 构建可分发的数据库（v3.5 起 CSV、JSON 不再随安装包发布）。

**为什么有这一步**：v3.4 之前，知识图谱 CSV 与配置文件是「运行时数据」——安装包带着
它们，程序启动时读文件播种到 SQLite。v3.5 明确发布策略：安装包只带 SQLite 库，
CSV/JSON 降级为**本地构建输入**，用本脚本在打包前生成库文件。

    data/csv/*.csv   ──[本脚本]──▶  kg.db      （知识图谱，随包分发）
    data/config.json ──[本脚本]──▶  config.db  （出厂配置，随包分发）
    png/ + music/    ──[build_assets_db.py]──▶ assets.db（资源，随包分发）

此后程序运行时**只读 SQLite**，不再依赖任何 CSV/JSON。它们的用途变成：
① 构建输入；② 用户手动导入的交换格式（面板「导入 CSV / 导入配置」）；③ 服务器下发
   的载荷格式——这是后续 C/S 架构的接入点：服务器只需下发与本地同构的 CSV/JSON，
   客户端用同样的 import 接口入库即可，无需为「远程数据」另写一套格式。

**v3.8：配置种子由 ``data/config.json`` 改为 ``data/config.json``**，
配置的导入导出也统一为 JSON，YAML 彻底退役。

用法::

    uv run python tools/build_databases.py              # 构建 kg.db + config.db
    uv run python tools/build_databases.py --only kg    # 只重建知识图谱库
    uv run python tools/build_databases.py --force      # 强制重建（忽略已存在）
    uv run python tools/build_databases.py --check      # 只校验，不写入
"""

import argparse
import datetime
import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from config_store import ConfigStore                # noqa: E402
from kg_store import KGStore                        # noqa: E402

CSV_DIR = os.path.join(ROOT, 'data', 'csv')
# 第二套图谱：AI / 教育 / 数据库领域（v3.8.3 起一并入库）。
# 与原神图谱合并进同一个 kg.db——面板里两类实体共存、可互相检索。
CSV_DIR_EDU = os.path.join(ROOT, 'data', 'csv-edu')
SEED_JSON = os.path.join(ROOT, 'data', 'config.json')
KG_DB = os.path.join(ROOT, 'kg.db')
CONFIG_DB = os.path.join(ROOT, 'config.db')


def _human(n):
    return f'{n / 1024 / 1024:.1f} MB' if n >= 1024 * 1024 else f'{n / 1024:.0f} KB'


def _version():
    try:
        import tomllib
        with open(os.path.join(ROOT, 'pyproject.toml'), 'rb') as f:
            return tomllib.load(f)['project']['version']
    except Exception:
        return '0.0.0'


def build_kg(force=False, check_only=False, verbose=True, backup=True):
    """由 data/csv + data/csv-edu 一起构建 kg.db。返回报告 dict。

    ⚠️ **会丢弃程序里对图谱做的编辑**。知识图谱在运行时可由用户编辑
    （管理面板「知识图谱」页），而 CSV 只是当初的初始数据——两者并非同一份内容。
    因此本函数**重建前自动备份**现有 kg.db 到 ``kg.db.bak-<时间戳>``，
    避免「重新构建 → 编辑成果被 CSV 覆盖 → 新安装包仍是旧图谱」。

    日常打包其实**不需要**重建：kg.db 已随源码分发，直接构建即可
    （不加 ``--force`` 时本函数会跳过）。

    两套 CSV 是**先后导入、同一事务外两次调用**：原神图谱先（提供主键与
    12 种内置类型），edu 后（``ai`` / ``education`` / ``database`` 作为新类型
    自动注册）。⚠️ 不能合成一次 ``import_csv([dir1, dir2])``——该方法只接受
    单个路径，分两次导入也便于报告里分别给出两套数据各自的节点/关系数。
    """
    if not os.path.isdir(CSV_DIR):
        raise FileNotFoundError(
            f'知识图谱 CSV 目录不存在：{CSV_DIR}\n'
            f'CSV 是构建输入，不随安装包分发。若要重建知识图谱库，请先备齐 CSV。')

    edu_present = os.path.isdir(CSV_DIR_EDU)

    if os.path.isfile(KG_DB) and not force and not check_only:
        store = KGStore(KG_DB, auto_seed=False)
        report = {'skipped': True, 'nodes': len(store.nodes), 'edges': len(store._edges),
                  'path': KG_DB}
        store.close()
        if verbose:
            print(f'  kg.db 已存在，跳过重建（打包直接用它即可；'
                  f'--force 会用 CSV 覆盖并丢弃你的编辑）：'
                  f'{report["nodes"]} 节点 / {report["edges"]} 关系')
        return report

    csv_count = len([f for f in os.listdir(CSV_DIR) if f.endswith('.csv')])
    edu_count = (len([f for f in os.listdir(CSV_DIR_EDU) if f.endswith('.csv')])
                 if edu_present else 0)
    if check_only:
        store = KGStore(KG_DB, auto_seed=False) if os.path.isfile(KG_DB) else None
        report = {'csv_files': csv_count, 'edu_csv_files': edu_count,
                  'nodes': len(store.nodes) if store else 0,
                  'edges': len(store._edges) if store else 0}
        if store:
            store.close()
        if verbose:
            print(f'  [检查] CSV 原神 {csv_count} 个 / edu {edu_count} 个；kg.db '
                  f'{"存在" if report["nodes"] else "不存在/为空"}'
                  f'（{report["nodes"]} 节点 / {report["edges"]} 关系）')
        return report

    # 重建会丢弃用户在程序里对图谱的编辑——先备份，别让成果被静默覆盖
    backup_path = None
    if backup and os.path.isfile(KG_DB):
        stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
        backup_path = f'{KG_DB}.bak-{stamp}'
        shutil.copy2(KG_DB, backup_path)
        if verbose:
            print(f'  已备份现有图谱库 → {os.path.basename(backup_path)}'
                  f'（程序里编辑过的内容在里面，重建会丢弃）')

    # 临时库构建成功后再替换，避免中途失败留下半成品
    tmp_db = KG_DB + '.building'
    if os.path.isfile(tmp_db):
        os.remove(tmp_db)
    store = KGStore(tmp_db, auto_seed=False)
    try:
        # 先原神（replace 清空），再 edu 合并进来
        report = store.import_csv(CSV_DIR, replace=True)
        edu_report = None
        if edu_present:
            edu_report = store.import_csv(CSV_DIR_EDU)
            report['edu'] = {
                'nodes_added': edu_report['nodes_added'],
                'edges_added': edu_report['edges_added'],
                'rel_cn_added': edu_report['rel_cn_added'],
                'stubs': edu_report['stubs'],
            }
        built_from = 'data/csv + data/csv-edu' if edu_present else 'data/csv'
        store.set_meta('built_from', built_from)
        store.set_meta('app_version', _version())
        store.close()
        os.replace(tmp_db, KG_DB)
    except Exception:
        store.close()
        if os.path.isfile(tmp_db):
            os.remove(tmp_db)
        raise

    final = KGStore(KG_DB, auto_seed=False)
    result = {'path': KG_DB, 'nodes': len(final.nodes), 'edges': len(final._edges),
              'csv_files': csv_count, 'edu_csv_files': edu_count,
              'backup': backup_path, **report}
    final.close()
    if verbose:
        extra = f' + edu {edu_count} 个' if edu_present else ''
        print(f'  已生成 kg.db：{result["nodes"]} 节点 / {result["edges"]} 关系'
              f'（{_human(os.path.getsize(KG_DB))}，来自 {csv_count}{extra} CSV）')
    return result


def build_config(force=False, check_only=False, verbose=True, backup=True):
    """由 data/config.json 构建 config.db（出厂配置）。

    注意：config.db 既是「出厂配置」又是「用户本机状态」。安装包带一份出厂值，
    用户改动后即为本机状态；升级安装时 setup.iss 用 onlyifdoesntexist 保护，
    不会被新版本覆盖。

    同 build_kg：``--force`` 会丢弃用户调好的帧率/缩放，故重建前自动备份。
    """
    if os.path.isfile(CONFIG_DB) and not force and not check_only:
        store = ConfigStore(ROOT, auto_seed=False)
        report = {'skipped': True, 'roles': len(store.roles()),
                  'role': store.load()['role'], 'path': CONFIG_DB}
        store.close()
        if verbose:
            print(f'  config.db 已存在，跳过重建（打包直接用它即可；'
                  f'--force 会用 JSON 种子覆盖并丢弃你调好的帧率/缩放）：'
                  f'{report["roles"]} 个人物登记')
        return report

    # 重建会丢弃用户在本机调好的帧率/缩放——先备份，别让成果被静默覆盖
    backup_path = None
    if backup and not check_only and os.path.isfile(CONFIG_DB):
        stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
        backup_path = f'{CONFIG_DB}.bak-{stamp}'
        shutil.copy2(CONFIG_DB, backup_path)
        if verbose:
            print(f'  已备份现有配置库 → {os.path.basename(backup_path)}'
                  f'（你调好的帧率/缩放在里面，重建会丢弃）')

    seed_exists = os.path.isfile(SEED_JSON)
    if not seed_exists and verbose and not check_only:
        # 不中断：出厂配置退化为内置默认值，程序仍可用（人物登记由 assets.db 补齐）
        print(f'  提示：配置种子 {SEED_JSON} 不存在，'
              f'出厂配置将使用内置默认值（人物登记由程序按 assets.db 自动补齐）。')

    if check_only:
        report = {'seed_exists': seed_exists}
        if os.path.isfile(CONFIG_DB):
            store = ConfigStore(ROOT, auto_seed=False)
            report.update({'db_exists': True, 'roles': len(store.roles())})
            store.close()
        if verbose:
            print(f'  [检查] 种子 JSON {"存在" if seed_exists else "不存在"}；'
                  f'config.db {"已存在" if report.get("db_exists") else "不存在"}')
        return report

    tmp_db = CONFIG_DB + '.building'
    if os.path.isfile(tmp_db):
        os.remove(tmp_db)
    # 用临时目录承载，避免在半成品上写入
    tmp_dir = os.path.join(ROOT, '.build_tmp')
    os.makedirs(os.path.join(tmp_dir, 'data'), exist_ok=True)
    tmp_seed = os.path.join(tmp_dir, 'data', 'config.json')
    if seed_exists:
        with open(SEED_JSON, 'rb') as src, open(tmp_seed, 'wb') as dst:
            dst.write(src.read())
    try:
        # 关键：显式传 seed_path。v3.5 起 ConfigStore 默认不读种子文件
        # （运行时只认 config.db），构建时才会用 JSON 种子生成出厂值。
        # 种子不存在时 seed_path=None → 直接用内置默认值。
        tmp_store = ConfigStore(tmp_dir, seed_path=tmp_seed if seed_exists else None,
                                auto_seed=False)
        tmp_store.reset_to_seed()
        tmp_store.set_meta('seeded_from', 'data/config.json' if seed_exists else 'defaults')
        tmp_store.set_meta('app_version', _version())
        tmp_store.close()
        os.replace(os.path.join(tmp_dir, 'config.db'), tmp_db)
    finally:
        # 用模块级 shutil（顶部已 import）；此处再 import 会让整个函数把它
        # 视作局部变量，未执行到就 UnboundLocalError
        shutil.rmtree(tmp_dir, ignore_errors=True)

    os.replace(tmp_db, CONFIG_DB)
    store = ConfigStore(ROOT, auto_seed=False)
    result = {'path': CONFIG_DB, 'roles': len(store.roles()),
              'role': store.load()['role'], 'backup': backup_path}
    store.close()
    if verbose:
        print(f'  已生成 config.db：出厂角色「{result["role"]}」，'
              f'{result["roles"]} 个人物登记（{_human(os.path.getsize(CONFIG_DB))}）')
    return result


def build(only=None, force=False, check_only=False, verbose=True, backup=True):
    """构建（或检查）全部数据库。

    ⚠️ **打包时的正确用法是「不加 --force」**：kg.db / config.db 已在库里，
    程序运行时的编辑（新增实体、改名、调帧率缩放）都写在里面。不加 ``--force``
    时本函数只做存在性检查并跳过重建，你的编辑因此被保留。
    确认需要丢弃现有内容、从 CSV/JSON 重新生成时，才加 ``--force``
    （会先自动备份到 ``*.bak-<时间戳>``）。
    """
    version = _version()
    if verbose:
        print(f'构建数据库 v{version}'
              f'{"（仅检查）" if check_only else ""}，输入为本地 CSV/JSON，不入安装包')
        if force and not check_only:
            print('  ⚠ --force：用 CSV/JSON 覆盖现有库，'
                  '程序里编辑过的图谱与设置会丢失（将自动备份）')
    results = {}
    if only in (None, 'all', 'kg'):
        if verbose:
            print('知识图谱库 kg.db：')
        results['kg'] = build_kg(force, check_only, verbose, backup)
    if only in (None, 'all', 'config'):
        if verbose:
            print('配置库 config.db：')
        results['config'] = build_config(force, check_only, verbose, backup)
    if verbose:
        print('\n完成后即可打包：安装包只需这三个 .db、帮助文件与图标，不含任何 CSV/JSON。')
    return results


def main(argv=None):
    parser = argparse.ArgumentParser(
        description='由 data/csv 与 data/config.json 构建 kg.db 与 config.db',
        epilog='日常打包不加 --force：库已存在时只检查不重建，'
               '程序里的编辑（新增实体、改名、调帧率缩放）会保留。'
               '确需丢弃现有内容从 CSV/JSON 重新生成时才加 --force（会先自动备份）。')
    parser.add_argument('--only', choices=['all', 'kg', 'config'], default='all')
    parser.add_argument('--force', action='store_true',
                        help='强制重建：用 CSV/JSON 覆盖已存在的库（会先自动备份）')
    parser.add_argument('--check', action='store_true', help='只校验输入与产物，不写入')
    parser.add_argument('--no-backup', action='store_true',
                        help='--force 时不备份现有库（不建议）')
    args = parser.parse_args(argv)
    try:
        build(args.only, args.force, args.check, backup=not args.no_backup)
    except Exception as e:
        print(f'构建失败：{e}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
