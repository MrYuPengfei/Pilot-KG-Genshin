"""管理面板知识图谱页离屏冒烟：走真实的编辑/导入/导出槽函数。

不构造真实 Pilot（避免音频/托盘依赖），用最小桩提供 panel 所需的属性。
"""

import os
import sys
import tempfile

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('SDL_AUDIODRIVER', 'dummy')

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'tools'))

from PySide6.QtWidgets import QApplication, QMessageBox, QWidget   # noqa: E402

import kg_store                                                     # noqa: E402

_APP = None   # QApplication 的模块级引用，见 main()
from config_store import ConfigStore                              # noqa: E402
from manager_panel import ManagerPanel                               # noqa: E402


class FakeStore:
    """仅实现面板构造与 refresh 用到的资源库接口。"""

    def __init__(self, base_dir):
        self.base_dir = base_dir

    def list_roles(self):
        return ['钟离']

    def list_bgm_areas(self):
        return ['璃月']

    def list_frames(self, role):
        return ['0001.png']

    def list_voices(self, role, category=None):
        return ['早上好.mp3']

    def read_frame(self, role, name):
        return b''

    def read_voice(self, role, name):
        return b''

    def read_bgm(self, area):
        return b''

    def stats(self):
        return {'backend': 'sqlite', 'roles': 1, 'areas': 1, 'frames': 1,
                'voices': 0, 'bgms': 1, 'db_size_mb': 1.0}


class FakePilot(QWidget):
    """QWidget 兼作 pilot：面板会读取它的 store / config_store / _frames 等成员。

    v3.8 起面板是独立 QMainWindow，不再把 pilot 作为 Qt 父窗口传入。
    """

    def __init__(self, base_dir):
        super().__init__()
        self.store = FakeStore(base_dir)
        # v3.4 起面板会取 pilot.config_store（配置导入导出用）
        self.config_store = ConfigStore(base_dir)
        self.role_name = '钟离'
        self._frames = []
        self.index = 0
        self.audio_player = True

    def set_voice_enabled(self, v):
        self.audio_player = v

    def stop_bgm(self):
        pass

    def play_area_bgm(self, a):
        pass

    def set_role_timing(self, *a):
        pass

    def reshow(self, name):
        self.role_name = name

    def save_config(self):
        pass

    def reload_config(self):
        pass

    def _rebuild_role_menu(self):
        pass

    def set_visible(self, visible):
        self.setWindowOpacity(1.0 if visible else 0.0)

    def quit(self):
        """面板菜单「退出程序」会调用；桩件里什么都不做。"""

    def _rebuild_bgm_menu(self):
        pass


