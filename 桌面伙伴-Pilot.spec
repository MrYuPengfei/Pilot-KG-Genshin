# -*- mode: python ; coding: utf-8 -*-
# 打包配置：安装包 = 程序 + **三个 SQLite 库** + 帮助文档 + 图标。不含任何 CSV / JSON 配置。
#
# v3.5 发布策略（为后续 C/S 架构做准备）：
#   data/csv/*.csv   ──[build_databases.py]──▶ kg.db      ┐
#   data/config.json ──[build_databases.py]──▶ config.db  ├─ 随安装包分发
#   png/ + music/    ──[build_assets_db.py]──▶ assets.db  ┘
#
# CSV 与 JSON 降级为**本地构建输入**，运行时不再被程序读取；它们同时是
# 「服务器下发载荷」的格式——客户端用与本地导入完全相同的接口入库，
# 无需为远程数据另造一套格式。
#
# 打包前务必先构建三个库（config.db 缺失或过期会导致安装后设置不对）：
#   uv run python tools/build_assets_db.py     # assets.db
#   uv run python tools/build_databases.py     # kg.db + config.db
#
# config.db 特殊性：它既是包内出厂值、又是用户本机状态。安装脚本 setup.iss 用
# onlyifdoesntexist 安装它，升级时不会覆盖用户已有配置（用户删掉后重装即可恢复出厂值）。
#
# res/help.html（v3.8）：帮助文档独立成文件，启动时由 manager_panel 动态读取，
# 因此必须随包分发——缺了它程序照常运行，但帮助页会显示「未能载入帮助文件」。


a = Analysis(
    ['pilot.py'],
    pathex=[],
    binaries=[],
    datas=[('assets.db', '.'), ('kg.db', '.'), ('config.db', '.'),
           ('ico/icon256.ico', '.'), ('res/help.html', '.')],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='桌面伙伴-Pilot',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['ico/icon256.ico'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='桌面伙伴-Pilot',
)
