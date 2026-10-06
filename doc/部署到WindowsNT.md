# 部署到 Windows（PyInstaller + Inno Setup 6）

适用版本：**v3.8**。整体链路：`pilot.py` → PyInstaller 打包成 `dist/原神桌面伙伴/` → Inno Setup 编译 `setup.iss` 生成安装向导 `inno_build/原神桌面伙伴安装向导.exe`。

| 环节 | 工具 | 产物 | 典型耗时 |
| --- | --- | --- | --- |
| 资源入库 | `tools/build_assets_db.py` | `assets.db`（约 460MB） | 约 15 秒 |
| 打包 | PyInstaller 6+（onedir） | `dist/原神桌面伙伴/`（约 500MB） | 约 3 分钟 |
| 制作安装包 | Inno Setup 6 | `inno_build/原神桌面伙伴安装向导.exe`（约 480MB） | 约 2~3 分钟 |

---

## 版本号同步点（有 3 处，改版时必须一起改）

| 文件 | 字段 | 作用 |
| --- | --- | --- |
| `manager_panel.py` | `APP_VERSION = '3.8'` | 面板标题、状态栏、帮助页显示的版本号 |
| `setup.iss` | `#define AppVersion "3.8"` | 安装包属性、"新版本"提示 |
| `pyproject.toml` | `version = "3.8.0"` | 包元数据（可带第三位补丁号） |

> `pyproject.toml` 用三段式 `3.8.0`，另两处用两段式 `3.8`——这是有意的，测试只校验两者**前缀一致**
> （`tests/test_v38.py::test_version_three_places_match`）。
> 三处漏改不会导致构建失败，但会让用户看到互相矛盾的版本号。

---

## 步骤 0：环境准备

```shell
# 需要 Python 3.14+ 与 uv（https://docs.astral.sh/uv/）
uv sync                      # 安装运行依赖
uv run pytest -q             # 19 passed 才继续往下走
```

另外需要：

- **Inno Setup 6**（https://jrsoftware.org/isinfo.php ）
- PyInstaller **不需要预装**——用 `uv run --with pyinstaller` 临时提供，避免污染项目依赖。

## 步骤 1：构建三个数据库（v3.5 起安装包只带 `.db`）

安装包 = 程序 + **三个 SQLite 库** + 图标，**不含任何 CSV / YAML**。
CSV 与 YAML 降级为**本地构建输入**，打包前必须先由它们生成库文件。

```shell
# ① 资源库（素材 → assets.db）
uv run python tools/build_assets_db.py
#   可选参数：--output 指定输出路径、--img-dir/--music-dir 换目录名、-v 打印进度
#   预期输出：完成：9820 条资源 -> ...\assets.db（459.5 MB）

# ② 知识图谱库（data/csv/*.csv → kg.db）+ ③ 出厂配置库（data/config.json → config.db）
uv run python tools/build_databases.py
#   可选参数：--only kg|config|all、--force 强制重建、--check 只校验不写入
#   预期输出：kg.db 已存在，跳过重建：1911 节点 / 7356 关系；config.db 30 个人物登记
```

> ⚠️ **打包时不要加 `--force`**（v3.7 起请务必注意）。
>
> `kg.db` 与 `config.db` 既是「出厂产物」又是「用户本机状态」——你在程序里
> 新增的图谱实体、改过的名字、调好的帧率与缩放，**都写在这两个库里**。
> 一旦用 `--force` 重建，它们会被 `data/csv`、`data/config.json` **静默覆盖**，
> 表现为「重新构建后新安装包里还是旧数据」。
>
> 正确做法：**直接构建**（不加 `--force`）——库已存在时只检查不重建，
> 你的编辑因此被保留。只有确认要丢弃现有内容、从 CSV/YAML 重新生成时才加
> `--force`，且它会**自动备份**到 `kg.db.bak-<时间戳>` / `config.db.bak-<时间戳>`。
>
> ```shell
> uv run python tools/build_databases.py            # ✓ 日常打包用这个
> uv run python tools/build_databases.py --force    # ✗ 会覆盖编辑（但有备份）
> ```

打包前自检（三个库都必须存在且非空）：

```shell
uv run python tools/build_databases.py --check
ls -la assets.db kg.db config.db
```

