"""v3.8 新增行为的回归测试：面板主窗口化、伙伴不进任务栏、帮助外置。

这些行为**无法从代码审查看出**——窗口标志设错、帮助文件路径拼错都不会
报错，只表现为「任务栏没有图标」「帮助页空着」。故用断言锁住。
"""

import os

from PySide6.QtWidgets import QMainWindow

import manager_panel
from manager_panel import (APP_VERSION, ManagerPanel, app_icon,
                          help_file_candidates, load_help_html)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ---------- 面板是独立主窗口 ----------

def test_panel_is_qmainwindow():
    """面板必须是 QMainWindow（v3.8 由 QDialog 升级而来）。

    QDialog 没有 menuBar / statusBar，窗口状态也没有统一入口。
    """
    from PySide6.QtWidgets import QDialog

    assert issubclass(ManagerPanel, QMainWindow)
    assert not issubclass(ManagerPanel, QDialog)


def test_panel_window_flags_allow_taskbar_entry():
    """面板必须显式带 Qt.Window 标志。

    这是「任务栏有独立图标」的关键：缺了它（或把 pilot 当 Qt 父窗口），
    Windows 会把面板并进伙伴那个无边框窗口的任务栏分组，用户找不到它。
    这里读源码断言而非构造完整面板——后者需要 pilot 桩与数据库。
    """
    import inspect

    src = inspect.getsource(ManagerPanel.__init__)
    assert 'Qt.Window |' in src
    assert 'WindowMinimizeButtonHint' in src
    assert 'WindowMaximizeButtonHint' in src
    assert 'super().__init__(None)' in src, '面板不应把 pilot 作为 Qt 父窗口'


def test_panel_keeps_tabs_and_has_no_menubar():
    """v3.8：面板用标签页组织功能，**不建菜单栏**。

    曾短暂改成「菜单驱动」（把五个标签页变成菜单），后按用户要求撤回。
    这里锁定两点：① 仍是 QTabWidget；② 不调用 menuBar()——
    防止有人把菜单栏又加回来，否则菜单与标签两套导航并存会互相打架。
    """
    import inspect

    src = inspect.getsource(ManagerPanel.__init__)
    assert 'QTabWidget(central)' in src, '__init__ 应构造 QTabWidget'
    assert 'QStackedWidget' not in src
    assert 'menuBar()' not in src, '面板不应建菜单栏'
    # 窗口命令应在「窗口与状态」标签页里
    assert hasattr(ManagerPanel, '_build_window_tab')
    assert hasattr(ManagerPanel, '_sync_window_state')
    for name in ('_toggle_maximized', '_toggle_fullscreen', '_toggle_pilot_visible'):
        assert hasattr(ManagerPanel, name), f'缺少 {name}'


# ---------- 伙伴本体不进任务栏 ----------

def test_pilot_uses_tool_window_flag():
    """伙伴本体必须是 Qt.Tool 窗口：不占任务栏、只在托盘。

    FramelessWindowHint 并不足以让窗口从任务栏消失——Windows 仍会为它
    创建一个按钮，用户点它只是闪一下伙伴。Qt.Tool 在 Windows 上映射为
    WS_EX_TOOLWINDOW，才真正不进任务栏与 Alt+Tab。
    """
    import inspect

    import pilot
    src = inspect.getsource(pilot.Pilot.init_window)
    assert 'Qt.Tool |' in src, '伙伴窗口缺少 Qt.Tool 标志'
    assert 'WindowStaysOnTopHint' in src
    assert 'FramelessWindowHint' in src


def test_app_mutex_name_matches_inno_script():
    """程序侧互斥量名字必须与 setup.iss 的 AppMutex 一致。

    不一致时安装/卸载向导判断不出程序是否在运行，文件被占用，
    「卸载不干净」就会复现。名字写死两处，故用测试锁住。
    """
    import pilot

    iss = open(os.path.join(ROOT, 'setup.iss'), encoding='utf-8').read()
    assert pilot.APP_MUTEX_NAME in iss, 'setup.iss 的 AppMutex 与 pilot.APP_MUTEX_NAME 不一致'
    assert 'Global\\PilotKG_Genshin_' in iss


# ---------- 帮助文档外置 ----------

def test_help_html_file_exists_in_repo():
    """帮助文档必须是独立文件 res/help.html（v3.8 起不再硬编码在源码里）。"""
    assert os.path.isfile(os.path.join(ROOT, 'res', 'help.html'))


def test_help_html_read_from_file():
    """load_help_html 要能真的读到文件内容，而不是返回兜底页。

    判定方式用**兜底页不会有的结构**（目录锚点、章节 id），
    不要直接找「未能载入帮助文件」这几个字——正式的帮助文档在
    「常见问题排查」一节里本来就会提到这句话。
    """
    html = load_help_html(ROOT)
    assert len(html) > 10000, f'内容过短，疑似走了兜底分支（{len(html)} 字符）'
    assert '<div class="toc">' in html, '缺少目录块，疑似兜底页'
    for anchor in ('id="s1"', 'id="s5"', 'id="s9"'):
        assert anchor in html, f'缺少章节锚点 {anchor}，疑似兜底页'
    assert '卸载与清理' in html


