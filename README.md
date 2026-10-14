# Pilot

## 项目名称 Pilot

pilot (名词)飞行员；（航空器）驾驶员；

pilot (形容词)试验性的；试点的；

KG （KnowledgeGraph）知识图谱;

## 项目介绍

该项目为通用 Pilot-KG 的前置项目，在不断迭代该项目的过程中，逐渐实现一个跨平台、可以自定义主题和素材、具备知识获取能力的桌面小工具。、配置管理）。

#### 目录结构

```
Pilot/
├── pilot.py                 主程序（入口，含托盘菜单与动画主循环）
├── manager_panel.py         管理面板（QMainWindow 主窗口，任务栏独立图标）
├── resource_store.py        资源访问抽象层（优先 assets.db，回退文件系统）
├── config_store.py          配置存储层（config.db 持久化 + 导入导出）
├── asset_exporter.py        素材导出（assets.db → png/ 与 music/ 目录或 zip）
├── asset_importer.py        第三方素材包导入核心
├── kg_store.py              知识图谱存储层（kg.db 持久化 + CSV 导入导出 + 增删改）
├── kg_editor.py             知识图谱编辑对话框（实体属性表 / 关系两端选择）
├── kg_view.py               知识图谱可视化组件（自我中心网画布）
├── assets.db                资源数据库（由 tools/build_assets_db.py 构建）
├── kg.db                    知识图谱数据库（由 tools/build_databases.py 构建）
├── config.db                出厂配置 + 用户本机设置（同一文件）
├── data/                    ⚠️ 仅构建输入：既不入 git、也不随安装包分发
│   ├── config.json          出厂配置种子（构建 config.db 用）
│   ├── csv-edu/             知识图谱初始 CSV（9 个，本构建的图谱来源）
│   └── 桌面伙伴素材/         素材包（png/ 序列帧 + music/ 地区 BGM）
├── res/                     资源（help.html 帮助文档、icon256.ico 图标）
├── setup.iss                Inno Setup 安装脚本（版本号三处同步点之一）
├── Pilot.spec              PyInstaller 打包配置
├── tools/                   构建、命令行与数据加工工具
├── tests/                   pytest 测试
├── exhibition/              各版本的项目详细介绍与配图
├── doc/                     部署说明、重构日志、知识图谱设计稿
...
```

#### 安装教程
 

A：Terminal/cmd（终端操作，需源码授权）

1. 获取源码后进入项目目录，使用 `uv sync` 安装依赖。
2. **构建三个数据库**：安装包只带 SQLite 库与 help.html，不含 CSV/JSON 配置——它们是构建输入。运行 `uv run python tools/build_assets_db.py` 与 `uv run python tools/build_databases.py` 生成 `assets.db` / `kg.db` / `config.db`。这三个库已入 `.gitignore`，必须先构建。
     
   随后首次运行会自动生成 `config.db`（有 `data/config.json` 时以其为种子，无则按 `assets.db` 补齐人物登记）；如需修改设置，启动后经托盘「管理面板 → 素材管理」调整即可（也可用该页的「导出/导入配置」备份或迁移，**格式一律为 JSON**）
3. `uv run python pilot.py` 运行程序（也可在编辑器中直接运行）。

B：Windows 安装包（免环境）

直接运行「Pilot安装向导.exe」即可，安装到用户目录（%LOCALAPPDATA%\Programs），无需管理员权限与 Python 环境。安装时可选勾选创建桌面图标与开机自启（默认不勾选）。

自行打包流程见 [部署到WindowsNT.md](doc/部署到WindowsNT.md)。

#### 使用说明

1. 基于 PySide6 开发的桌面伙伴 Pilot，内置 9 个动画角色与 7 个地区背景音乐（可用素材包导入继续扩充）。
2. 程序启动后常驻系统托盘，**托盘图标是唯一入口**：人物、音乐、管理面板、显示、退出都在右键菜单里；桌面窗口可拖动、右键隐藏。
3. 内置素材均来自**已获授权的第三方素材包**（CC0 / CC-BY 等），来源与协议见 [CREDITS.md](CREDITS.md)。自行添加素材时请同样使用有授权的素材。
4. ***友情提示：语音默认开启。（上班请静音，小心社死！dddd！）***

#### 功能说明

