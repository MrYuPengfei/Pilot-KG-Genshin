# 原神-桌面伙伴
## 安装包和第知识图谱数据
通过网盘分享的文件：3.8.3
链接: https://pan.baidu.com/s/1xeWh20HxcCA420cVye4A5g?pwd=5tuv 提取码: 5tuv


## 项目名称Pilot-KG-Genshin

pilot (名词)飞行员；（航空器）驾驶员；
pilot (形容词)试验性的；试点的；
KG （KnowledgeGraph）知识图谱;
Genshin （一款游戏）原神；

## 项目介绍

该项目为通用Pilot-KG的前置项目，在不断迭代该项目的过程中，逐渐实现一个跨平台、可以自定义主题和素材、具备知识获取能力和匿名聊天功能的桌面小工具。

打造一个桌面端小助手，通过大规模的文本数据训练原神领域的文本预训练模型， 利用收集到的三元组数据搭建原神知识图谱，通过预训练模型进行语音识别和智能问答，通过语音合成技术来帮助回答用户问题。

当前版本（v3.8）已实现：28 位原神人物的桌面伙伴（逐帧动画、拖动、隐藏）、人物语音与地区背景音乐、SQLite 资源库与帧缓存、第三方素材包导入、图形化管理面板（含知识图谱可视化/编辑、素材导出与配置导入导出）；语音识别与智能问答仍在规划中（见「后期开发」）。

#### 目录结构

```
Pilot-KG-Genshin/
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
│   ├── config.json          出厂配置种子（构建 config.db 用，v3.8 起为 JSON）
│   └── csv/                 知识图谱初始 CSV（27 个，构建 kg.db 用）
|   └── png/、music/         原始素材目录（打包进 assets.db 后可不分发）
├── res/
│   └── help.html          帮助文档（v3.8 外置，启动时动态读取）
├── ico/                     图标（icon256.ico / .bmp、app_icon.ico、logo.ico）
├── tools/                   构建、命令行与数据采集工具
├── tests/                   pytest 测试
...
```

#### 安装教程

A：Terminal/cmd（终端操作）

1. git clone https://github.com/MrYuPengfei/Pilot-KG-Genshin.git 克隆项目。
2. cd Pilot-KG-Genshin 进入目录，使用 `uv sync` 安装依赖。
3. **构建三个数据库**：安装包只带 SQLite 库与 help.html，不含 CSV/JSON 配置——它们是构建输入。运行 `uv run python tools/build_assets_db.py` 与 `uv run python tools/build_databases.py` 生成 `assets.db` / `kg.db` / `config.db`。克隆后的仓库里这三个库都不存在（已入 `.gitignore`），必须先构建。
   随后首次运行会自动生成 `config.db`（有 `data/config.json` 时以其为种子，无则按 `assets.db` 补齐人物登记）；如需修改设置，启动后经托盘「管理面板 → 素材管理」调整即可（也可用该页的「导出/导入配置」备份或迁移，**格式一律为 JSON**）
4. （可选）`uv run python tools/build_assets_db.py` 把 png/、music/ 下的零散资源打包为单个 assets.db；存在数据库时程序自动从数据库读取，否则回退读取目录文件。
5. (1) `uv run python pilot.py` 运行程序<br>
   (2)或直接在PyCharm等编辑器中直接右键运行。
   (3)在终端输入 nohup python -u pilot.py >pet.log 2>&1 & （直接后台运行程序！这样就不用一直开着编辑器了！）

B：Windows 安装包（免环境）
直接运行「桌面伙伴-Pilot安装向导.exe」即可，安装到用户目录（%LOCALAPPDATA%\Programs），无需管理员权限与 Python 环境。安装时可选勾选创建桌面图标与开机自启（默认不勾选）。

项目详细介绍见 [项目详细介绍.md](exhibition/项目详细介绍.md)。

自行打包流程见 [部署到WindowsNT.md](doc/部署到WindowsNT.md)。

![安装模式选择](exhibition/data/Snipaste_2026-10-04_10-53-09.png)

#### 使用说明

1. 基于 PySide6 开发的桌面伙伴-Pilot，内置 28 位人物（可用素材包导入继续扩充）。
2. 程序启动后常驻系统托盘，**托盘图标是唯一入口**：人物、音乐、管理面板、显示、退出都在右键菜单里；桌面窗口可拖动、右键隐藏。
3. 素材（png/gif 已全部转换完成并随仓库上传），克隆后装好依赖即可运行。（仅供开发研究玩乐，请勿当做商业用途！！！）
4. 着实不太建议非社交牛逼症患者在白天以及人多的地方使用，社交牛逼症患者或二刺猿重度患者请自便。
5. *****友情提示：语音默认开启。（上班请静音，小心社死！dddd！）***** 