| 库 | 来源 | 说明 |
| --- | --- | --- |
| `assets.db` | `png/` + `music/` | 资源（帧、语音、BGM） |
| `kg.db` | `data/csv/*.csv` | 知识图谱，1911 节点 / 7356 关系 |
| `config.db` | `data/config.json` | 出厂配置（当前人物、各人物帧率与缩放） |

> **`config.db` 是唯一「装完就会被用户改写」的库**：用户改设置后它就是本机状态。
> `setup.iss` 用 `onlyifdoesntexist` 安装它，**升级不会覆盖用户配置**；
> 删掉后重装即可恢复出厂值。
>
> **运行时不读 CSV / YAML**：实测把整个 `data/` 删掉，程序照常启动、图谱与设置面板
> 功能完整（知识图谱来自包内 `kg.db`，配置缺失时按 `assets.db` 补齐人物登记）。

## 步骤 2：清理构建缓存（**最容易被跳过、也最容易出事的一步**）

```shell
rm -rf build dist
rm -rf "$LOCALAPPDATA/pyinstaller"        # Windows 上即 %LOCALAPPDATA%\pyinstaller
```

> ⚠️ **为什么必须手动删**：PyInstaller 的 `--clean` 开关在部分环境下删除缓存的步骤会被安全策略
> 拦截而**静默跳过**，随后复用上一版的 Analysis 缓存。结果是新模块和新数据不进包，
> **但构建日志照样显示 `Build complete!`**，非常容易误判。
>
> 本项目已经因此踩坑多次：改过入口名、加过 `kg_store`/`kg_view`、新增 KG 数据后，
> 产物里模块或 CSV 缺失，而构建「看起来成功」。**只要复用缓存，之前所有校验都可能白做。**

如果删除操作被安全策略/回收站机制拦截，可用 `.NET` 直接删除：

```powershell
[System.IO.Directory]::Delete("D:\VMwareShareFolder\project\Pilot\dist", $true)
```

## 步骤 3：PyInstaller 打包

```shell
uv run --with pyinstaller pyinstaller pilot.py \
    --name "原神桌面伙伴" --onedir --noconsole \
    --icon=ico/icon256.ico --noconfirm \
    --add-data "assets.db;." \
    --add-data "kg.db;." \
    --add-data "config.db;." \
    --add-data "ico/icon256.ico;."
```

（Windows `cmd` 里把行尾的 `\` 换成 `^`。这里故意**不加 `--clean`**，清缓存交给上一步显式做。）

说明：

- 用 **onedir**（单文件夹）模式，启动快。产物为 `dist/原神桌面伙伴/原神桌面伙伴.exe` + `_internal/`（`assets.db`、`kg.db`、`config.db`、`icon256.ico` 都在 `_internal` 里，**没有任何 CSV/YAML，也没有 data/**）。
- 不再需要 2.0 之前那种为每个角色写一条 `--add-data` 的长命令。
- `resource_store.py`、`asset_importer.py`、`config_store.py`、`kg_store.py`、`kg_editor.py`、`kg_view.py`、`tools.build_assets_db` 会依 import 关系自动进包，无需额外参数。
- `tools.build_databases.py` / `tools.build_assets_db.py` / `tools.build_data_pack.py` 都是构建与发布工具，**不应进包**；如误被分析进去可在 `excludes` 里排除。

### 3.1 打包后必须逐项校验

```shell
# ① 全部自有模块在 PYZ 里（pilot 是入口脚本，编译进 EXE，不在 PYZ 中，属正常）
for m in manager_panel resource_store asset_importer config_store kg_store kg_editor kg_view; do
  grep -q "'$m'" "build/原神桌面伙伴/PYZ-00.toc" && echo "OK  $m" || echo "MISS $m"
done
grep -c "tools.build_assets_db" "build/原神桌面伙伴/PYZ-00.toc"

# ② 数据文件在 _internal 里就位
ls -la "dist/原神桌面伙伴/_internal/assets.db" \
       "dist/原神桌面伙伴/_internal/kg.db" \
       "dist/原神桌面伙伴/_internal/config.db" \
       "dist/原神桌面伙伴/_internal/icon256.ico"