1. 支持人物的切换、拖动、隐藏、简单交互（拖动窗口、点击触发语音等）。
2. 快捷键：
   - Windows：<code>Ctrl + ↑</code> / <code>Ctrl + ↓</code> 缩放人物，<code>Ctrl + Q</code> 退出；
   - macOS：<code>Command + ↑</code> / <code>Command + ↓</code> 缩放人物，<code>Command + Q</code> 退出。
3. 支持背景音乐和人物语音播放，音量可在管理面板或系统音量条调节。
4. 资源管理基于 SQLite 单文件数据库（assets.db）：近万零散资源打包为一个文件，换人物时全帧预加载进内存，动画播放零磁盘 I/O；没有数据库时自动回退读取 png/、music/ 目录。
5. 支持自行添加人物、语音、音乐：把**已获授权的**素材按下述布局放成文件夹或 zip，通过托盘菜单「管理面板 → 素材管理」导入，或使用命令行 `uv run python tools/import_assets.py <素材包路径>`，导入后新人物/新地区直接出现在菜单里：

```
素材包/
  png/<人物>/*.png                # 人物帧（逐帧 PNG）
  apng/<人物>/*.png               # APNG 动画（自带帧时长与循环，优先于 png）
  music/<人物>/*.mp3              # 人物语音，按 早上好/中午好/晚上好/晚安/闲聊*/想要了解* 命名自动分类
  music/<地区>/background.mp3     # 地区背景音乐（目录含 background.mp3 即识别为地区）
```

⚠️ 目录约定本身就是语义：`music/<人物>/闲聊*.mp3` 是角色语音，`music/<地区>/background.mp3` 才是地区背景音乐，**改名会改变素材的播放入口**。

6. 托盘菜单「管理面板」提供图形化管理：
   - 人物管理：帧预览、按人物调整帧率/缩放（即时生效并保存）、设为当前伙伴、删除人物；
   - 音乐管理：地区背景音乐播放/停止、人物语音开关、一键静音；
   - 素材管理：资源统计、素材包导入、**素材导出**（全部或仅当前人物，目录或 zip，结果可再导入）、配置导出（**仅 JSON**）与导入（覆盖/合并）；
   - 知识图谱：基于 kg.db 的可视化探索与编辑（3 类实体、1297 节点、5913 关系），支持实体搜索、单击查看属性与关系、双击节点展开关系网；可新增/改名/改类型/改属性/删除实体，以及新增/改名/换对端/删除关系；支持 CSV 目录或单文件导入（合并或覆盖）与按原始布局导出；
   - 帮助文档：素材导入注意事项、版本变更记录、**完整的许可协议说明**、第三方开源库与素材授权。
7. 内置动画角色（9 个）：Cube、Disk、Dual Ball、Spinner（含 5 个规格变体）；内置背景音乐地区（7 个）：Crystal Cave、Cyberpunk Moonlight Sonata、Dripping water loop、Enchanted Tiki 86、Next to You、The Field Of Dreams、Town Theme RPG。

#### 界面展示

![知识图谱·实体关系](exhibition/v3.2/data/Snipaste_2026-10-04_11-00-37.png)

![知识图谱·关系清单](exhibition/v3.2/data/Snipaste_2026-10-04_11-01-27.png)

![人物管理](exhibition/v3.2/data/Snipaste_2026-10-04_10-59-35.png)

![素材管理](exhibition/v3.2/data/Snipaste_2026-10-04_10-59-43.png)

#### windows任务栏显示菜单

![托盘菜单](exhibition/v3.2/data/Snipaste_2026-10-04_10-56-03.png)

### 知识图谱设计和展示

#### 实体设计（3 类）

图谱数据来自 `data/csv-edu/`，覆盖教育 / AI / 数据库三个领域：

| 类型键 | 中文名 | 节点数 |
|---|---|---|
| `education` | 教育领域 | 776 |
| `ai` | AI领域 | 315 |
| `database` | 数据库领域 | 206 |

合计 **1297 个实体**。实体表的统一列约定见 `tools/unify_entity_headers.py`：

| 列名 | 含义 |
|---|---|
| `name` | **实体主键**（英文名；暂无官方译名时回退 `name_cn`） |
| `name_cn` | 中文名（供展示与中文搜索） |
| `label` | 类型键（`ai` / `education` / `database`） |
| `label_cn` | 类型中文名，仅作展示 |

