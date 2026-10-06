# PySide6 重构日志

本日志按增量步骤记录从 PyQt5 到 PySide6 的迁移过程。每一步都包含修改范围和紧随其后的验证结果。

## 第 0 步：建立基线并迁移依赖声明

- 状态：已完成
- 修改：将运行依赖移入 `pyproject.toml`，增加 `PySide6`、`PyYAML`、`pygame` 和开发依赖 `pytest`；更新 `requirements.txt`，不再声明 PyQt5。
- 基线验证：`uv lock` 通过；`python -m compileall -q pilot.py src tools GenshinKG` 通过。
- 基线备注：现有代码仍导入 PyQt5；编译阶段发现项目其他脚本已有无效转义序列警告，暂不属于本次迁移范围。

## 第 1 步：迁移 Qt 导入和 Qt6 API

- 状态：已完成
- 修改：将入口模块的 Qt 导入替换为 PySide6；迁移 `QAction` 所属模块、主屏幕查询、鼠标全局坐标、枚举值、菜单执行和应用事件循环；移除未使用的 `PyQt5.sip`。
- 修改：将 `pygame.mixer` 初始化移入 `Pet` 初始化，允许测试导入纯函数而不启动音频设备。
- 测试：`uv run pytest -q` 通过，1 passed；`uv run python -m compileall -q pilot.py tests` 通过；Pylance 文件语法检查通过。
- 测试备注：首次 pytest 收集失败是仓库根目录未进入测试模块搜索路径，新增 `tests/conftest.py` 后重跑通过。
- 文档：更新 README 和备用依赖清单中的 PySide6、uv 安装与运行方式。

## 最终验证

- `uv lock --check`：通过。
- `uv run pytest -q`：通过，1 passed。
- `uv run python -m compileall -q pilot.py tests`：通过。
- PySide6 QApplication/QAction 运行时烟雾测试：通过。
- 项目源码、README 和依赖声明中的 PyQt5 残留扫描：通过；本日志保留历史迁移记录中的 `PyQt5` 文本。
- 环境备注：默认源和备用源均使 `pygame==2.6.1` 在 Python 3.14 上进入源码构建并长时间停滞；改用兼容同一 `pygame` 导入接口的 `pygame-ce`，以获得可安装的 Python 3.14 wheel。

## 第 2 步：SQLite 资源库与动画帧缓存

- 状态：已完成
- 背景：项目资源为约 9800 个零散文件（9476 帧 PNG + 344 条 MP3，合计约 470MB），分发与备份不便；且原实现每个动画帧（60~80ms 一次）都执行一次磁盘读取 + PNG 解码 + 缩放，CPU 与磁盘 I/O 持续空转。
- 新增 `tools/build_assets_db.py`：扫描 `png/`、`music/`，把帧、语音（按文件名归类 greeting/chat/know）、区域 BGM 导入单文件 `assets.db`（表 `assets(role, kind, name, category, data)`）；本次构建 9820 条、459.5MB，耗时约 14 秒。
- 新增 `resource_store.py`：`ResourceStore` 统一资源入口，存在 `assets.db` 时用 SQLite 后端，否则自动回退文件系统；对上层只暴露字节流与名称列表。
- 修改 `pilot.py`：帧、语音、BGM 全部改走 `ResourceStore`（`QPixmap.loadFromData`、`mixer.Sound(file=BytesIO)`、`mixer.music.load(BytesIO)`，BGM 流持有引用防回收）；切换角色时一次性预加载并预缩放全部帧（含 mask 缓存），`act()` 变为纯内存切换；Ctrl +/- 缩放后重建缓存；顺带修复托盘图标依赖磁盘路径、`BASE_DIR` 重复拼接、`role_audio` 死代码与大段注释死代码。
- 性能实测：达达利亚 219 帧从 DB 解码 + 缩放的一次性成本约 0.5 秒（2.3ms/帧），此前同等开销每帧重复发生。
- 测试：新增 `tests/test_resource_store.py`（文件系统与 SQLite 后端一致性、语音分类、缺键异常），`uv run pytest -q` 4 passed；`compileall` 通过；离屏 Qt 烟雾测试通过；DB 抽样字节与磁盘文件 MD5 一致。
- 备注：数据库核实全库共 28 个角色，与托盘菜单一一对应；`assets.db` 为生成物，已加入 `.gitignore`。

## 第 3 步：第三方素材导入模块与动态菜单

- 状态：已完成
- 背景：原人物/地区菜单在代码中硬编码，新增角色需要改代码；用户需要导入自定义人物和地区的第三方素材。
- 新增 `asset_importer.py`：素材包（目录或 zip，沿用 `png/<人物>`、`music/<人物>`、`music/<地区>/background.mp3` 布局）导入 `assets.db`，同名资源覆盖更新；地区识别规则从硬编码三地泛化为「目录含 background.mp3 即为地区」；新人物自动在 `config.yaml` 的 `frame_scale` 登记默认值 `[60, 1.0]`。
- 新增 `tools/import_assets.py`：命令行导入入口。
- 修改 `pilot.py`：人物菜单（约 110 行硬编码 QAction）与音乐菜单改为按 `ResourceStore` 动态生成；`set_audio` 泛化为支持任意地区；托盘新增「导入素材包」入口，运行中导入后菜单即时刷新；`ResourceStore` 新增 `list_bgm_areas()`；`reshow` 对未登记角色做 `setdefault` 容错；右键语音菜单增加空列表保护。
- 修复边界 bug：单帧角色在 `init_window`/`act` 中索引越界（`IndexError`），旧代码同样存在此隐患，第三方素材（常见单帧）使其暴露；现对索引做钳制。
- 测试：新增 `tests/test_asset_importer.py`（目录/zip 导入、幂等覆盖、config 登记、空包与缺失路径异常），`uv run pytest -q` 9 passed；离屏 + 哑音频驱动的端到端烟雾测试通过（动态菜单 28 角色、导入后新角色/新地区即时出现、单帧角色切换正常）；烟雾测试均在临时 DB 副本上进行，真实库已验证无残留。

## 第 4 步：重写安装脚本（setup.iss）并验证完整安装链路

- 状态：已完成
- 背景：2.0 起资源收进单个 `assets.db`，旧安装脚本（1.1）存在多个问题：无 `AppId`（升级/卸载无法正确注册）；默认装到 `{commonpf}`（Program Files），程序运行时写 `config.yaml`/`assets.db` 会因权限不足失败；欢迎页弹 MsgBox 影响体验；无卸载图标与可选快捷方式。
- 重写 `setup.iss`：固定 `AppId` GUID；版本号 2.0；默认安装到 `{localappdata}\Programs\原神桌面伙伴`（每用户、免管理员、程序可写自身文件），`PrivilegesRequired=lowest`（保留 dialog 允许覆盖）；仅限 64 位；`CloseApplications` 自动关闭运行中的伙伴以支持覆盖安装；可选桌面图标与开机自启任务；卸载显示图标与开始菜单卸载项；压缩改 `lzma2/normal`（资源本身已压缩，平衡体积与构建速度）；移除欢迎页 MsgBox。
- 更新 `部署到WindowsNT.md`：PyInstaller 命令从 50+ 条 `--add-data` 简化为只带 `config.yaml`、`assets.db`、`icon256.ico` 三项。
- 验证（全链路实测）：`uv run --with pyinstaller pyinstaller` onedir 打包成功（dist 592M，`_internal/assets.db` 462M 就位）；`ISCC.exe setup.iss` 编译成功（133 秒）；安装向导静默安装到默认用户目录成功，文件布局与可写性验证通过；静默卸载因会话子进程回收被中断（非安装包问题），残留目录已手动清理。
- 产物：`inno_build/原神桌面伙伴安装向导.exe`（480M）；`build/`、`dist/`、`inno_build/`、`*.spec` 已加入 `.gitignore`。

## 第 5 步：管理面板（版本 2.1）

- 状态：已完成
- 新增 `manager_panel.py`：托盘菜单「管理面板」打开的单例对话框，三个标签页——
  - 人物管理：角色列表 + 首帧预览 + 帧/语音数量；按角色调整帧间隔与缩放（当前角色即时生效并持久化）；设为当前伙伴；删除人物（确认后从 assets.db 移除并同步菜单，至少保留一个）。
  - 音乐管理：地区 BGM 播放/停止、人物语音开关、一键静音，与托盘音乐菜单状态双向同步。
  - 素材管理：后端/角色/地区/帧/语音/DB 大小统计；zip 或目录导入素材包。
- `pilot.py` 新增面板支撑接口：`open_manager`/`on_manager_closed`、`save_config`、`set_role_timing`、`play_area_bgm`/`stop_bgm`/`set_voice_enabled`、`import_from_path`（托盘导入入口复用）；`quit` 改走 `save_config`。
- `resource_store.py` 新增 `stats()`、`delete_role()`、`delete_area()`（删除仅 sqlite 后端）。
- 测试：`test_resource_store.py` 增加统计与删除用例，pytest 12 passed；离屏烟雾测试覆盖面板三个标签页核心操作（预览刷新、设置即时生效、BGM/语音控制、统计、删除同步、单例释放），真实 config.yaml 以快照-恢复方式保护。
- 版本号：`setup.iss` 与 `pyproject.toml` 升至 2.1；PyInstaller + Inno 重新构建安装包。

## 第 5.1 步：管理面板帮助文档页（2.1 补充）

- 状态：已完成
- 新增：管理面板第四个标签页「帮助文档」（`QTextBrowser` 渲染内置 HTML，链接由系统浏览器打开），内容包括——
  - 导入素材注意事项：素材包布局、语音命名分类规则、地区识别规则（含 background.mp3 即地区）、同名覆盖、新人物默认值、版权提醒；
  - 版本变更记录：v1.1 / v2.0 / v2.1；
  - 第三方开源库清单：PySide6（LGPLv3）、pygame-ce（LGPLv2.1）、PyYAML（MIT）、SQLite（Public Domain）、pytest（MIT）、PyInstaller（GPL）、Inno Setup；
  - 开源地址 https://github.com/MrYuPengfei/Pilot-KG-Genshin.git 。
- 面板窗口标题改为带版本号（`APP_VERSION` 常量统一维护）。
- 测试：离屏烟雾测试校验四个标签页存在、帮助页四个内容板块与开源地址齐全、外链可点击；安装包已重新构建（PYZ 校验含 manager_panel）。
## 版本 3.0：知识图谱可视化（2026-10-04）

- 状态：已完成
- 新增 `kg_store.py`：加载 GenshinKG/data 的 12 类节点（label-*.csv）与 11 种关系（rel-*.csv），构建名称索引与无向邻接表；实测 1911 节点、7511 边。要点——
  - 关系两端按名称解析，文件名仅作类型提示（rel-country-area.csv 实际方向是 地区→国家）；
  - 过滤「暂无/无」等垃圾节点与自环；标签文件缺失的实体按类型提示建桩节点；
  - 提供 stats / find / search（前缀优先）/ neighbors / ego_network 查询。
