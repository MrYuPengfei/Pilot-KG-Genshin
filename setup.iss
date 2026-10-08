; =============================================================
; 桌面伙伴-Pilot 安装脚本（Inno Setup 6）
;
; 前置步骤（PyInstaller 6+，onedir 模式）：
;   uv run --with pyinstaller pyinstaller 桌面伙伴-Pilot.spec
;
;   等价的命令行写法（建议直接用 spec，datas 已含下面几项）：
;   uv run --with pyinstaller pyinstaller pilot.py ^
;       --name "桌面伙伴-Pilot" --onedir --noconsole ^
;       --icon=ico/icon256.ico --noconfirm ^
;       --add-data "assets.db;." ^
;       --add-data "kg.db;." ^
;       --add-data "config.db;." ^
;       --add-data "res/help.html;." ^
;       --add-data "ico/icon256.ico;."
;
; 编译：
;   "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" setup.iss
;
; 说明：
; - 安装包 = 程序 + 三个 SQLite 库（assets.db / kg.db / config.db）
;   + 帮助文档 help.html + 图标，**不含任何 CSV / JSON 配置**；
; - 资源已收进单个 assets.db，无需再打包 png/、music/ 目录；
; - config.db 既是出厂值也是用户本机状态，故用 onlyifdoesntexist 安装：
;   升级时保留用户已有配置；删掉后重装即可恢复出厂值；
; - res/help.html 必须随包分发（v3.8）：帮助页在运行时动态读取它，
;   缺文件不会崩，但帮助页会显示「未能载入帮助文件」；
; - 程序运行时需写 config.db / assets.db / kg.db（保存设置、导入素材与图谱），
;   因此默认安装到用户目录（免管理员权限），不要改装 Program Files。
;
; **卸载（v3.8 重做，解决「卸载不干净」）**：
;   原先只删 PyInstaller 登记过的文件，运行期新产生的文件会留下来，
;   且 {app} 目录非空时 Inno 不会删除它——用户看到的就是「卸载了但目录还在」。
;   现在：① 卸载前先结束正在运行的进程（否则文件被占用，删不掉）；
;        ② 删完登记文件后整目录清空并删除 {app}；
;        ③ 顺带清理构建期备份（*.bak-*）与缓存；
;        ④ 卸载前询问是否保留用户数据（三个 .db），可选择留作备份。
; =============================================================

