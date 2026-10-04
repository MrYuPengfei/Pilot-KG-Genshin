# 部署到 Windows（PyInstaller + Inno Setup 6）

整体链路：`desktoppet.py` → PyInstaller 打包成 `dist/原神桌面宠物/` → Inno Setup 编译 `setup.iss` 生成安装向导。

## 步骤 0：准备资源库

2.0 起资源不再按目录打包，而是收进单个 `assets.db`（约 460MB）。如果仓库里还没有：

```shell
uv run python tools/build_assets_db.py
```

> 注意：必须先有 `assets.db` 再打包。安装包只携带 `assets.db`、`config.yaml` 和图标，不再携带 `png/`、`music/` 目录。

## 步骤 1：PyInstaller 打包

安装 PyInstaller（uv 会临时提供，无需装入项目依赖）：

```shell
uv run --with pyinstaller pyinstaller desktoppet.py ^
    --name "原神桌面宠物" --onedir --noconsole ^
    --icon=src/icon256.ico --clean --noconfirm ^
    --add-data "config.yaml;." ^
    --add-data "assets.db;." ^
    --add-data "src/icon256.ico;."
```

（bash 环境把行尾的 `^` 换成 `\`。）

说明：

- 用 **onedir**（单文件夹）模式，启动快；产物为 `dist/原神桌面宠物/原神桌面宠物.exe` + `_internal/`（assets.db、config.yaml 在 `_internal` 里）。
- 不再需要 2.0 之前那种为每个角色写一条 `--add-data` 的长命令。
- `resource_store.py`、`asset_importer.py`、`tools.build_assets_db` 都会被 PyInstaller 依 import 关系自动打进包，无需额外参数。

## 步骤 2：Inno Setup 生成安装包

1. 安装 Inno Setup 6（官网 https://jrsoftware.org/isinfo.php ）。
2. 命令行编译（也可在 Inno 的 GUI 里打开编译）：

   ```shell
   "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" setup.iss
   ```

3. 产物在 `inno_build/原神桌面宠物安装向导.exe`。

## 安装行为说明（2.0 起的变化）

- **安装目录默认为 `%LOCALAPPDATA%\Programs\原神桌面宠物`**（每用户安装，免管理员权限）。
  原因是程序运行时要写 `config.yaml`（退出时保存设置）和 `assets.db`（导入素材包），
  装进 `Program Files` 会因权限不足导致保存失败——请勿把 `DefaultDirName` 改回 `{commonpf}`。
- 覆盖安装时安装向导会自动关闭正在运行的宠物进程。
- 安装时可勾选创建桌面图标、开机自启（默认均不勾选）。
- 卸载有独立图标和开始菜单项。

## 测试安装包

1. 在一台干净机器（或虚拟机）上运行安装向导，确认能安装、能启动、托盘菜单正常。
2. 重点验证：切换人物、播放语音/背景音乐、调整缩放后退出重进（配置应保留）、托盘「导入素材包」导入一个 zip（数据库应可写）。
3. 覆盖安装一遍旧版本之上，验证升级流程。