- 新增 `kg_view.py`：QGraphicsView 自我中心网画布——中心节点 + 邻居放射布局（半径随邻居数自适应）、12 类节点着色、边中点标注关系名、单击选中、双击展开、滚轮缩放、ScrollHandDrag 平移。
- 管理面板新增「知识图谱」标签页：搜索框（QCompleter 全名补全）+ 类型图例 + 画布/详情分割布局；详情页展示节点属性表与关系清单；图谱数据首次切到该页时才加载（懒加载），不拖慢面板启动。面板默认尺寸调大到 960x620。
- 托盘菜单移除「导入素材包」入口及 `import_pack()` 死方法（素材导入统一走管理面板），帮助文档相关描述同步更新；管理面板增加窗口图标（沿用当前伙伴当前帧，与托盘一致）。
- 版本号：`manager_panel.APP_VERSION`、`setup.iss`、`pyproject.toml` 升至 3.0；帮助页版本记录补充 v3.0。
- 打包：PyInstaller 命令新增 `--add-data "GenshinKG/data;GenshinKG/data"`，部署文档同步。
- 测试：新增 `tests/test_kg_store.py` 7 项（加载统计、邻居关系、关系方向解析、垃圾节点过滤、搜索、自我中心网、缺失目录异常），`uv run pytest -q` 19 passed；离屏烟雾测试覆盖懒加载、搜索定位出图、详情面板、双击展开、空结果处理。

## 版本 3.1：全局更名 宠物 → 伙伴（2026-10-04）

- 状态：已完成
- 代码：`pilot.py` 主类 `Pet` → `Pilot`（含 `super()` 与 `__main__` 实例化）；托盘人物菜单属性 `self.pets` → `self.partners`。
- 代码：`manager_panel.py` 构造参数与属性 `pet` → `pilot`（25 处），面板标题与帮助文档文案同步更名。
- 文案：全项目「宠物」→「伙伴」（应用名 原神桌面宠物 → 原神桌面伙伴、设为当前宠物 → 设为当前伙伴、安装向导名等），涉及 `pilot.py` / `manager_panel.py` / `setup.iss` / `README.md` / `REFACTORING_LOG.md` / `部署到WindowsNT.md`。
- 版本号：`manager_panel.APP_VERSION`、`setup.iss`、`pyproject.toml` 升至 3.1；帮助页版本记录补充 v3.0 / v3.1 两条。
- 打包：PyInstaller `--name` 与 `setup.iss`（AppName/AppExeName/OutputBaseFilename/Source 路径）同步更名；删除过期的 `原神桌面宠物.spec`。
- 注意：`AppId` GUID 保持不变（同一应用、可覆盖升级），但安装目录随 AppName 变为 `%LOCALAPPDATA%\Programs\原神桌面伙伴`，旧目录不会自动删除。
- 测试：`uv run pytest -q` 19 passed；离屏烟雾测试确认类名 Pilot、托盘菜单与人物菜单（28 项）正常、管理面板五个标签页、知识图谱检索、角色切换均正常。

## 版本 3.1 补充：入口脚本更名与仓库迁移（2026-10-04）

- 状态：已完成
- 代码：`desktoppet.py` → **`pilot.py`**（`git mv` 保留历史）；测试 `tests/test_desktoppet.py` → `tests/test_pilot.py`；删除过期 spec 文件（原神桌面伙伴.spec / 原神桌面宠物.spec，均由 PyInstaller 重新生成，不需要入库）。
- 引用更新：`setup.iss` 与 `部署到WindowsNT.md` 的 pyinstaller 入口、`README.md` 运行命令、`REFACTORING_LOG.md` 历史条目、`resource_store.py` 文档串、`pyproject.toml` 包名（yuanshen-desktoppet → pilot）。
- 仓库迁移：GitHub 仓库由 `MrYuPengfei/yuanshen-desktoppet` 改为 **`MrYuPengfei/Pilot-KG-Genshin`**；本地 `origin` 与 `github` 两个 remote 均已指向新地址。同步更新位置——`manager_panel.py`（帮助页 REPO_URL / REPO_PAGE 常量）、`README.md`（clone 地址与 `cd` 目录名）、`setup.iss`（AppURL，原为 gitee 旧地址一并修正）、`REFACTORING_LOG.md`。
- 陷阱：批量替换仓库地址时，gitee 旧地址以 `https://gitee.com/...` 形式硬编码在 `setup.iss` 的 AppURL 中，替换后短暂产生 `https://https://github.com/...` 双重前缀，已修正为单层 https。
- 测试：`uv run pytest -q` 19 passed；`uv lock` 刷新；离屏烟雾测试确认——入口 `from pilot import Pilot` 正常、类名 Pilot、托盘菜单五项、人物菜单 28 项、管理面板五标签页、面板图标非空、帮助页新地址可点击且无旧地址残留、知识图谱检索「钟离」出图（1911 节点）。

## 版本 3.2：文档完善（2026-10-04）

- 状态：已完成
- 版本号：`manager_panel.APP_VERSION`、`setup.iss# AppVersion`、`pyproject.toml` 同步升至 3.2（这三处是版本号的唯一来源，部署文档已写明需同步）。
- README：
  - 新增「目录结构」小节，说明 pilot.py / manager_panel.py / resource_store.py / asset_importer.py / kg_store.py / kg_view.py / assets.db / GenshinKG/data / tools / tests 的职责；
  - 「使用说明」补明程序常驻托盘、托盘是唯一入口；
  - 「功能说明」快捷键补全方向键（Ctrl/Command + ↑↓）与音量说明；
  - 版本记录补 v3.2、v3.1（补记入口脚本更名），v3.0 去掉与 v3.1 重复的「托盘菜单精简」；
  - 「后期开发（V3.1 展望）」改为「规划中」——v3.1 已发布，不应再作为展望标题；新增「音量调节面板化」待办；
  - 「开发与测试」测试项数 12 → 19，补 GUI 冒烟测试命令与「新增素材后是否需重建 assets.db」说明；
  - 致谢补原项目出处与知识图谱设计参考；新增「许可协议」小节；
  - 尾部松散的「制作windows应用程序安装包」段落并入「安装教程 B」。
- README 事实性修正：**LICENSE 实为 Apache License 2.0**（此前误写 GPL），已更正；素材版权声明指向米哈游。
- 管理面板帮助页：章节由 4 节扩为 5 节——新增「三、管理面板使用说明」（五个标签页各自能做什么 + 快捷键 + 改动即时保存的说明），原「三、第三方开源库」「四、开源地址」顺延为四、五；导入注意事项补充「删除素材只影响数据库记录、不删原始文件」；修正 v3.0/v3.1 内容重复（知识图谱条目原被误挂在 v3.1 下）。
- 部署到WindowsNT.md：补适用版本与「版本号 3 处需同步」提示；把实测踩到的 PyInstaller 缓存复用陷阱写入文档（含 PYZ-00.toc 与 _internal 数据校验清单）；产物补体积/耗时；测试清单修正已删除的托盘「导入素材包」入口，改用管理面板并新增知识图谱验证项；新增「静默安装验证」小节（含卸载程序异步、需轮询确认的注意事项）。
- 验证：`uv run pytest -q` 19 passed；离屏烟雾测试确认帮助页五个章节编号连续、面板标题 v3.2、版本记录无重复条目、三处版本号一致。

## 版本 3.3：知识图谱入库、CSV 导入导出与编辑（2026-10-05）

- 状态：已完成
- 背景：v3.0 起知识图谱每次启动都从 `GenshinKG/data` 的 27 个 CSV 现读现解析，运行时无法修改——面板只能看不能改；数据与代码同源也让「备份/分享自己的图谱」没有落点。

### 存储层：kg_store.py 重写为 SQLite

- 新增 `kg.db`（与 `assets.db` 并列，位于程序目录），三张表：
  - `kg_nodes(type, name, attrs)`，`attrs` 为 JSON 字符串，主键 `(type, name)`；
  - `kg_edges(id, src_type, src_name, rel, dst_type, dst_name)`，五列唯一约束防重复，端点各建索引；
  - `kg_meta(key, value)`，记录播种版本。
- 首次运行若库为空，自动从 `GenshinKG/data` 播种（实测 1911 节点 / 7356 边，约 0.74s，库 2.9MB）；此后运行时数据以库为准，CSV 退化为导入/导出格式与「恢复出厂」来源。
- 内存索引（`nodes` / `_name_index` / `adj` / `_edges`）在每次写入后 `_reindex()` 全量重建，1900 节点 / 7300 边为毫秒级，换取实现简单与索引绝不与库不一致。
- 播种时的初始数据目录缺失**直接抛 FileNotFoundError**（不再静默得到空图谱——空图谱会让用户误以为数据丢了）。
- 建图去重：同一关系的正反向只建一条邻接，避免自我中心网出现重复边（v3.0 会把 `A→B` 与 `B→A` 画两遍）。

### 解析规则修正（两处实际影响数据正确性）

- **实体类型列优先级改为 `label` → 文件名类型 → `type`**：`label-artifacts.csv` 自身带 `type` 列（圣遗物部位：花/羽/沙/杯/冠），原先若让 `type` 优先会把 189 个圣遗物实体全部判为非法类型丢弃，并在关系端点处误建 189 个 `character` 桩节点（人物数虚高到 185、圣遗物为 0）。修正后人物 65、圣遗物 189，与 CSV 实际行数一致。
- **同一行两端不取同类型桩**：`rel-character-element.csv` 中两个未知实体会先后落到同一个提示类型上，现按「另一端已占用」排除，角色/元素各归其类。
- `_SKIP_ATTRS` 增加 `name`：实体自身字段不应同时出现在属性表里。

### CSV 导入导出

- `import_csv(path, replace=False)` 支持三种形态：目录（`label-*.csv` + `rel-*.csv`）、单个关系表（表头含 `node1,rel,node2`，或 `relations.csv` 等别名）、单个实体表（表头含 `name` 且含 `label`/`type`）。返回报告含新增/更新/跳过/桩实体数量与被忽略的文件名。
- 覆盖模式（`replace=True`）先清库，面板导入前弹窗让用户选「合并 / 覆盖 / 取消」。
- `export_csv(out_dir)` 输出原始布局：实体表 `label-<类型>.csv`（属性列取该类型全部实体的并集，保证列稳定），关系表按**真实方向**命名 `rel-<源类型>-<目标类型>.csv`（原始数据中 `rel-country-area.csv` 的方向与文件名相反，回灌靠类型提示消歧，故导出时纠正为 `rel-area-country.csv`）。导出目录可被 `import_csv` 整目录回灌，往返实测 1911/7356 完全一致。
- 导入在单个事务内完成，并自建局部名称索引：新插入的实体立即可被后续关系解析（否则事务内 `self._name_index` 尚未刷新，端点会全部落到建桩分支）。

### 编辑能力

- 存储层：`add_node` / `update_node` / `delete_node`（级联删关系）/ `add_edge` / `update_edge` / `delete_edge`，改名或改类型时用两条 UPDATE 同步迁移关系的两端，不产生断链。
- 新增 `update_edge_touching` / `delete_edge_touching`：可视化按无向遍历展示，UI 只知道「某实体 — 关系 — 另一实体」，不应要求调用方判断三元组方向；这两个方法自动识别实际存储方向。`update_edge_touching` 换对端时保持锚点的相对位置（锚点作源端则接在后面，作目标端则接在前面）。
- 新增 `kg_editor.py`：`NodeEditDialog`（类型/名称/属性键值表，属性行可增删，上限 64 行）、`EdgeEditDialog`（两端 `EntityPicker` + 关系名 + 「⇄ 交换两端」）、`EntityPicker`（类型下拉 + 1911 项补全，显示「名称 [类型]」；可直接输入不存在的名字，对话框确认时按所选类型建为新实体）。关系名输入已有键时提示对应中文（`element_is` → 显示为「神之眼」），自填则按原文显示。
- 面板知识图谱页：顶部加「导入 CSV / 导出 CSV / 重新载入」；右侧由单一详情框改为「详情 + 关系列表 + 两行按钮（新增/编辑/删除实体、新增/编辑/删除关系）」；关系列表区分方向（`→` 出边 / `←` 入边）并与按钮启用状态联动；所有编辑走统一的 `_kg_after_change()` 刷新（自动补全、状态行、画布、详情、关系列表选中项），当前实体被删除时清空画布并提示重新定位。
- `kg_view.KGCanvas` 增 `clear()`。
- 打包：`原神桌面伙伴.spec` 的 datas 增 `kg.db`。

