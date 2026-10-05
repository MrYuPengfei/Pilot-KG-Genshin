import io
import os
import random
import sys
import pygame.mixer as mixer
from PySide6 import QtWidgets
from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QPixmap, QIcon, QCursor, QAction
from PySide6.QtWidgets import (QSystemTrayIcon, QMenuBar, QMenu, QApplication, QMainWindow)
import datetime

from asset_importer import import_assets
from config_store import ConfigStore
from manager_panel import ManagerPanel
from resource_store import ResourceStore

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# 三个库并列在程序目录：assets.db（资源）、kg.db（图谱）、config.db（配置）；
# data/config.yaml 仅作配置种子与导入导出格式，不参与日常读写。
config_store = ConfigStore(BASE_DIR)
config = config_store.load()


# 问候语时段表：小时 -> 语音关键词。覆盖全天，避免出现「某几小时静默」。
# 深夜与凌晨用「晚安」，下午（15~17 点）过渡到「晚上好」——原先这三段直接返回
# False，导致一天里有 7 个小时（0~3、15~17 点）不问候。
GREETING_SCHEDULE = (
    ((23, 5), '晚安'),        # 23:00~04:59（跨零点）
    ((5, 11), '早上好'),       # 05:00~10:59
    ((11, 15), '中午好'),      # 11:00~14:59
    ((15, 23), '晚上好'),      # 15:00~22:59
)
# 同时段内的降级顺序：角色可能只录了其中一两条
GREETING_FALLBACKS = {
    '晚安': ('晚安', '晚上好', '中午好', '早上好'),
    '早上好': ('早上好', '中午好', '晚上好', '晚安'),
    '中午好': ('中午好', '早上好', '晚上好', '晚安'),
    '晚上好': ('晚上好', '晚安', '中午好', '早上好'),
}
# 冷却只针对「同一个人 + 同一时段」：连点同一人时不超过这个间隔，
# 换人（或跨过整点、时段关键词变化）会立即问候。
GREETING_COOLDOWN = 60


def greeting_name(hour):
    """按小时返回该时段的问候关键词（如「早上好」）；无对应时段返回 None。"""
    hour = int(hour) % 24
    for (start, end), name in GREETING_SCHEDULE:
        if start <= end:
            if start <= hour < end:
                return name
        elif hour >= start or hour < end:   # 跨零点的区间
            return name
    return None


def pick_greeting(available, hour):
    """从角色实际拥有的问候语音里挑一条合适的。

    :param available: 该角色拥有的问候语音文件名列表
    :param hour: 当前小时
    :return: 文件名；一个都没有时返回 None

    按**关键词**而非全名匹配，因此「早上好问候菲谢尔.mp3」这类带后缀的
    文件也能在早上被选中（菲谢尔就没有标准的「早上好.mp3」）。
    """
    if not available:
        return None
    preferred = greeting_name(hour)
    order = GREETING_FALLBACKS.get(preferred, (preferred,))
    for keyword in order:
        for name in available:            # 同一关键词可能有多个版本
            if keyword in name:
                return name
    # 都不匹配时退而求其次：用该角色有的第一条问候
    return available[0]


