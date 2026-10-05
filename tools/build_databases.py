"""由 CSV / YAML 构建可分发的数据库（v3.5 起 CSV、YAML 不再随安装包发布）。

**为什么有这一步**：v3.4 之前，知识图谱 CSV 与配置 YAML 是「运行时数据」——安装包带着
它们，程序启动时读文件播种到 SQLite。v3.5 明确发布策略：安装包只带 SQLite 库，
CSV/YAML 降级为**本地构建输入**，用本脚本在打包前生成库文件。

    data/csv/*.csv  ──[本脚本]──▶  kg.db      （知识图谱，随包分发）
    data/config.yaml ──[本脚本]──▶  config.db  （出厂配置，随包分发）
    png/ + music/    ──[build_assets_db.py]──▶ assets.db（资源，随包分发）

此后程序运行时**只读 SQLite**，不再依赖任何 CSV/YAML。CSV/YAML 唯一的用途变成：
① 构建输入；② 用户手动导入的交换格式（面板「导入 CSV / 导入配置」）；③ 服务器下发
   的载荷格式——这是后续 C/S 架构的接入点：服务器只需下发与本地同构的 CSV/YAML，
   客户端用同样的 import 接口入库即可，无需为「远程数据」另写一套格式。

用法::

    uv run python tools/build_databases.py              # 构建 kg.db + config.db
    uv run python tools/build_databases.py --only kg    # 只重建知识图谱库
    uv run python tools/build_databases.py --force      # 强制重建（忽略已存在）
    uv run python tools/build_databases.py --check      # 只校验，不写入
"""

import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from config_store import ConfigStore                # noqa: E402
from kg_store import KGStore                        # noqa: E402

CSV_DIR = os.path.join(ROOT, 'data', 'csv')
SEED_YAML = os.path.join(ROOT, 'data', 'config.yaml')
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


def build_kg(force=False, check_only=False, verbose=True):
    """由 data/csv 构建 kg.db。返回报告 dict。"""
    if not os.path.isdir(CSV_DIR):
        raise FileNotFoundError(
            f'知识图谱 CSV 目录不存在：{CSV_DIR}\n'
            f'CSV 是构建输入，不随安装包分发。若要重建知识图谱库，请先备齐 27 个 CSV。')

    if os.path.isfile(KG_DB) and not force and not check_only:
        store = KGStore(KG_DB, auto_seed=False)
        report = {'skipped': True, 'nodes': len(store.nodes), 'edges': len(store._edges),
                  'path': KG_DB}
        store.close()
        if verbose:
            print(f'  kg.db 已存在，跳过重建（--force 可强制重建）：'
                  f'{report["nodes"]} 节点 / {report["edges"]} 关系')
        return report

    csv_count = len([f for f in os.listdir(CSV_DIR) if f.endswith('.csv')])
    if check_only:
        store = KGStore(KG_DB, auto_seed=False) if os.path.isfile(KG_DB) else None
        report = {'csv_files': csv_count,
                  'nodes': len(store.nodes) if store else 0,
                  'edges': len(store._edges) if store else 0}
        if store:
            store.close()
        if verbose:
            print(f'  [检查] CSV {csv_count} 个；kg.db '
                  f'{"存在" if report["nodes"] else "不存在/为空"}'
                  f'（{report["nodes"]} 节点 / {report["edges"]} 关系）')
        return report

    # 临时库构建成功后再替换，避免中途失败留下半成品
    tmp_db = KG_DB + '.building'
    if os.path.isfile(tmp_db):
        os.remove(tmp_db)
    store = KGStore(tmp_db, auto_seed=False)
    try:
        report = store.import_csv(CSV_DIR, replace=True)
        store.set_meta('built_from', 'data/csv')
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
              'csv_files': csv_count, **report}
    final.close()
    if verbose:
        print(f'  已生成 kg.db：{result["nodes"]} 节点 / {result["edges"]} 关系'
              f'（{_human(os.path.getsize(KG_DB))}，来自 {csv_count} 个 CSV）')
    return result