### 验证

- `tests/test_kg_store.py` 重写为 26 项：播种统计、跨实例持久化（不重复播种）、关系方向解析、占位名过滤、圣遗物类型不被 type 列带偏、实体/关系 CRUD 与改名迁移、方向无关的改/删、导出回灌往返一致、关系按真实方向命名、单关系表/单实体表导入、建桩、同名冲突与合并语义、错误路径。
- 新增 `tools/smoke_kg_panel.py`：以 QWidget 桩充当 pilot 构造 `ManagerPanel`，走真实的搜索定位、新增实体/关系、删除实体、导出与回灌导入链路（模态框已打桩）。
- `uv run pytest -q` 38 passed（原 19 + 知识图谱 26，其中 7 项为改写后的原有用例）；`uv run python tools/smoke_kg_panel.py` 通过；`compileall` 通过。
- 文档：README（版本、目录结构、功能说明、版本记录、测试命令）、帮助页（新增「知识图谱：数据存储与编辑」小节与 v3.3 记录，原 v3.2 条目下沉保留）、本日志。
- 遗留提示：kg.db 属运行期生成物，与 assets.db 同样应加入 `.gitignore`（打包时由 spec 的 datas 带入，不入库）。

## 版本 3.4：目录重构与配置 SQLite 化（2026-10-05）

- 状态：已完成
- 背景：v3.3 把知识图谱搬进了数据库，但项目目录仍留着 v2 时代的历史包袱——`src/`（图标）、`GenshinKG/{data,utils}`（数据与采集脚本）分散在两处，`config.yaml` 仍是程序运行时直接改写的文件（git 冲突高发、无法像 assets.db/kg.db 统一管理、也无法导入导出）。本次把这些一并收口。

### 目录重构

| 原位置 | 新位置 | 说明 |
| --- | --- | --- |
| `src/` | `ico/` | 4 个图标（icon256.ico/.bmp、app_icon.ico、logo.ico） |
| `GenshinKG/data/`（27 CSV） | `data/csv/` | 知识图谱初始数据，兼作导入/导出格式 |
| `GenshinKG/utils/{built_kg,convert_relationship}.py` | `tools/` | 数据加工脚本 |
| `GenshinKG/utils/mihoyo_spider.py` | 删除 | 与 `tools/mihoyo_spider.py` 重名且为其旧版子集（tools 版 1002 行含更多调试代码，是超集），按用户决定保留 tools 版 |
| `config.yaml` | `data/config.yaml` | 降级为配置种子 / 导入导出格式 |