#### 功能说明

1. 支持人物的切换、拖动、隐藏、简单交互（拖动窗口、点击触发语音等）。
2. 快捷键：
   - Windows：<code>Ctrl + ↑</code> / <code>Ctrl + ↓</code> 缩放人物，<code>Ctrl + Q</code> 退出；
   - macOS：<code>Command + ↑</code> / <code>Command + ↓</code> 缩放人物，<code>Command + Q</code> 退出。
3. 支持背景音乐和人物语音播放，音量可在管理面板或系统音量条调节。
4. 资源管理基于 SQLite 单文件数据库（assets.db）：近万零散资源打包为一个文件，换人物时全帧预加载进内存，动画播放零磁盘 I/O；没有数据库时自动回退读取 png/、music/ 目录。
5. 支持自行添加人物、语音、音乐：把素材按下述布局放成文件夹或 zip，通过托盘菜单「管理面板 → 素材管理」导入，或使用命令行 `uv run python tools/import_assets.py <素材包路径>`，导入后新人物/新地区直接出现在菜单里：

```
素材包/
  png/<人物>/*.png                # 人物帧（逐帧 PNG）
  music/<人物>/*.mp3              # 人物语音，按 早上好/中午好/晚上好/晚安/闲聊*/想要了解* 命名自动分类
  music/<地区>/background.mp3     # 地区背景音乐（目录含 background.mp3 即识别为地区）
```

6. 托盘菜单「管理面板」提供图形化管理：
   - 人物管理：帧预览、按人物调整帧率/缩放（即时生效并保存）、设为当前伙伴、删除人物；
   - 音乐管理：地区背景音乐播放/停止、人物语音开关、一键静音；
   - 素材管理：资源统计、素材包导入、**素材导出**（全部或仅当前人物，目录或 zip，结果可再导入）、配置导出（**仅 JSON**）与导入（覆盖/合并）；
   - 知识图谱：基于 kg.db 的可视化探索与编辑（12 类实体、1900+ 节点、7300+ 关系），支持实体搜索、单击查看属性与关系、双击节点展开关系网；可新增/改名/改类型/改属性/删除实体，以及新增/改名/换对端/删除关系；支持 CSV 目录或单文件导入（合并或覆盖）与按原始布局导出；
   - 帮助文档：素材导入注意事项、版本变更记录、第三方开源库与许可说明。
7. 内置人物（28 位）：七七、优菈、八重神子、刻晴、可莉、夜兰、宵宫、早柚、枫原万叶、珊瑚宫心海、班尼特、琴、甘雨、神里绫人、神里绫华、胡桃、芭芭拉、荒泷一斗、莫娜、菲谢尔、行秋、达达利亚、迪卢克、迪奥娜、钟离、阿贝多、雷电将军、魈；内置背景音乐地区：蒙德、璃月、稻妻。

#### 界面展示

![知识图谱·可莉](exhibition/data/Snipaste_2026-10-04_11-00-37.png)
![知识图谱·关系清单](exhibition/data/Snipaste_2026-10-04_11-01-27.png)
![人物管理](exhibition/data/Snipaste_2026-10-04_10-59-35.png)
![素材管理](exhibition/data/Snipaste_2026-10-04_10-59-43.png)

#### windows任务栏显示菜单

![托盘菜单](exhibition/data/Snipaste_2026-10-04_10-56-03.png)

### 知识图谱设计和展示

#### 节点设计（12类）<br>

人物：character<br>
武器：weapon<br>
神之眼：element<br>
国家：country<br>
地区：area<br>
二级地区：place<br>
材料：material<br>
副本：instance<br>
非玩家角色：npc<br>
怪物：master<br>
料理：food<br>
圣遗物：artifacts<br>

#### 关系设计（14类）<br>

人物-神之眼是-神之眼<br>
人物-特殊料理是-料理<br>
人物-来自-国家<br>
人物-突破材料是-突破材料<br>
人物-圣遗物是-圣遗物<br>
人物-培养材料是-培养材料<br>
人物-武器是-武器<br>
料理-原料是-制作材料<br>
地区-属于-国家<br>
二级地区-属于-地区（暂无）<br>
副本-掉落-圣遗物<br>
副本-掉落-材料<br>
副本-位于-地区<br>
怪物-掉落-材料<br>
武器-突破材料是-材料<br>
![知识图谱设计](exhibition/data/知识图谱.jpg)
![图数据库](exhibition/data/neo4j.png)

#### 版本记录