⚠️ **主键必须是 `name` 而不是 `name_cn`**：中文名不唯一——库里有 11 组同中文名
（如 `RLHF` 与 `reinforcement learning from human feedback` 共用
「基于人类反馈的强化学习」）。拿中文名当主键会让同一概念裂成多个实体，
实测节点数 732→1392 翻倍、关系数 1063→784 骤降（端点解析失败退化成桩）。

#### 关系设计（324 个关系名 / 5913 条关系）

关系表 `rel-*.csv` 三列约定：`名称A, 关系名, 名称B`，引用的是**中文名**，
故导入时端点解析会同时匹配 `name` 与 `name_cn`。

高频关系举例：

| 关系名 | 条数 | 含义 |
|---|---|---|
| `part_of` | 518 | 是……的一部分 |
| `enables` | 483 | 使……成为可能 |
| `related_to` | 424 | 相关 |
| `contrasts_with` | 386 | 与……形成对比 |
| `supports` | 247 | 支持 |
| `requires` | 226 | 需要 |
| `uses` | 173 | 使用 |
| `measured_by` | 151 | 由……度量 |
| `instance_of` | 146 | 是……的实例 |
| `informs` | 132 | 为……提供依据 |

关系中文名是**数据**而不是代码常量：存在 `kg_rel_names` 表里，随 CSV 导入导出往返，
新增关系只需改 CSV，不必动 `kg_store.py`。

#### 版本记录