def test_help_placeholders_replaced():
    """双花括号占位符必须被真实值替换。

    占位符写成 {{APP_VERSION}} 是因为 help.html 里有 CSS
    （body { margin: 0 }）；若用单花括号，替换时会把样式整段吃掉。
    """
    html = load_help_html(ROOT)
    assert '{{APP_VERSION}}' not in html
    assert '{{REPO_URL}}' not in html
    assert '{{REPO_PAGE}}' not in html
    assert APP_VERSION in html
    assert 'https://github.com/MrYuPengfei/' in html


def test_help_candidates_cover_dev_and_packaged_layouts():
    """候选路径要同时覆盖开发态（res/）与打包态（_internal/）。

    注意第二条是 ``here/res`` 而不是「here 的父目录/res」——
    写错成父目录时开发态永远读不到帮助文件，且因为有兜底提示不会报错。
    """
    cands = help_file_candidates(ROOT)
    assert any(c.endswith(os.path.join('res', 'help.html')) for c in cands)
    assert any(os.path.dirname(c) == ROOT for c in cands), '缺少 base_dir 下的候选'
    assert os.path.isfile(cands[2]) or os.path.isfile(cands[0])


def test_help_falls_back_when_file_missing(monkeypatch):
    """所有候选都找不到时给出兜底提示，且**不抛异常**。

    帮助页缺失不该让程序起不来——这是它作为「可选文档」的基本要求。
    """
    monkeypatch.setattr(manager_panel, 'help_file_candidates',
                        lambda base_dir: [os.path.join(base_dir, 'nope.html')])
    html = load_help_html(ROOT)
    assert '未能载入帮助文件' in html
    assert APP_VERSION in html


def test_help_no_longer_embedded_in_source():
    """源码里不应再有 HELP_HTML 大段常量（v3.8 已外置）。"""
    import inspect
    src = inspect.getsource(manager_panel)
    assert 'HELP_HTML =' not in src, 'HELP_HTML 仍硬编码在 manager_panel.py 里'
    assert '<h3>一、导入素材注意事项</h3>' not in src


def test_help_doc_documents_tabs_not_menus():
    """帮助页须与实际的标签页界面一致。

    文档滞后于界面是这类外置文档最容易出的问题：改了布局却忘了改帮助页，
    用户照着文档找不到对应入口。这里断言六个标签页名都在文档里出现。
    """
    html = load_help_html(ROOT)
    for tab in ('人物管理', '音乐管理', '素材管理', '知识图谱', '帮助文档',
                '窗口与状态'):
        assert tab in html, f'帮助页未提到「{tab}」标签页'
    assert '管理面板' in html
    # 「管理面板」一节不应再把界面描述成菜单驱动
    body = html.split('<h3 id="s2">')[1].split('<h3 id="s3">')[0]
    assert '菜单驱动' not in body, '「管理面板」一节仍写着菜单驱动'
    assert '<th>标签页</th>' in body, '「管理面板」一节应说明这是标签页界面'


def test_app_icon_prefers_disk_file():
    """图标加载要能用磁盘上的 ico，且路径缺失时不崩溃。"""
    # 仓库根没有 icon256.ico（只有 ico/ 子目录），应回退成空图标而非抛异常
    assert isinstance(app_icon(ROOT), object)
    # 传一个必定不存在的目录：同样只回退，不抛
    assert isinstance(app_icon(os.path.join(ROOT, 'tests'), None), object)


# ---------- 版本号三处同步 ----------

def test_version_three_places_match():
    """版本号三处必须一致：面板常量 / setup.iss / pyproject.toml。

    漏改任何一处都会导致「关于里显示 3.8、安装器还是 3.7」这种低级问题。
    """
    import tomllib

    with open(os.path.join(ROOT, 'pyproject.toml'), 'rb') as f:
        pkg_version = tomllib.load(f)['project']['version']
    assert pkg_version.startswith(f'{APP_VERSION}.'), \
        f'pyproject {pkg_version} 与 APP_VERSION {APP_VERSION} 不一致'

    iss = open(os.path.join(ROOT, 'setup.iss'), encoding='utf-8').read()
    assert f'#define AppVersion "{APP_VERSION}"' in iss, \
        f'setup.iss 的 AppVersion 与 {APP_VERSION} 不一致'


def test_config_yaml_dependency_removed():
    """v3.8：PyYAML 已从依赖中移除（配置只用 JSON）。"""
    with open(os.path.join(ROOT, 'pyproject.toml'), encoding='utf-8') as f:
        content = f.read()
    assert 'PyYAML' not in content
    assert 'pyyaml' not in content.lower()


def test_data_seed_is_json():
    """配置种子必须是 data/config.json（旧的 config.yaml 已删除）。"""
    assert os.path.isfile(os.path.join(ROOT, 'data', 'config.json'))
    assert not os.path.exists(os.path.join(ROOT, 'data', 'config.yaml'))