# 安装包不应含任何 CSV / YAML（v3.5 硬性要求）
find "dist/原神桌面伙伴/_internal" -maxdepth 2 \( -name "*.csv" -o -name "*.yaml" -o -name "*.yml" -o -name "*.json" \) \
  | head -5 | grep . && echo "异常：包内存在 CSV/YAML" || echo "OK  包内无 CSV/YAML"
ls -d "dist/原神桌面伙伴/_internal/data" 2>/dev/null && echo "异常：包内存在 data/" || echo "OK  无 data/"
```

另外看构建日志应出现 `Building PYZ because PYZ-00.toc is non existent`；
若显示 `Building PYZ because PYZ-00.toc is newer`，说明复用了旧缓存，**回步骤 2 重来**。

> 上面这套手工校验已固化成脚本，一条命令跑完六组检查（退出码非 0 即失败）：
>
> ```shell
> uv run python tools/verify_package.py
> ```
>
> 它还会额外断言 `tools.build_databases` / `tools.build_data_pack` **没有**被打进包
> （它们是构建与发布工具，不该随程序分发）。

## 步骤 4：Inno Setup 生成安装包

```shell
"C:\Program Files (x86)\Inno Setup 6\ISCC.exe" setup.iss
```

也可以在 Inno 的 GUI 里打开 `setup.iss` 直接编译。

- 产物：`inno_build/原神桌面伙伴安装向导.exe`（约 480MB，编译约 2~3 分钟）。
- 校验版本：Inno 编译日志首行会显示 `Setup Version`，应与 `AppVersion` 一致。
- `setup.iss` 中的路径全部相对于项目根目录，**必须在根目录执行编译**。

---

## 安装行为说明（2.0 起的变化）

- **安装目录默认为 `%LOCALAPPDATA%\Programs\原神桌面伙伴`**（每用户安装，免管理员权限）。
  原因是程序运行时要写 `config.db`（保存设置）、`assets.db`（导入素材包）与 `kg.db`（图谱编辑），
  装进 `Program Files` 会因权限不足导致保存失败——**请勿把 `DefaultDirName` 改回 `{commonpf}`**。
- `PrivilegesRequired=lowest`，但保留了 `dialogn`，允许用户主动提权安装到其他位置。
- 仅支持 64 位系统（`ArchitecturesAllowed=x64compatible`）。
- 覆盖安装时安装向导会自动关闭正在运行的伙伴进程（`CloseApplications=yes`）。
- 安装时可勾选**创建桌面图标**、**开机自启**（默认均不勾选）。
- 卸载有独立图标和开始菜单项；卸载时清理运行期产生的 `_internal\__pycache__`。
- 安装完成后自动启动程序（`skipifsilent`，静默安装时不启动）。

---

## 测试安装包

1. 在一台干净机器（或虚拟机）上运行安装向导，确认能安装、能启动、托盘菜单正常。
2. 重点验证：
   - 切换人物、播放语音/背景音乐；
   - 在管理面板调整帧率/缩放后退出重进（配置应保留）；
   - **管理面板 → 素材管理** 导入一个 zip 素材包（确认数据库可写、新人物即时出现在托盘菜单）；
   - **管理面板 → 知识图谱**，搜索「钟离」能出图（验证 `data\csv` 已随包分发，27 个 CSV）。
3. 覆盖安装一遍旧版本之上，验证升级流程（`AppId` 不变，`{localappdata}` 路径不变）。

## 静默安装验证（CI / 无人值守）

```shell
# 静默安装到默认用户目录
inno_build/原神桌面伙伴安装向导.exe /VERYSILENT /SUPPRESSMSGBOXES /NORESTART

# 检查关键文件（应存在且约 460MB）
ls -la "$LOCALAPPDATA/Programs/原神桌面伙伴/_internal/assets.db"
ls "$LOCALAPPDATA/Programs/原神桌面伙伴/_internal/data/csv" | wc -l         # 应为 27