#define AppName "桌面伙伴-Pilot"
#define AppVersion "3.8.3"
#define AppPublisher "于鹏飞"
#define AppURL "https://github.com/MrYuPengfei/Pilot-KG-Genshin"
#define AppExeName "桌面伙伴-Pilot.exe"
; 卸载时判断「程序是否在运行」用；与 pilot.py 的 create_app_mutex 保持一致。
; 注意 Inno 的 { } 与常量展开会互相干扰，这里把整个名字定义成一个常量，
; 不要写成 Global\{#AppName}_... —— 前缀的 Global\{ 会被当成常量起始而报错。
#define AppMutexName "Global\PilotKG_Genshin_2B18A692_647A_4A78_BAF2_489F44D660B4"

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

; v3.8：AppMutex 让安装/卸载能可靠判断「程序是否在运行」。
; 没有它时 Inno 只能靠 CloseApplications 的 Restart Manager 匹配进程名，
; 偶尔会漏判正在运行的实例，导致删文件失败、卸载不干净。
; 程序侧对应实现见 pilot.py 的单实例互斥量（create_app_mutex）。
AppMutex={#AppMutexName}

; 记录日志，便于排查卸载/覆盖安装问题
SetupLogging=yes
UninstallLogging=yes

; 界面与外观
LicenseFile=LICENSE
SetupIconFile=ico\icon256.ico
WizardImageFile=ico\icon256.bmp
WizardSmallImageFile=ico\icon256.bmp
WizardStyle=modern
UninstallDisplayIcon={app}\icon256.ico

; 输出
OutputDir=./inno_build
OutputBaseFilename=桌面伙伴-Pilot安装向导

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
; PyInstaller onedir 输出：exe 在根，其余在 _internal（含三个 .db 与 help.html）
;
; config.db 与 kg.db 都用 onlyifdoesntexist 单独安装——它们**既是包内出厂值、
; 又是用户本机状态**：用户在面板里改的设置与图谱编辑就写在这两个库里。
; 若跟着 recursesubdirs 无条件覆盖，**每次升级都会把用户的编辑清空**，
; 表现为「明明存了，升级后就没了」。
;
; 代价是新版本附带的出厂图谱/出厂配置不会自动更新到已安装的机器上。
; 需要恢复出厂值时删掉对应的 .db 再重新安装即可（帮助页有说明）。
Source: "dist\桌面伙伴-Pilot\桌面伙伴-Pilot.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "dist\桌面伙伴-Pilot\_internal\*"; DestDir: "{app}\_internal"; Flags: ignoreversion recursesubdirs; Excludes: "config.db,kg.db"
Source: "dist\桌面伙伴-Pilot\_internal\config.db"; DestDir: "{app}\_internal"; Flags: onlyifdoesntexist
Source: "dist\桌面伙伴-Pilot\_internal\kg.db"; DestDir: "{app}\_internal"; Flags: onlyifdoesntexist
Source: "ico\icon256.ico"; DestDir: "{app}"; Flags: ignoreversion

[InstallDelete]
; v3.8：安装时清掉旧版本遗留。升级前若上一版有卸载没删干净的文件，
; 它们会一直躺在目录里（也是「卸载不干净」的一部分）。
; 只删明确的构建期残留，不碰用户的三个 .db。
Type: filesandordirs; Name: "{app}\dist_data"
Type: filesandordirs; Name: "{app}\data"
Type: filesandordirs; Name: "{app}\build"
Type: filesandordirs; Name: "{app}\GenshinKG"
Type: filesandordirs; Name: "{app}\src"
Type: filesandordirs; Name: "{app}\__pycache__"
Type: filesandordirs; Name: "{app}\_internal\__pycache__"
Type: filesandordirs; Name: "{app}\.build_tmp"
Type: files; Name: "{app}\config.yaml"
Type: files; Name: "{app}\桌面伙伴-Pilot.old"

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

[UninstallRun]
; v3.8：卸载前结束正在运行的伙伴。
; 没有这一步，程序还开着时 exe 与 _internal 下的文件被占用，
; Inno 删不掉——用户看到的正是「卸载了但目录还在，重装又提示文件占用」。
; taskkill 对未运行的进程会返回非 0，这里刻意不检查返回值。
Filename: "taskkill"; Parameters: "/F /IM {#AppExeName}"; Flags: runhidden; RunOnceId: "KillRunningApp"

[UninstallDelete]
; ① 清理运行期产生的缓存与构建期备份
Type: filesandordirs; Name: "{app}\_internal\__pycache__"
Type: filesandordirs; Name: "{app}\__pycache__"
Type: filesandordirs; Name: "{app}\.build_tmp"
Type: files; Name: "{app}\_internal\*.bak-*"
Type: files; Name: "{app}\*.bak-*"
; ② 兜底：把整个安装目录删掉。
; Inno 自会删除它登记过的文件，但**运行期新产生的文件不在登记之列**，
; 而非空的 {app} 目录 Inno 不会删除——这就是历史上「卸载不干净」的主因。
; userdata 勾选时这三个 .db 已被 [Code] 移到别处，不会误删用户数据。
Type: filesandordirs; Name: "{app}"

[Code]
// v3.8：卸载时可选保留用户数据。
//
// 为什么不用 UninstallAllowUserDataKeep：该指令在本机 Inno Setup 6.3.3 中
// 并不存在（写进脚本会直接编译失败），所以改为在删除前把三个库**搬到**
// 安装目录之外，再让 [UninstallDelete] 照常清空 {app}。
const
  // 换行符。Pascal Script 没有 NewLine 常量；而写字面量 #13#10 也不行——
  // ISPP 预处理阶段会扫描每一行，把行内出现的 #13 当成未知预处理器指令
  // （报 Unknown preprocessor directive），编译直接失败。
  Nl = #13#10;

var
  UserDataKeptDir: String;
  ExecResult: Integer;

// 卸载开始前：结束进程 + 询问是否保留数据
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  DataDir, Msg: String;
  Names: array[0..2] of String;
  I: Integer;
begin
  if CurUninstallStep = usUninstall then
  begin
    // 先结束正在运行的伙伴，否则文件被占用导致删除失败。
    // [UninstallRun] 里也做了一次，两者互为保险（静默卸载时
    // SuppressibleMsgBox 会被 /SUPPRESSMSGBOXES 抑制，这里保证进程一定被结束）。
    Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /IM {#AppExeName}', '',
         SW_HIDE, ewWaitUntilTerminated, ExecResult);

    // 询问是否保留用户数据（三个 SQLite 库）
    Msg := '是否保留已导入的素材、知识图谱与设置？' + Nl +
           '选择「否」将彻底删除（assets.db / kg.db / config.db，约 460MB，不可恢复）。' +
           Nl + Nl + '选择「是」会把它们备份到安装目录之外，重装后可手动拷回。';
    // SuppressibleMsgBox 的第 4 个参数 Default 是**必填**的：
    // /SUPPRESSMSGBOXES 静默卸载时不弹框、直接返回它。
    // 这里传 IDYES——静默卸载默认**保留**用户数据（不销毁用户成果，
    // 也避免无人值守时被静默删掉 460MB 素材）。
    if SuppressibleMsgBox(Msg, mbConfirmation, MB_YESNO, IDYES) = IDYES then
    begin
      DataDir := ExpandConstant('{userappdata}\桌面伙伴-Pilot-备份');
      if not DirExists(DataDir) then CreateDir(DataDir);
      Names[0] := 'assets.db';
      Names[1] := 'kg.db';
      Names[2] := 'config.db';
      for I := 0 to 2 do
      begin
        // FileCopy 三个参数，第三个 FailIfExists **必填**（传 False=允许覆盖）。
        // 覆盖而非先删：assets.db 有 460MB，先删再拷一旦中途失败，
        // 备份就两头空了。
        if FileExists(ExpandConstant('{app}\_internal\') + Names[I]) then
          FileCopy(ExpandConstant('{app}\_internal\') + Names[I],
                   DataDir + '\' + Names[I], False);
      end;
      UserDataKeptDir := DataDir;
    end;
  end;
  if (CurUninstallStep = usPostUninstall) and (UserDataKeptDir <> '') then
  begin
    Msg := '已保留你的数据备份：' + Nl + UserDataKeptDir + Nl + Nl +
           '重装桌面伙伴-Pilot 后，把该目录下的三个 .db 文件拷回' +
           '安装目录的 _internal 子目录即可恢复。';
    SuppressibleMsgBox(Msg, mbInformation, MB_OK, 0);
  end;
end;
