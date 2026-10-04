# PySide6 重构日志

本日志按增量步骤记录从 PyQt5 到 PySide6 的迁移过程。每一步都包含修改范围和紧随其后的验证结果。

## 第 0 步：建立基线并迁移依赖声明

- 状态：已完成
- 修改：将运行依赖移入 `pyproject.toml`，增加 `PySide6`、`PyYAML`、`pygame` 和开发依赖 `pytest`；更新 `requirements.txt`，不再声明 PyQt5。
- 基线验证：`uv lock` 通过；`python -m compileall -q desktoppet.py src tools GenshinKG` 通过。
- 基线备注：现有代码仍导入 PyQt5；编译阶段发现项目其他脚本已有无效转义序列警告，暂不属于本次迁移范围。

## 第 1 步：迁移 Qt 导入和 Qt6 API

- 状态：已完成
- 修改：将入口模块的 Qt 导入替换为 PySide6；迁移 `QAction` 所属模块、主屏幕查询、鼠标全局坐标、枚举值、菜单执行和应用事件循环；移除未使用的 `PyQt5.sip`。
- 修改：将 `pygame.mixer` 初始化移入 `Pet` 初始化，允许测试导入纯函数而不启动音频设备。
- 测试：`uv run pytest -q` 通过，1 passed；`uv run python -m compileall -q desktoppet.py tests` 通过；Pylance 文件语法检查通过。
- 测试备注：首次 pytest 收集失败是仓库根目录未进入测试模块搜索路径，新增 `tests/conftest.py` 后重跑通过。
- 文档：更新 README 和备用依赖清单中的 PySide6、uv 安装与运行方式。

## 最终验证

- `uv lock --check`：通过。
- `uv run pytest -q`：通过，1 passed。
- `uv run python -m compileall -q desktoppet.py tests`：通过。
- PySide6 QApplication/QAction 运行时烟雾测试：通过。
- 项目源码、README 和依赖声明中的 PyQt5 残留扫描：通过；本日志保留历史迁移记录中的 `PyQt5` 文本。
- 环境备注：默认源和备用源均使 `pygame==2.6.1` 在 Python 3.14 上进入源码构建并长时间停滞；改用兼容同一 `pygame` 导入接口的 `pygame-ce`，以获得可安装的 Python 3.14 wheel。

## 第 2 步：SQLite 资源库与动画帧缓存

- 状态：已完成
- 背景：项目资源为约 9800 个零散文件（9476 帧 PNG + 344 条 MP3，合计约 470MB），分发与备份不便；且原实现每个动画帧（60~80ms 一次）都执行一次磁盘读取 + PNG 解码 + 缩放，CPU 与磁盘 I/O 持续空转。
- 新增 `tools/build_assets_db.py`：扫描 `png/`、`music/`，把帧、语音（按文件名归类 greeting/chat/know）、区域 BGM 导入单文件 `assets.db`（表 `assets(role, kind, name, category, data)`）；本次构建 9820 条、459.5MB，耗时约 14 秒。
- 新增 `resource_store.py`：`ResourceStore` 统一资源入口，存在 `assets.db` 时用 SQLite 后端，否则自动回退文件系统；对上层只暴露字节流与名称列表。
- 修改 `desktoppet.py`：帧、语音、BGM 全部改走 `ResourceStore`（`QPixmap.loadFromData`、`mixer.Sound(file=BytesIO)`、`mixer.music.load(BytesIO)`，BGM 流持有引用防回收）；切换角色时一次性预加载并预缩放全部帧（含 mask 缓存），`act()` 变为纯内存切换；Ctrl +/- 缩放后重建缓存；顺带修复托盘图标依赖磁盘路径、`BASE_DIR` 重复拼接、`role_audio` 死代码与大段注释死代码。
- 性能实测：达达利亚 219 帧从 DB 解码 + 缩放的一次性成本约 0.5 秒（2.3ms/帧），此前同等开销每帧重复发生。
- 测试：新增 `tests/test_resource_store.py`（文件系统与 SQLite 后端一致性、语音分类、缺键异常），`uv run pytest -q` 4 passed；`compileall` 通过；离屏 Qt 烟雾测试通过；DB 抽样字节与磁盘文件 MD5 一致。
- 备注：数据库核实全库共 28 个角色，与托盘菜单一一对应；`assets.db` 为生成物，已加入 `.gitignore`。

## 第 3 步：第三方素材导入模块与动态菜单

- 状态：已完成
- 背景：原人物/地区菜单在代码中硬编码，新增角色需要改代码；用户需要导入自定义人物和地区的第三方素材。
- 新增 `asset_importer.py`：素材包（目录或 zip，沿用 `png/<人物>`、`music/<人物>`、`music/<地区>/background.mp3` 布局）导入 `assets.db`，同名资源覆盖更新；地区识别规则从硬编码三地泛化为「目录含 background.mp3 即为地区」；新人物自动在 `config.yaml` 的 `frame_scale` 登记默认值 `[60, 1.0]`。
- 新增 `tools/import_assets.py`：命令行导入入口。
- 修改 `desktoppet.py`：人物菜单（约 110 行硬编码 QAction）与音乐菜单改为按 `ResourceStore` 动态生成；`set_audio` 泛化为支持任意地区；托盘新增「导入素材包」入口，运行中导入后菜单即时刷新；`ResourceStore` 新增 `list_bgm_areas()`；`reshow` 对未登记角色做 `setdefault` 容错；右键语音菜单增加空列表保护。
- 修复边界 bug：单帧角色在 `init_window`/`act` 中索引越界（`IndexError`），旧代码同样存在此隐患，第三方素材（常见单帧）使其暴露；现对索引做钳制。
- 测试：新增 `tests/test_asset_importer.py`（目录/zip 导入、幂等覆盖、config 登记、空包与缺失路径异常），`uv run pytest -q` 9 passed；离屏 + 哑音频驱动的端到端烟雾测试通过（动态菜单 28 角色、导入后新角色/新地区即时出现、单帧角色切换正常）；烟雾测试均在临时 DB 副本上进行，真实库已验证无残留。

