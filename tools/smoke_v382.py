"""v3.8.2 新增功能的离屏冒烟：删除背景音乐 / 导出当前背景音乐。

走**真实的槽函数与对话框**（模态框打桩为自动确认），验证用户实际点击的完整路径：
音乐管理页选地区 → 删 → 列表/菜单刷新；素材管理页选「仅当前背景音乐」→ 导出 → 产物正确。

用 assets.db 的临时副本，绝不碰真实资源库。
"""

import os
import shutil
import sys
import tempfile

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('SDL_AUDIODRIVER', 'dummy')

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox, QWidget  # noqa: E402

from config_store import ConfigStore      # noqa: E402
from manager_panel import ManagerPanel    # noqa: E402
from resource_store import ResourceStore  # noqa: E402

_APP = None
ASSETS_DB = os.path.join(ROOT, 'assets.db')

if not os.path.isfile(ASSETS_DB):
    print('需要真实 assets.db，跳过')
    sys.exit(0)


class FakePilot(QWidget):
    """pilot 桩：记录被调用的方法，验证「删除时停播」「菜单重建」确实发生了。"""

    def __init__(self, base_dir):
        super().__init__()
        self.store = ResourceStore(base_dir, 'png', 'music', 'assets.db')
        self.config_store = ConfigStore(base_dir, auto_seed=False)
        self.role_name = self.store.list_roles()[0]
        self._frames = []
        self.index = 0
        self.audio_player = False
        self.stopped = 0            # stop_bgm 被调次数
        self.bgm_menu_rebuilt = 0   # _rebuild_bgm_menu 被调次数
        self.saved = 0

    def set_voice_enabled(self, v):
        self.audio_player = v

    def stop_bgm(self):
        self.stopped += 1

    def play_area_bgm(self, area):
        pass

    def set_role_timing(self, *a):
        pass

    def reshow(self, name):
        self.role_name = name

    def save_config(self):
        self.saved += 1

    def _rebuild_role_menu(self):
        pass

    def _rebuild_bgm_menu(self):
        self.bgm_menu_rebuilt += 1

    def set_visible(self, visible):
        self.setWindowOpacity(1.0 if visible else 0.0)

    def quit(self):
        pass


def main():
    global _APP
    if _APP is None:
        _APP = QApplication.instance() or QApplication([])

    workdir = tempfile.mkdtemp(prefix='v382_smoke_')
    shutil.copy(ASSETS_DB, os.path.join(workdir, 'assets.db'))

    config = {'frame_scale': {}, 'bg_music': None, 'audio': False, 'role': None}
    pilot = FakePilot(workdir)
    config['role'] = pilot.role_name
    panel = ManagerPanel(pilot, config)

    try:
        # ---------- 音乐管理页：删除背景音乐 ----------
        areas_before = pilot.store.list_bgm_areas()
        print('删前地区:', areas_before)
        assert areas_before, '前置：资源库里应有地区背景音乐'
        assert panel.area_list.count() == len(areas_before)

        target = areas_before[0]
        panel.area_list.setCurrentRow(0)
        assert panel._selected_area() == target
        print('删除按钮:', panel.delete_bgm_btn.text())

        # 未选中时不应误删
        panel.area_list.clearSelection()
        panel.area_list.setCurrentRow(-1)
        panel._delete_area_bgm()
        assert pilot.store.list_bgm_areas() == areas_before, '未选中不该删任何东西'
        print('未选中时删除: 安全（无改动）')

        # 模拟「正在播放该地区」，删除时应先停播并清掉播放状态
        panel.area_list.setCurrentRow(0)
        config['bg_music'] = target
        panel._delete_area_bgm()
        print('删除后 地区:', pilot.store.list_bgm_areas(),
              '| stop_bgm 调用:', pilot.stopped,
              '| bg_music:', config['bg_music'],
              '| 菜单重建:', pilot.bgm_menu_rebuilt)
        assert target not in pilot.store.list_bgm_areas(), '目标地区应已删除'
        assert pilot.stopped == 1, '删的是正在播放的地区，应先停播'
        assert config['bg_music'] is False, '播放状态必须清掉，否则菜单会留残标记'
        assert pilot.bgm_menu_rebuilt >= 1, '托盘菜单必须重建'
        assert panel.area_list.count() == len(pilot.store.list_bgm_areas()), \
            '地区列表应已刷新'
        # 人物资源不受影响
        assert len(pilot.store.list_roles()) > 0

        # ---------- 素材管理页：导出当前背景音乐 ----------
        scopes = [panel.export_scope_combo.itemText(i)
                  for i in range(panel.export_scope_combo.count())]
        print('导出范围:', scopes)
        assert '仅当前背景音乐' in scopes

        idx = panel.export_scope_combo.findData('current_bgm')
        assert idx >= 0
        panel.export_scope_combo.setCurrentIndex(idx)
        panel.area_list.setCurrentRow(0)
        export_area = panel._selected_area()
        print('待导出地区:', export_area)

        out_dir = os.path.join(workdir, 'export_out')
        os.makedirs(out_dir, exist_ok=True)
        # 跳过文件对话框：直接导出到临时目录
        QFileDialog.getExistingDirectory = staticmethod(lambda *a, **k: out_dir)
        panel._export_assets(as_zip=False)

        produced = []
        for root, _dirs, files in os.walk(out_dir):
            for f in files:
                p = os.path.join(root, f)
                produced.append(os.path.relpath(p, out_dir).replace('\\', '/'))
        print('导出产物:', produced)
        # 目录导出会落在「<地区>背景音乐」子目录下，故比对时带上这一层
        assert produced == [f'{export_area}背景音乐/music/{export_area}'
                            '/background.mp3'], \
            f'只应有该地区的一个 BGM 文件，实际 {produced}'
        # 目录名带上地区名，便于识别
        top = os.listdir(out_dir)
        assert f'{export_area}背景音乐' in top, top
        print('导出目录名:', top)

    finally:
        panel.deleteLater()
        pilot.deleteLater()
        pilot.store.close()
        shutil.rmtree(workdir, ignore_errors=True)

    print('\nSMOKE OK')


if __name__ == '__main__':
    # 模态框打桩：确认框一律 Yes，提示框忽略
    QMessageBox.question = staticmethod(
        lambda *a, **k: QMessageBox.StandardButton.Yes)
    QMessageBox.information = staticmethod(lambda *a, **k: None)
    QMessageBox.warning = staticmethod(lambda *a, **k: None)
    main()