- **v3.8**：**管理面板新增「窗口与状态」标签页**——原先面板没有任何窗口状态入口（不能最小化、不能最大化），现在最小化、最大化/还原、全屏/退出全屏、隐藏面板与「显示桌面上的伙伴」都在这一页，同页还显示窗口状态、当前伙伴、资源库与版本；另加 `Ctrl+1`~`Ctrl+6` 快速切换六个标签页。面板**不建菜单栏**（功能都在标签页上），同时由 `QDialog` 升级为独立主窗口（`QMainWindow`）——任务栏出现独立图标，可最小化/最大化/还原；点关闭按钮只是隐藏到托盘，不再销毁面板（原先会丢失已填表单并重新加载图谱）。**伙伴本体不再占用任务栏**：窗口改用 `Qt.Tool`（Windows 上映射为 `WS_EX_TOOLWINDOW`），启动后只在系统托盘有图标，任务栏不再出现空占位按钮。**配置导入导出一律改用 JSON**：删除 `export_yaml`、YAML 解析路径与 `PyYAML` 依赖，面板移除「导出 YAML」按钮，配置种子由 `data/config.yaml` 迁为 `data/config.json`；导入 `.yaml/.yml` 会**明确报错**而非静默按 JSON 解析。**帮助文档外置**为 `res/help.html`，启动时动态读取并替换 `{{APP_VERSION}}` 等占位符（双花括号，避免吃掉 CSS），缺文件时回退提示页。**知识图谱改动即时落盘并受升级保护**：图谱的每次增删改本来就在操作当场写入 `kg.db`（补了 6 条「关掉连接重开」的回归测试锁住，避免只查内存索引而漏掉漏提交）；并修掉一个真实问题——**升级安装原本会无条件覆盖 `kg.db`**，把用户编辑的实体与关系清空，现与 `config.db` 一样改为「仅当不存在时才写入」。**卸载向导重做**：卸载前 `taskkill` 结束运行中的进程（原先文件被占用导致删不掉）、`[UninstallDelete]` 增加整目录删除（非空的 `{app}` Inno 不会删，这正是「卸载不干净」的主因）、新增 `[InstallDelete]` 清理旧版残留、卸载时可选保留三个 `.db`（备份到 `%APPDATA%`，静默卸载默认保留）；新增 `AppMutex` 让安装/卸载可靠识别运行中的实例，并配合程序侧单实例互斥量。**显隐状态双向同步**：新增 `Pilot.set_visible()` 作为伙伴显隐的唯一入口，托盘隐藏/显示后「窗口与状态」页里的勾选状态会跟着更新（原先各处分调 `setWindowOpacity`，会导致面板显示过期状态）。启动时做 Python 单实例：重复启动不再出现两个托盘图标互相覆盖配置。
- **v3.7**：**修复「重新构建后图谱编辑丢失」**——根因是打包时用了 `build_databases.py --force`，会用 CSV/YAML 覆盖 `kg.db`/`config.db`，而用户的图谱编辑与设置就在这两个库里；现改为**日常打包不加 `--force`**（库已存在即跳过），且 `--force` 会自动备份到 `*.bak-<时间戳>`。**图谱 CSV 的导入/导出/重新载入移到「素材管理」页**（与素材、配置并列成独立分组），并理顺导入对话框的取消/退出逻辑（原先两层模态框、语义含糊）。**管理面板全页面按钮统一为 132×32**（原先人物页 233/232 差 1px、音乐页与图谱页 640×480）。**消除类型检查器警告**（`db_size_mb`/`db_size_kb` 是 `float | None` 联合类型，直接用格式说明符会报「不支持格式规范」）。此外还修复了图谱双击崩溃、编辑对话框补全 `itemFromIndex(str)` 崩溃、画布 `ungrabMouse` 警告、启动时托盘 `No Icon set`；切换人物时按时段问好（冷却按「同一人 + 同一时段」计）。
- **v3.6**：新增**素材导出**（管理面板「素材管理」页，全部/仅当前人物 × 目录/zip，结果符合素材包格式可再导入）；**修复人物切换异常**（切换后不再被拽回左上角、窗口尺寸正确跟随缩放、大缩放角色不出屏、切换后立即落库），修正动画帧循环跳过首帧与切换时 QLabel 堆积；**修复角色问好**（语音分类器改按关键词识别问候语，菲谢尔/迪奥娜的「早上好问候菲谢尔.mp3」等此前被归为无分类导致早上问候失败；时段表补全 0~3 点与 15~17 点共 7 小时静默；缺语音自动降级；问候只在启动时播一次）；**移除「恢复出厂设置」按钮**（改为删除 config.db 后重装）。
- **v3.5**：数据一律由 SQLite 管理——安装包只带 `assets.db` / `kg.db` / `config.db` 三个库与图标，**不含任何 CSV / YAML**；新增 `tools/build_databases.py` 由 `data/csv`、`data/config.yaml` 构建两个库（CSV/YAML 降级为构建输入）；运行时彻底不读 CSV/YAML（实测删除整个 `data/` 后功能完整）；两个库新增 `schema_version` 与来源元信息、`kg_store` 补 `set_meta/get_meta/info`；`config.db` 以 `onlyifdoesntexist` 安装，升级不覆盖用户配置。此举为后续 C/S 架构预留——服务器下发 CSV/YAML 即可，客户端用现成导入接口入库。
- **v3.4**：目录重构（`src/` → `ico/`、`GenshinKG/data/` → `data/csv/`、`GenshinKG/utils/` 并入 `tools/`，`GenshinKG/` 目录取消）；配置改用 SQLite（新增 `config_store.py` 与 `config.db`，`config.yaml` 移至 `data/config.yaml` 并降级为种子/导入导出格式）；新增配置文件导入导出；配置种子损坏或人物无资源时自动兜底。**`data/` 整个目录不再纳入 git 管理**（含 27 个知识图谱 CSV 与配置种子），新克隆需自行补齐该目录，详见安装教程第 3 步。
- **v3.3**：知识图谱入库（新增 `kg.db`，SQLite 三表；首次运行自动播种，CSV 退化为导入/导出格式）；新增知识图谱 CSV 导入（目录/单文件，合并或覆盖）与导出（可整目录回灌）；新增节点与关系的增删改（改名/改类型/改属性自动迁移关系端点，关系列表区分方向）。
- **v3.2**：文档全面完善（README、部署说明、重构日志、管理面板帮助页）；仓库迁移至 `Pilot-KG-Genshin`；帮助页新增管理面板使用说明。
- **v3.1**：全局更名——「桌面宠物」→「桌面伙伴」，主程序类 `Pet` → `Pilot`，入口脚本 `desktoppet.py` → `pilot.py`，应用名与安装包同步更名；托盘菜单精简。
- **v3.0**：知识图谱可视化（管理面板「知识图谱」页：实体搜索、自我中心网、属性与关系详情、双击展开）。
- **v2.1**：新增管理面板（人物/音乐/素材/帮助文档），设置变更即时保存。
- **v2.0**：SQLite 资源库（assets.db）+ 帧缓存（动画零磁盘 I/O）；第三方素材包导入；全新 Inno Setup 安装包（用户目录安装、免管理员权限）。
- **v1.x**：基础桌面伙伴功能（切换/拖动/隐藏/语音/背景音乐）。