- **v3.8**：**管理面板新增「窗口与状态」标签页**——原先面板没有任何窗口状态入口（不能最小化、不能最大化），现在最小化、最大化/还原、全屏/退出全屏、隐藏面板与「显示桌面上的伙伴」都在这一页，同页还显示窗口状态、当前伙伴、资源库与版本；另加 `Ctrl+1`~`Ctrl+6` 快速切换六个标签页。面板**不建菜单栏**（功能都在标签页上），同时由 `QDialog` 升级为独立主窗口（`QMainWindow`）——任务栏出现独立图标，可最小化/最大化/还原；点关闭按钮只是隐藏到托盘，不再销毁面板（原先会丢失已填表单并重新加载图谱）。**伙伴本体不再占用任务栏**：窗口改用 `Qt.Tool`（Windows 上映射为 `WS_EX_TOOLWINDOW`），启动后只在系统托盘有图标，任务栏不再出现空占位按钮。**配置导入导出一律改用 JSON**：删除 `export_yaml`、YAML 解析路径与 `PyYAML` 依赖，面板移除「导出 YAML」按钮，配置种子由 `data/config.yaml` 迁为 `data/config.json`；导入 `.yaml/.yml` 会**明确报错**而非静默按 JSON 解析。**帮助文档外置**为 `res/help.html`，启动时动态读取并替换 `{{APP_VERSION}}` 等占位符（双花括号，避免吃掉 CSS），缺文件时回退提示页。**知识图谱改动即时落盘并受升级保护**：图谱的每次增删改本来就在操作当场写入 `kg.db`（补了 6 条「关掉连接重开」的回归测试锁住，避免只查内存索引而漏掉漏提交）；并修掉一个真实问题——**升级安装原本会无条件覆盖 `kg.db`**，把用户编辑的实体与关系清空，现与 `config.db` 一样改为「仅当不存在时才写入」。**卸载向导重做**：卸载前 `taskkill` 结束运行中的进程（原先文件被占用导致删不掉）、`[UninstallDelete]` 增加整目录删除（非空的 `{app}` Inno 不会删，这正是「卸载不干净」的主因）、新增 `[InstallDelete]` 清理旧版残留、卸载时可选保留三个 `.db`（备份到 `%APPDATA%`，静默卸载默认保留）；新增 `AppMutex` 让安装/卸载可靠识别运行中的实例，并配合程序侧单实例互斥量。**显隐状态双向同步**：新增 `Pilot.set_visible()` 作为伙伴显隐的唯一入口，托盘隐藏/显示后「窗口与状态」页里的勾选状态会跟着更新（原先各处分调 `setWindowOpacity`，会导致面板显示过期状态）。启动时做 Python 单实例：重复启动不再出现两个托盘图标互相覆盖配置。
- **v3.7**：**修复「重新构建后图谱编辑丢失」**——根因是打包时用了 `build_databases.py --force`，会用 CSV/YAML 覆盖 `kg.db`/`config.db`，而用户的图谱编辑与设置就在这两个库里；现改为**日常打包不加 `--force`**（库已存在即跳过），且 `--force` 会自动备份到 `*.bak-<时间戳>`。**图谱 CSV 的导入/导出/重新载入移到「素材管理」页**（与素材、配置并列成独立分组），并理顺导入对话框的取消/退出逻辑（原先两层模态框、语义含糊）。**管理面板全页面按钮统一为 132×32**（原先人物页 233/232 差 1px、音乐页与图谱页 640×480）。**消除类型检查器警告**（`db_size_mb`/`db_size_kb` 是 `float | None` 联合类型，直接用格式说明符会报「不支持格式规范」）。此外还修复了图谱双击崩溃、编辑对话框补全 `itemFromIndex(str)` 崩溃、画布 `ungrabMouse` 警告、启动时托盘 `No Icon set`；切换人物时按时段问好（冷却按「同一人 + 同一时段」计）。
- **v3.6**：新增**素材导出**（管理面板「素材管理」页，全部/仅当前人物 × 目录/zip，结果符合素材包格式可再导入）；**修复人物切换异常**（切换后不再被拽回左上角、窗口尺寸正确跟随缩放、大缩放角色不出屏、切换后立即落库），修正动画帧循环跳过首帧与切换时 QLabel 堆积；**修复角色问好**（语音分类器改按关键词识别问候语，菲谢尔/迪奥娜的「早上好问候菲谢尔.mp3」等此前被归为无分类导致早上问候失败；时段表补全 0~~3 点与 15~~17 点共 7 小时静默；缺语音自动降级；问候只在启动时播一次）；**移除「恢复出厂设置」按钮**（改为删除 config.db 后重装）。
- **v3.5**：数据一律由 SQLite 管理——安装包只带 `assets.db` / `kg.db` / `config.db` 三个库与图标，**不含任何 CSV / YAML**；新增 `tools/build_databases.py` 由图谱 CSV、`data/config.json` 构建两个库（CSV/YAML 降级为构建输入）；运行时彻底不读 CSV/YAML（实测删除整个 `data/` 后功能完整）；两个库新增 `schema_version` 与来源元信息、`kg_store` 补 `set_meta/get_meta/info`；`config.db` 以 `onlyifdoesntexist` 安装，升级不覆盖用户配置。此举为后续 C/S 架构预留——服务器下发 CSV/YAML 即可，客户端用现成导入接口入库。
- **v3.4**：目录重构（`src/` → `ico/`、数据目录统一到 `data/`、数据加工脚本并入 `tools/`）；配置改用 SQLite（新增 `config_store.py` 与 `config.db`，`config.yaml` 移至 `data/config.yaml` 并降级为种子/导入导出格式）；新增配置文件导入导出；配置种子损坏或人物无资源时自动兜底。**`data/` 整个目录不再纳入 git 管理**（含 27 个知识图谱 CSV 与配置种子），新克隆需自行补齐该目录，详见安装教程第 3 步。
- **v3.3**：知识图谱入库（新增 `kg.db`，SQLite 三表；首次运行自动播种，CSV 退化为导入/导出格式）；新增知识图谱 CSV 导入（目录/单文件，合并或覆盖）与导出（可整目录回灌）；新增节点与关系的增删改（改名/改类型/改属性自动迁移关系端点，关系列表区分方向）。
- **v3.2**：文档全面完善（README、部署说明、重构日志、管理面板帮助页）；帮助页新增管理面板使用说明。
- **v3.1**：全局更名——「桌面宠物」→「桌面伙伴」，主程序类 `Pet` → `Pilot`，入口脚本 `desktoppet.py` → `pilot.py`，应用名与安装包同步更名；托盘菜单精简。
- **v3.0**：知识图谱可视化（管理面板「知识图谱」页：实体搜索、自我中心网、属性与关系详情、双击展开）。
- **v2.1**：新增管理面板（人物/音乐/素材/帮助文档），设置变更即时保存。
- **v2.0**：SQLite 资源库（assets.db）+ 帧缓存（动画零磁盘 I/O）；第三方素材包导入；全新 Inno Setup 安装包（用户目录安装、免管理员权限）。
- **v1.x**：基础桌面伙伴功能（切换/拖动/隐藏/语音/背景音乐）。