def main():
    # QApplication 必须保持模块级引用：局部变量在函数返回后会被回收，
    # 而 Qt 要求该对象存活到进程结束，否则后续操作可能崩溃。
    global _APP
    if _APP is None:
        _APP = QApplication.instance() or QApplication([])
    workdir = tempfile.mkdtemp(prefix='kg_panel_')
    # 图谱库与素材库同目录，但用独立库避免污染真实 kg.db
    kg_store.reset_default_store()
    real_store = kg_store.KGStore(os.path.join(workdir, 'kg.db'),
                                   seed_dir=os.path.join(ROOT, 'data', 'csv'))
    kg_store._default = real_store      # 让面板拿到这份临时库

    panel = ManagerPanel(FakePilot(workdir), {'frame_scale': {'钟离': [60, 1.0]},
                                              'bg_music': None})
    ok = panel._ensure_kg_loaded()
    print('加载图谱:', ok, '| 状态:', panel.kg_status.text())
    assert ok

    # 定位实体
    panel.kg_search.setText('钟离')
    panel._on_kg_search()
    print('当前实体:', panel._kg_current)
    print('关系条数:', len(panel._kg_rel_edges), '| 前3条:',
          [panel.kg_rel_list.item(i).text() for i in range(min(3, panel.kg_rel_list.count()))])
    assert panel._kg_current == ('character', '钟离')
    assert panel._kg_rel_edges

    # 按钮启用状态
    print('编辑实体可用:', panel.kg_edit_node_btn.isEnabled())
    assert panel.kg_edit_node_btn.isEnabled()

    # 新增实体（绕过对话框，直接走存储层 + 刷新链路）
    real_store.add_node('npc', '冒烟测试NPC', {'来源': 'smoke'})
    panel._kg_after_change(keep_key=('npc', '冒烟测试NPC'))
    print('新增后当前实体:', panel._kg_current,
          '| 详情含来源:', '来源' in panel.kg_detail.toPlainText())

    # 新增关系：锚点为当前实体
    anchor = panel._kg_current
    real_store.add_edge(('character', '钟离'), 'smoke_rel', anchor)
    panel._kg_after_change(keep_key=anchor, keep_edge=('smoke_rel', anchor))
    print('关系列表条数:', len(panel._kg_rel_edges))
    assert any(r == 'smoke_rel' for r, _, _ in panel._kg_rel_edges)

    # 方向无关的删除
    n = real_store.delete_edge_touching(anchor, 'smoke_rel', ('character', '钟离'))
    print('删除关系行数:', n)
    assert n == 1

    # 删除实体
    nodes, edges = real_store.delete_node(anchor)
    panel._kg_after_change()
    print('删除实体:', nodes, '关联关系:', edges, '| 画布已清空:',
          panel.kg_canvas.center_key is None)
    assert panel.kg_canvas.center_key is None

    # 导出
    out = os.path.join(workdir, 'exported')
    report = real_store.export_csv(out)
    print('导出:', report['node_files'], '个实体表,', report['edge_files'], '个关系表')
    assert report['node_rows'] > 1800 and report['edge_rows'] > 7000

    # 覆盖导入回灌（直接调存储层，槽函数需交互弹窗不在此跑）
    rep = real_store.import_csv(out, replace=True)
    print('回灌导入:', rep['nodes_added'], '实体 /', rep['edges_added'], '关系')
    assert rep['edges_added'] == report['edge_rows']

    # ---- 新增能力：带权重的边 + 未登记类型（data/csv-edu）----
    edu_dir = os.path.join(ROOT, 'data', 'csv-edu')
    if os.path.isdir(edu_dir):
        edu_rep = real_store.import_csv(edu_dir, replace=True)
        print('edu 导入:', edu_rep['nodes_added'], '实体 /', edu_rep['edges_added'],
              '关系 / 带权重', edu_rep['edges_weighted'],
              '/ 新类型', [cn for _k, cn in edu_rep['new_types']])
        # 早期版本这里是 0 实体 / 681 关系全跳过
        assert edu_rep['nodes_added'] > 500
        assert edu_rep['edges_skipped'] == 0
        assert edu_rep['edges_weighted'] == edu_rep['edges_added']

        # 图例应随新类型重建
        panel._kg_after_change()
        legend = panel.kg_legend.text()
        assert 'AI' in legend or 'ai' in legend, legend

        # 按中文名定位（实体名是英文）
        panel.kg_search.setText('大语言模型')
        panel._on_kg_search()
        print('中文名搜索定位:', panel._kg_current)
        assert panel._kg_current is not None
        assert '大语言模型' in panel.kg_detail.toPlainText()

        # 关系列表应显示权重
        rel_texts = [panel.kg_rel_list.item(i).text()
                     for i in range(panel.kg_rel_list.count())]
        assert any('·' in t for t in rel_texts), rel_texts[:5]
        print('带权重关系条目示例:', next(t for t in rel_texts if '·' in t))

        # 画布已按权重重绘
        assert panel.kg_canvas.center_key == panel._kg_current

        # 带权重图谱的导出 → 回灌往返
        edu_out = os.path.join(workdir, 'exported_edu')
        edu_report = real_store.export_csv(edu_out)
        print('edu 导出:', edu_report['node_files'], '实体表 /',
              edu_report['edge_files'], '关系表 / 带权重文件',
              edu_report['weighted_files'])
        assert edu_report['weighted_files'] == edu_report['edge_files']
        again = real_store.import_csv(edu_out, replace=True)
        assert again['nodes_added'] == edu_report['node_rows']
        assert again['edges_added'] == edu_report['edge_rows']
        assert again['edges_skipped'] == 0
        print('edu 往返: 权重保留',
              real_store.edge_weight(('ai', 'instruction tuning'),
                                     'derived_from',
                                     ('ai', 'foundation model')))
    else:
        print('（无 data/csv-edu，跳过带权重边冒烟）')

    panel.deleteLater()
    real_store.close()
    print('\nSMOKE OK')


if __name__ == '__main__':
    # 屏蔽可能弹出的模态框
    QMessageBox.information = staticmethod(lambda *a, **k: None)
    QMessageBox.question = staticmethod(
        lambda *a, **k: QMessageBox.StandardButton.Yes)
    main()