- 全部用 `git mv` 迁移以保留文件历史；`GenshinKG/` 目录至此完全消失。
- 两个迁入的脚本：相对路径 `../data`、`../kg_data/done` 改为模块常量 `KG_CSV`（`<项目根>/data/csv`），并加文件头注明来源与「当前不可直接运行」的原因——`built_kg.py` 依赖第三方包 `connDB`（Neo4j 客户端）且默认连的是外部实例，`convert_relationship.py` 输入仍指向早已不在仓库内的 `rec_intention/kg_data`。
- 打包同步：`原神桌面伙伴.spec`（`icon=`、`datas` 全部改为新路径，并新增 `kg.db`）、`setup.iss`（`SetupIconFile`/`WizardImageFile`/`Source:` 指向 `ico\`）。
- **.gitignore 陷阱**：`data/` 原本整目录被忽略，CSV 迁进来后会被 git 丢掉（`git mv` 暂存过所以本地看着正常，但新克隆或新增文件会出问题）。改为精确规则：`data/*` 全忽略，再用 `!data/csv/`、`!data/config.yaml` 反向豁免这两项需入库的路径，并用 `git check-ignore` 逐项验证过（`data/png`、`data/music`、`data/bgm`、`data/kg`、`data/config.db` 仍正确忽略）。
- 顺手修了 README 的失效链接：`src/*.png` 早已随素材移入 `exhibition/data/`，但 README 仍在引用（死链），按 `exhibition/项目详细介绍.md` 里的权威标注逐张对应替换；同时修正 `[部署到WindowsNT.md]` 的路径（文档已移入 `doc/`）。

### 配置改用 SQLite

- 新增 `config_store.py`，配置存 `data/config.db`：`kv`（标量项，JSON 编码）、`frame_scale`（角色 → 间隔/缩放）、`config_meta`（播种来源等）。
- `data/config.yaml` 仅在库为空时播种一次；**程序日常不再改写它**，备份改用面板的导出功能。
- 接口与旧 yaml 读写语义一致：`load()` 返回普通 dict（调用方照旧修改），`save(config)` 整体落库，因此 `pilot.py` 与 `manager_panel.py` 的读写点改动很小。
- `pilot.py`：模块级 `config` 改为 `ConfigStore(DATA_DIR).load()`；`save_config()` 落库；新增 `reload_config()` 供配置导入后重载；`Pilot.config_store` 暴露给面板。删掉了 `import yaml`。
- `asset_importer.import_assets` 第三参数由 `config_path`（yaml 路径）改为 `ConfigStore` 实例，登记新角色改调 `register_role()`（幂等，不覆盖用户已调好的帧率/缩放）；原 `_register_roles_in_config()` 删除，仅在模块文档串里说明迁移路径。
- `tools/import_assets.py` CLI 同步改为构造 ConfigStore。

### 面板：配置导入导出

- 「素材管理」页新增「配置文件」分组：配置存储统计、**导出 YAML / 导出 JSON / 导入配置 / 恢复出厂设置**。
- 导入前弹窗选模式：**覆盖**（整体替换，随后会切到配置里的人物、重建托盘菜单）或**合并**（只补充缺失的人物登记、保留现有设置）；导入报告列出被忽略的未知键。
- 恢复出厂按 `data/config.yaml` 重新播种，操作前确认。

### 健壮性（本次实际修掉的问题）

- **YAML 损坏导致程序起不来**：`_read_yaml` 原来只捕 `OSError/ValueError`，而 `yaml.scanner.ScannerError` 不在其内，一个格式错误的配置文件会直接抛异常崩在启动阶段。改为捕 `Exception` 并静默退回内置默认值 `DEFAULTS`——配置是可选输入，为它崩程序不合理。`_try_json` 同理。
- **导入他人配置可能指向本地没有的人物**：`config['role']` 指向不存在的角色时，原代码 `config['frame_scale'][role]` 直接 KeyError。现启动时先确认该人物确有帧资源，否则回退到第一个可用人物并回写配置；`frame_scale` 缺登记时补默认值。
- **数值越界**：`frame_scale` 入库前夹紧到面板允许范围（间隔 20~1000ms、缩放 0.1~3.0），防止手改配置写出 0 间隔导致动画不刷新；非法值（非数字/长度不对）退回 `[60, 1.0]`。
- **脏键入库**：`save()` 只写 `SCALAR_KEYS` 白名单内的键，旧 config.yaml 曾有目录名与人物名不符的脏 key，不再混入新库。
- 格式嗅探：`.yaml` 里装 JSON 也能正确导入（先试 YAML，失败再试 JSON，反之亦然）；空文件/无法识别给明确中文错误而非堆栈。

### 验证

- 新增 `tests/test_config_store.py` 18 项：播种、跨实例持久化、种子缺失/损坏兜底、标量与 frame_scale 读写、越界夹紧、非法值兜底、register 幂等、脏键过滤、导出导入往返（YAML/JSON）、合并 vs 覆盖语义、未知键上报、格式嗅探、错误路径、恢复出厂、stats。
- `tests/test_asset_importer.py` 改为传 `ConfigStore`，并新增「重复导入不覆盖用户手工调过的帧率/缩放」「不传配置库也能导入」两项。
- `uv run pytest -q` **58 passed**（v3.3 为 38）；`compileall` 通过。
- 真实环境离屏烟雾（`QT_QPA_PLATFORM=offscreen SDL_AUDIODRIVER=dummy`）：Pilot 启动正常（早柚、339 帧），面板 5 个标签页、标题 v3.4、配置统计正常显示，改帧率落库成功，配置导出→导入往返一致，知识图谱页正常出图（1911 节点/7356 边）；另单独验证「role 指向不存在的人物」时回退到早柚并自动修正配置。
- 文档：README（目录结构、安装步骤第 3 条、功能说明、版本记录、测试项数、失效链接）、帮助页（新增「配置文件：存储、导入与导出」小节 + v3.4 记录，v3.3 条目下沉保留）、部署文档（打包命令/校验清单/版本号同步点/权限说明）、本日志。
- 遗留：`data/config.db` 是运行期生成物，已入 .gitignore；打包只需带 `data/config.yaml`，首启动会自行播种。

### 补充（同日）：`data/` 整个目录移出 git 管理

- 按用户要求，`data/csv`（27 个知识图谱 CSV）与 `data/config.yaml`（配置种子）不再纳入版本控制。
- `.gitignore` 简化为单条 `data/`（此前是 `data/*` + 两条反向豁免）；`git rm -r --cached data/csv data/config.yaml` 从索引移除，**本地文件全部保留**。
- 验证：`git check-ignore` 逐项确认 `data/csv/*.csv`、`data/config.yaml`、`data/config.db`、`data/png`、`data/kg` 均被忽略；`git ls-files data/` 返回 0；`git status data/` 干净。
- 运行不受影响：`uv run pytest -q` 58 passed；真实离屏启动正常（早柚 339 帧、图谱 1911 节点/7356 边）——这些文件本来就在本机，不参与运行时的版本控制。

**连带影响（已在文档中显式说明，避免以后踩坑）**：
- 这两项是**打包与首次运行的硬依赖**：`原神桌面伙伴.spec` 的 `datas` 引用 `data/config.yaml` 与 `data/csv`；`kg_store` 首次播种依赖 `data/csv`；`config_store` 播种依赖 `data/config.yaml`。
- 新克隆的仓库里 `data/csv` 为空、无 `data/config.yaml`，**直接打包会得到没有知识图谱、配置退回内置默认值的安装包**。
- 补救路径：`data/csv` 可由图谱页「导出 CSV」重建（导出布局与原始布局一致，可整目录回灌）；`data/config.yaml` 至少需含 `role` 与 `frame_scale`。
- 文档同步：部署文档新增「0.1 打包前置」小节（含就位检查命令）与两条故障排查项；README 目录结构标注「需自行放置」、安装教程新增第 3 步「补齐数据目录」、v3.4 版本记录说明。

### 补充 2（同日）：安装包瘦身 + config.db 移至项目根

- **发布方式调整**：`data/` 与 `*.db` 改为走**非 git clone 渠道**发布；**安装包不再携带 `data/` 文件夹**。
  - `原神桌面伙伴.spec` 的 `datas` 只保留 `assets.db`、`kg.db`、`ico/icon256.ico`，并在文件头写明「需要随包分发 data/ 时如何补回」。
  - `setup.iss` 同步；**顺带修掉 v3.4 重构遗留的 `src\icon256.ico` 3 处**（`SetupIconFile` / `WizardImageFile` / `Source:`，应为 `ico\`）——这个错误会让 Inno Setup 找不到图标文件。
  - `[UninstallDelete]` 增加 `config.db` 与 `data/`，卸载时清理本机状态。
  - 打包后校验清单补两条断言：包内**不应存在** `data/` 与 `config.db`。
- **新增 `tools/build_data_pack.py`**：把 `data/` 打成独立压缩包供非 git 渠道发布。
  - `pilot_kg_csv_<版本>.zip`（仅 27 个 CSV）与 `pilot_data_<版本>.zip`（27 个 CSV + `config.yaml`），各约 416KB；
  - `--only kg|data|all`、`--out <目录>` 可选；用户解压到程序目录（`_internal/`）即生效。
  - `dist_data/` 已入 `.gitignore`。
- **数据缺失兜底**（保证不带 data/ 也能正常用）：
  - `ConfigStore.ensure_roles(roles)`：按 `assets.db` 中实际存在的人物补齐 `frame_scale` 登记，幂等、不覆盖已有设置；`pilot.py` 启动时调用。实测无 `data/config.yaml` 时自动登记全部 28 人，人物菜单与设置面板完整可用。
  - `kg_store` 缺 CSV 时的 `FileNotFoundError` 从「甩一个路径」改为可操作提示（指向数据包与面板导入入口）；面板用 `html.escape` 逐行渲染多行错误（`manager_panel` 新增 `import html`——不加会在错误路径上直接 NameError）。
- **config.db 位置调整**：`data/config.db` → **项目根目录**，与 `assets.db`、`kg.db` 并列。
  - `ConfigStore.__init__(base_dir, db_name='config.db', seed_path=None)`：库落在 `base_dir`，种子固定读 `<base>/data/config.yaml`（`seed_path` 可覆盖）。
  - `pilot.py` 改为 `ConfigStore(BASE_DIR)`，并删掉已无人使用的 `DATA_DIR` 常量。
  - 本机配置迁移后完好：30 个人物参数（含夜兰 2.45 缩放）全部保留。
  - **踩坑**：库位置一改，测试里把种子写在库同目录的写法会静默走 `DEFAULTS` 兜底而**假通过**。测试改用 `seed_dir` fixture 造 `<root>/data/config.yaml`，并新增 `test_db_in_root_seed_in_data` 锁定该布局。
- **验证**：`uv run pytest -q` **63 passed**（新增 `ensure_roles` 4 项 + 布局 1 项）；真实离屏启动正常（早柚 339 帧、菜单 28 项、配置统计 28KB）；两个缺失场景逐一实测（无种子→28 人登记；缺 CSV 且缺 kg.db→图谱页给出可操作提示）。
- 文档：README（目录结构、安装第 3 步、开发命令、版本记录）、部署文档（打包前置重写、打包命令、校验清单、模块清单、权限说明）、帮助页（数据目录说明与迁移说明）、本日志。
- 遗留：安装包本体**未经实际构建验证**（本次打包任务被取消），spec datas 已按要求改好但建议下次打包时按校验清单核对一遍包内无 `data/`。

## 版本 3.5：数据一律由 SQLite 管理（2026-10-05）

- 状态：已完成
- 目标：安装包 = 程序 + **三个 `.db`** + 图标，**不含任何 CSV / YAML**。CSV/YAML 降级为
  **本地构建输入**。此举为后续 **C/S 架构**铺路——服务器 S 可下发同格式 CSV 与素材，
  客户端 C 用现成导入接口入库，无需为远程数据另造格式或另写代码路径。

### 构建层：CSV/YAML → 库

- 新增 `tools/build_databases.py`：
  - `data/csv/*.csv` → `kg.db`（实测 1911 节点 / 7356 边 / 2.9MB）
  - `data/config.yaml` → `config.db`（出厂配置：角色 + 30 个人物登记 / 28KB）
  - 参数：`--only kg|config|all`、`--force` 强制重建、`--check` 只校验不写入（打包前自检）
  - 写入策略：先写 `<name>.building` 临时文件、成功后 `os.replace`，**失败不留半成品**；
    `build_kg` 捕获异常后清理临时文件。
  - 记录 `built_from` / `app_version` 元信息，便于追溯来源与版本。
- 至此三个库的来源统一：`png/+music/ → assets.db`（原有）、`data/csv → kg.db`、`data/config.yaml → config.db`。

### 运行时：彻底不读 CSV/YAML

- `kg_store.get_default_store()` 不再默认 `seed_dir=data/csv`；库为空且无显式 seed_dir 时
  抛可操作错误（提示重新安装或用「导入 CSV」），而不是留一个空白图谱页。
- `ConfigStore.__init__(base_dir, db_name='config.db', seed_path=None)`：**`seed_path` 缺省即不读 YAML**；
  `_seed_from_yaml` 无种子时用内置 `DEFAULTS`。`reset_to_seed()` 语义改为「重置为内置默认值」，
  面板的「恢复出厂设置」随后调 `ensure_roles(store.list_roles())` 按资源库补齐人物登记。
- **实测**：把整个 `data/` 移走，程序启动正常——早柚 339 帧、人物菜单 28 项、图谱 1911 节点/7356 关系、
  搜索「甘雨」命中 44 条关系、面板标题 v3.5。**这正是「安装包不含 data/ 也能用」的证明。**

### C/S 预留

- `kg_store` 新增 `set_meta()` / `get_meta()` / `info()`（此前没有 meta 接口），`info()` 返回
  `schema_version` / `built_from` / `app_version` / 节点关系统计。
- `config_store` 补齐同名 meta 接口；两库均新增 `SCHEMA_VERSION` 常量并在建库时写入
  `config_meta` / `kg_meta`——将来服务端与客户端结构版本不匹配时可**拒绝导入而非静默出错**。
- 面板知识图谱状态栏显示来源与版本：`实体 1911 个 · 关系 7356 条 · 存储 SQLite (kg.db) · 库 2.9 MB · 来源 data/csv v3.5.0`。
- **已验证 C/S 通路**：构造「服务器」目录下发 CSV + config.yaml，客户端用
  `kg_store.import_csv()` / `config_store.import_file()` 接收——与本地导入**完全同一接口**，
  结果 1911 节点 / 7356 关系、配置 30 人登记全部正确入库。

### 打包

- `原神桌面伙伴.spec`：`datas=[assets.db, kg.db, config.db, ico/icon256.ico]`；文件头写明
  三个库各自的来源与「打包前先跑两个构建脚本」，以及 config.db 的特殊性。
- `setup.iss`：
  - `config.db` 用 **`onlyifdoesntexist`** 单独安装，且 `recursesubdirs` 那行加
    `Excludes: "config.db"`——否则覆盖安装会**把用户调好的参数全清掉**。升级保留用户配置，
    删掉该文件后重装即恢复出厂值。
  - `[UninstallDelete]` 不再删除 `config.db`（属用户数据），只清 `__pycache__`。
  - 打包命令注释、产物说明同步。
- 部署文档：步骤 1 由「准备 assets.db」重写为「构建三个数据库」，含三库来源对照表与
  打包前自检命令；校验清单新增「包内不应存在任何 `*.csv` / `*.yaml` / `*.yml`」的 `find` 断言；
  两条排查项改为「重建对应库」。

### 测试

- 新增 `tests/test_build_databases.py` 13 项（用 `importlib` 按文件加载构建工具并 monkeypatch
  路径常量到 tmp 目录）：CSV→kg、YAML→config、force/skip/重复构建、缺 CSV 报错、
  **缺种子仍可构建**（退化为默认值）、失败不留半成品、产物是合法 SQLite（表结构断言）、
  `--check` 不写盘、**运行时无 CSV 仍能打开库**。
- 两处测试因签名变更同步调整：`seed_dir` fixture 返回 `(root, seed)` 并显式传 `seed_path`；
  `test_db_in_root_seed_in_data` 拆为「运行时不读 YAML」与「显式传种子时按 YAML 播种」两项。
- `uv run pytest -q` **77 passed**（v3.4 为 63）。

### 踩坑记录

1. 改 `ConfigStore` 签名后 9 个测试失败——原因不是代码错，而是 fixture 没传 `seed_path`，
   导致静默走 `DEFAULTS` 兜底、断言对不上。**教训：把「默认不读文件」这类行为改成显式传参时，
   要先排查所有构造点**，否则测试会给出误导性的失败。
2. 验证「无 data/ 运行时」时用 `mv data /tmp/xxx` 且恢复命令与验证命令分成两次调用，
   中途被中断导致 **`data/` 遗留在 /tmp**。**教训：破坏性验证应在独立临时目录里用复制/软链构造
   替身，不要移动真实目录**；若必须移动，恢复动作要和移动放在同一条命令里。

### 补充 3：v3.5 实际构建验证（同日 15:03-15:20，全链路通过）

- 新增 `tools/verify_package.py`：把原先散在文档里的手工校验固化成脚本，六组检查——
  目录结构 / 三库大小下限（挡空库与半成品）/ **无 CSV·YAML·data** / 图标 /
  PYZ 模块（并断言 `tools.build_databases`、`tools.build_data_pack` **未进包**）/ 库内容抽样。
  退出码非 0 即失败，可直接接 CI。

- 实测链路（全部真实执行，非推断）：
  1. 清理 `build`+`dist` → 2. PyInstaller **119 秒**，日志 `PYZ-00.toc is non existent`（缓存全新）
     → 3. `verify_package.py` **全绿** → 4. ISCC **164 秒** → 5. 静默安装 **84 秒**
     → 6. **安装目录 CSV/YAML 数量 = 0、无 `data/`**，三库齐备
     → 7. **删掉 `_internal/config.db` 后 exe 仍存活 25s 并自行重建 28,672 字节配置库**
     （`role=七七` + 按 `assets.db` 补齐 28 人，`seeded_from=defaults`）
     → 8. 已安装程序正常运行（出厂「早柚」+ 30 人、图谱 1911/7356）
     → 9. **升级保护实测**：改 `role` 为钟离 → 覆盖安装 → 仍是钟离，`onlyifdoesntexist` 生效
     → 10. 静默卸载，文件数归 0。
  - 安装包：`inno_build/原神桌面伙伴安装向导.exe`，503,153,713 字节（479.6 MB）。
  - 第 7、9 两项是本版最关键的证据：前者证明运行时确实不依赖 YAML，后者证明打包配置
    里那句 `onlyifdoesntexist` 不是想当然——它真的挡住了覆盖安装。

- 踩坑（写入部署文档「实测记录」小节）：
  - 在 `dist/原神桌面伙伴/_internal` 里跑 `uv run python` 会报
    `Module use of python314.dll conflicts with this version of Python`——
    该目录里有打包进来的 `python314.dll`。**检查包内文件请回项目根目录用绝对路径**。
  - 卸载程序异步：退出码 0 后目录仍短暂存在，需轮询确认（本次文件已归 0，仅剩空目录）。

## 版本 3.6：素材导出 + 修复人物切换异常（2026-10-05）

- 状态：已完成
- 起因：用户反馈「人物切换异常」。排查发现并非单一问题，而是**三个叠加的缺陷**；
  同时补上素材的反向能力（此前只有导入、没有导出）。

### 一、人物切换异常：三个叠加缺陷

**① 窗口定位参数错位（主因）**

`init_window` 里写的是 `setGeometry(0, 400, self.pos_x, self.pos_y)`，而
`setGeometry(x, y, 宽, 高)`——**把「位置」当成了「宽高」**。后果：

- 位置恒为 `(0, 400)`，`reshow()` 里随机生成的 `pos_x/pos_y` 从未生效；
- 宽高被赋成随机坐标（随后又被 `resize` 覆盖，所以这一半看不出来）。

改成 `setGeometry(pos_x, pos_y, w, h)`，并新增 `_random_position()` / `_clamp_position()`
按当前人物**实际帧尺寸**夹紧位置——缩放后窗口可能很大（2.45 倍的夜兰在 800×800 屏上占
735×735），沿用旧坐标必然出屏。

**② `setMask` 抬高 `minimumSize` 导致尺寸不跟随（最隐蔽）**

切到小缩放角色后窗口仍是上一位的大小（如 2.45 倍夜兰 → 0.6 倍七七，窗口仍 735×735）。
逐步打印后定位到：**`setMask()` 会把窗口的 `minimumSize` 顶到遮罩尺寸，而 `clearMask()`
不会把它还原**，于是后续 `resize(180)` 被 Qt 静默忽略（不报错、也不生效）。

修复放在 `_apply_frame()`——`act()` 也走这里，所以每帧都受益：

```python
if size.width() < self.minimumWidth() or ...:
    self.setMinimumSize(0, 0)   # 解除上一帧遮罩留下的下限
self.resize(size)
self.setMask(mask)
self.setMinimumSize(0, 0)       # setMask 之后再次清零
```

> 排查教训：这个问题我先怀疑了 `setMask` 阻止缩小、也怀疑了 `setWindowFlags` 重置几何，
> 两次都被证伪。**最后靠「逐步打印每一步的真实尺寸」才定位到 `minimumSize`**。
> 遇到「调了没反应且不报错」的 Qt 问题，应该尽早打探针，不要靠推理反复试。

**③ 切换后不落库**

`reshow()` 改了 `config['role']` 但不调 `save_config()`，只有退出时才写库。
程序被强杀/崩溃就丢掉切换结果。现在切换即刻落库。

**顺带修掉的两处：**
- **动画跳过首帧**：`act()` 原本 `index = 1 if len>1 else 0`，而 `init_window` 也把
  `index` 初始化为 1，导致第 0 帧永不显示；只有 1~2 帧的自定义角色会**卡死在第 2 帧**。
  改为 `index = (index + 1) % total`，`init_window` 从 0 帧起步。
- **QLabel 堆积**：`init_window` 每次都 `QLabel(self)` + `setCentralWidget()`，
  而后者会删除并替换旧控件——切几十次后已删除控件堆积。改为**复用同一个 QLabel**。
- `init_window` 内的顺序也做了调整：先 `_apply_frame()` 定尺寸 → 再设窗口属性 → 最后定位。
  `setWindowFlags()` 会重置几何，定位必须放在它之后。

### 二、素材导出（新增 `asset_exporter.py`）

- `export_assets(store, out_dir, roles=None, areas=None, as_zip=False, progress=None)`：
  把 `assets.db` 还原为**与 `asset_importer` 严格对称**的布局——
  `png/<角色>/*.png`、`music/<角色>/*.mp3`、`music/<地区>/background.mp3`。
- **对称性是核心契约**：导出的包能被现有导入器直接并入，因此可用来备份、离线编辑后回导、
  分享给 others。已用测试锁死（导出→导入→再导出，文件集完全一致）。
- zip 用 `ZIP_STORED`（PNG/MP3 本身已压缩，再压几乎不省体积却更费 CPU）。
- 面板「素材管理」页新增导出分组：范围（全部 / 仅当前人物）× 格式（目录 / zip），
  带进度条对话框（460MB 全量导出实测约 34 秒）。
- 「仅当前人物」时**不导出地区 BGM**——它们与人物无关，带上与选项名不符（第一版漏了这点，
  实测时发现 zip 里混进了三个地区的 background.mp3，已修正）。

### 三、测试

- 新增 `tests/test_asset_exporter.py` 9 项：目录布局、字节一致、范围筛选、进度回调、
  zip 内容、空库报错、**导出目录可被导入器识别**、**导出 zip 可被导入器识别**、
  导出→导入→再导出幂等。用临时 sqlite 库，不碰真实 460MB 资源。
- 新增 `tests/test_role_switch.py` 7 项（离屏 Qt + 真实 assets.db）：
  切换即刻落库、窗口不再固定在左上角、尺寸跟随缩放（含大→小与 小→大双向）、
  切换后不越界、反复切换不漂移、QLabel 复用、帧循环覆盖全部帧。
  **有效性已验证**：临时退回 ② 的修复后，`test_size_follows_character_scale` 与
  `test_switched_window_stays_on_screen` 如期失败。
- `tools/smoke_kg_panel.py` 的 `FakePilot` 补上 `config_store` / `reload_config` /
  `_rebuild_bgm_menu`（此前漏了，冒烟脚本从 v3.4 起就已在报错）。

### 四、验证

- `uv run pytest -q`：**86 passed**（不含 GUI 切换测试）+ 7 项 GUI 测试 = **93 项**。
- 真实素材端到端：全量导出 **9820 个文件 / 34 秒**，与资源库条目数一致；
  单人物 zip 313 条目且不含地区。
- 真实素材往返：导出「七七 + 璃月」→ 用现有 `import_assets` 回导 → 帧 301 / 语音 12 / BGM 1，
  布局对称性成立。
- 切换修复实测：大→小（735→180）、小→大（180→735）尺寸均正确；遍历 28 人**越界数 0**；
  反复切换 6 次尺寸稳定。

### 补充 4：修复角色问好 + 移除「恢复出厂设置」（v3.6 追加）

用户提供了菲谢尔的语音文件清单，据此定位到 greeting 的**真正根因**——不是「她没有早上好」，
而是**文件名叫 `早上好问候菲谢尔.mp3`**，`_classify_voice` 用全等匹配
（`stem in ('早上好','中午好','晚上好','晚安')`）判不出类别 → `category=None`
→ `list_voices(role,'greeting')` 拿不到它 → 早上问候直接 `FileNotFoundError`。
经全库排查同类问题共 **4 条**：菲谢尔 ×2、迪奥娜 ×2（「中午好罐头.mp3」「中午好异响.mp3」）。

**修法（三处）：**
1. **分类器改关键词匹配**：新增 `GREETING_KEYWORDS`，`any(k in stem for k in ...)` 判为 greeting。
   已在库中修正这 4 条存量数据的 `category`（备份 `/tmp/assets_backup.db`）。
2. **时段表补全**：原 `greeting()` 的 `10>=t>=4 / 14>=t>=11 / 24>=t>17` 三段之外，
   **0~3 点与 15~17 点共 7 小时返回 False**（完全静默）。改为 `GREETING_SCHEDULE`
   区间表（支持跨零点的 `(23,5)`），深夜与凌晨说「晚安」，下午过渡到「晚上好」，全天覆盖。
3. **缺文件降级 + 只问候一次**：新增 `pick_greeting(available, hour)`，按关键词在该角色
   实际拥有的文件里挑，缺则按候选顺序降级（原先直接取文件会抛异常）。
   同时把问候从 `init_window` 移到启动流程调 `play_greeting()`——原先**每次切换人物都重新
   问候一遍**，一天切十次就被问候十次。异常捕获 `FileNotFoundError` / `RuntimeError`
   （pygame mixer 的异常是 RuntimeError，不是 `pygame.error`——`pygame` 并未整体导入，
   写 `pygame.error` 会 NameError）。

**移除「恢复出厂设置」**：该按钮会连带清空每个人物调好的帧率与缩放，风险大于便利。
已删除按钮、槽函数 `_reset_config`（827 字符）与帮助页说明，改为提示
「删除程序目录下的 config.db 后重新安装」——安装脚本本来就是 `onlyifdoesntexist`，
删掉后重装即恢复出厂值。

**顺带修好的两处陈旧内容：**
- `tests/test_pilot.py` 仍在 `from pilot import greeting`——该函数已删，
  且它断言的 `greeting(3) is False` / `greeting(24)=='晚上好.mp3'` 正是被修掉的两个 BUG。
  改为指向新 API，完整测试移到 `tests/test_greeting.py`（29 项）。
- **帮助页版本链断裂**：v3.4 的内容被误挂在「当前版本」标题下，而 v3.5 / v3.6 段落
  根本不存在（此前用 `grep` 误判为写入成功）。已补齐 v3.4 / v3.5 / v3.6 三段，
  校验七个版本段落与 `{APP_VERSION}` 渲染均正常。
- `tools/smoke_kg_panel.py` 的 `FakeStore` 补 `read_frame/read_voice/read_bgm/list_bgm_areas`，
  消除冒烟输出里的 AttributeError 噪音。

**测试**：新增 `tests/test_greeting.py` 29 项（分类器、24 小时覆盖、逐小时时段、越界小时、
带后缀文件、降级、多版本稳定性、全角色覆盖）。**有效性已验证**：临时退回分类器修复后
4 项如期失败。端到端实测：模拟早上 7 点启动 + 遍历 28 个角色问候，**异常数 0**。

**总计**：116（轻量）+ 7（GUI 切换）= **123 项通过**。

## 版本 3.7：切换人物时按时段问好 + 按钮布局统一 + 代码质量整改（2026-10-05）

- 状态：已完成
- 三项要求：① 切换人物时按时段打招呼；②「素材管理」页导出按钮与导入按钮位置大小一致；
  ③ 不增删功能的前提下提升代码质量、消除警告与错误；④ 重新构建安装包。

### 一、切换人物时按时段问好

**改动**：`Pilot.reshow()` 末尾调用 `self.play_greeting()`。问候内容按**调用时刻**的小时
重新判定（不再像 v3.6 那样「只在启动时播一次」），所以上午切换角色说「早上好」、
傍晚切换说「晚上好」、深夜说「晚安」。

**同时把「问候只播一次」换成「一分钟冷却」**：

v3.6 为了避免「一天切十次人物被问候十次」，把问候改成仅启动时播放——这等于把
「切换人物不打招呼」当成了修复。实际需求是**切换时也要问候**，只是别太吵。
因此把布尔标记 `_greeted` 换成时间戳 `_last_greeting`，两次问候间隔小于
`GREETING_COOLDOWN`（60 秒）就跳过；`force=True`（启动时）不受冷却限制。
实测连切 5 个人物只播 1 次，冷却过期后切回则正常问候。

**顺带清掉两个死变量**：`self.now_time`（v3.5 改用 `GREETING_SCHEDULE` 后再无人读取）
与 `self._greeted`（被时间戳取代）。

**一处易错**：问候放在 `reshow()` 的**最末尾**（`save_config()` 之后）。因为 `reshow`
中途会把 `self.role_name` 改成**回退后的角色**（该人物无帧资源时），放中间会用到旧名字。

**测试有效性已验证**：临时把 `reshow` 里的 `play_greeting()` 删掉（退回 v3.6 行为），
`test_switching_character_greets` 如期失败。第一版测试只直接调 `play_greeting()`、
绕过了 `reshow`，**抓不到这个 BUG**——补了走真实 `reshow` 的那条才真正锁住。

### 二、导入 / 导出按钮统一

原先是两个独立分组（`导入素材包` 与 `导出素材`），按钮宽度随文字长短而异
（「导入 zip 素材包」比「导出为目录」宽一截），视觉上明显不齐。

- 合并为同一分组「素材导入 / 导出」，五个按钮 + 范围下拉排在**同一行**；
- 用 `setFixedSize(132, 32)` **显式统一尺寸**——只靠 `addStretch` 是不够的：
  同一行的 `QPushButton` 默认 sizePolicy 会被拉伸成等宽，文字长短仍会导致观感差异；
- 导出范围下拉（全部素材 / 仅当前人物）也并入同一行，并放在按钮之前（先选后做）；
- 顺手把配置那行的三个按钮（原先 280×20）也统一为 132×32。

实测五个按钮均为 `132x32 @ y=27`，配置三个按钮同为 `132x32`。

### 三、代码质量整改（不增删任何功能）

**1. 消除 15 处编译警告（`SyntaxWarning: invalid escape sequence`）**

全部集中在两个第三方采集脚本（`tools/convert_relationship.py` 6 处、
`tools/mihoyo_spider.py` 7 处），成因是 `re.sub('\*\d+', ...)` 这类
**非原始字符串里写了 `\*` / `\d` / `\)` / `\[`**。Python 3.12 起会告警，未来会变成
`SyntaxError`。改为原始字符串（`r'\*\d+'`）后**语义完全等价**，已抽样核对匹配行为。

写法上用「行内匹配 `re.xxx('` 后取到闭合引号 + 判断是否含非标准转义」精确定位，
不用正则全局替换，避免误伤普通字符串。第一次尝试用 AST 过滤（`encode('ascii')`）
反而漏掉了含中文的整段正则——教训：AST 过滤条件要按实际数据放宽，别想当然。

**2. 修一处会崩的 f-string 笔误（真实 NameError）**

`tools/convert_relationship.py:61` 原为 `to_csv(fstr(KG_CSV) + '/done/rel-character-{mat}.csv')`
——把 f-string 前缀写成了 `fstr(`，一旦执行到就 `NameError: name 'fstr' is not defined`，
而且路径里的 `{mat}` 也不会被插值。已改为 `f'{KG_CSV}/done/rel-character-{mat}.csv'`。

**3. 清理 13 处 pyflakes 告警**

| 位置 | 问题 |
| --- | --- |
| `pilot.py` | `QImage` / `QFileDialog` / `QMessageBox` 导入未使用 |
| `manager_panel.py` | `QSizePolicy` / `REL_NAMES` 未使用；三行 f-string 无占位符 |
| `kg_editor.py` | `rel_cn` 未使用 |
| `kg_view.py` | `REL_NAMES` 未使用 |
| `tools/build_databases.py` | `DEFAULTS` 未使用 |
| `tools/smoke_kg_panel.py` | `QDialog` 未使用；**`list_bgm_areas` 重复定义**；`app` 局部变量未使用 |
| `tests/*.py` | 3 处无用导入 |

其中两点值得记：
- `kg_view.py` 里的 `rel_cn` 是**循环变量遮蔽**了同名函数，不是导入问题——核实后才没动它；
- `smoke_kg_panel.py` 的 `app = QApplication(...)` 是**必须保留引用**的
  （被 GC 后 Qt 操作会崩）。改成模块级 `_APP` 变量，而非简单删掉或写 `noqa`（pyflakes 不认 noqa）。

**4. 未处理的部分（有意保留）**

`tools/mihoyo_spider.py` 剩 8 处「局部变量赋值后未使用」——这些变量原本的用途在
`tools/build_databases.py` 迁入时连同相关逻辑一起被注释掉了。该脚本 v3.4 已注明
「依赖已不存在的目录与外部包，当前不可直接运行」，改动它风险大于收益，保持原样。

**结果**：32 个 py 文件**编译警告 0 条**；核心 8 模块 + 构建/校验工具 + 全部测试
**pyflakes 零告警**。

### 四、测试

- `tests/test_greeting.py` 新增 **16 项**（29 → 45）：时段正确性（9 个小时点参数化，
  含跨零点的 23/2/4 点）、冷却拦截、冷却过期、force 跳过、语音关闭、无语音文件、
  资源库异常、播放失败不记时间戳。
  用 `_StubPilot` + `Pilot.play_greeting.__get__` **复用真实方法**（不是复制逻辑）。
- **踩坑**：`_freeze_hour` 一开始把整个 `datetime` 模块替换成类，
  结果 `pilot.py` 里的 `datetime.datetime.now()` 报 `has no attribute 'datetime'`。
  正确做法是只替换模块内的 `datetime` **属性**。
- `tests/test_role_switch.py` 新增 1 项 `test_switching_character_greets`：
  走真实 `reshow()` 验证「切换 → 新人物 → 时段正确」，这条才是真正锁住 BUG 的测试。
- **总计：132（轻量）+ 8（GUI 切换）= 140 项通过**；`tools/smoke_kg_panel.py` 通过。

### 五、重新构建（实测）

- 版本号三处同步 3.7（`APP_VERSION` / `setup.iss` / `pyproject.toml`）。
- 三个库重新构建：`kg.db` 1911 节点 / 7356 关系（2.9MB）、`config.db` 出厂「早柚」+ 30 人登记（28KB）。
- 构建与安装包实测数据见部署文档「本次构建实测记录」小节。

### 补充 5（v3.7 当晚修正）：托盘切换不问候 + 导入导出拆为两个模块

**用户反馈两条**：① 通过托盘更改人物后依旧没有问好；② 素材的导入和导出应该是两个模块。

#### ① 托盘切换不问候：冷却粒度错了

**排查**：托盘菜单的 `QAction` 确实调的是 `self.reshow(r)`，与面板切换**同一条路径**，
问候代码也在 `reshow()` 末尾。实测触发 `partners.actions()[0]` 后 `played` 为空、
`_last_greeting` 时间戳未变——**不是没调用，而是被冷却拦住了**。

**根因**：v3.7 首版把冷却做成「全局时间戳 + 60 秒」：

```python
if not force and self._last_greeting is not None:
    if (now - self._last_greeting).total_seconds() < GREETING_COOLDOWN:
        return
```

启动时已问候过一次，**此后 60 秒内切换任何人物都会被跳过**。启动问候 + 快速切换
是绝大多数使用场景，等于把功能废掉了。冷却的本意是「别让同一个人反复说话」，
实现却成了「不管换谁都不许说话」——**粒度错了**。

**改法**：`_last_greeting` 由 `datetime` 改为三元组 `(时刻, 人物, 时段关键词)`，
冷却只在**「同一个人 + 同一时段」**时生效：

```python
if not force and self._last_greeting:
    elapsed = (now - self._last_greeting[0]).total_seconds()
    same_role = (self._last_greeting[1] == self.role_name)
    same_slot = (self._last_greeting[2] == keyword)
    if same_role and same_slot and elapsed < GREETING_COOLDOWN:
        return
```

于是：**换人立即问候**、**跨时段（早上好→中午好）立即问候**、
只有连点**同一人且同一时段**才被限流。实测：
- 启动后立刻点托盘第 2、3 个人物 → 均正常播「晚上好.mp3」
- 连点同一人 6 次 → 只播 1 次
- 交替点两个人 4 次 → 播 4 次

**测试**：新增 3 项（`test_switching_another_role_bypasses_cooldown`、
`test_new_time_slot_bypasses_cooldown`、`test_repeated_same_role_same_slot_is_throttled`），
并修正 `test_cooldown_expires_and_greets_again`（元组解包）。
**有效性已验证**：退回全局时间戳冷却后，前两项如期失败。

> 教训：加「防打扰」这类限流时，**限流的粒度必须对齐用户真正在意的对象**。
> 这里用户在意的是「别被同一个人反复吵」，而不是「别被问候」。
> 只测「播放了没有」而不断言「什么时候该播、什么时候不该播」，就会漏掉这类问题。

#### ② 导入与导出拆为两个独立模块

v3.7 首版把两者**合并**成一个「素材导入 / 导出」分组（用户反馈的正是这一点）。
现拆回三个独立分组，各自职责清晰：

| 分组 | 内容 |
| --- | --- |
| 导入素材 | 导入 zip 素材包 · 导入素材目录 · 刷新统计 |
| 导出素材 | 范围下拉（全部 / 仅当前人物）· 导出为目录 · 导出为 zip |
| 配置文件 | 导出 YAML · 导出 JSON · 导入配置 |

但**按钮尺寸仍统一**——即使用户不再要求同宽，两个模块并排时宽度不一致仍显凌乱。
提取 `BTN_W, BTN_H = 132, 32` 为局部常量，三组共用（原先配置组是硬编码的 `132, 32`）。
实测 8 个按钮全部 `132x32`，三个分组 y 坐标 156 / 233 / 310 依次排列。

> 注：`addStretch` 不能替代 `setFixedSize`——同一行的 QPushButton 默认
> sizePolicy 会被拉伸成等宽，文字长短仍导致观感差异。

#### 验证

- `tests/test_greeting.py` 45 → **48 项**；`test_role_switch.py` 8 项（含走真实
  `reshow` 的 `test_switching_character_greets`）。
- **总计 135（轻量）+ 8（GUI）= 143 项通过**。
- 静态检查：核心模块 + tools + tests **pyflakes 零告警**。
- 端到端：托盘 `QAction.trigger()` 实测换人问候、连点冷却；面板三模块截图确认。

### 补充 6（v3.7 当晚）：修复知识图谱双击崩溃 + 托盘图标警告

用户运行 `python .\pilot.py` 报告两条输出：

```
QSystemTrayIcon::setVisible: No Icon set
Error calling Python override of QGraphicsEllipseItem::mouseDoubleClickEvent():
RuntimeError: libshiboken: Internal C++ object (NodeItem) already deleted.
```

#### ① 双击崩溃：事件重入导致「自己删掉自己」

**根因**。双击节点的调用链是：

```
NodeItem.mouseDoubleClickEvent
  → canvas.nodeExpanded.emit(key)        # 同步
    → ManagerPanel._on_kg_node_expanded
      → KGCanvas.show_ego(key)
        → self._scene.clear()             # ← 把正在处理事件的 self 也删了
  → super().mouseDoubleClickEvent(event)  # ← 访问已删除的 C++ 对象，抛 RuntimeError
```

`show_ego()` 每次都以 `self._scene.clear()` 重建整个场景，**而 `clear()` 不区分
「旧节点」与「当前正在被双击的节点」**。信号是同步发射的，所以 `emit` 返回时
`self` 的 C++ 侧已被销毁；紧接着的 `super()` 就炸了。

`NodeItem.canvas` 这条 Python 引用是问题能暴露出来的前提——它让 Python 包装对象
在 C++ 对象被删后仍存活，于是 Qt 仍会把事件投递到悬空对象上。

**修法（两层）**：

1. **调整顺序**：先取引用（`key, canvas = self.key, self.canvas`）、
   **先**调 `super().mouseDoubleClickEvent(event)`，**再**发射信号，
   之后不再触碰 `self`：
   ```python
   def mouseDoubleClickEvent(self, event):
       if not self._alive:
           return
       if event.button() != Qt.LeftButton:
           super().mouseDoubleClickEvent(event)
           return
       key, canvas = self.key, self.canvas
       super().mouseDoubleClickEvent(event)   # 基类先处理完
       canvas.nodeExpanded.emit(key)          # 再发信号（此时 self 可能已被删）
   ```
   `mousePressEvent` 同样调整（单击也会触发详情重绘）。
2. **存活标记兜底**：`NodeItem.__init__` 设 `self._alive = True`；
   `KGCanvas._retire_items()` 在 `clear()` **之前**把所有在场景内的 `NodeItem`
   标记为 `False`；事件处理开头检查该标记直接返回。`hoverEnterEvent` 同样加了防护。

**验证**：先确认原实现能复现（退回后同样抛
`libshiboken: Internal C++ object (NodeItem) already deleted`），再确认修复后
连续双击 3 次、单击 3 次、滞后投递均无异常。

> 教训：Qt 里「在事件处理中销毁自己」是经典陷阱。信号同步发射意味着槽里的
> `clear()` 会在 `emit` 返回前完成，而重绘类槽函数尤其容易踩到。
> 稳妥做法是**顺序 + 存活标记**双保险，后者应对「Qt 仍投递悬空事件」的情况。

#### ② 托盘 `No Icon set`：显示早于设图标

**根因**：`Pilot.__init__` 里原来是

```python
self.tray()          # tray() 内部会 self.tp.show()
self.init_window()   # 这里才 self.tp.setIcon(...)
```

`tray()` 先执行并 `show()` 了托盘，此时图标还是空的，Qt 打印警告。

**修法**：交换顺序——`init_window()`（负责 `setIcon`）先，`tray()`（内部 `show`）后。
`reshow()` 里的 `self.tp.show()` 保持不变（那里 `init_window()` 已先执行、图标已新）。

#### 测试

新增 `tests/test_kg_view.py` **9 项**（离屏 Qt + 真实 kg.db / assets.db）：
场景有节点、双击发出正确 key 且不抛错、连续双击安全、单击安全、
**滞后投递安全短路**、`_retire_items` 标记全部旧节点、`clear()` 也标记、
**端到端连真实面板**走完 `nodeExpanded → show_ego` 全链路、
**托盘顺序断言**（用 `inspect.getsource` 检查 `init_window()` 早于 `tray()`）。

**有效性已验证**：退回修复后 `test_stale_node_event_short_circuits` 与
`test_double_click_via_panel_repaint` 如期失败。

> 踩坑：构造测试事件时，`QGraphicsItem` 只接受 `QGraphicsSceneMouseEvent`
> （不是 `QMouseEvent`），且 `setScenePos()` 只接受一个 `QPointF` 参数。
> 另外 `_Pilot` 桩件必须真的继承 `QWidget`（面板会把它当 `QDialog` 的 parent），
> 运行时改 `__bases__` 不可靠。

**总计：144（轻量）+ 8（GUI 切换）= 152 项通过**；核心模块 pyflakes 零告警。

### 补充 7（v3.7 深夜）：修复补全崩溃 + 画布鼠标抓取警告

用户再次运行 `python .\pilot.py`，报告两条：

```
QGraphicsItem::ungrabMouse: not a mouse grabber
Traceback (most recent call last):
File "kg_editor.py", line 64, in _on_completer_activated
  item = self._model.itemFromIndex(index)
TypeError: 'QStandardItemModel.itemFromIndex' called with wrong argument types:
PySide6.QtGui.QStandardItemModel.itemFromIndex(str)
```

#### ① 补全崩溃：把 QString 当成 QModelIndex

**根因**。`QCompleter.activated` 有**两个同名重载**：

```
activated(QString); activated(QModelIndex)
```

Qt 在用户点击候选时发的是**前者**（参数是补全框里的显示文本，如「护摩之杖 [武器]」）。
而 **PySide6 在不限定类型时也只会连上这一个**——实测：

```python
c.activated.connect(lambda x: ...)          # 收到的是 str
c.activated.emit(model.index(0, 0))
# Shiboken::Conversions::_pythonToCppCopy: Cannot copy-convert ... (QModelIndex) to C++
```

即 QModelIndex 重载在 Python 侧**根本连不上也投递不了**。旧代码把 `str` 直接传给
`itemFromIndex()`，必然抛 TypeError。

**修法**。不把信号参数当索引用，改为**用候选文本反查行**：

```python
def _on_completer_activated(self, text):
    self._sync_type(text)

def _find_candidate_row(self, text):
    for row in range(self._model.rowCount()):
        if self._model.item(row).text() == text:
            return row
    return -1
```

文本与模型一一对应（`refresh()` 里拼的「名称 [类型]」），反查可靠；文本对不上时
（用户直接输入新名字）退回 `completer.currentIndex()`，仍拿不到就安静返回。

顺带把 `highlighted` 也接上——键盘上下移动候选时同步类型，做到「所见即所选」。

> 教训：PySide6 的**同名信号重载**要在连接处用 `signal[Type]` 限定，否则 Python
> 侧只认第一个、且可能与 C++ 实际发出的那个不一致。更稳的做法是**不依赖信号参数**，
> 改从接收者自身状态（`currentIndex()`、模型反查）取数据。

> 第一版修法只改成 `currentIndex()`，虽然不再抛异常，但直接调用时索引无效、
> **类型没回填**——测试立刻暴露了这点，才补上文本反查。

#### ② `ungrabMouse: not a mouse grabber`

**根因**。`QGraphicsItem.mousePressEvent()` 的默认实现会 `grabMouse()` 接管后续事件。
而节点在双击时会被 `scene.clear()` 销毁，Qt 于是在松手时找不到 grabber，打印该警告。

**修法**：节点的三个鼠标处理**都不再调用 `super()`**，改为 `event.accept()` /
`event.ignore()` 直接表态。节点只需响应「按下」这一瞬，拖拽平移由
`QGraphicsView` 的 `ScrollHandDrag` 负责，本来就不需要节点参与 grab 流程。
`hoverEnterEvent` 同样处理（其默认实现会做 hover grab）。

> 这条约束用 **AST 断言**锁在测试里（`test_mouse_handlers_do_not_call_super`）——
> 一开始想用 `'super().' not in inspect.getsource(...)`，结果 docstring 里
> 出现的 `super()` 字样导致误报，改用 AST 找 `Call` 节点才可靠。

#### 测试

- 新增 `tests/test_kg_editor.py` **10 项**：候选加载、传字符串不崩且类型正确回填、
  名称去后缀、highlighted 同步类型、文本失配时退回 currentIndex、
  空/None/无匹配安全（参数化 3 例）、直接输入新名仍可建实体、占位名仍被拒。
- `tests/test_kg_view.py` 9 → **11 项**：新增「鼠标处理不得调用 super()」（AST 断言）
  与「完整按下→释放→双击→再交互序列无 grab 警告」。
- **有效性已验证**：退回两处修复后 **6 项如期失败**。
- **总计 156（轻量）+ 8（GUI 切换）= 164 项通过**；核心模块 pyflakes 零告警。

### 补充 8（v3.7 深夜）：修复「重新构建后图谱编辑丢失」+ CSV 模块重组

用户反馈四件事：① 在知识图谱页编辑后数据没保存到数据库，新安装包仍是旧数据；
② CSV 导入导出对话框的取消/退出逻辑不对；③ CSV 按钮应在素材管理页；
④ 素材管理页按钮应大小一致对齐。另需消除 `'float | int | Any' 不支持格式规范` 警告。

#### ① 图谱编辑「丢失」——真凶是构建流程，不是存储

**先验证存储层**（排除误判）：`KGStore.add_node/add_edge` 都用 `with self._conn:`
事务写入，进程退出后另开连接读磁盘确认**确实落盘**（2 节点 / 1 关系）。
存储层没问题。

**真正的根因在构建流程**。`kg.db` / `config.db` 既是「出厂产物」又是**用户本机状态**——
程序里新增的图谱实体、改过的名字、调好的帧率与缩放，全都写在这两个库里。
而 v3.5 定的流程是「打包前先跑 `build_databases.py --force`」，
**`--force` 会用 `data/csv`、`data/config.yaml` 静默覆盖它们**。
于是每次重新构建，用户的编辑都被抹掉，新安装包自然还是旧图谱。

**修法（三层）**：

1. `build_databases.py` 的提示语改成明确的**打包正确用法**：
   > 日常打包**不加 `--force`**——库已存在时只检查不重建，编辑因此被保留。
   > 确认要丢弃现有内容才加 `--force`。
   （`build()` 开头、跳过分支的提示、argparse 的 `description`/`epilog` 都改了）
2. `--force` 时**自动备份**到 `kg.db.bak-<时间戳>` / `config.db.bak-<时间戳>`，
   返回值带 `backup` 路径；新增 `--no-backup` 可关闭。报告里明确提示
   「程序里编辑过的内容在里面，重建会丢弃」。
3. `.gitignore` 加 `*.db.bak-*` 与 `*.db.building`。
4. 部署文档加醒目警告框 + README 开发命令段加注释；故障排查表里两处
   `--force` 也改成不加（库不存在时 `build_databases.py` 本就会生成）。

**顺带修一个我自己引入的 bug**：`build_config` 里原有 `finally: import shutil`，
与顶部模块级 `import shutil` 冲突——Python 视其为函数局部变量，
未执行到就 `UnboundLocalError`。已删掉局部的（顶部已有）。

**测试**：新增 4 项（备份含用户编辑内容、库不存在时无需备份、config.db 同样备份、
`--no-backup` 生效），已验证退回后失败。

#### ② CSV 对话框逻辑重写

**原逻辑的毛病**：`_on_kg_import` 先弹一个自建的三按钮 `QMessageBox`
（目录 / 单文件 / 取消），选完再弹 `_kg_do_import` 的 Yes/No/Cancel——
**两层模态框嵌套**，且第二层用「确定 = 合并，取消 = 覆盖」表述，
「取消」既是取消操作又表示覆盖，语义混乱；窗口右上角关闭也走 `else` 分支不明确。

**改为单层、语义明确**：

- 第一层：用 `addButton` + `setInformativeText` 说明两种来源的差别，
  补 `StandardButton.Cancel` 并设为默认按钮；**关窗与取消同义**（都不导入）。
- 第二层：合并 / 覆盖 / 取消三个按钮，**「合并」是默认**（安全的那条路），
  覆盖标为 `DestructiveRole`（红色警示）。`informativeText` 讲清两者差异。
- 判别一律用 `box.clickedButton() is <btn>`，不用 `exec()` 的返回码；
  文件对话框取消（空路径）也单独判空返回。

#### ③ CSV 按钮迁到「素材管理」页

- 知识图谱页顶部移除三个按钮，改为一行提示「数据导入导出见『素材管理』页」。
- 素材管理页新增「知识图谱数据」分组：图谱存储统计 + 导入图谱 CSV / 导出图谱 CSV /
  重新载入图谱。统计走新的 `_update_kg_stat()`，图谱载入/变化时自动同步
  （未载入时只提示位置，不强制打开大库）。

#### ④ 按钮尺寸全页面统一

原先只有「素材管理」页统一过，其余三页都是各自的默认尺寸：

| 页面 | 原状态 |
| --- | --- |
| 人物管理 | 233×20 与 232×20（**差 1px，肉眼可见的不对齐**） |
| 音乐管理 | 640×480（撑满整行） |
| 知识图谱 | 640×480 |

**做法**：把 `BTN_W, BTN_H` 提到**模块级常量**（原来只是 `_build_assets_tab`
的局部变量，别的页用不了），标注为 `int`；给全部 17 个按钮
（人物 3 + 音乐 3 + 素材 11 + 图谱 7 中的按钮，另含搜索框「定位」）加
`setFixedSize`，每行末尾补 `addStretch(1)`。实测**四个页面全部 132×32，只有一种尺寸**。

#### ⑤ 消除 `float | int | Any` 格式警告

这个警告来自**类型检查器**（IDE），不是 Python 运行时。定位方法：先用
`ast` 扫出所有「带格式说明符的 f-string」，再逐个核对值的来源。

真凶 3 处（另 3 处在 `asset_exporter._human_size`）：

| 位置 | 表达式 | 问题 |
| --- | --- | --- |
| `manager_panel._kg_update_status` | `s['db_size_mb']:.1f` | `float \| None` |
| `manager_panel.refresh` | `s['db_size_mb']:.1f` | 同上 |
| `manager_panel.refresh` | `cs['db_size_kb']:.0f` | 同上 |
| `asset_exporter._human_size` | `n / 1024:.0f` | `int \| float` |

`resource_store.stats()` 的 `size_mb` 在**文件后端下是 `None`**（没有库文件），
类型就是 `float | None`；`config_store.stats()` 的 `size_kb` 同理。
**修法**：先判空取出到局部变量，再 `float(...)` 显式转换后格式化；
`_human_size` 开头 `n = float(n)`。修复后 ast 复查 6 处格式化的值都已是明确 float。

> 注意：这不是「编译器语法警告」（那类 v3.7 白天已清零，这里 34 个文件仍为 0 条），
> 而是 IDE 类型检查提示。运行时加 `-W error` 验证过：干净。

**测试总计：160（轻量）+ 8（GUI 切换）= 168 项通过**；核心模块 pyflakes 零告警。

## 版本 3.8：面板主窗口化、伙伴退到托盘、配置改 JSON、帮助外置、卸载修复（2026-10-06）

### 面板：新增「窗口与状态」标签页

- **动机**：面板原先是 `Pilot` 的子弹窗，Windows 把它并进伙伴那个「无边框置顶」
  窗口的任务栏分组，用户在任务栏上根本找不到它；而且面板**没有任何窗口状态入口**，
  不能最小化、不能最大化。
- **窗口命令放哪**：先试过放菜单栏，用户要求「不要 menus，改成新标签页」；
  随后又试过「把五个标签页全部转入 menus」，最终**按用户要求撤回菜单方案**，
  恢复标签页并新增一个「窗口与状态」页承载窗口命令。
- **实现**：`QTabWidget` 仍是中央控件（六个标签页）；
  窗口页上半部分是命令按钮（最小化 / 最大化·还原 / 全屏·退出全屏 / 隐藏面板），
  下半部分是「当前状态」（窗口状态、当前伙伴、资源库、版本）；
  伙伴显隐用 `QCheckBox` 而非按钮——它是**状态**而非动作。
- ⚠️ **不建菜单栏**：`menuBar()` 一旦被调用，菜单与标签两套导航会并存并互相打架。
  `tests/test_v38.py::test_panel_keeps_tabs_and_has_no_menubar` 锁住这一点。
- 另加 `Ctrl+1` ~ `Ctrl+6` 快速切换六个标签页（`_build_shortcuts()`，
  同样必须在所有标签页建好之后调用，否则会绑错页）。
- 顺带修掉一个真实缺陷：原先各处直接调 `setWindowOpacity`，
  从托盘隐藏伙伴后勾选框仍显示「已勾选」。现新增
  `Pilot.set_visible(visible)` 作为**显隐唯一入口**，末尾回调面板 `_sync_window_state()`。

### 面板：QDialog → QMainWindow

- **动机**：面板原先是 `Pilot` 的子弹窗，Windows 把它并进伙伴那个「无边框置顶」
  窗口的任务栏分组，用户在任务栏上根本找不到它；而且面板没有任何窗口状态入口，
  不能最小化、不能最大化。
- **改法**：`super().__init__(None)` + 显式
  `setWindowFlags(Qt.Window | Close | Minimize | Maximize ButtonHint)`。
  **不把 pilot 作为 Qt 父窗口**是任务栏能独立成条目的关键；
  pilot 改由 `self.pilot` 属性引用（原来两者是 Qt 父子关系）。
- **配套**：`changeEvent` 里按 `WindowStateChange` 同步「窗口与状态」页的
  按钮文案与勾选；`keyPressEvent` 里 **Esc 退出全屏**（全屏时标签页与标题栏
  控件都可能被盖住，没这个出口用户会被困住）。
- **关闭语义改为「隐藏」**：`closeEvent` 里 `event.ignore()` + `hide()`，
  且**不再调 `pilot.on_manager_closed()`**——那会把 `_panel` 置空，
  下次打开会新建实例，旧实例连同资源一起泄漏（关闭一次就白丢一次已填的表单
  和已加载的图谱）。真正销毁只发生在 `Pilot.quit()`
  （`setAttribute(WA_DeleteOnClose, True)` + `close()` + `deleteLater()`）。

### 伙伴本体：加 Qt.Tool，不进任务栏

- 原先只有 `FramelessWindowHint`，Windows **仍会**给伙伴创建一个任务栏按钮，
  而它不可最小化、点它只是闪一下伙伴——一个点不动的空占位。
- `Qt.Tool` 在 Windows 上映射为 `WS_EX_TOOLWINDOW`，才真正不进任务栏与 Alt+Tab。
- 与上一条方向相反（一处要独立成条目、一处要彻底消失），**改任一处都要重读这两段**。
- 另设 `applicationName` / `applicationDisplayName`，让任务栏与 Alt+Tab 显示中文名。

### 配置：只用 JSON

- 删除 `ConfigStore.export_yaml` 与 YAML 解析路径；`_read_yaml` → `_read_json`、
  `_seed_from_yaml` → `_seed_from_file`；种子迁为 `data/config.json`（30 个人物登记）。
- **`PyYAML` 从 `pyproject.toml` / `requirements.txt` / `uv.lock` 移除**，
  打包产物里不再有 `yaml/` 目录。
- `import_file` 遇到 `.yaml` / `.yml` **明确报错**并提示另存为 JSON，
  而不是静默按 JSON 解析——静默兼容已退役的格式会让用户以为导入成功、实际写进了错结构。
- 属性名 `yaml_path` 作为 `seed_path` 的兼容别名保留（旧代码/测试可能仍引用）。

### 帮助文档外置为 res/help.html

- `manager_panel.py` 里约 270 行 HTML 整体搬进 `res/help.html`（13.5KB，含 CSS），
  `load_help_html(base_dir)` 启动时读取并替换 `{{APP_VERSION}}` 等占位符。
- **占位符用双花括号**：文件里有 CSS（`body { ... }`），单花括号会在替换时把样式吃掉。
- ⚠️ **候选路径第三项是 `here/res/help.html`，不是「here 的父目录/res」**——
  写错时开发态永远读不到文件，且因为有兜底提示**不报错**，只是帮助页空白。
  这个 bug 真的发生过一次，靠运行时打印候选路径才抓到。
- spec datas 与 `verify_package.py` 都已覆盖该文件（缺它属静默故障，必须拦住）。
- **同日重写内容**：从「按页面罗列」改为「按主题组织」的十节结构——
  ① 程序是怎么工作的（窗口与托盘）② 管理面板七个菜单 ③ 导入导出素材
  ④ 知识图谱 ⑤ 配置（JSON）⑥ 数据文件/备份与迁移 ⑦ 卸载与清理
  ⑧ 常见问题排查 ⑨ 版本变更记录 ⑩ 许可与素材版权；开头加目录锚点跳转，
  并把配置 JSON 的顶层键名列成表。

### 知识图谱：确认即时落盘 + 修复升级覆盖

- **先核实，不臆改**：「每次增删改都保存到 kg.db」这个需求，实测发现**存储层本来
  就是即时提交的**——`add_node` / `update_node` / `delete_node` / `add_edge` /
  `update_edge` / `delete_edge` 每个写方法都用 `with self._conn:` 包裹，
  块退出即 commit；`update_edge_touching` / `delete_edge_touching` 只做方向识别后
  委托给它们。也确认了没有任何地方绕过存储层直接改内存索引
  （`kg_view.py` 是纯展示，不含写操作）。故**没有改这部分逻辑**。
- **但找到了真正的丢数据原因**：`setup.iss` 的 `[Files]` 用
  `recursesubdirs` 批量复制 `_internal\*`，只把 `config.db` 列进 `Excludes`，
  **`kg.db` 每次升级都被无条件覆盖**——用户的图谱编辑其实存进了 kg.db，
  却在装新版本时被安装器清空。现把 `kg.db` 也移出批量复制，
  改为与 `config.db` 同样的 `onlyifdoesntexist`。
- **补 7 条回归测试**（`tests/test_kg_store.py`）：新增 / 改 / 删实体、
  新增关系、改关系（含换对端）/ 删关系、整目录导入 CSV，
  以及「升级不得覆盖 kg.db」的脚本断言。
  关键写法：**关掉连接重开一个新实例再查**，而不是查内存索引——
  只查 `store.nodes` 是测不出漏提交的（内存里一直有，文件里可能没有）。
- 顺带记下测试断言的两处陷阱：`_edges` 是 `set of ((类型,名), 关系名, (类型,名))`
  三元组（不是五元组）；导入关系 CSV 时对端实体会被**自动补建**，
  所以 2 人物 + 2 关系的结果是 **4** 个节点而不是 2。

### 卸载：修复「卸载不干净」

- **根因**：`{app}` 目录非空时 Inno **不会删除它**，而程序运行期产生的文件
  （含用户导出的素材、图谱编辑）不在安装登记之列；再叠加程序没关、文件被占用，
  删不掉。实测机器上就留着一个 0 文件的空目录。
- **改法**：`[UninstallRun]` 先 `taskkill /F` 结束进程；`[UninstallDelete]` 增加
  `Type: filesandordirs; Name: "{app}"` 兜底整目录删除；`[InstallDelete]` 清理旧版残留
  （`dist_data` / `data` / `GenshinKG` / `config.yaml` 等）。
- **可选保留用户数据**：卸载前询问是否保留三个 `.db`，选「是」则**拷到 `{app}` 之外**
  （`%APPDATA%\原神桌面伙伴-备份`）再清空目录。
  ⚠️ **不能用 `UninstallAllowUserDataKeep`**——该指令在本机 Inno Setup 6.3.3 中
  并不存在（官方指令表里没有），写进脚本直接编译失败。
- 新增 `AppMutex`，配合程序侧 `create_app_mutex()` 单实例互斥量，
  让安装/卸载能可靠判断程序是否在运行（名字写死在两处，已用测试锁住一致性）。

### 测试与验收

- `uv run --with pyflakes`：核心模块 + tools + tests **零告警**。
- `pytest -q`：**185 项全通过**（原 171 + `tests/test_v38.py` 14）。
- `tools/smoke_kg_panel.py` 离屏冒烟 **SMOKE OK**（QMainWindow 下真实编辑/导入/导出链路正常）。
- 运行时验证面板：`Qt.Window` 置位、父窗口 `None`、最大化/还原/全屏/最小化
  状态与菜单文案均正确同步、close 后隐藏且实例仍可用。
- `build_databases.py`（不加 `--force`）→ 三个库保留；PyInstaller 打包 →
  日志出现 `Building COLLECT because COLLECT-00.toc is non existent`（未复用缓存）；
  `verify_package.py` 退出码 0；产物 exe 离屏跑 25 秒**输出为空**。
- 完整安装链路：静默安装到隔离目录 → 目录内 CSV/YAML/JSON 计数为 0、无 `data/`、
  `help.html` 就位 → 已安装程序离屏跑 25 秒输出为空 → 静默卸载后
  **`{app}` 目录本身消失（0 残留）**，且「保留数据」路径确实产出了
  `%APPDATA%` 下的三个 `.db` 备份。