def build_config(force=False, check_only=False, verbose=True):
    """由 data/config.yaml 构建 config.db（出厂配置）。

    注意：config.db 既是「出厂配置」又是「用户本机状态」。安装包带一份出厂值，
    用户改动后即为本机状态；升级安装时 setup.iss 用 onlyifdoesntexist 保护，
    不会被新版本覆盖。
    """
    if os.path.isfile(CONFIG_DB) and not force and not check_only:
        store = ConfigStore(ROOT, auto_seed=False)
        report = {'skipped': True, 'roles': len(store.roles()),
                  'role': store.load()['role'], 'path': CONFIG_DB}
        store.close()
        if verbose:
            print(f'  config.db 已存在，跳过重建（--force 可强制重建）：'
                  f'{report["roles"]} 个人物登记')
        return report

    seed_exists = os.path.isfile(SEED_YAML)
    if not seed_exists and verbose and not check_only:
        # 不中断：出厂配置退化为内置默认值，程序仍可用（人物登记由 assets.db 补齐）
        print(f'  提示：配置种子 {SEED_YAML} 不存在，'
              f'出厂配置将使用内置默认值（人物登记由程序按 assets.db 自动补齐）。')

    if check_only:
        report = {'seed_exists': seed_exists}
        if os.path.isfile(CONFIG_DB):
            store = ConfigStore(ROOT, auto_seed=False)
            report.update({'db_exists': True, 'roles': len(store.roles())})
            store.close()
        if verbose:
            print(f'  [检查] 种子 YAML {"存在" if seed_exists else "不存在"}；'
                  f'config.db {"已存在" if report.get("db_exists") else "不存在"}')
        return report

    tmp_db = CONFIG_DB + '.building'
    if os.path.isfile(tmp_db):
        os.remove(tmp_db)
    # 用临时目录承载，避免在半成品上写入
    tmp_dir = os.path.join(ROOT, '.build_tmp')
    os.makedirs(os.path.join(tmp_dir, 'data'), exist_ok=True)
    tmp_yaml = os.path.join(tmp_dir, 'data', 'config.yaml')
    if seed_exists:
        with open(SEED_YAML, 'rb') as src, open(tmp_yaml, 'wb') as dst:
            dst.write(src.read())
    try:
        # 关键：显式传 seed_path。v3.5 起 ConfigStore 默认不读 YAML
        # （运行时只认 config.db），构建时才会用 YAML 生成出厂值。
        # 种子不存在时 seed_path=None → 直接用内置默认值。
        tmp_store = ConfigStore(tmp_dir, seed_path=tmp_yaml if seed_exists else None,
                                auto_seed=False)
        tmp_store.reset_to_seed()
        tmp_store.set_meta('seeded_from', 'data/config.yaml' if seed_exists else 'defaults')
        tmp_store.set_meta('app_version', _version())
        tmp_store.close()
        os.replace(os.path.join(tmp_dir, 'config.db'), tmp_db)
    finally:
        import shutil
        shutil.rmtree(tmp_dir, ignore_errors=True)

    os.replace(tmp_db, CONFIG_DB)
    store = ConfigStore(ROOT, auto_seed=False)
    result = {'path': CONFIG_DB, 'roles': len(store.roles()),
              'role': store.load()['role']}
    store.close()
    if verbose:
        print(f'  已生成 config.db：出厂角色「{result["role"]}」，'
              f'{result["roles"]} 个人物登记（{_human(os.path.getsize(CONFIG_DB))}）')
    return result


def build(only=None, force=False, check_only=False, verbose=True):
    """构建（或检查）全部数据库。"""
    version = _version()
    if verbose:
        print(f'构建数据库 v{version}'
              f'{"（仅检查）" if check_only else ""}，输入为本地 CSV/YAML，不入安装包')
    results = {}
    if only in (None, 'all', 'kg'):
        if verbose:
            print('知识图谱库 kg.db：')
        results['kg'] = build_kg(force, check_only, verbose)
    if only in (None, 'all', 'config'):
        if verbose:
            print('配置库 config.db：')
        results['config'] = build_config(force, check_only, verbose)
    if verbose:
        print('\n完成后即可打包：安装包只需这三个 .db 与图标，不含任何 CSV/YAML。')
    return results


def main(argv=None):
    parser = argparse.ArgumentParser(
        description='由 data/csv 与 data/config.yaml 构建 kg.db 与 config.db')
    parser.add_argument('--only', choices=['all', 'kg', 'config'], default='all')
    parser.add_argument('--force', action='store_true', help='强制重建（覆盖已存在的库）')
    parser.add_argument('--check', action='store_true', help='只校验输入与产物，不写入')
    args = parser.parse_args(argv)
    try:
        build(args.only, args.force, args.check)
    except Exception as e:
        print(f'构建失败：{e}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