# 静默卸载
"$LOCALAPPDATA/Programs/原神桌面伙伴/unins000.exe" /VERYSILENT /SUPPRESSMSGBOXES /NORESTART
```

`/DIR=` 可指定安装目录做隔离测试；若不指定则落到 `%LOCALAPPDATA%\Programs\原神桌面伙伴`。

> **卸载是异步的**：直接 `ls` 可能早于卸载完成而误判「目录还在」，脚本里应轮询确认目录消失。
> 实测卸载约 3 秒完成，安装约 1.5 分钟（解压 500MB）。

## 本次构建实测记录（v3.7，2026-10-05 22:02~22:09 全链路，含当日全部修复）

| 环节 | 结果 |
| --- | --- |
| `uv run pytest -q` | **168 passed**（160 轻量 + 8 GUI 切换） |
| 清理 `build`/`dist` | PowerShell `Remove-Item -Recurse -Force`（bash 的 `rm -rf` 会被安全闸门拦） |
| 前置构建 | `uv run python tools/build_databases.py`（**不加 `--force`**）→ 正确**跳过重建**并提示「`--force` 会用 CSV 覆盖并丢弃你的编辑」：`kg.db` 1911 节点 / 7356 关系（2,998,272 字节）、`config.db` 30 人登记（28,672 字节）；`--check` 通过。三个库文件时间戳保持构建前的原值（**未被覆盖**） |
| PyInstaller（onedir） | 成功，**2 分 22 秒**，日志为 `Building COLLECT because COLLECT-00.toc is non existent`（全新构建，未复用缓存） |
| `tools/verify_package.py` | **全绿**（六组检查：目录结构 / 三库大小下限 / 无 CSV·YAML·data / 图标 / PYZ 模块 / 库内容抽样） |
| PYZ 模块校验 | `manager_panel` / `resource_store` / `asset_importer` / `config_store` / `kg_store` / `kg_editor` / `kg_view` / `tools.build_assets_db` 全部命中；`tools.build_databases`、`tools.build_data_pack` **未进包**（符合预期） |
| `_internal` 数据校验 | `assets.db` 483,860,480 字节（461.4MB）、`kg.db` 2,998,272 字节（1911 节点 / 7356 关系 / `schema_version=1`）、`config.db` 28,672 字节、`icon256.ico` 均就位 |
| **包内 CSV/YAML 检查** | **数量 = 0**，且**无 `data/` 目录**（v3.5 硬性要求达成） |
| 产物 exe 离屏运行 | 存活 25 秒正常，**输出零 Qt 警告**；三个库在 `_internal` 内就位 |
| Inno Setup 编译 | 成功，**125.2 秒** |
| 安装包 | `inno_build/原神桌面伙伴安装向导.exe`，**503,155,522 字节（479.6 MB）** |
| 静默安装 | 成功（**71 秒**）；安装目录三库齐备，**CSV/YAML 数量 = 0、无 `data/`** |
| 已安装程序离屏启动 | 存活 25 秒正常、**输出零 Qt 警告** |
| 静默卸载 | 成功；文件数归 0（卸载程序异步，需轮询约 10~30 秒） |
| 冒烟 + 静态检查 | `tools/smoke_kg_panel.py` **SMOKE OK**；核心模块 + tools + tests **pyflakes 零告警** |

> **为什么这次特别关注「零 Qt 警告」**：v3.7 当日修掉的四类问题
> （图谱双击 `Internal C++ object already deleted`、编辑对话框 `itemFromIndex(str)`、
> 画布 `ungrabMouse: not a mouse grabber`、启动时托盘 `No Icon set`）
> 都会在**运行时输出到 stderr**。产物 exe 与已安装程序各跑 25 秒、输出为空，
> 说明这些修复确实进了包。
>
> 上一轮（17:45 那次）还实测过「删除 `_internal/config.db` 后 exe 自行重建 28,672 字节配置库
> （`role=七七` + 按 `assets.db` 补齐 28 人）」，证明运行时确实不依赖任何 YAML —— 该结论仍然有效。
> 「升级保护」（`onlyifdoesntexist`）也已在更早几轮实测确认。

> **打包前建议先跑静态检查**（v3.7 起项目零告警基线）：
> ```shell
> uv run --with pyflakes python -m pyflakes pilot.py manager_panel.py config_store.py \
>     resource_store.py asset_importer.py asset_exporter.py kg_store.py kg_editor.py \
>     kg_view.py tools/ tests/          # 应无输出
> uv run python -W error::SyntaxWarning -m compileall -q pilot.py manager_panel.py tools/
> ```
> `tools/mihoyo_spider.py` 有 8 处「局部变量未使用」是**有意保留**的（其用途在 v3.4 迁入时
> 已随相关逻辑一起注释掉，该脚本本就不可直接运行），不必清理。

> `pilot` 作为入口脚本不进入 PYZ（它被编译进 EXE 本身），校验时不必检查。

> **产物目录内不要用 `uv run python` 跑脚本**：`_internal` 里有打包进来的 `python314.dll`，
> 会与 uv 选中的解释器冲突（`Module use of python314.dll conflicts with this version of Python`）。
> 需要检查包内文件时，回项目根目录用绝对路径访问。

> 校验脚本：`uv run python tools/verify_package.py`（构建完成后运行，退出码非 0 即失败）。

---

## 故障排查

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| 产物缺少新模块或新数据，但构建显示成功 | 复用了旧 Analysis 缓存 | 手动删 `build/`、`dist/`、`%LOCALAPPDATA%\pyinstaller` 后重打（步骤 2、3.1） |
| 安装后启动即崩，提示缺 `assets.db` | 打包时 `--add-data` 漏了或 DB 未生成 | 先跑 `build_assets_db.py`，再补 `--add-data "assets.db;."` |
| 知识图谱页空白 / 搜索无结果 | `kg.db` 未随包分发或为空 | 跑 `uv run python tools/build_databases.py --only kg`（库不存在时会自动生成）后重新打包；确认 `_internal/kg.db` 约 2.9MB |
| 配置被重置 / 当前人物不对 | `config.db` 未随包分发，程序回退到内置默认值（七七 + 按资源库补齐登记） | 跑 `uv run python tools/build_databases.py --only config` 后重新打包 |
| 面板/托盘里没有新导入的人物 | `assets.db` 不可写 | 装到了 `Program Files`；改装到 `%LOCALAPPDATA%\Programs` |
| 退出后设置没保存 | 同上，配置文件不可写 | 同上；`DefaultDirName` 不要改回 `{commonpf}` |
| 覆盖安装失败提示文件占用 | 旧进程未退出 | 已配 `CloseApplications=yes`；仍失败则手动结束 `原神桌面伙伴.exe` 后重试 |
| 卸载后目录仍在 | 卸载程序异步退出 | 轮询等待，不要立即判定失败 |
| 单个人物无动画/窗口不显示 | 该角色只有 1 帧 | 属正常：`pilot.py` 已做单帧保护，按静态图显示 |
| 传了 `/DIR=` 却装到了默认目录 | **bash 会吞掉反斜杠**：`"C:\\Users\\..."` 被解析成 `C:Users...` | 改用**正斜杠**或单引号：`/DIR='C:/Users/<用户名>/AppData/Local/Programs/pilot_test'`；或直接用默认目录 |

### 冒烟测试：确认打包后的 exe 真能跑

安装完成后不必手动点开，可用离屏方式验证整链路初始化（托盘、SQLite、帧缓存、音频）：

```shell
cd "$LOCALAPPDATA/Programs/原神桌面伙伴"
QT_QPA_PLATFORM=offscreen SDL_AUDIODRIVER=dummy "./原神桌面伙伴.exe" &
sleep 20
tasklist | grep -qi "原神桌面伙伴" && echo "OK: 进程存活 20s" || echo "FAIL: 进程已退出"
taskkill //IM "原神桌面伙伴.exe" //F
```

> `SDL_AUDIODRIVER=dummy` 避免无音频设备的环境初始化失败；
> 进程存活 20 秒即说明 `assets.db` 可读、帧解码成功、托盘与定时器正常。

## 重新构建的完整速查（TL;DR）

```shell
uv run pytest -q                                  # 19 passed
uv run python tools/build_assets_db.py            # 若 assets.db 不存在
rm -rf build dist "$LOCALAPPDATA/pyinstaller"     # 必须！
uv run --with pyinstaller pyinstaller pilot.py --name "原神桌面伙伴" \
    --onedir --noconsole --icon=ico/icon256.ico --noconfirm \
    --add-data "data/config.yaml;data" --add-data "assets.db;." --add-data "kg.db;." \
    --add-data "ico/icon256.ico;." --add-data "data/csv;data/csv"
# → 校验 PYZ-00.toc 与 _internal（步骤 3.1）
"C:\Program Files (x86)\Inno Setup 6\ISCC.exe" setup.iss
```
