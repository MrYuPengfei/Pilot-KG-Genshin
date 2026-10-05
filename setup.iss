; =============================================================
; 原神桌面伙伴 安装脚本（Inno Setup 6）
;
; 前置步骤（PyInstaller 6+，onedir 模式）：
;   uv run --with pyinstaller pyinstaller 原神桌面伙伴.spec
;
;   等价的命令行写法（建议直接用 spec，datas 已含下面几项）：
;   uv run --with pyinstaller pyinstaller pilot.py ^
;       --name "原神桌面伙伴" --onedir --noconsole ^
;       --icon=ico/icon256.ico --noconfirm ^
;       --add-data "assets.db;." ^
;       --add-data "kg.db;." ^
;       --add-data "config.db;." ^
;       --add-data "ico/icon256.ico;."
;
; 编译：
;   "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" setup.iss
;
; 说明：
; - 安装包 = 程序 + 三个 SQLite 库（assets.db / kg.db / config.db）+ 图标，
;   **不含任何 CSV / YAML**（v3.5 起数据一律由数据库管理，CSV/YAML 只是构建输入）；
; - 资源已收进单个 assets.db，无需再打包 png/、music/ 目录；
; - config.db 既是出厂值也是用户本机状态，故用 onlyifdoesntexist 安装：
;   升级时保留用户已有配置；删掉后重装即可恢复出厂值；
; - 程序运行时需写 config.db / assets.db / kg.db（保存设置、导入素材与图谱），
;   因此默认安装到用户目录（免管理员权限），不要改装 Program Files。
; =============================================================

#define AppName "原神桌面伙伴"
#define AppVersion "3.7"
#define AppPublisher "于鹏飞"
#define AppURL "https://github.com/MrYuPengfei/Pilot-KG-Genshin"
#define AppExeName "原神桌面伙伴.exe"

[Setup]
; AppId 唯一标识本应用，升级安装/卸载都依赖它，发布后不要修改
AppId={{2B18A692-647A-4A78-BAF2-489F44D660B4}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}
AppUpdatesURL={#AppURL}

; 安装到当前用户目录：免管理员权限，且程序可写自身配置与资源库
DefaultDirName={localappdata}\Programs\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog

; 仅 64 位系统
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

; 界面与外观
LicenseFile=LICENSE
SetupIconFile=ico\icon256.ico
WizardImageFile=ico\icon256.bmp
WizardSmallImageFile=ico\icon256.bmp
WizardStyle=modern
UninstallDisplayIcon={app}\icon256.ico

; 输出
OutputDir=./inno_build
OutputBaseFilename=原神桌面伙伴安装向导

; 压缩：资源本身已压缩（PNG/MP3），normal 级别在体积和构建速度间较均衡
Compression=lzma2/normal
SolidCompression=yes

; 覆盖安装前自动关闭正在运行的伙伴，避免文件占用导致安装失败
CloseApplications=yes
CloseApplicationsFilter=*.exe
RestartApplications=no

[Languages]
Name: "zh_CN"; MessagesFile: "ChineseSimplified.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "startupicon"; Description: "开机自动启动"; GroupDescription: "其他:"; Flags: unchecked

[Files]
; PyInstaller onedir 输出：exe 在根，其余在 _internal（含三个 .db）
; 注意 config.db 用 onlyifdoesntexist 单独安装——它既是包内出厂值，又是用户本机
; 状态。若跟着 recursesubdirs 无条件覆盖，升级会把用户调好的参数全清掉。
Source: "dist\原神桌面伙伴\原神桌面伙伴.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "dist\原神桌面伙伴\_internal\*"; DestDir: "{app}\_internal"; Flags: ignoreversion recursesubdirs; Excludes: "config.db"
Source: "dist\原神桌面伙伴\_internal\config.db"; DestDir: "{app}\_internal"; Flags: onlyifdoesntexist
Source: "ico\icon256.ico"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
; 开始菜单
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"; IconFilename: "{app}\icon256.ico"
Name: "{group}\卸载 {#AppName}"; Filename: "{uninstallexe}"
; 桌面（可选任务）
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; IconFilename: "{app}\icon256.ico"; Tasks: desktopicon
; 开机自启（可选任务）
Name: "{userstartup}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: startupicon

[Run]
; 安装完成后启动
Filename: "{app}\{#AppExeName}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; 卸载时清理运行期产生的缓存（config.db 属于用户数据，不随卸载删除）
Type: filesandordirs; Name: "{app}\_internal\__pycache__"