#### 开发与测试

```shell
uv run pytest        # 运行测试套件（资源库、配置、素材导入导出、知识图谱、问候、人物切换、画布与编辑交互等 167 项）
uv run python tools/build_assets_db.py              # 由 png/、music/ 重新构建 assets.db
uv run python tools/build_databases.py              # 生成 kg.db / config.db（库已存在则跳过，保留你的编辑）
uv run python tools/build_databases.py --force      # 强制用 CSV/JSON 重建（会覆盖编辑，先自动备份）
uv run python tools/verify_package.py               # 校验打包产物（文件、三库、help.html、无 CSV/JSON、模块）
uv run python tools/import_assets.py <素材包路径>   # 命令行导入素材包（zip 或目录）
uv run python tools/smoke_kg_panel.py              # 知识图谱面板离屏冒烟（编辑/导入/导出）
uv run python -c "from kg_store import get_default_store; get_default_store()"  # 手动初始化 kg.db
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

1. ✅ 基于原神信息的知识图谱（数据见 `data/csv/`，可视化见管理面板「知识图谱」页）
2. ✅ 基于 RoBERTa 预训练模型对原神数据进行继续预训练（https://gitee.com/fg_slash/GenshinBert ）
3. ❎ 用户语音输入、语音识别、意图识别
4. ❎ 部分人物的语音合成、自动问答
5. ❎ 音量调节面板化（当前依赖系统音量条）

#### 参与贡献

1. 知识一个默默无闻的60级小萌新罢了。
2. 原项目：https://github.com/fg0521/Genshin-Impact-Desktoppet.git
3. 绿幕素材来源于B站UP:皮皮虾米锅巴
4. 知识图谱数据与设计参考 `data/csv/` 目录及 `doc/知识图谱.jpg`

## 许可协议

本项目源码以 **Apache License 2.0** 开源（详见 [LICENSE](LICENSE)）。
游戏图像、语音等素材版权归上海米哈游网络科技股份有限公司所有，
仅供学习交流，请勿用于商业用途。
