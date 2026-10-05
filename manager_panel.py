"""管理面板：人物管理 / 音乐管理 / 素材管理 / 知识图谱 / 帮助文档五个标签页。

从托盘菜单「管理面板」打开。面板通过 Pilot 暴露的方法操作，
所有变更即时生效并与托盘菜单状态保持同步。
"""

import html
import os

from PySide6.QtCore import Qt, QStringListModel
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (QDialog, QTabWidget, QWidget, QVBoxLayout, QHBoxLayout,
                               QListWidget, QLabel, QPushButton, QSpinBox, QDoubleSpinBox,
                               QCheckBox, QMessageBox, QFileDialog, QGroupBox, QFormLayout,
                               QTextBrowser, QLineEdit, QCompleter, QSplitter,
                               QComboBox, QProgressDialog, QApplication)

from asset_exporter import export_assets, _human_size
from kg_store import (NODE_TYPES, get_default_store, reset_default_store,
                      rel_cn, type_cn)
from kg_editor import NodeEditDialog, EdgeEditDialog
from kg_view import KGCanvas

APP_VERSION = '3.7'
REPO_URL = 'https://github.com/MrYuPengfei/Pilot-KG-Genshin.git'
REPO_PAGE = 'https://github.com/MrYuPengfei/'

HELP_HTML = f"""
<h2>原神桌面伙伴 v{APP_VERSION} · 帮助文档</h2>
<p><a href="{REPO_PAGE}">开源地址：{REPO_URL}</a></p>
<hr>

<h3>一、导入素材注意事项</h3>
<p>通过「素材管理」标签页导入 <b>zip 文件或目录</b>，
素材包内部必须沿用如下布局（png/ 与 music/ 可只提供其一）：</p>
<pre>
素材包/
  png/&lt;人物&gt;/*.png                人物帧（逐帧 PNG）
  music/&lt;人物&gt;/*.mp3              人物语音
  music/&lt;地区&gt;/background.mp3     地区背景音乐
</pre>
<ul>
<li><b>帧图片</b>：建议统一尺寸、按播放顺序命名（如 0001.png、0002.png…），程序按文件名排序播放；
单帧人物也可正常显示（静态图）。</li>
<li><b>语音命名决定自动分类</b>：「早上好 / 中午好 / 晚上好 / 晚安」归入问候（按时段自动播放），
「闲聊*」归入闲聊，「想要了解*」归入了解；其余命名不分类，仅占用语音列表。</li>
<li><b>地区识别规则</b>：music/ 下只要目录内含 background.mp3 即被识别为地区，
因此请勿把 background.mp3 放进人物语音目录。</li>
<li><b>同名覆盖</b>：重复导入时同名资源会被覆盖更新，不会产生重复记录。</li>
<li><b>新人物默认值</b>：首次导入的人物按 帧间隔 60ms、缩放 1.0 登记，
可在「人物管理」标签页中调整并保存。</li>
<li><b>导入即生效</b>：导入成功后新人物/新地区立即出现在托盘菜单和人物列表中，无需重启。</li>
<li><b>删除素材</b>：「素材管理」标签页可删除已导入的人物或地区；
删除只影响资源库中的记录，不会删除原始素材文件。</li>
<li><b>导出素材</b>：「素材管理」标签页可把资源库中的素材<b>按上面这套布局还原</b>成
目录或 zip——导出的包可以直接再导入，因此可用于备份、离线编辑后回导、分享给他人。
资源库约 460MB，全量导出需要几十秒，期间界面会短暂无响应。</li>
<li><b>版权提醒</b>：本项目仅供学习交流，请勿导入或分发侵犯第三方版权的素材。</li>
</ul>
<hr>

<h3>二、版本变更记录</h3>
<h4>v{APP_VERSION}（当前版本）</h4>
<ul>
<li><b>切换人物时会按时段问好</b>：<b>托盘菜单</b>或管理面板切换角色后，新人物会按
<b>当前时段</b>向你问好——早上说「早上好」、中午说「中午好」、下午与晚上说「晚上好」、
深夜与凌晨说「晚安」。为避免连点同一个人时变成噪音，同一人在同一时段内一分钟只问一次；
<b>换人</b>或<b>跨过时段</b>则立即问候，不受此限制。</li>
<li><b>「素材管理」页的导入与导出拆为两个独立模块</b>：两者职责不同，分组展示更清晰
（「导入素材」/「导出素材」/「配置文件」各为一组）；但所有按钮尺寸统一为
<code>132×32</code>，视觉上整齐一致。导出范围（全部素材 / 仅当前人物）在导出模块内。</li>
<li><b>修复编辑对话框的补全崩溃</b>：在「新增 / 编辑关系」里点击实体搜索框的
补全候选时，曾抛出 <code>itemFromIndex(str)</code>——补全控件发出的信号带的是文本
而非索引，代码却当索引用。现改为按候选文本定位，并让键盘上下移动时也同步类型。</li>
<li><b>消除画布的鼠标抓取警告</b>：节点不再调用基类的鼠标处理（那会抓取鼠标），
双击重建场景后不会再出现 <code>ungrabMouse: not a mouse grabber</code>。</li>
<li><b>修复知识图谱双击崩溃</b>：双击节点时画布会以它为中心重绘，而重绘会销毁
「正在处理这次双击的节点对象」本身，导致抛出
<code>Internal C++ object (NodeItem) already deleted</code>。现已调整事件处理顺序，
并为已销毁的节点加存活标记，滞后到达的点击会被安全忽略。</li>
<li><b>消除启动时的托盘警告</b>：原先托盘在设置图标之前就被显示，Qt 会打印
<code>QSystemTrayIcon::setVisible: No Icon set</code>；现已改为先设图标再显示托盘。</li>
<li><b>代码质量整改</b>（不改变任何功能）：清理 15 处无效的正则转义警告与
无用导入、修正一处会触发 <code>NameError</code> 的 f-string 笔误、
消除重复定义的方法；核心模块与全部测试现已通过静态检查零告警。</li>
</ul>
<h4>v3.6</h4>
<ul>
<li><b>新增素材导出</b>（管理面板「素材管理」页）：可把资源库中的帧、语音、地区背景音乐
还原为 <code>png/</code> 与 <code>music/</code> 目录树，或打包成单个 zip；
可选择「全部素材」或「仅当前人物」。导出结果<b>符合素材包格式</b>，可用「导入素材」直接并入，
也便于备份、离线编辑后回导、分享给他人。</li>
<li><b>修复人物切换异常</b>：切换人物后不再被拽回屏幕左上角（窗口定位参数错位），
窗口尺寸能正确跟随人物的缩放设置（切换遮罩残留导致的尺寸下限未解除），
大缩放角色也不会跑出屏幕；切换后立即保存当前人物，无需等到退出程序。</li>
<li>动画帧循环修正：不再跳过首帧，仅 1~2 帧的自定义角色也能正常播放；
反复切换人物不再累积已删除的界面控件。</li>
<li><b>修复角色问好</b>：语音分类器改按<b>关键词</b>识别问候语——菲谢尔的
「早上好问候菲谢尔.mp3」、迪奥娜的「中午好罐头.mp3」此前被归为无分类，早上问候找不到文件；
时段表补全（原先 0~3 点与 15~17 点共 7 小时完全静默）；缺对应语音时自动降级到该角色
已有的问候，不会因缺文件而中断（切换人物时的问候见 v3.7）。</li>
<li><b>移除「恢复出厂设置」按钮</b>：它会连带清空每个人物调好的帧率与缩放，风险大于便利。
确需恢复出厂值时，删除程序目录下的 <code>config.db</code> 后重新安装即可。</li>
</ul>
<h4>v3.5</h4>
<ul>
<li><b>数据一律由 SQLite 管理</b>：安装包只带 <code>assets.db</code>、<code>kg.db</code>、
<code>config.db</code> 三个库与图标，<b>不含任何 CSV / YAML</b>；</li>
<li>CSV 与 YAML 降级为<b>本地构建输入</b>：由 <code>tools/build_databases.py</code> 生成
<code>kg.db</code> 与出厂 <code>config.db</code>，打包前执行一次即可；</li>
<li><b>运行时不再读取 CSV / YAML</b>——知识图谱来自包内 <code>kg.db</code>，配置来自
<code>config.db</code>。若 <code>config.db</code> 缺失，会用内置默认值并按
<code>assets.db</code> 中已有的人物自动登记帧率与缩放，功能完整可用；</li>
<li>两个库新增库结构版本（<code>schema_version</code>）与来源标记，知识图谱页状态栏
会显示当前图谱的来源与版本；</li>
<li><code>config.db</code> 以「仅当不存在时安装」方式随包分发，<b>升级不会覆盖你的设置</b>。</li>
</ul>
<h4>v3.4</h4>
<ul>
<li><b>目录重构</b>：<code>src/</code> → <code>ico/</code>（图标）；
<code>GenshinKG/data/</code> → <code>data/csv/</code>（知识图谱初始数据）；
<code>GenshinKG/utils/</code> 的脚本并入 <code>tools/</code>。
原先承载素材与数据的 <code>GenshinKG/</code> 目录已全部并入上述位置，不再单独存在；</li>
<li><b>配置改用 SQLite 管理</b>：新增 <code>config_store.py</code>，配置存放于
<code>config.db</code>（表 <code>kv</code> / <code>frame_scale</code> / <code>config_meta</code>）。
原 <code>config.yaml</code> 移至 <code>data/config.yaml</code> 并降级为<b>初始种子与导入导出格式</b>——
首次运行播种一次，之后以库为准。配置不再被程序运行时改写，也不再是 git 冲突高发文件；</li>
<li><b>新增配置文件导入导出</b>（管理面板「素材管理」页）：可导出 YAML / JSON 备份，
或从 YAML / JSON 导入（<b>覆盖</b>会整体替换，<b>合并</b>只补充缺失的人物登记并保留现有设置）；</li>
<li><b>健壮性</b>：配置种子缺失或损坏时自动退回内置默认值，不会因配置问题导致程序无法启动；
导入他人配置时若当前人物在本地无资源，会自动回退到第一个可用人物；
人物帧间隔与缩放在入库前夹紧到面板允许范围（20~1000ms、0.1~3.0）；</li>
</ul>
<h4>v3.3</h4>
<ul>
<li>知识图谱改为数据库存储：新增 <code>kg.db</code>（SQLite，表 kg_nodes / kg_edges / kg_meta），
与素材库 <code>assets.db</code> 并列；首次运行自动从 <code>data/csv</code> 播种，
此后以库为准，CSV 退化为导入/导出格式；</li>
<li>知识图谱新增 CSV 导入与导出：可导入 CSV 目录（<code>label-*.csv</code> + <code>rel-*.csv</code>）
或单个实体表/关系表，支持「合并」与「覆盖」两种模式；导出按原始布局生成
<code>label-&lt;类型&gt;.csv</code> 与 <code>rel-&lt;源类型&gt;-&lt;目标类型&gt;.csv</code>，导出目录可整目录回灌；</li>
<li>知识图谱新增节点与关系编辑：可新增、改名/改类型/改属性、删除实体（连带其关系），
以及新增、改名、换对端、删除关系；关系列表区分方向（<code>→</code> 出边 / <code>←</code> 入边）；</li>
<li>文档全面完善：README、部署说明、重构日志与本页同步至 v3.3，
补齐目录结构、快捷键、知识图谱使用说明与致谢信息；</li>
<li>项目仓库迁移至 <code>Pilot-KG-Genshin</code>，帮助页开源地址同步更新；</li>
<li>安装器发布地址由旧 gitee 仓库改为 GitHub。</li>
</ul>
<h4>v3.2</h4>
<ul>
<li>文档全面完善：README、部署说明、重构日志与本页同步至 v3.2，
补齐目录结构、快捷键、知识图谱使用说明与致谢信息；</li>
<li>项目仓库迁移至 <code>Pilot-KG-Genshin</code>，帮助页开源地址同步更新；</li>
<li>安装器发布地址由旧 gitee 仓库改为 GitHub。</li>
</ul>
<h4>v3.1</h4>
<ul>
<li>全局更名：「桌面宠物」统一改为「桌面伙伴」，主程序类 <code>Pet</code> 更名为 <code>Pilot</code>，
应用名、安装目录与安装包名称同步更名；</li>
<li>入口脚本由 <code>desktoppet.py</code> 更名为 <code>pilot.py</code>，包名同步；</li>
<li>托盘菜单精简：移除「导入素材包」入口（素材导入统一由管理面板「素材管理」承担）。</li>
</ul>
<h4>v3.0</h4>
<ul>
<li>知识图谱可视化首次上线（管理面板「知识图谱」页，基于 data/csv 数据：
12 类实体、1900+ 节点、7500+ 关系，支持实体搜索、自我中心网展示、
单击查看属性与关系、双击节点继续展开）。</li>
</ul>
<h4>v2.1</h4>
<ul>
<li>新增管理面板：人物预览与管理、帧率/缩放调整、音乐控制、资源统计、素材导入；</li>
<li>管理面板内置帮助文档页；</li>
<li>配置变更即时保存，不再依赖退出时写盘。</li>
</ul>
<h4>v2.0</h4>
<ul>
<li>资源收进单个 SQLite 数据库 assets.db（替代近万个零散文件，附带文件系统回退）；</li>
<li>动画帧预加载缓存：消除每帧磁盘读取与重复解码缩放，动画更流畅；</li>
<li>新增第三方素材导入模块（目录/zip），人物与地区菜单改为动态生成；</li>
<li>修复单帧人物索引越界等多项问题；</li>
<li>全新安装包：每用户目录安装（免管理员）、支持覆盖安装与正常卸载。</li>
</ul>
<h4>v1.1</h4>
<ul>
<li>基础桌面伙伴：人物切换、拖动、隐藏、时段问候、闲聊/了解语音、地区背景音乐。</li>
</ul>
<hr>

<h3>三、管理面板使用说明</h3>
<p>本面板共五个标签页，所有改动<b>即时生效并自动保存</b>（写入 config.db / assets.db / kg.db，
无需重启程序）。</p>
<table border="1" cellspacing="0" cellpadding="4">
<tr><th>标签页</th><th>能做什么</th></tr>
<tr><td>人物管理</td>
<td>左侧列出全部人物（含导入的），选中后显示首帧预览与帧数/语音数；
可按人物调整帧间隔（20~1000ms）与缩放比例（0.1~3.0）、「设为当前伙伴」、「删除此人物」；
列表中的「当前」标记即为正在显示的伙伴。</td></tr>
<tr><td>音乐管理</td>
<td>选择地区播放/停止背景音乐、开关人物语音、一键静音；
与托盘「音乐」菜单的「～」选中状态双向同步。</td></tr>
<tr><td>素材管理</td>
<td>查看资源统计（存储后端、人物/地区/帧/语音数量、数据库大小）；
导入 zip 或目录素材包；删除已导入的人物或地区；
<b>导出素材</b>（全部或仅当前人物；目录或 zip，结果可再导入）；
导出/导入配置文件（YAML / JSON）。</td></tr>
<tr><td>知识图谱</td>
<td>搜索实体（人物、武器、材料、副本、料理…）后展示以该实体为中心的自我中心网；
<b>单击</b>节点看属性与关系清单，<b>双击</b>节点以它为中心重新展开，滚轮缩放、拖拽平移。
右侧可新增/编辑/删除<b>实体</b>与<b>关系</b>，顶部可导入/导出 CSV、重新载入。
首次打开该页时才加载图谱数据。</td></tr>
<tr><td>帮助文档</td><td>本页：导入注意事项、版本记录、开源库许可与项目地址。</td></tr>
</table>
<p><b>快捷键</b>：Windows 下 Ctrl + ↑ / ↓ 缩放人物，Ctrl + Q 退出；
桌面右键可隐藏伙伴，托盘菜单可随时唤回。</p>

<h4>配置文件：存储、导入与导出</h4>
<p>配置存放于程序目录的 <b>config.db</b>（SQLite），包含三张表：<code>kv</code>（当前人物、
语音开关、背景音乐、素材路径等标量项）、<code>frame_scale</code>（每个人物的帧间隔与缩放）、
<code>config_meta</code>（记录播种来源等元信息）。</p>
<p>本文件随安装包分发一份<b>出厂值</b>，你在此处的任何修改都会写回同一个文件。
为避免升级时覆盖你的设置，<b>覆盖安装只会在该文件不存在时才写入</b>——
想恢复出厂值，删掉 <code>config.db</code> 后重新安装即可。</p>
<p>出厂值由 <code>data/config.yaml</code> 在打包阶段生成（<code>tools/build_databases.py</code>），
运行时程序<b>不再读取任何 YAML</b>；YAML 仅作为构建输入与手动导入的交换格式
（也是后续服务器下发的载荷格式）。若 <code>config.db</code> 缺失，程序会用内置默认值
并按 <code>assets.db</code> 中已有的人物自动登记帧率与缩放，<b>功能完整可用</b>。</p>
<ul>
<li><b>导出 YAML / JSON</b>：把当前配置存到指定文件。YAML 与旧版 config.yaml 同格式，
可手工编辑后回导；JSON 便于程序化处理。</li>
<li><b>导入配置</b>：选择 YAML 或 JSON 文件后，会让你选择模式——
<b>覆盖</b>整体替换当前设置（当前人物、语音开关、背景音乐都会随之切换），
<b>合并</b>则只补充缺失的人物登记、保留现有设置。导入报告会列出无法识别的键（会被忽略）。</li>
<li><b>恢复出厂值</b>：面板不再提供一键重置（避免误清空调好的缩放与帧率）。
如确需恢复出厂值，<b>删除程序目录下的 <code>config.db</code> 后重新安装</b>即可——
安装程序只在文件不存在时才写入出厂配置，因此不会覆盖你已有的设置。</li>
<li><b>容错说明</b>：库文件缺失或配置内容损坏时会自动使用内置默认值，程序不会因此无法启动；
导入的配置若把当前人物指向了本地没有资源的人物，启动时会自动回退到第一个可用人物。</li>
<li><b>迁移机器</b>：配置、资源、图谱分属三个库文件——<code>config.db</code>、<code>assets.db</code>、<code>kg.db</code>，
均位于程序目录。换机器时把这三个文件（或导出的配置文件）一并带过去即可。</li>
</ul>

<h4>知识图谱：数据存储与编辑</h4>
<p>图谱数据存放于程序目录下的 <b>kg.db</b>（SQLite），随安装包分发，<b>运行时不读取 CSV</b>。
它包含三张表：<code>kg_nodes</code>（实体，属性以 JSON 保存）、<code>kg_edges</code>（有向关系）、
<code>kg_meta</code>（库结构版本与来源等元信息）。状态栏会显示当前图谱的来源与版本。
若 <code>kg.db</code> 缺失，可重新安装，或用下方「导入 CSV」从 CSV 导入。</p>
<ul>
<li><b>编辑实体</b>：选中实体后可改名、改类型、增删属性行。改名或改类型时，
其全部关系的两端会自动跟着迁移，不会出现断链。</li>
<li><b>删除实体</b>：会连带删除该实体的所有关系，操作前有确认弹窗提示关系条数。</li>
<li><b>编辑关系</b>：在关系列表中选中一条（<code>→</code> 表示出边、<code>←</code> 表示入边），
可改关系名或更换对端实体；两端可直接输入新名字，输入不存在的名字会自动按所选类型建为新实体。</li>
<li><b>关系名</b>：填写 <code>element_is</code>、<code>part_of</code> 等已有键会显示对应中文
（神之眼、属于…）；也可以自填中文或英文，此时直接按原文显示。</li>
<li><b>导入 CSV</b>：可选择 CSV 目录（推荐，<code>label-*.csv</code> +
<code>rel-*.csv</code>）或单个 CSV 文件。单个文件按表头自动识别：
含 <code>node1,rel,node2</code> 视为关系表，含 <code>name</code> 且含
<code>label</code>/<code>type</code> 视为实体表。导入时可选
<b>合并</b>（同名实体覆盖属性）或<b>覆盖</b>（先清空现有图谱），导入完成后会报告新增/跳过数量。</li>
<li><b>导出 CSV</b>：把当前图谱导出为目录，实体表命名为 <code>label-&lt;类型&gt;.csv</code>，
关系表按真实方向命名为 <code>rel-&lt;源类型&gt;-&lt;目标类型&gt;.csv</code>；
该目录可被「导入 CSV」整目录回灌，便于备份、分享与用表格软件编辑。</li>
<li><b>重新载入</b>：丢弃内存中的状态，从 kg.db 重新读入。</li>
<li><b>提示</b>：直接删除或替换 <code>kg.db</code> 后重启程序，会重新从初始 CSV 播种，
即恢复为出厂图谱；若要保留自己的编辑，请先用「导出 CSV」备份。</li>
</ul>
<hr>

<h3>四、第三方开源库</h3>
<table border="1" cellspacing="0" cellpadding="4">
<tr><th>库</th><th>用途</th><th>许可证</th></tr>
<tr><td>PySide6 (Qt for Python)</td><td>窗口、托盘、管理面板等全部 GUI</td><td>LGPLv3</td></tr>
<tr><td>pygame-ce</td><td>语音与背景音乐播放</td><td>LGPLv2.1</td></tr>
<tr><td>PyYAML</td><td>配置文件读写</td><td>MIT</td></tr>
<tr><td>SQLite（Python 内置 sqlite3）</td><td>资源数据库 assets.db</td><td>Public Domain</td></tr>
<tr><td>pytest（开发依赖）</td><td>自动化测试</td><td>MIT</td></tr>
<tr><td>PyInstaller（打包工具）</td><td>生成 Windows 可执行程序</td><td>GPL（打包产物不受限）</td></tr>
<tr><td>Inno Setup（打包工具）</td><td>生成安装向导</td><td>Inno Setup License</td></tr>
</table>
<hr>

<h3>五、音视频素材</h3>
<p>本软件仅供开发研究玩乐，请勿用作商业用途。音视频素材版权归上海米哈游网络科技股份有限公司所有。<br>
</p>
<hr>

<h3>六、后续开发计划</h3>
<p>
本项目为 <a href="{REPO_PAGE}">Pilot-KG</a> 系列的前置项目，<br>
后续将扩展为跨平台、可自定义主题与素材、具备知识获取与匿名聊天能力的桌面助手。
</p>

<hr>
"""