## 第 4 步：重写安装脚本（setup.iss）并验证完整安装链路

- 状态：已完成
- 背景：2.0 起资源收进单个 `assets.db`，旧安装脚本（1.1）存在多个问题：无 `AppId`（升级/卸载无法正确注册）；默认装到 `{commonpf}`（Program Files），程序运行时写 `config.yaml`/`assets.db` 会因权限不足失败；欢迎页弹 MsgBox 影响体验；无卸载图标与可选快捷方式。
- 重写 `setup.iss`：固定 `AppId` GUID；版本号 2.0；默认安装到 `{localappdata}\Programs\原神桌面宠物`（每用户、免管理员、程序可写自身文件），`PrivilegesRequired=lowest`（保留 dialog 允许覆盖）；仅限 64 位；`CloseApplications` 自动关闭运行中的宠物以支持覆盖安装；可选桌面图标与开机自启任务；卸载显示图标与开始菜单卸载项；压缩改 `lzma2/normal`（资源本身已压缩，平衡体积与构建速度）；移除欢迎页 MsgBox。
- 更新 `部署到WindowsNT.md`：PyInstaller 命令从 50+ 条 `--add-data` 简化为只带 `config.yaml`、`assets.db`、`icon256.ico` 三项。
- 验证（全链路实测）：`uv run --with pyinstaller pyinstaller` onedir 打包成功（dist 592M，`_internal/assets.db` 462M 就位）；`ISCC.exe setup.iss` 编译成功（133 秒）；安装向导静默安装到默认用户目录成功，文件布局与可写性验证通过；静默卸载因会话子进程回收被中断（非安装包问题），残留目录已手动清理。
- 产物：`inno_build/原神桌面宠物安装向导.exe`（480M）；`build/`、`dist/`、`inno_build/`、`*.spec` 已加入 `.gitignore`。

## 第 5 步：管理面板（版本 2.1）

- 状态：已完成
- 新增 `manager_panel.py`：托盘菜单「管理面板」打开的单例对话框，三个标签页——
  - 人物管理：角色列表 + 首帧预览 + 帧/语音数量；按角色调整帧间隔与缩放（当前角色即时生效并持久化）；设为当前宠物；删除人物（确认后从 assets.db 移除并同步菜单，至少保留一个）。
  - 音乐管理：地区 BGM 播放/停止、人物语音开关、一键静音，与托盘音乐菜单状态双向同步。
  - 素材管理：后端/角色/地区/帧/语音/DB 大小统计；zip 或目录导入素材包。
- `desktoppet.py` 新增面板支撑接口：`open_manager`/`on_manager_closed`、`save_config`、`set_role_timing`、`play_area_bgm`/`stop_bgm`/`set_voice_enabled`、`import_from_path`（托盘导入入口复用）；`quit` 改走 `save_config`。
- `resource_store.py` 新增 `stats()`、`delete_role()`、`delete_area()`（删除仅 sqlite 后端）。
- 测试：`test_resource_store.py` 增加统计与删除用例，pytest 12 passed；离屏烟雾测试覆盖面板三个标签页核心操作（预览刷新、设置即时生效、BGM/语音控制、统计、删除同步、单例释放），真实 config.yaml 以快照-恢复方式保护。
- 版本号：`setup.iss` 与 `pyproject.toml` 升至 2.1；PyInstaller + Inno 重新构建安装包。

## 第 5.1 步：管理面板帮助文档页（2.1 补充）

- 状态：已完成
- 新增：管理面板第四个标签页「帮助文档」（`QTextBrowser` 渲染内置 HTML，链接由系统浏览器打开），内容包括——
  - 导入素材注意事项：素材包布局、语音命名分类规则、地区识别规则（含 background.mp3 即地区）、同名覆盖、新人物默认值、版权提醒；
  - 版本变更记录：v1.1 / v2.0 / v2.1；
  - 第三方开源库清单：PySide6（LGPLv3）、pygame-ce（LGPLv2.1）、PyYAML（MIT）、SQLite（Public Domain）、pytest（MIT）、PyInstaller（GPL）、Inno Setup；
  - 开源地址 https://github.com/MrYuPengfei/yuanshen-desktoppet.git 。
- 面板窗口标题改为带版本号（`APP_VERSION` 常量统一维护）。
- 测试：离屏烟雾测试校验四个标签页存在、帮助页四个内容板块与开源地址齐全、外链可点击；安装包已重新构建（PYZ 校验含 manager_panel）。