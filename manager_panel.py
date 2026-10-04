"""管理面板：人物管理 / 音乐管理 / 素材管理 / 帮助文档四个标签页。

从托盘菜单「管理面板」打开。面板通过 Pet 暴露的方法操作，
所有变更即时生效并与托盘菜单状态保持同步。
"""

import os

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (QDialog, QTabWidget, QWidget, QVBoxLayout, QHBoxLayout,
                               QListWidget, QLabel, QPushButton, QSpinBox, QDoubleSpinBox,
                               QCheckBox, QMessageBox, QFileDialog, QGroupBox, QFormLayout,
                               QSizePolicy, QTextBrowser)

APP_VERSION = '2.1'
REPO_URL = 'https://github.com/MrYuPengfei/yuanshen-desktoppet.git'
REPO_PAGE = 'https://github.com/MrYuPengfei/yuanshen-desktoppet'

HELP_HTML = f"""
<h2>原神桌面宠物 v{APP_VERSION} · 帮助文档</h2>
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
<li><b>版权提醒</b>：本项目仅供学习交流，请勿导入或分发侵犯第三方版权的素材。</li>
</ul>
<hr>

<h3>二、版本变更记录</h3>
<h4>v{APP_VERSION}（当前版本）</h4>
<ul>
<li>新增管理面板：人物预览与管理、帧率/缩放调整、音乐控制、资源统计、素材导入；</li>
<li>管理面板内置帮助文档页（本页）；</li>
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
<li>基础桌面宠物：人物切换、拖动、隐藏、时段问候、闲聊/了解语音、地区背景音乐。</li>
</ul>
<hr>

<h3>三、第三方开源库</h3>
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

<h3>四、开源地址</h3>
<p>仓库：<a href="{REPO_PAGE}">{REPO_PAGE}</a><br>
克隆：<code>git clone {REPO_URL}</code></p>
<p>仅供开发研究玩乐，请勿用作商业用途。游戏素材版权归上海米哈游网络科技股份有限公司所有。</p>
"""


class ManagerPanel(QDialog):
    def __init__(self, pet, config):
        super().__init__(pet)
        self.pet = pet
        self.store = pet.store
        self.config = config
        self.setWindowTitle(f'原神桌面宠物 v{APP_VERSION} · 管理面板')
        # 窗口图标：与系统托盘一致，使用当前宠物的当前帧（不依赖磁盘路径）
        if pet._frames:
            self.setWindowIcon(QIcon(pet._frames[pet.index][0]))
        self.resize(660, 440)

        layout = QVBoxLayout(self)
        self.tabs = QTabWidget(self)
        layout.addWidget(self.tabs)

        self._build_roles_tab()
        self._build_music_tab()
        self._build_assets_tab()
        self._build_help_tab()
        self.refresh()

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
        self.set_current_btn = QPushButton('设为当前宠物')
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
        self.role_status_label.setText('当前宠物' if role == self.pet.role_name else '未使用')
        self.role_status_label.setStyleSheet(
            'color: #d33; font-weight: bold;' if role == self.pet.role_name else '')

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
        self.pet.set_role_timing(role, self.interval_spin.value(), self.scale_spin.value())
        QMessageBox.information(self, '已应用', f'「{role}」的播放设置已保存。')

    def _set_current_role(self):
        role = self._selected_role()
        if not role or role == self.pet.role_name:
            return
        self.pet.reshow(role)
        self._on_role_selected(role)
        self.pet.save_config()

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
        if role == self.pet.role_name:
            self.pet.reshow(self.store.list_roles()[0])
        self.pet._rebuild_role_menu()
        self.pet.save_config()
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
        self.voice_checkbox.toggled.connect(self.pet.set_voice_enabled)
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
        self.pet.play_area_bgm(item.text())
        self._refresh_music_state()

    def _stop_bgm(self):
        self.pet.stop_bgm()
        self._refresh_music_state()

    def _mute_all(self):
        self.pet.set_voice_enabled(False)
        self.pet.stop_bgm()
        self._refresh_music_state()

    def _refresh_music_state(self):
        current = self.config.get('bg_music')
        self.bgm_state_label.setText(
            f'正在播放: {current}' if current else '背景音乐: 未播放')
        self.voice_checkbox.blockSignals(True)
        self.voice_checkbox.setChecked(self.pet.audio_player)
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

        import_box = QGroupBox('导入素材包（新人物 / 新地区，导入后立即出现在菜单中）')
        import_row = QHBoxLayout(import_box)
        import_zip_btn = QPushButton('导入 zip 素材包')
        import_zip_btn.clicked.connect(self._import_zip)
        import_dir_btn = QPushButton('导入素材目录')
        import_dir_btn.clicked.connect(self._import_dir)
        refresh_btn = QPushButton('刷新统计')
        refresh_btn.clicked.connect(self.refresh)
        import_row.addWidget(import_zip_btn)
        import_row.addWidget(import_dir_btn)
        import_row.addWidget(refresh_btn)
        root.addWidget(import_box)
        root.addStretch(1)

        self.tabs.addTab(tab, '素材管理')

    def _do_import(self, path):
        try:
            report = self.pet.import_from_path(path)
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
        target = current_role or self.pet.role_name
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

    def closeEvent(self, event):
        self.pet.on_manager_closed()
        super().closeEvent(event)