class Pilot(QMainWindow):
    def __init__(self):
        super(Pilot, self).__init__()
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
        # 配置库句柄挂在实例上，供管理面板做配置导入导出
        self.config_store = config_store
        self._bgm_stream = None  # 持有 BGM 字节流，防止播放期间被回收

        self.wt = 300
        self.ht = 300
        available = self.store.list_roles()
        # 安装包不携带 data/config.yaml，配置由内置默认值播种（只登记了一个角色）。
        # 这里以资源库中实际存在的人物为准补齐登记，使人物菜单与设置面板完整可用。
        if config_store.ensure_roles(available):
            config['frame_scale'] = config_store.load()['frame_scale']
        # 配置里的人物可能没有资源（如导入了他人配置），回退到第一个可用人物，
        # 否则后续读帧会 IndexError 直接崩在启动阶段
        if not self.store.list_frames(self.role_name):
            if not available:
                raise RuntimeError('资源库中没有任何人物资源，请先导入素材包')
            self.role_name = available[0]
            config['role'] = self.role_name
        # 人物未登记帧率/缩放时用默认值（登记发生在导入素材时，不一定覆盖全部人物）
        config['frame_scale'].setdefault(self.role_name, [60, 1.0])
        self.scale = config['frame_scale'][self.role_name][1]
        # 位置留 0，由 init_window 按实际帧尺寸夹紧到屏幕内（见 _random_position）
        self.pos_x = 0
        self.pos_y = 0
        self.index = 0   # init_window 会用首帧覆盖，这里先给合法初值
        # 最近一次问候的 (时刻, 人物, 时段关键词)；None=还没问候过。见 play_greeting
        self._last_greeting = None

        self.file_list = self.store.list_frames(self.role_name)  # 全部帧文件名（已排序）
        self.talk_list = self.store.list_voices(self.role_name, 'chat')
        self.know_list = self.store.list_voices(self.role_name, 'know')
        self._load_frame_cache()  # 预加载并预缩放全部帧，动画期间不再碰磁盘

        if self.bg_music:
            self._play_bgm(self.bg_music)

        self.tp = QSystemTrayIcon(self)  # 初始化系统托盘
        self.tp.setToolTip('原来你也玩原神')
        # 顺序要紧：先 init_window()（它负责 setIcon），再 tray()（内部会 show()）。
        # 反过来托盘会在还没有图标时被显示，Qt 打印
        # 「QSystemTrayIcon::setVisible: No Icon set」。
        self.init_window()
        self.tray()
        self.play_greeting()   # 启动问候一次（按当前时段）
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.act)
        self.timer.start(config['frame_scale'][self.role_name][0])
        self.is_follow_mouse = False  # 初始化鼠标没有移动
        self.mouse_drag_pos = self.pos()
        self._panel = None  # 管理面板实例（单例，关闭后置 None）

    # ---------- 配置持久化 ----------

    def save_config(self):
        """把内存中的 config 落库（程序目录的 config.db）。"""
        config_store.save(config)

    def reload_config(self):
        """从配置库重新载入，丢弃内存中的改动（供配置导入后调用）。"""
        config.clear()
        config.update(config_store.load())
        self.audio_player = config['audio']
        self.role_name = config['role']
        self.music_path = config['music_path']
        self.img_path = config['img_path']
        self.bg_music = config.get('bg_music')
        self.save_config()

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
        if not self._frames:
            return
        # 从当前帧往后步进，到末尾回到 0。用 % 取模可正确处理「末帧→首帧」的衔接，
        # 也保证只有 1~2 帧时仍能正常播放（原先固定从 1 起，2 帧角色会卡在第 2 帧）。
        self.index = (self.index + 1) % len(self._frames)
        self._apply_frame(self.index)

    def _apply_frame(self, index=0):
        """把指定帧套用到窗口（供初始化与切换后立即显示）。

        注意顺序：``setMask`` 会把窗口的 minimumSize 顶到该遮罩的尺寸，
        之后再 ``resize`` 到更小的尺寸就会被 Qt 静默忽略。因此这里
        resize → setMask → 再把下限清零，保证「从大缩放切到小缩放」时
        窗口尺寸真的能缩小。
        """
        if not self._frames:
            return
        self.index = index % len(self._frames)
        self.pm, mask = self._frames[self.index]
        size = self.pm.size()
        if size.width() < self.minimumWidth() or size.height() < self.minimumHeight():
            self.setMinimumSize(0, 0)   # 先解除上一帧遮罩留下的下限
        self.resize(size)
        self.setMask(mask)
        self.setMinimumSize(0, 0)
        self.lbl.setPixmap(self.pm)

    def _clamp_position(self, w, h):
        """把已记录的位置夹进屏幕，保证整个窗口完整可见。

        缩放后窗口可能很大（如 2.45 倍的夜兰在 800×800 屏幕上占 735×735），
        沿用切换前的坐标会有一部分跑到屏幕外，伙伴「消失」且难以拖回。
        """
        max_x = max(0, self.screenwidth - w)
        max_y = max(0, self.screenheight - h)
        return (max(0, min(self.pos_x, max_x)), max(0, min(self.pos_y, max_y)))

    def _random_position(self, w, h):
        """在屏幕内随机取一个位置（并保证窗口完整可见）。"""
        max_x = max(0, self.screenwidth - w)
        max_y = max(0, self.screenheight - h)
        return random.randint(0, max_x), random.randint(0, max_y)

    def init_window(self):
        """
        初始化窗口
        """
        # 用「当前帧缓存的首帧」而非 self.index 处的帧来量尺寸：
        # 切换人物时 self.index 仍指向上一位的帧循环位置，量到的会是旧尺寸。
        # 顺序上必须先套用帧（_apply_frame 内部会 resize 到新尺寸）再定位，
        # 否则 setGeometry 会用上一位的尺寸把窗口又撑回去。
        pm0 = self._frames[0][0] if self._frames else None
        w = pm0.size().width() if pm0 is not None else self.wt
        h = pm0.size().height() if pm0 is not None else self.ht
        if not self.pos_x and not self.pos_y:
            self.pos_x, self.pos_y = self._random_position(w, h)

        # 复用同一个 QLabel：setCentralWidget 会删除并替换旧控件，
        # 每次切换都新建一个会让已删除控件堆积（切几十次后内存明显上涨）。
        if getattr(self, 'lbl', None) is None:
            self.lbl = QtWidgets.QLabel(self)  # 初始化一个QLabel对象
            self.lbl.setScaledContents(True)
            self.setCentralWidget(self.lbl)

        # 换人前先解除上一位留下的尺寸下限。
        # setMask 会把窗口的 minimumSize 顶到遮罩大小（如 2.45 倍的 735×735），
        # clearMask 不会把它还原，于是后续 resize(180) 被 Qt 悄悄忽略——
        # 表现为「切到小个子角色后窗口仍是上一个的大小」。这里显式清零。
        self.clearMask()
        self.setMinimumSize(0, 0)
        self._apply_frame(0)          # 套用新人物的首帧，同时 resize 到正确尺寸

        # 窗口属性必须在定位之前设好：setWindowFlags 会重置窗口几何，
        # 若在其之前 setGeometry，位置与尺寸会被 Qt 丢弃（这正是「切换后总被
        # 拽回左上角 / 尺寸不跟随」的直接原因）。
        self.setWindowFlags(Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint)  # 窗口置顶且去掉边框
        self.setAutoFillBackground(False)  # 设置窗口背景透明
        self.setAttribute(Qt.WA_TranslucentBackground, True)

        # 最后定位：按当前人物的实际尺寸夹紧在屏幕内，保证完整可见
        self.pos_x, self.pos_y = self._clamp_position(w, h)
        self.setGeometry(self.pos_x, self.pos_y, w, h)
        self.show()  # 显示窗口
        self.tp.setIcon(QIcon(self._frames[self.index][0]))  # 系统托盘图标

    def play_greeting(self, force=False):
        """播放**当前人物**在**当前时段**的问候语音。

        启动与每次切换人物都会调用，问候内容按调用时刻的小时重新判定
        （早上好 / 中午好 / 晚上好 / 晚安），所以上午切换角色说「早上好」，
        傍晚切换说「晚上好」。

        三处容错（v3.6~v3.7）：
        1. **缺语音不再崩**——角色可能没录某个时段的问候（菲谢尔就没有标准的
           「早上好」），原先直接取文件会抛 FileNotFoundError；现按候选顺序降级，
           一个都没有就静默跳过。
        2. **冷却只针对同一个人**——``GREETING_COOLDOWN`` 秒内**不重复播同一人**
           （防止连点同一个人时刷屏），但**换人一定播**。v3.7 首版把冷却做成了
           全局时间戳，结果启动问候后 60 秒内切换任何人都被拦掉，托盘切换听不到
           问候——冷却的粒度错了。
        3. **时段变化立即重播**——跨过整点、时段关键词不同（如「早上好」→「中午好」）
           时无需等冷却。

        ``force=True`` 可跳过全部冷却（用于测试与强制重播）。
        """
        if not self.audio_player:
            return
        now = datetime.datetime.now()
        keyword = greeting_name(now.hour)
        if not force and self._last_greeting:
            elapsed = (now - self._last_greeting[0]).total_seconds()
            same_role = (self._last_greeting[1] == self.role_name)
            same_slot = (self._last_greeting[2] == keyword)
            # 只有「同一个人 + 同一时段」才需要冷却；换人或跨时段立即播
            if same_role and same_slot and elapsed < GREETING_COOLDOWN:
                return
        try:
            available = self.store.list_voices(self.role_name, 'greeting')
        except Exception:
            return
        name = pick_greeting(available, now.hour)
        if not name:
            return
        try:
            self._play_voice(self.role_name, name, volume=0.5)
            # 记录 (时刻, 人物, 时段关键词)：冷却要同时比对三者，见方法文档
            self._last_greeting = (now, self.role_name, keyword)
        except (FileNotFoundError, RuntimeError) as e:
            # 语音缺失/损坏都不该影响程序运行（pygame 的 mixer 异常多为 RuntimeError）
            print(f'问候语音播放失败（{self.role_name}/{name}）：{e}')

    def tray(self):
        """
        建立一个托盘
        """
        self.bar = QMenuBar(self)
        self.menu = self.bar.addMenu('菜单')
        self.partners = self.menu.addMenu('人物')
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
        self.partners.clear()
        available = set(self.store.list_roles())
        # config 中登记过的角色按登记顺序排前，其余（新导入未登记的）排在后面
        ordered = [r for r in config['frame_scale'] if r in available]
        ordered += sorted(available - set(ordered))
        for role in ordered:
            act = QAction(role, self)
            act.triggered.connect(lambda checked=False, r=role: self.reshow(r))
            self.partners.addAction(act)

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
        """从 zip 或目录导入素材包，刷新菜单并同步配置，返回导入报告。"""
        report = import_assets(path, os.path.join(BASE_DIR, 'assets.db'),
                               config_store)
        # 导入会为新角色登记默认帧率/缩进，从配置库同步回内存
        config.clear()
        config.update(config_store.load())
        self._rebuild_role_menu()
        self._rebuild_bgm_menu()
        return report

    def reshow(self, name):
        """切换到指定人物：重载语音、重建帧缓存、重新落位并保存设置。

        切换后立即写入配置库（而不是等到退出时），这样即使程序被强杀，
        下次启动仍是刚才那个人物。切换完成时按**当前时段**向新人物问好
        （受 :data:`GREETING_COOLDOWN` 冷却保护，连点切换不会一直播）。
        """
        self.talk_list = self.store.list_voices(name, 'chat')
        self.know_list = self.store.list_voices(name, 'know')
        if mixer.get_busy():
            mixer.stop()
        self.role_name = name
        config['role'] = name
        config['frame_scale'].setdefault(name, [60, 1.0])  # 新导入角色可能没有登记
        self.scale = config['frame_scale'][self.role_name][1]
        self.file_list = self.store.list_frames(self.role_name)
        if not self.file_list:
            # 该人物没有帧资源：回退到第一个可用人物，避免动画循环取帧越界
            fallback = self.store.list_roles()
            if not fallback:
                raise RuntimeError('资源库中没有任何人物资源，请先导入素材包')
            name = fallback[0]
            self.role_name = name
            config['role'] = name
            config['frame_scale'].setdefault(name, [60, 1.0])
            self.scale = config['frame_scale'][name][1]
            self.file_list = self.store.list_frames(name)
        self._load_frame_cache()
        # 每个新人物给一个新的随机位置；init_window 会按其实际尺寸夹紧在屏幕内
        w = self._frames[0][0].size().width() if self._frames else self.wt
        h = self._frames[0][0].size().height() if self._frames else self.ht
        self.pos_x, self.pos_y = self._random_position(w, h)
        self.init_window()   # 内部会 setIcon + show 窗口
        # 托盘此刻已由 init_window 设好图标，这里再 show 一次是安全的
        # （早期版本 tray() 先于 init_window 执行，导致启动时「No Icon set」警告）
        self.tp.show()
        self.timer.start(config['frame_scale'][self.role_name][0])
        self.save_config()   # 切换即刻落库，不依赖退出时保存
        self.play_greeting()  # 按时段向新人物问好（冷却内会跳过）

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
            # 通过设置透明度方式隐藏伙伴
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
    pilot = Pilot()
    sys.exit(app.exec())
