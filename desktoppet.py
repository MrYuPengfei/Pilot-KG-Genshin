import io
import os
import random
import sys
import pygame.mixer as mixer
from PySide6 import QtWidgets
from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QPixmap, QIcon, QImage, QCursor, QAction
from PySide6.QtWidgets import (QSystemTrayIcon, QMenuBar, QMenu, QApplication, QMainWindow,
                               QFileDialog, QMessageBox)
import datetime
import yaml

from asset_importer import import_assets
from manager_panel import ManagerPanel
from resource_store import ResourceStore

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(BASE_DIR, 'config.yaml'), 'r', encoding='utf-8') as f:
    config = yaml.safe_load(f)


def greeting(time):
    if 10 >= time >= 4:
        return '早上好.mp3'
    elif 14 >= time >= 11:
        return '中午好.mp3'
    elif 24 >= time > 17:
        return '晚上好.mp3'
    else:
        return False


class Pet(QMainWindow):
    def __init__(self):
        super(Pet, self).__init__()
        mixer.init()
        self.audio_player = config['audio']
        self.role_name = config['role']
        self.music_path = config['music_path']
        self.img_path = config['img_path']
        self.bg_music = config['bg_music']
        screenRect = QApplication.primaryScreen().geometry()
        self.screenheight, self.screenwidth = screenRect.height(), screenRect.width()

        # 资源统一走 ResourceStore：有 assets.db 读数据库，否则回退文件系统
        self.store = ResourceStore(BASE_DIR, self.img_path, self.music_path)
        self._bgm_stream = None  # 持有 BGM 字节流，防止播放期间被回收

        self.wt = 300
        self.ht = 300
        self.scale = config['frame_scale'][self.role_name][1]
        self.pos_x = random.randint(0, self.screenwidth)
        self.pos_y = random.randint(0, self.screenheight)
        self.now_time = datetime.datetime.now().hour

        self.file_list = self.store.list_frames(self.role_name)  # 全部帧文件名（已排序）
        self.talk_list = self.store.list_voices(self.role_name, 'chat')
        self.know_list = self.store.list_voices(self.role_name, 'know')
        self._load_frame_cache()  # 预加载并预缩放全部帧，动画期间不再碰磁盘

        if self.bg_music:
            self._play_bgm(self.bg_music)

        self.tp = QSystemTrayIcon(self)  # 初始化系统托盘
        self.tp.setToolTip('原来你也玩原神')
        self.tray()
        self.init_window()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.act)
        self.timer.start(config['frame_scale'][self.role_name][0])
        self.is_follow_mouse = False  # 初始化鼠标没有移动
        self.mouse_drag_pos = self.pos()
        self._panel = None  # 管理面板实例（单例，关闭后置 None）

    # ---------- 配置持久化 ----------

    def save_config(self):
        """把内存中的 config 写回 config.yaml。"""
        with open(os.path.join(BASE_DIR, 'config.yaml'), 'w', encoding='utf-8') as f:
            yaml.dump(config, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

    # ---------- 管理面板 ----------

    def open_manager(self):
        """打开（或聚焦）管理面板。"""
        if self._panel is None:
            self._panel = ManagerPanel(self, config)
        self._panel.refresh()
        self._panel.show()
        self._panel.raise_()
        self._panel.activateWindow()

    def on_manager_closed(self):
        self._panel = None

    def set_role_timing(self, role, interval, scale):
        """设置指定角色的帧间隔与缩放；若是当前角色则即时生效。"""
        entry = config['frame_scale'].setdefault(role, [interval, scale])
        entry[0], entry[1] = interval, scale
        if role == self.role_name:
            self.scale = scale
            self._load_frame_cache()
            self.index = 1 if len(self._frames) > 1 else 0
            self.timer.start(interval)
        self.save_config()

    def play_area_bgm(self, area):
        """播放指定地区背景音乐（管理面板/菜单共用）。"""
        if mixer.music.get_busy():
            mixer.music.stop()
        self._play_bgm(area)
        config['bg_music'] = area
        self.music_off.setText('关闭所有')
        self._rebuild_bgm_menu()
        self.save_config()

    def stop_bgm(self):
        """停止背景音乐。"""
        if mixer.music.get_busy():
            mixer.music.stop()
        config['bg_music'] = False
        self._rebuild_bgm_menu()
        self.save_config()

    def set_voice_enabled(self, enabled):
        """开关人物语音。"""
        self.audio_player = enabled
        config['audio'] = enabled
        if not enabled and mixer.get_busy():
            mixer.stop()
        self._rebuild_bgm_menu()
        self.save_config()

    def _load_frame_cache(self):
        """把当前角色的全部帧解码、缩放好并缓存 mask，act() 只做内存切换。"""
        w = int(self.scale * self.wt)
        h = int(self.scale * self.wt)
        frames = []
        for name in self.file_list:
            pm = QPixmap()
            pm.loadFromData(self.store.read_frame(self.role_name, name))
            pm = pm.scaled(w, h)
            frames.append((pm, pm.mask()))
        self._frames = frames

    def _play_bgm(self, area):
        """从资源库读取背景音乐并循环播放。"""
        self._bgm_stream = io.BytesIO(self.store.read_bgm(area))
        mixer.music.load(self._bgm_stream)
        mixer.music.play(-1)

    def _play_voice(self, role, name, volume=None):
        """从资源库读取语音并播放。"""
        audio = mixer.Sound(file=io.BytesIO(self.store.read_voice(role, name)))
        if volume is not None:
            audio.set_volume(volume)
        audio.play()

    def act(self):
        """
        切换缓存中的帧，实现动画效果
        """
        if self.index < len(self._frames) - 1:
            self.index += 1
        else:
            self.index = 1 if len(self._frames) > 1 else 0
        self.pm, mask = self._frames[self.index]
        self.resize(self.pm.size())
        self.setMask(mask)
        self.lbl.setPixmap(self.pm)

    def init_window(self):
        """
        初始化窗口
        """
        self.setGeometry(0, 400, self.pos_x, self.pos_y)  # 设置窗口和位置

        self.lbl = QtWidgets.QLabel(self)  # 初始化一个QLabel对象
        self.lbl.setScaledContents(True)
        self.setCentralWidget(self.lbl)

        self.index = 1 if len(self._frames) > 1 else 0
        self.pm, mask = self._frames[self.index]
        self.resize(self.pm.size())
        self.setMask(mask)
        self.lbl.setPixmap(self.pm)  # 设置Qlabel为一个Pimap图片

        self.setWindowFlags(Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint)  # 设置窗口置顶以及去掉边框
        self.setAutoFillBackground(False)  # 设置窗口背景透明
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.show()  # 显示窗口
        self.tp.setIcon(QIcon(self._frames[self.index][0]))  # 系统托盘图标
        if self.audio_player:
            self.role_music.setText('人物语音～')
            greet = greeting(self.now_time)
            if greet:
                self._play_voice(self.role_name, greet, volume=0.5)

    def tray(self):
        """
        建立一个托盘
        """
        self.bar = QMenuBar(self)
        self.menu = self.bar.addMenu('菜单')
        self.pets = self.menu.addMenu('人物')
        self._rebuild_role_menu()

        self.bgmusics = self.menu.addMenu('音乐')
        self._rebuild_bgm_menu()

        manager_action = QAction('管理面板', self)
        manager_action.triggered.connect(self.open_manager)
        self.menu.addAction(manager_action)


        show = QAction('显示', self)
        show.triggered.connect(self.showwin)
        self.menu.addAction(show)

        quit = QAction('退出', self)
        quit.triggered.connect(self.quit)
        self.menu.addAction(quit)

        self.tp.setContextMenu(self.menu)
        self.tp.show()

    def _rebuild_role_menu(self):
        """按资源库中实际存在的角色动态生成人物菜单。"""
        self.pets.clear()
        available = set(self.store.list_roles())
        # config 中登记过的角色按登记顺序排前，其余（新导入未登记的）排在后面
        ordered = [r for r in config['frame_scale'] if r in available]
        ordered += sorted(available - set(ordered))
        for role in ordered:
            act = QAction(role, self)
            act.triggered.connect(lambda checked=False, r=role: self.reshow(r))
            self.pets.addAction(act)

    def _rebuild_bgm_menu(self):
        """按资源库中实际存在的地区动态生成音乐菜单。"""
        self.bgmusics.clear()
        current = config.get('bg_music')
        self.area_actions = {}
        for area in self.store.list_bgm_areas():
            act = QAction(area + '～' if current == area else area, self)
            act.triggered.connect(lambda checked=False, a=act: self.set_audio(a.text()))
            self.bgmusics.addAction(act)
            self.area_actions[area] = act

        self.role_music = QAction('人物语音～' if self.audio_player else '人物语音', self)
        self.role_music.triggered.connect(lambda: self.set_audio(self.role_music.text()))
        self.bgmusics.addAction(self.role_music)
        self.music_off = QAction('关闭所有', self)
        self.music_off.triggered.connect(lambda: self.set_audio(self.music_off.text()))
        self.bgmusics.addAction(self.music_off)

    def import_from_path(self, path):
        """从 zip 或目录导入素材包，刷新菜单并同步 config，返回导入报告。"""
        report = import_assets(path, os.path.join(BASE_DIR, 'assets.db'),
                               os.path.join(BASE_DIR, 'config.yaml'))
        # 导入可能向 config.yaml 登记了新角色，同步到内存
        with open(os.path.join(BASE_DIR, 'config.yaml'), 'r', encoding='utf-8') as f:
            config.update(yaml.safe_load(f))
        self._rebuild_role_menu()
        self._rebuild_bgm_menu()
        return report

    def reshow(self, name):
        """
        桌面宠物的替换
        """
        self.talk_list = self.store.list_voices(name, 'chat')
        self.know_list = self.store.list_voices(name, 'know')
        if mixer.get_busy():
            mixer.stop()
        self.role_name = name
        config['role'] = name
        config['frame_scale'].setdefault(name, [60, 1.0])  # 新导入角色可能没有登记
        self.scale = config['frame_scale'][self.role_name][1]
        self.pos_x = random.randint(0, self.screenwidth)
        self.pos_y = random.randint(0, self.screenheight)
        self.file_list = self.store.list_frames(self.role_name)
        self._load_frame_cache()
        self.init_window()
        self.tp.show()
        self.timer.start(config['frame_scale'][self.role_name][0])

    def mousePressEvent(self, event):
        # 鼠标左键事件
        if event.button() == Qt.MouseButton.LeftButton:
            self.is_follow_mouse = True
            self.mouse_drag_pos = event.globalPosition().toPoint() - self.pos()
            event.accept()
            self.setCursor(QCursor(Qt.CursorShape.OpenHandCursor))

    def mouseMoveEvent(self, event):
        # 鼠标移动事件
        if self.is_follow_mouse:
            self.move(event.globalPosition().toPoint() - self.mouse_drag_pos)
            xy = self.pos()
            self.pos_x, self.pos_y = xy.x(), xy.y()
            event.accept()

    def mouseReleaseEvent(self, event):
        # 鼠标松开事件
        self.is_follow_mouse = False
        self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))

    def keyPressEvent(self, event):
        # command & Q   ==>quit
        if event.key() == Qt.Key.Key_Q and event.modifiers() == Qt.KeyboardModifier.ControlModifier:
            self.quit()
        scale_changed = False
        # command & +   ==>bigger
        if event.modifiers() == Qt.KeyboardModifier.ControlModifier and event.key() == Qt.Key.Key_Equal:  # 两键组合
            self.scale += 0.01
            scale_changed = True
        # command & -   ==>smaller
        if event.modifiers() == Qt.KeyboardModifier.ControlModifier and event.key() == Qt.Key.Key_Minus:  # 两键组合
            self.scale -= 0.01
            scale_changed = True
        if scale_changed:
            config['frame_scale'][self.role_name][1] = self.scale
            self._load_frame_cache()  # 缩放变了，按新尺寸重建帧缓存

    def quit(self):
        # 退出程序
        self.save_config()
        self.store.close()
        self.close()
        sys.exit()

    def contextMenuEvent(self, event):
        # 定义菜单
        menu = QMenu(self)
        konwing = menu.addAction("了解")
        talking = menu.addAction("闲聊")
        hide = menu.addAction("隐藏")
        quitAction = menu.addAction("退出")
        # 使用exec_()方法显示菜单。从鼠标右键事件对象中获得当前坐标。mapToGlobal()方法把当前组件的相对坐标转换为窗口（window）的绝对坐标。
        action = menu.exec(self.mapToGlobal(event.pos()))
        if action == quitAction:
            self.quit()
        elif action == hide:
            # 通过设置透明度方式隐藏宠物
            self.setWindowOpacity(0)
        elif action == talking and self.audio_player and not mixer.get_busy() and self.talk_list:
            self._play_voice(self.role_name, random.choice(self.talk_list))
        elif action == konwing and self.audio_player and not mixer.get_busy() and self.know_list:
            self._play_voice(self.role_name, random.choice(self.know_list))

    def showwin(self):
        self.setWindowOpacity(1)

    def set_audio(self, area):
        """
        :param area: 菜单项当前文本（'～' 后缀表示已选中，再次点击为取消选中）
        :return:
        """

        # 判断是否为关闭所有
        if '关闭所有' in area:
            if '～' in area: # 之前为关闭所有 接下来需要取消关闭所有
                self.music_off.setText('关闭所有')
            else:   # 接下来需要关闭所有
                self.music_off.setText('关闭所有～')
                self.audio_player = False
                config['bg_music'] = False
                self.role_music.setText('人物语音')
                for act in self.area_actions.values(): # 修改对应的状态显示
                    act.setText(act.text().replace('～', ''))
                if mixer.get_busy():    # 关闭语音音效
                    mixer.stop()
                if mixer.music.get_busy():  # 关闭背景音效
                    mixer.music.stop()
        elif area in ('人物语音', '人物语音～'):
            if '～' in area:
                self.role_music.setText('人物语音')
                self.audio_player = False
                if mixer.get_busy():  # 关闭语音音效
                    mixer.stop()
            else:
                self.music_off.setText('关闭所有')
                self.role_music.setText('人物语音～')
                self.audio_player = True
        else:   # 地区 BGM（地区列表由资源库动态决定，支持导入的自定义地区）
            base = area[:-1] if area.endswith('～') else area
            if base not in self.area_actions:
                return
            if area.endswith('～'):  # ～表示之前为选中状态 需要执行取消选中操作
                self.area_actions[base].setText(base)
                config['bg_music'] = False
                if mixer.music.get_busy():  # 关闭背景音效
                    mixer.music.stop()
            else:
                self.music_off.setText('关闭所有')
                for a, act in self.area_actions.items():
                    act.setText(a + '～' if a == base else a)
                if mixer.music.get_busy():
                    mixer.music.stop()
                self._play_bgm(base)
                config['bg_music'] = base
        config['audio'] = self.audio_player


if __name__ == '__main__':
    # 创建程序和对象
    app = QApplication(sys.argv)
    pet = Pet()
    sys.exit(app.exec())