#### 开发与测试

```shell
uv run pytest        # 运行测试套件（资源库、配置、素材导入导出、知识图谱、问候、人物切换、画布与编辑交互等 274 项）
uv run python tools/build_assets_db.py              # 由 png/、music/ 重新构建 assets.db
uv run python tools/build_databases.py              # 生成 kg.db / config.db（库已存在则跳过，保留你的编辑）
uv run python tools/build_databases.py --force      # 强制用 CSV/JSON 重建（会覆盖编辑，先自动备份）
uv run python tools/build_data_pack.py              # 打包 data/ 供他人补齐构建输入
uv run python tools/verify_package.py               # 校验打包产物（文件、三库、help.html、无 CSV/JSON、模块）
uv run python tools/import_assets.py <素材包路径>   # 命令行导入素材包（zip 或目录）
uv run python tools/smoke_kg_panel.py              # 知识图谱面板离屏冒烟（编辑/导入/导出）
uv run python tools/check_kg_upgrade.py            # 检查图谱库版本与结构是否需要迁移
uv run python -c "from kg_store import get_default_store; get_default_store()"  # 手动初始化 kg.db
```


```

新增素材后需重跑一次 `build_assets_db.py` 才会进数据库；也可直接在管理面板导入（增量 upsert，不必重建）。

> ⚠️ **打包时不要给 `build_databases.py` 加 `--force`**：`kg.db` / `config.db` 既是出厂产物
> 又是你的本机状态（新增的图谱实体、改过的名字、调好的帧率缩放都在里面），
> `--force` 会用 `data/csv`、`data/config.json` 静默覆盖它们。
> 日常直接跑 `build_databases.py` 即可——库已存在时它只检查不重建。

GUI 冒烟测试（无显示环境）：

```shell
QT_QPA_PLATFORM=offscreen SDL_AUDIODRIVER=dummy uv run python pilot.py
```

#### 规划中

1. ✅ 教育 / AI 领域知识图谱（数据见 `data/csv-edu/`，可视化见管理面板「知识图谱」页）
2. ✅ APNG 动画格式的导入与导出（自带帧时长与循环，优先于逐帧 PNG）
3. ❎ 用户语音输入、语音识别、意图识别
4. ❎ 部分人物的语音合成、自动问答
5. ❎ 音量调节面板化（当前依赖系统音量条）


### 第三方组件与素材

| 库 | 用途 | 许可证 |
|---|---|---|
| PySide6 (Qt for Python) | 窗口、托盘、管理面板等全部 GUI | LGPLv3 |
| pygame-ce | 语音与背景音乐播放 | LGPLv2.1 |
| SQLite（Python 内置 sqlite3） | 素材 / 配置 / 知识图谱三个数据库 | Public Domain |
| pytest（开发依赖） | 自动化测试 | MIT |
| PyInstaller（打包工具） | 生成 Windows 可执行程序 | GPL（打包产物不受限） |
| Inno Setup（打包工具） | 生成安装向导 | Inno Setup License |

内置**素材**均来自已获授权的第三方素材包（CC0 / CC-BY 等），
逐项目来源与协议见 [CREDITS.md](CREDITS.md)。其中 CC-BY-SA / GPL 素材
（如 LPC 精灵表）**必须随分发附带署名文件** `CREDITS.csv`。

自行导入的素材由使用者自行负责，请勿分发侵犯第三方版权的内容。

## 后续开发计划
1. 支持个性化UI、支持QSS，实现炫酷的前端界面。
2. 支持端侧Agent，调用Hermes API。
3. 支持与智能助手/桌面伙伴的动作交换，一些类似于QQ宠物的小游戏。
4. 支持apng格式的导入，提高加载素材的速度，减少零碎文件。
5. 支持矢量化的角色导入，无损放大和缩小人物。（备注：有点难实现）
6. 支持更多的图功能。
7. 支持客户端的动态更新和资源动态下载，按需从服务器（CDN）下载自己感兴趣的素材。
8. 支持P2P通讯，实现与其他客户端的匿名通讯。（备注：技术上可行，但通常有法律风险）
9. 支持Beta和Stable分支的发布，构建良好的技术交流社区。（备注：需要比较高的社区热度）