class ManagerPanel(QDialog):
    def __init__(self, pilot, config):
        super().__init__(pilot)
        self.pilot = pilot
        self.store = pilot.store
        self.config = config
        # v3.4：配置以 SQLite 为准（config.db），config dict 是其内存副本
        self.config_store = pilot.config_store
        self.setWindowTitle(f'原神桌面伙伴 v{APP_VERSION} · 管理面板')
        # 窗口图标：与系统托盘一致，使用当前伙伴的当前帧（不依赖磁盘路径）
        if pilot._frames:
            self.setWindowIcon(QIcon(pilot._frames[pilot.index][0]))
        self.resize(960, 620)

        layout = QVBoxLayout(self)
        self.tabs = QTabWidget(self)
        layout.addWidget(self.tabs)

        self._build_roles_tab()
        self._build_music_tab()
        self._build_assets_tab()
        self._build_kg_tab()
        self._build_help_tab()
        # 知识图谱页首次被打开时才加载数据（1900+ 节点，避免拖慢面板启动）
        self.tabs.currentChanged.connect(self._on_tab_changed)
        self.refresh()

    def _on_tab_changed(self, index):
        if self.tabs.tabText(index) == '知识图谱':
            self._ensure_kg_loaded()

    # ================= 知识图谱 =================

    def _build_kg_tab(self):
        tab = QWidget()
        root = QVBoxLayout(tab)

        # 顶部：搜索栏 + 数据操作
        top = QHBoxLayout()
        self.kg_search = QLineEdit()
        self.kg_search.setPlaceholderText('搜索实体（人物/武器/材料/副本/料理…），回车定位')
        self.kg_search.setMaximumWidth(320)
        self.kg_completer = QCompleter(self)
        self.kg_completer.setCaseSensitivity(Qt.CaseInsensitive)
        self.kg_completer.setFilterMode(Qt.MatchContains)
        self.kg_search.setCompleter(self.kg_completer)
        self.kg_search.returnPressed.connect(self._on_kg_search)
        top.addWidget(self.kg_search)
        search_btn = QPushButton('定位')
        search_btn.clicked.connect(self._on_kg_search)
        top.addWidget(search_btn)
        top.addStretch(1)
        for text, slot, tip in (
                ('导入 CSV', self._on_kg_import, '从 CSV 文件或目录导入图谱数据'),
                ('导出 CSV', self._on_kg_export, '把当前图谱导出为 CSV 目录'),
                ('重新载入', self._on_kg_reload, '丢弃内存改动，从数据库重新载入'),
        ):
            btn = QPushButton(text)
            btn.setToolTip(tip)
            btn.clicked.connect(slot)
            top.addWidget(btn)
        root.addLayout(top)

        # 中部：画布 + 详情/关系/操作
        splitter = QSplitter(Qt.Horizontal)
        self.kg_canvas = KGCanvas()
        splitter.addWidget(self.kg_canvas)

        side = QWidget()
        side_layout = QVBoxLayout(side)
        side_layout.setContentsMargins(0, 0, 0, 0)

        self.kg_detail = QTextBrowser()
        self.kg_detail.setMaximumHeight(230)
        side_layout.addWidget(self.kg_detail)

        self.kg_rel_list = QListWidget()
        self.kg_rel_list.setToolTip('当前实体的关系，选中后可编辑或删除')
        self.kg_rel_list.currentRowChanged.connect(
            lambda _i: self._sync_kg_buttons())
        side_layout.addWidget(self.kg_rel_list, 1)

        # 实体与关系操作按钮
        node_row = QHBoxLayout()
        self.kg_add_node_btn = QPushButton('新增实体')
        self.kg_add_node_btn.clicked.connect(self._on_kg_add_node)
        self.kg_edit_node_btn = QPushButton('编辑实体')
        self.kg_edit_node_btn.clicked.connect(self._on_kg_edit_node)
        self.kg_del_node_btn = QPushButton('删除实体')
        self.kg_del_node_btn.clicked.connect(self._on_kg_delete_node)
        for btn in (self.kg_add_node_btn, self.kg_edit_node_btn, self.kg_del_node_btn):
            node_row.addWidget(btn)
        side_layout.addLayout(node_row)

        rel_row = QHBoxLayout()
        self.kg_add_rel_btn = QPushButton('新增关系')
        self.kg_add_rel_btn.clicked.connect(self._on_kg_add_edge)
        self.kg_edit_rel_btn = QPushButton('编辑关系')
        self.kg_edit_rel_btn.clicked.connect(self._on_kg_edit_edge)
        self.kg_del_rel_btn = QPushButton('删除关系')
        self.kg_del_rel_btn.clicked.connect(self._on_kg_delete_edge)
        for btn in (self.kg_add_rel_btn, self.kg_edit_rel_btn, self.kg_del_rel_btn):
            rel_row.addWidget(btn)
        side_layout.addLayout(rel_row)

        side.setMaximumWidth(320)
        splitter.addWidget(side)
        splitter.setStretchFactor(0, 1)
        root.addWidget(splitter, 1)

        self.kg_status = QLabel('')
        self.kg_status.setStyleSheet('color: #7f8c8d;')
        root.addWidget(self.kg_status)

        legend = QLabel('　'.join(
            f'<font color="{color}">●</font>{cn}'
            for cn, color in NODE_TYPES.values()))
        legend.setTextFormat(Qt.RichText)
        legend.setStyleSheet('color: #7f8c8d;')
        root.addWidget(legend)

        hint = QLabel('单击节点查看详情，双击节点以其为中心展开，滚轮缩放、拖拽平移；'
                      '右侧可编辑实体与关系')
        hint.setStyleSheet('color: #7f8c8d;')
        root.addWidget(hint)

        self.kg_canvas.nodeSelected.connect(self._on_kg_node_selected)
        self.kg_canvas.nodeExpanded.connect(self._on_kg_node_expanded)
        self.tabs.addTab(tab, '知识图谱')

        self._kg_ready = False   # 图谱数据较大，首次切换到本页时再加载
        self._kg_current = None  # 当前选中实体键
        self._kg_rel_edges = []  # 与关系列表一一对应的 (rel, 对端键, 方向)

    def _ensure_kg_loaded(self):
        if self._kg_ready:
            return True
        try:
            self.kg = get_default_store(self.store.base_dir)
        except Exception as e:
            # 错误信息可能是多行（如 kg.db 缺失时的操作指引），逐行转义后换行显示
            detail = '<br>'.join(html.escape(line) for line in str(e).splitlines())
            self.kg_detail.setHtml(
                f'<p style="color:#c0392b"><b>知识图谱数据加载失败</b></p>'
                f'<p style="color:#7f8c8d">{detail}</p>'
                f'<p>知识图谱以 <code>kg.db</code> 随安装包分发（不含 CSV）。'
                f'若库文件缺失，可重新安装，或点上方「导入 CSV」'
                f'从 CSV 导入——CSV 既可由本地 <code>data/csv</code> 提供，'
                f'也可由服务器下发（格式完全相同）。</p>')
            return False
        self.kg_canvas.bind(self.kg)
        self._kg_refresh_completer()
        self._kg_update_status()
        self.kg_detail.setHtml(
            '<h3>原神知识图谱</h3>'
            '<p>在上方搜索框输入实体名称开始探索，例如：钟离、蒙德、护摩之杖。</p>'
            '<p>也可直接新增实体与关系，或用「导入 CSV」合并外部图谱数据。</p>')
        self._kg_ready = True
        self._sync_kg_buttons()
        return True

    def _kg_refresh_completer(self):
        self.kg_completer.setModel(QStringListModel(self.kg.all_names()))

    def _kg_update_status(self):
        s = self.kg.stats()
        size = f' · 库 {s["db_size_mb"]:.1f} MB' if s['db_size_mb'] is not None else ''
        # 附带数据来源（构建来源 / 版本），既是构建追溯，也便于将来核对服务器下发
        info = self.kg.info() if hasattr(self.kg, 'info') else {}
        origin = info.get('built_from', 'unknown')
        app_v = info.get('app_version', '')
        tail = f' · 来源 {origin}' + (f' v{app_v}' if app_v and app_v != 'unknown' else '')
        self.kg_status.setText(
            f'实体 {s["nodes"]} 个 · 关系 {s["edges"]} 条 · 存储 SQLite (kg.db){size}{tail}')

    def _on_kg_search(self):
        if not self._ensure_kg_loaded():
            return
        text = self.kg_search.text().strip()
        if not text:
            return
        keys = self.kg.find(text)
        if not keys:
            keys = self.kg.search(text, limit=1)
        if not keys:
            self.kg_detail.setHtml(f'<p>未找到与「{text}」相关的实体。</p>')
            return
        self.kg_canvas.show_ego(keys[0])

    def _on_kg_node_selected(self, key):
        if not getattr(self, '_kg_ready', False):
            return
        node = self.kg.nodes.get(key)
        if node is None:
            return
        self._kg_current = key
        cn_type = NODE_TYPES.get(key[0], (key[0],))[0]
        parts = [f'<h3>{key[1]} <small style="color:#7f8c8d">[{cn_type}]</small></h3>']
        if node['attrs']:
            parts.append('<table border="0" cellspacing="0" cellpadding="2">')
            for k, v in node['attrs'].items():
                v = v.replace('<', '&lt;')
                if len(v) > 300:
                    v = v[:300] + '…'
                parts.append(f'<tr><td><b>{k}</b></td><td>{v}</td></tr>')
            parts.append('</table>')
        else:
            parts.append('<p style="color:#7f8c8d">（无属性）</p>')
        self.kg_detail.setHtml(''.join(parts))
        self._kg_fill_relations(key)
        self._sync_kg_buttons()

    def _kg_fill_relations(self, key):
        """把当前实体有向关系填进列表：出边显示「关系 → 对端」，入边显示「对端 → 关系」。"""
        self.kg_rel_list.blockSignals(True)
        self.kg_rel_list.clear()
        self._kg_rel_edges = []
        for rel, other, direction in self.kg.edges_of(key):
            o_type = NODE_TYPES.get(other[0], (other[0],))[0]
            arrow = '→' if direction == 'out' else '←'
            self.kg_rel_list.addItem(f'{rel_cn(rel)} {arrow} {other[1]}  [{o_type}]')
            self._kg_rel_edges.append((rel, other, direction))
        self.kg_rel_list.blockSignals(False)
        if not self._kg_rel_edges:
            self.kg_rel_list.addItem('（暂无关系）')
            self.kg_rel_list.setEnabled(False)
        else:
            self.kg_rel_list.setEnabled(True)

    def _on_kg_node_expanded(self, key):
        self.kg_canvas.show_ego(key)

    # ---------- 知识图谱：实体编辑 ----------

    def _sync_kg_buttons(self):
        """按当前选中实体与关系列表选中项启用/禁用按钮。"""
        has_node = getattr(self, '_kg_current', None) is not None
        has_rel = bool(getattr(self, '_kg_rel_edges', [])) and \
            self.kg_rel_list.currentRow() >= 0
        for btn in (self.kg_edit_node_btn, self.kg_del_node_btn):
            btn.setEnabled(has_node)
        for btn in (self.kg_add_rel_btn, self.kg_edit_rel_btn, self.kg_del_rel_btn):
            btn.setEnabled(has_node)
        self.kg_edit_rel_btn.setEnabled(has_rel)
        self.kg_del_rel_btn.setEnabled(has_rel)

    def _kg_selected_edge(self):
        """返回关系列表当前选中项 (rel, 对端键, 方向)，未选中返回 None。"""
        row = self.kg_rel_list.currentRow()
        if 0 <= row < len(getattr(self, '_kg_rel_edges', [])):
            return self._kg_rel_edges[row]
        return None

    def _kg_after_change(self, keep_key=None, keep_edge=None):
        """编辑/导入后统一刷新：索引、自动补全、状态、画布与详情。"""
        self._kg_refresh_completer()
        self._kg_update_status()
        key = keep_key or self._kg_current
        if key is not None and key not in self.kg.nodes:
            key = None
        if key is None:
            self._kg_current = None
            self.kg_canvas.clear()
            self.kg_rel_list.clear()
            self._kg_rel_edges = []
            self.kg_detail.setHtml('<p style="color:#7f8c8d">'
                                   '当前实体已不存在，请重新搜索定位。</p>')
            self._sync_kg_buttons()
            return
        self.kg_canvas.show_ego(key)
        if keep_edge is not None:
            # 关系列表重建后按关系名+对端重新定位，保持选中
            for i, (rel, other, _d) in enumerate(self._kg_rel_edges):
                if rel == keep_edge[0] and other == keep_edge[1]:
                    self.kg_rel_list.setCurrentRow(i)
                    break
        self._sync_kg_buttons()

    def _on_kg_add_node(self):
        if not self._ensure_kg_loaded():
            return
        dlg = NodeEditDialog(self.kg, None, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        ntype, name, attrs = dlg.values()
        try:
            created = self.kg.add_node(ntype, name, attrs, overwrite=False)
        except ValueError as e:
            QMessageBox.warning(self, '新增失败', str(e))
            return
        if not created:
            QMessageBox.information(
                self, '已存在',
                f'「{type_cn(ntype)} · {name}」已存在。'
                '如需修改其属性，请使用「编辑实体」。')
            return
        self._kg_after_change(keep_key=(ntype, name))

    def _on_kg_edit_node(self):
        key = getattr(self, '_kg_current', None)
        if key is None or not self._ensure_kg_loaded():
            return
        dlg = NodeEditDialog(self.kg, key, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        ntype, name, attrs = dlg.values()
        try:
            new_key = self.kg.update_node(key, name=name, ntype=ntype, attrs=attrs)
        except (ValueError, KeyError) as e:
            QMessageBox.warning(self, '保存失败', str(e).strip("'"))
            return
        self._kg_after_change(keep_key=new_key)

    def _on_kg_delete_node(self):
        key = getattr(self, '_kg_current', None)
        if key is None or not self._ensure_kg_loaded():
            return
        n_rel = len(self.kg.edges_of(key))
        ret = QMessageBox.question(
            self, '确认删除',
            f'确定删除实体「{key[1]}」吗？\n其关联的 {n_rel} 条关系也会一并删除。')
        if ret != QMessageBox.StandardButton.Yes:
            return
        nodes, edges = self.kg.delete_node(key)
        self._kg_current = None
        self._kg_after_change()
        QMessageBox.information(
            self, '已删除', f'已删除实体 {nodes} 个、关联关系 {edges} 条。')

    # ---------- 知识图谱：关系编辑 ----------

    def _on_kg_add_edge(self):
        anchor = getattr(self, '_kg_current', None)
        if not self._ensure_kg_loaded():
            return
        dlg = EdgeEditDialog(self.kg, None, anchor=anchor,
                             exclude=[anchor] if anchor else (), parent=self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        src, rel, dst = dlg.values()
        missing = [n for n, k in (('源', src), ('目标', dst)) if k is None]
        if missing or not rel:
            QMessageBox.warning(self, '信息不完整', '请填写关系名与两端实体。')
            return
        try:
            for key in (src, dst):
                if key not in self.kg.nodes:      # 对话框允许直接输入新实体名
                    self.kg.add_node(key[0], key[1], {}, overwrite=False)
            created = self.kg.add_edge(src, rel, dst, overwrite=False)
        except (ValueError, KeyError) as e:
            QMessageBox.warning(self, '新增失败', str(e).strip("'"))
            return
        if not created:
            QMessageBox.information(self, '已存在', '这两者之间已存在同名关系。')
            return
        self._kg_after_change(keep_edge=(rel, dst))

    def _on_kg_edit_edge(self):
        anchor = getattr(self, '_kg_current', None)
        selected = self._kg_selected_edge()
        if anchor is None or selected is None or not self._ensure_kg_loaded():
            return
        rel, other, direction = selected
        # 统一以当前实体为源端构造有向三元组，方向由列表给出
        edge = (anchor, rel, other) if direction == 'out' else (other, rel, anchor)
        dlg = EdgeEditDialog(self.kg, edge=edge, anchor=anchor, parent=self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        src, new_rel, dst = dlg.values()
        missing = [n for n, k in (('源', src), ('目标', dst)) if k is None]
        if missing or not new_rel:
            QMessageBox.warning(self, '信息不完整', '请填写关系名与两端实体。')
            return
        try:
            for key in (src, dst):
                if key not in self.kg.nodes:
                    self.kg.add_node(key[0], key[1], {}, overwrite=False)
            self.kg.update_edge(edge, (src, new_rel, dst))
        except (ValueError, KeyError) as e:
            QMessageBox.warning(self, '保存失败', str(e).strip("'"))
            return
        self._kg_after_change(keep_edge=(new_rel, dst))

    def _on_kg_delete_edge(self):
        anchor = getattr(self, '_kg_current', None)
        selected = self._kg_selected_edge()
        if anchor is None or selected is None or not self._ensure_kg_loaded():
            return
        rel, other, _direction = selected
        ret = QMessageBox.question(
            self, '确认删除',
            f'确定删除关系「{rel_cn(rel)}」吗？\n{anchor[1]} — {rel_cn(rel)} — {other[1]}')
        if ret != QMessageBox.StandardButton.Yes:
            return
        self.kg.delete_edge_touching(anchor, rel, other)
        self._kg_after_change()

    # ---------- 知识图谱：导入 / 导出 / 重载 ----------

    def _on_kg_import(self):
        """导入入口：先选来源类型（图谱目录最贴合原始布局，单文件用于补充零散表）。"""
        if not self._ensure_kg_loaded():
            return
        box = QMessageBox(self)
        box.setWindowTitle('导入知识图谱')
        box.setText('选择要导入的内容：')
        dir_btn = box.addButton('CSV 目录（含 label-*.csv / rel-*.csv）',
                                QMessageBox.ButtonRole.AcceptRole)
        file_btn = box.addButton('单个 CSV 文件', QMessageBox.ButtonRole.AcceptRole)
        box.addButton('取消', QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is dir_btn:
            path = QFileDialog.getExistingDirectory(
                self, '选择知识图谱 CSV 目录')
        elif box.clickedButton() is file_btn:
            path, _ = QFileDialog.getOpenFileName(
                self, '选择知识图谱 CSV（实体表或关系表）', '', 'CSV 文件 (*.csv)')
        else:
            return
        if path:
            self._kg_do_import(path)

    def _kg_do_import(self, path):
        """导入前确认合并/覆盖，覆盖模式会清空现有图谱。"""
        s = self.kg.stats()
        ret = QMessageBox.question(
            self, '导入知识图谱',
            f'将导入：{os.path.basename(path)}\n\n'
            f'当前库中有实体 {s["nodes"]} 个、关系 {s["edges"]} 条。\n\n'
            f'确定 = 合并（同名实体覆盖属性）\n'
            f'取消 = 覆盖（先清空现有图谱）',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            | QMessageBox.StandardButton.Cancel)
        if ret == QMessageBox.StandardButton.Cancel:
            return
        replace = ret == QMessageBox.StandardButton.No
        try:
            report = self.kg.import_csv(path, replace=replace)
        except Exception as e:
            QMessageBox.warning(self, '导入失败', str(e))
            return
        self._kg_current = None
        self._kg_after_change()
        msg = (f'实体：新增 {report["nodes_added"]}，更新 {report["nodes_updated"]}\n'
               f'关系：新增 {report["edges_added"]}，跳过 {report["edges_skipped"]}')
        if report['stubs']:
            msg += f'\n自动补建实体 {report["stubs"]} 个'
        if report['ignored_files']:
            msg += f'\n忽略无法识别的文件：{", ".join(report["ignored_files"])}'
        QMessageBox.information(self, '导入完成', msg)

    def _on_kg_export(self):
        if not self._ensure_kg_loaded():
            return
        path = QFileDialog.getExistingDirectory(self, '选择导出目录')
        if not path:
            return
        try:
            report = self.kg.export_csv(path)
        except Exception as e:
            QMessageBox.warning(self, '导出失败', str(e))
            return
        QMessageBox.information(
            self, '导出完成',
            f'实体表 {report["node_files"]} 个（{report["node_rows"]} 行）\n'
            f'关系表 {report["edge_files"]} 个（{report["edge_rows"]} 行）\n\n'
            f'已导出到：{report["dir"]}\n'
            f'该目录可被「导入 CSV」整目录回灌。')

    def _on_kg_reload(self):
        """重置单例并重新打开数据库，丢弃内存中的未落库改动。"""
        if not self._ensure_kg_loaded():
            return
        reset_default_store()
        self._kg_ready = False
        self._kg_current = None
        if self._ensure_kg_loaded():
            self._kg_after_change()
        QMessageBox.information(self, '已重新载入', '知识图谱已从 kg.db 重新读入。')


    # ================= 帮助文档 =================

    def _build_help_tab(self):
        tab = QWidget()
        root = QVBoxLayout(tab)
        browser = QTextBrowser()
        browser.setHtml(HELP_HTML)
        browser.setOpenExternalLinks(True)  # 链接交给系统浏览器打开
        root.addWidget(browser)
        self.tabs.addTab(tab, '帮助文档')

    # ================= 人物管理 =================

    def _build_roles_tab(self):
        tab = QWidget()
        root = QHBoxLayout(tab)

        self.role_list = QListWidget()
        self.role_list.setMaximumWidth(200)
        self.role_list.currentTextChanged.connect(self._on_role_selected)
        root.addWidget(self.role_list)

        right = QVBoxLayout()

        preview_row = QHBoxLayout()
        self.preview = QLabel('（无预览）')
        self.preview.setFixedSize(180, 180)
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setStyleSheet('border: 1px solid #ccc; background: transparent;')
        preview_row.addWidget(self.preview)

        info_box = QGroupBox('信息')
        info_form = QFormLayout(info_box)
        self.role_frames_label = QLabel('-')
        self.role_voices_label = QLabel('-')
        self.role_status_label = QLabel('-')
        info_form.addRow('帧数量:', self.role_frames_label)
        info_form.addRow('语音数量:', self.role_voices_label)
        info_form.addRow('状态:', self.role_status_label)
        preview_row.addWidget(info_box, stretch=1)
        right.addLayout(preview_row)

        setting_box = QGroupBox('播放设置（对该人物生效）')
        setting_form = QFormLayout(setting_box)
        self.interval_spin = QSpinBox()
        self.interval_spin.setRange(20, 1000)
        self.interval_spin.setSuffix(' ms')
        self.scale_spin = QDoubleSpinBox()
        self.scale_spin.setRange(0.1, 3.0)
        self.scale_spin.setSingleStep(0.05)
        self.scale_spin.setDecimals(2)
        setting_form.addRow('帧间隔:', self.interval_spin)
        setting_form.addRow('缩放比例:', self.scale_spin)
        right.addWidget(setting_box)

        btn_row = QHBoxLayout()
        self.apply_btn = QPushButton('应用设置')
        self.apply_btn.clicked.connect(self._apply_role_settings)
        self.set_current_btn = QPushButton('设为当前伙伴')
        self.set_current_btn.clicked.connect(self._set_current_role)
        self.delete_btn = QPushButton('删除此人物')
        self.delete_btn.clicked.connect(self._delete_role)
        btn_row.addWidget(self.apply_btn)
        btn_row.addWidget(self.set_current_btn)
        btn_row.addWidget(self.delete_btn)
        right.addLayout(btn_row)
        right.addStretch(1)

        root.addLayout(right, stretch=1)
        self.tabs.addTab(tab, '人物管理')

    def _on_role_selected(self, role):
        if not role:
            return
        frames = self.store.list_frames(role)
        voices = self.store.list_voices(role)
        self.role_frames_label.setText(str(len(frames)))
        self.role_voices_label.setText(str(len(voices)))
        self.role_status_label.setText('当前伙伴' if role == self.pilot.role_name else '未使用')
        self.role_status_label.setStyleSheet(
            'color: #d33; font-weight: bold;' if role == self.pilot.role_name else '')

        if frames:
            pm = QPixmap()
            pm.loadFromData(self.store.read_frame(role, frames[0]))
            self.preview.setPixmap(pm.scaled(
                self.preview.size(), Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation))
        else:
            self.preview.setPixmap(QPixmap())
            self.preview.setText('（无帧）')

        interval, scale = self.config['frame_scale'].get(role, [60, 1.0])
        self.interval_spin.setValue(int(interval))
        self.scale_spin.setValue(float(scale))

    def _selected_role(self):
        item = self.role_list.currentItem()
        return item.text() if item else None

    def _apply_role_settings(self):
        role = self._selected_role()
        if not role:
            return
        self.pilot.set_role_timing(role, self.interval_spin.value(), self.scale_spin.value())
        QMessageBox.information(self, '已应用', f'「{role}」的播放设置已保存。')

    def _set_current_role(self):
        role = self._selected_role()
        if not role or role == self.pilot.role_name:
            return
        self.pilot.reshow(role)
        self._on_role_selected(role)
        self.pilot.save_config()

    def _delete_role(self):
        role = self._selected_role()
        if not role:
            return
        roles = self.store.list_roles()
        if len(roles) <= 1:
            QMessageBox.warning(self, '无法删除', '至少需要保留一个人物。')
            return
        ret = QMessageBox.question(
            self, '确认删除',
            f'确定删除「{role}」的全部帧和语音吗？此操作不可恢复。')
        if ret != QMessageBox.StandardButton.Yes:
            return
        try:
            self.store.delete_role(role)
        except RuntimeError as e:
            QMessageBox.warning(self, '无法删除', str(e))
            return
        self.config['frame_scale'].pop(role, None)
        if role == self.pilot.role_name:
            self.pilot.reshow(self.store.list_roles()[0])
        self.pilot._rebuild_role_menu()
        self.pilot.save_config()
        self.refresh()

    # ================= 音乐管理 =================

    def _build_music_tab(self):
        tab = QWidget()
        root = QHBoxLayout(tab)

        self.area_list = QListWidget()
        self.area_list.setMaximumWidth(200)
        root.addWidget(self.area_list)

        right = QVBoxLayout()
        bgm_box = QGroupBox('背景音乐')
        bgm_row = QHBoxLayout(bgm_box)
        self.play_bgm_btn = QPushButton('播放选中地区')
        self.play_bgm_btn.clicked.connect(self._play_selected_area)
        self.stop_bgm_btn = QPushButton('停止背景音乐')
        self.stop_bgm_btn.clicked.connect(self._stop_bgm)
        bgm_row.addWidget(self.play_bgm_btn)
        bgm_row.addWidget(self.stop_bgm_btn)
        right.addWidget(bgm_box)

        self.bgm_state_label = QLabel('-')
        right.addWidget(self.bgm_state_label)

        voice_box = QGroupBox('人物语音')
        voice_layout = QVBoxLayout(voice_box)
        self.voice_checkbox = QCheckBox('启用人物语音（问候 / 闲聊 / 了解）')
        self.voice_checkbox.toggled.connect(self.pilot.set_voice_enabled)
        voice_layout.addWidget(self.voice_checkbox)
        right.addWidget(voice_box)

        self.mute_all_btn = QPushButton('关闭所有声音')
        self.mute_all_btn.clicked.connect(self._mute_all)
        right.addWidget(self.mute_all_btn)
        right.addStretch(1)

        root.addLayout(right, stretch=1)
        self.tabs.addTab(tab, '音乐管理')

    def _play_selected_area(self):
        item = self.area_list.currentItem()
        if not item:
            return
        self.pilot.play_area_bgm(item.text())
        self._refresh_music_state()

    def _stop_bgm(self):
        self.pilot.stop_bgm()
        self._refresh_music_state()

    def _mute_all(self):
        self.pilot.set_voice_enabled(False)
        self.pilot.stop_bgm()
        self._refresh_music_state()

    def _refresh_music_state(self):
        current = self.config.get('bg_music')
        self.bgm_state_label.setText(
            f'正在播放: {current}' if current else '背景音乐: 未播放')
        self.voice_checkbox.blockSignals(True)
        self.voice_checkbox.setChecked(self.pilot.audio_player)
        self.voice_checkbox.blockSignals(False)

    # ================= 素材管理 =================

    def _build_assets_tab(self):
        tab = QWidget()
        root = QVBoxLayout(tab)

        stats_box = QGroupBox('资源统计')
        stats_form = QFormLayout(stats_box)
        self.stat_backend = QLabel('-')
        self.stat_roles = QLabel('-')
        self.stat_areas = QLabel('-')
        self.stat_frames = QLabel('-')
        self.stat_voices = QLabel('-')
        self.stat_size = QLabel('-')
        stats_form.addRow('存储后端:', self.stat_backend)
        stats_form.addRow('人物数量:', self.stat_roles)
        stats_form.addRow('地区数量:', self.stat_areas)
        stats_form.addRow('帧总数:', self.stat_frames)
        stats_form.addRow('语音总数:', self.stat_voices)
        stats_form.addRow('数据库大小:', self.stat_size)
        root.addWidget(stats_box)

        # 导入与导出是**两个独立模块**（各自分组），但按钮尺寸保持一致——
        # 同一行的 QPushButton 默认 sizePolicy 会被拉伸成等宽，文字长短仍会
        # 导致观感不齐，因此显式锁定为同一固定尺寸。导入、导出、配置三组通用。
        BTN_W, BTN_H = 132, 32

        import_box = QGroupBox('导入素材（新人物 / 新地区，导入后立即出现在菜单中）')
        import_row = QHBoxLayout(import_box)
        import_zip_btn = QPushButton('导入 zip 素材包')
        import_zip_btn.setToolTip('从 zip 素材包导入人物帧、语音与地区背景音乐')
        import_zip_btn.clicked.connect(self._import_zip)
        import_dir_btn = QPushButton('导入素材目录')
        import_dir_btn.setToolTip('从 png/ 与 music/ 目录树导入')
        import_dir_btn.clicked.connect(self._import_dir)
        refresh_btn = QPushButton('刷新统计')
        refresh_btn.setToolTip('重新读取资源库并刷新上方统计')
        refresh_btn.clicked.connect(self.refresh)
        for btn in (import_zip_btn, import_dir_btn, refresh_btn):
            btn.setFixedSize(BTN_W, BTN_H)
            import_row.addWidget(btn)
        import_row.addStretch(1)   # 按钮保持自身尺寸，不被拉伸填满整行
        root.addWidget(import_box)

        export_box = QGroupBox('导出素材（还原为 png/ 与 music/ 目录，可直接再导入或分享）')
        export_row = QHBoxLayout(export_box)
        # 范围选择放在按钮之前：先限定范围再点导出，符合「先选后做」的顺序
        self.export_scope_combo = QComboBox()
        self.export_scope_combo.addItem('全部素材', None)
        self.export_scope_combo.addItem('仅当前人物', 'current')
        self.export_scope_combo.setToolTip('「仅当前人物」只导出该角色的帧与语音，不含地区背景音乐')
        self.export_scope_combo.setFixedHeight(BTN_H)
        export_dir_btn = QPushButton('导出为目录')
        export_dir_btn.setToolTip('写出 png/<角色>、music/<角色>、music/<地区> 目录树')
        export_dir_btn.clicked.connect(lambda: self._export_assets(as_zip=False))
        export_zip_btn = QPushButton('导出为 zip')
        export_zip_btn.setToolTip('打包成单个 zip，体积不变但便于传输')
        export_zip_btn.clicked.connect(lambda: self._export_assets(as_zip=True))
        export_row.addWidget(self.export_scope_combo)
        for btn in (export_dir_btn, export_zip_btn):
            btn.setFixedSize(BTN_W, BTN_H)
            export_row.addWidget(btn)
        export_row.addStretch(1)
        root.addWidget(export_box)

        # 配置导入导出（v3.4：配置改由 config.db 管理）
        cfg_box = QGroupBox('配置文件（存于 config.db，可导出备份或迁移到其他机器）')
        cfg_layout = QVBoxLayout(cfg_box)
        cfg_form = QFormLayout()
        self.stat_config = QLabel('-')
        self.stat_config_roles = QLabel('-')
        cfg_form.addRow('配置存储:', self.stat_config)
        cfg_form.addRow('已登记人物:', self.stat_config_roles)
        cfg_layout.addLayout(cfg_form)

        cfg_row = QHBoxLayout()
        export_yaml_btn = QPushButton('导出 YAML')
        export_yaml_btn.setToolTip('导出为 data/config.yaml 同格式，便于人工编辑后回导')
        export_yaml_btn.clicked.connect(lambda: self._export_config('yaml'))
        export_json_btn = QPushButton('导出 JSON')
        export_json_btn.setToolTip('导出为 JSON，便于程序化处理')
        export_json_btn.clicked.connect(lambda: self._export_config('json'))
        import_cfg_btn = QPushButton('导入配置')
        import_cfg_btn.setToolTip('从 YAML / JSON 配置文件导入，可选覆盖或合并')
        import_cfg_btn.clicked.connect(self._import_config)
        # v3.6：移除「恢复出厂设置」——它会清空用户调好的缩放/帧率，风险大于便利。
        # 需要恢复出厂值时删掉 config.db 后重新安装即可（见帮助页说明）。
        # 与导入/导出按钮共用同一尺寸常量，三组按钮外观完全一致
        for btn in (export_yaml_btn, export_json_btn, import_cfg_btn):
            btn.setFixedSize(BTN_W, BTN_H)
            cfg_row.addWidget(btn)
        cfg_layout.addLayout(cfg_row)
        root.addWidget(cfg_box)
        root.addStretch(1)

        self.tabs.addTab(tab, '素材管理')

    def _export_assets(self, as_zip=False):
        """导出素材：按所选范围与格式导出全部帧/语音/BGM。

        素材库约 460MB，导出会耗时，故用带进度条的模态对话框；期间界面冻结属
        正常现象（读写都是顺序 IO），对话框上的「取消」可在完成后生效。
        """
        scope = self.export_scope_combo.currentData()
        roles = [self._selected_role()] if scope == 'current' else None
        areas = None
        if scope == 'current':
            if not roles[0]:
                QMessageBox.information(
                    self, '请先选择人物',
                    '「仅当前人物」需要先在「人物管理」里选中一个角色。')
                return
            # 「仅当前人物」只导该人物，不导地区背景音乐——它们与人物无关，
            # 全量带上会平白多出几 MB 且与选项名不符。
            areas = []

        if as_zip:
            default = '桌面伙伴素材.zip'
            path, _ = QFileDialog.getSaveFileName(
                self, '导出素材为 zip', default, 'Zip 压缩包 (*.zip)')
            if not path:
                return
            out_path = path
        else:
            out_dir = QFileDialog.getExistingDirectory(self, '选择导出目录')
            if not out_dir:
                return
            out_path = os.path.join(out_dir, '桌面伙伴素材')

        dlg = QProgressDialog('正在导出素材…', '取消', 0, 100, self)
        dlg.setWindowTitle('导出素材')
        dlg.setWindowModality(Qt.WindowModal)
        dlg.setMinimumDuration(300)   # 300ms 内完成就不闪一下
        dlg.setAutoClose(False)
        dlg.setAutoReset(False)

        def on_progress(done, total, label):
            dlg.setMaximum(total)
            dlg.setValue(done)
            dlg.setLabelText(f'正在导出 {done}/{total}\n{os.path.basename(label)}')
            QApplication.processEvents()

        try:
            report = export_assets(self.store, out_path, roles=roles, areas=areas,
                                   as_zip=as_zip, progress=on_progress)
        except Exception as e:
            dlg.close()
            QMessageBox.warning(self, '导出失败', str(e))
            return
        finally:
            dlg.close()

        size = _human_size(report['bytes'])
        QMessageBox.information(
            self, '导出完成',
            f'文件 {report["files"]} 个（{size}）\n'
            f'人物 {report["roles"]} 个 · 地区 {report["areas"]} 个\n\n'
            f'已导出到：{report["path"]}\n\n'
            f'导出结果符合素材包格式，可用「导入素材」直接并入。')

    def _export_config(self, fmt):
        """导出配置到用户选择的路径。"""
        try:
            if fmt == 'json':
                path, _ = QFileDialog.getSaveFileName(
                    self, '导出配置为 JSON', 'pilot_config.json',
                    'JSON 配置 (*.json)')
            else:
                path, _ = QFileDialog.getSaveFileName(
                    self, '导出配置为 YAML', 'pilot_config.yaml',
                    'YAML 配置 (*.yaml *.yml)')
            if not path:
                return
            if fmt == 'json':
                self.config_store.export_json(path)
            else:
                self.config_store.export_yaml(path)
        except Exception as e:
            QMessageBox.warning(self, '导出失败', str(e))
            return
        QMessageBox.information(self, '导出完成', f'配置已导出到：\n{path}')

    def _import_config(self):
        """导入配置文件，先确认覆盖或合并。"""
        path, _ = QFileDialog.getOpenFileName(
            self, '选择配置文件', '', '配置文件 (*.yaml *.yml *.json)')
        if not path:
            return
        ret = QMessageBox.question(
            self, '导入配置',
            f'将导入：{os.path.basename(path)}\n\n'
            f'确定 = 覆盖（当前设置全部替换）\n'
            f'取消 = 合并（只补充缺失的人物登记，保留现有设置）\n',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            | QMessageBox.StandardButton.Cancel)
        if ret == QMessageBox.StandardButton.Cancel:
            return
        replace = ret == QMessageBox.StandardButton.Yes
        try:
            report = self.config_store.import_file(path, replace=replace)
        except Exception as e:
            QMessageBox.warning(self, '导入失败', str(e))
            return
        # 覆盖可能换掉当前人物/语音开关/背景音乐，需重载并重建界面
        self.pilot.reload_config()
        self.config.clear()
        self.config.update(self.pilot.config)
        self._after_config_change()
        msg = (f'设置项 {report["scalars"]} 个已更新\n'
               f'人物登记：新增 {report["roles_added"]}，保留 {report["roles_kept"]}')
        if report['unknown_keys']:
            msg += f'\n忽略无法识别的键：{", ".join(report["unknown_keys"])}'
        if report['mode'] == 'replace':
            msg += '\n\n当前伙伴与音频开关已按导入的配置切换。'
        QMessageBox.information(self, '导入完成', msg)

    def _after_config_change(self):
        """配置被导入后刷新面板与托盘菜单。"""
        self.refresh()
        self.pilot.reshow(self.pilot.role_name)
        self.pilot._rebuild_role_menu()
        self.pilot._rebuild_bgm_menu()

    def _do_import(self, path):
        try:
            report = self.pilot.import_from_path(path)
        except Exception as e:
            QMessageBox.warning(self, '导入失败', str(e))
            return
        self.refresh()
        QMessageBox.information(
            self, '导入完成',
            f"帧 {report['frames']} / 语音 {report['voices']} / BGM {report['bgms']}\n"
            f"新角色: {', '.join(report['new_roles']) or '无'}\n"
            f"地区: {', '.join(report['areas']) or '无'}")

    def _import_zip(self):
        path, _ = QFileDialog.getOpenFileName(self, '选择素材包（zip）', '', 'Zip 素材包 (*.zip)')
        if path:
            self._do_import(path)

    def _import_dir(self):
        path = QFileDialog.getExistingDirectory(self, '选择素材包目录')
        if path:
            self._do_import(path)

    # ================= 通用刷新 =================

    def refresh(self):
        """重新加载人物/地区列表与统计，保持当前选中项。"""
        current_role = self._selected_role()
        self.role_list.blockSignals(True)
        self.role_list.clear()
        self.role_list.addItems(self.store.list_roles())
        self.role_list.blockSignals(False)
        target = current_role or self.pilot.role_name
        matches = self.role_list.findItems(target, Qt.MatchFlag.MatchExactly)
        if matches:
            self.role_list.setCurrentItem(matches[0])
        elif self.role_list.count():
            self.role_list.setCurrentRow(0)

        self.area_list.clear()
        self.area_list.addItems(self.store.list_bgm_areas())
        self._refresh_music_state()

        s = self.store.stats()
        self.stat_backend.setText('SQLite (assets.db)' if s['backend'] == 'sqlite' else '文件系统目录')
        self.stat_roles.setText(str(s['roles']))
        self.stat_areas.setText(str(s['areas']))
        self.stat_frames.setText(str(s['frames']))
        self.stat_voices.setText(str(s['voices']))
        self.stat_size.setText(f"{s['db_size_mb']:.1f} MB" if s['db_size_mb'] is not None else '-')

        cs = self.config_store.stats()
        self.stat_config.setText(
            f"SQLite ({os.path.basename(cs['db_path'])}) · {cs['db_size_kb']:.0f} KB")
        self.stat_config_roles.setText(str(cs['roles']))

    def closeEvent(self, event):
        self.pilot.on_manager_closed()
        super().closeEvent(event)
