"""打包产物校验：确认安装包只含三个 .db、help.html 与图标，不含任何 CSV / JSON 配置。

配合 `原神桌面伙伴.spec` + `setup.iss` 使用。在**构建完成后**运行：

    uv run python tools/verify_package.py

逐项检查（任一 FAIL 即退出码 1，便于接 CI）：
  ① 产物目录结构：exe 在根、数据在 _internal
  ② 三个库就位且非空（大小下限校验，挡住「空库/半成品」）
  ③ **包内不存在任何 CSV / YAML / JSON**（v3.5 硬性要求，v3.8 扩到 JSON）
  ④ 图标与**帮助文档 res/help.html** 就位（v3.8：缺它帮助页会显示兜底提示）
  ⑤ 自有模块都在 PYZ 里（pilot 是入口脚本，不在 PYZ，属正常）
  ⑥ 图谱库内容抽样：节点/关系数与表结构
"""

import os
import sqlite3
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIST = os.path.join(ROOT, 'dist', '原神桌面伙伴')
INTERNAL = os.path.join(DIST, '_internal')
BUILD = os.path.join(ROOT, 'build', '原神桌面伙伴')

# 三个库的合理下限（字节），低于此值视为空库或半成品
MIN_SIZES = {'assets.db': 400 * 1024 * 1024,
             'kg.db': 2 * 1024 * 1024,
             'config.db': 8 * 1024}

MODULES = ['manager_panel', 'resource_store', 'asset_importer', 'config_store',
           'kg_store', 'kg_editor', 'kg_view']

_failures = []


def check(ok, label, detail=''):
    print(f'  {"OK  " if ok else "FAIL"} {label}' + (f'  —— {detail}' if detail else ''))
    if not ok:
        _failures.append(label)
    return ok


def main():
    print('校验打包产物：安装包应只含三个 .db、help.html 与图标，不含 CSV / JSON\n')

    print('① 目录结构')
    check(os.path.isfile(os.path.join(DIST, '原神桌面伙伴.exe')),
          'exe 位于产物根目录', os.path.join(DIST, '原神桌面伙伴.exe'))
    check(os.path.isdir(INTERNAL), '_internal 目录存在')

    print('\n② 三个数据库就位且非空')
    for name, min_size in MIN_SIZES.items():
        path = os.path.join(INTERNAL, name)
        if not check(os.path.isfile(path), f'{name} 存在'):
            continue
        size = os.path.getsize(path)
        check(size >= min_size, f'{name} 大小正常',
              f'{size / 1024 / 1024:.1f} MB（下限 {min_size / 1024 / 1024:.0f} MB）')

    print('\n③ 包内不得含 CSV / YAML / JSON（v3.5 硬性要求，v3.8 扩到 JSON）')
    offenders = []
    for base, _dirs, names in os.walk(DIST):
        for n in names:
            if n.lower().endswith(('.csv', '.yaml', '.yml', '.json')):
                offenders.append(os.path.relpath(os.path.join(base, n), DIST))
    check(not offenders, '无 CSV / YAML / JSON 文件',
          f'发现 {len(offenders)} 个：{offenders[:5]}' if offenders else '已确认')
    check(not os.path.isdir(os.path.join(INTERNAL, 'data')), '无 data/ 目录')
    # data/ 的内容已被打进库，这里只确认目录本身没被带进去
    check(not os.path.isdir(os.path.join(DIST, 'data')), '产物根目录无 data/')

    print('\n④ 图标与帮助文档')
    for icon in ('icon256.ico',):
        check(os.path.isfile(os.path.join(INTERNAL, icon))
              or os.path.isfile(os.path.join(DIST, icon)), f'{icon} 就位')
    # v3.8：帮助文档已从源码外置为 res/help.html，必须随包分发——
    # 缺它程序照常运行，但帮助页只会显示「未能载入帮助文件」，属静默故障。
    help_path = os.path.join(INTERNAL, 'help.html')
    if check(os.path.isfile(help_path), 'help.html 就位（帮助文档）', help_path):
        size = os.path.getsize(help_path)
        check(size > 5000, 'help.html 内容非空', f'{size} 字节')
        with open(help_path, encoding='utf-8', errors='ignore') as f:
            head = f.read(4000)
        check('{{APP_VERSION}}' in head, 'help.html 含版本占位符',
              '占位符应保留，由程序运行时替换')

    print('\n⑤ 自有模块在 PYZ 中')
    toc = os.path.join(BUILD, 'PYZ-00.toc')
    if check(os.path.isfile(toc), 'PYZ-00.toc 存在'):
        with open(toc, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
        for m in MODULES:
            check(f"'{m}'" in content, f'模块 {m} 已打包')
        check('tools.build_assets_db' in content, 'tools.build_assets_db 已打包')
        # 构建/发布工具不应进包
        for m in ('tools.build_databases', 'tools.build_data_pack'):
            check(f"'{m}'" not in content, f'构建工具 {m} 未进包')

    print('\n⑥ 知识图谱库内容抽样')
    kg = os.path.join(INTERNAL, 'kg.db')
    if os.path.isfile(kg):
        conn = sqlite3.connect(kg)
        try:
            tables = {r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
            check({'kg_nodes', 'kg_edges', 'kg_meta'} <= tables, 'kg.db 表结构完整',
                  ','.join(sorted(tables)))
            nodes = conn.execute('SELECT COUNT(*) FROM kg_nodes').fetchone()[0]
            edges = conn.execute('SELECT COUNT(*) FROM kg_edges').fetchone()[0]
            check(nodes > 1800, 'kg.db 节点数 > 1800', f'{nodes} 个')
            check(edges > 7000, 'kg.db 关系数 > 7000', f'{edges} 条')
            schema = conn.execute(
                "SELECT value FROM kg_meta WHERE key='schema_version'").fetchone()
            check(schema is not None, 'kg.db 记录 schema_version',
                  schema[0] if schema else '缺失')
        finally:
            conn.close()

    cfg = os.path.join(INTERNAL, 'config.db')
    if os.path.isfile(cfg):
        conn = sqlite3.connect(cfg)
        try:
            tables = {r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
            check({'kv', 'frame_scale', 'config_meta'} <= tables, 'config.db 表结构完整',
                  ','.join(sorted(tables)))
            roles = conn.execute('SELECT COUNT(*) FROM frame_scale').fetchone()[0]
            check(roles > 0, 'config.db 含人物登记', f'{roles} 人')
        finally:
            conn.close()

    print()
    if _failures:
        print(f'校验未通过：{len(_failures)} 项失败')
        for f in _failures:
            print(f'  - {f}')
        return 1
    print('全部校验通过：安装包 = 程序 + assets.db + kg.db + config.db '
          '+ help.html + 图标，无 CSV/YAML/JSON。')
    return 0


if __name__ == '__main__':
    sys.exit(main())
