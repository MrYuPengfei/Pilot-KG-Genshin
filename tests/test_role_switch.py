"""人物切换相关的回归测试。

锁住 v3.6 修复的三个缺陷（详见 doc/REFACTORING_LOG.md）：
1. ``setGeometry(x, y, w, h)`` 参数错位成 ``(0, 400, pos_x, pos_y)``，
   位置被写死左上角、随机位置从未生效；
2. ``setMask`` 会把 ``minimumSize`` 顶到遮罩尺寸且不随 ``clearMask`` 还原，
   导致「大缩放切回小缩放」时窗口尺寸不跟随（2.45 倍 → 0.6 倍仍是 735×735）；
3. 切换后未即时落库，配置要等到退出才保存。

这些都需要真实的 QApplication 与 Qt 几何/遮罩行为，纯逻辑测试覆盖不到，
因此这里用离屏 Qt 跑真实窗口。素材库很重，故只在真实 assets.db 存在时运行。
"""

import os

import pytest

pytest.importorskip('PySide6')

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('SDL_AUDIODRIVER', 'dummy')

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS_DB = os.path.join(ROOT, 'assets.db')

pytestmark = pytest.mark.skipif(
    not os.path.isfile(ASSETS_DB),
    reason='需要真实 assets.db（约 460MB），跳过窗口行为测试')


@pytest.fixture(scope='module')
def app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.fixture(scope='module')
def pilot_obj(app):
    """真实 Pilot 实例（读真实 assets.db，会把当前人物写进 config.db）。"""
    import pilot as pilot_mod
    from config_store import ConfigStore

    original = ConfigStore(ROOT, auto_seed=False).load()['role']
    p = pilot_mod.Pilot()
    yield p
    # 还原当前人物，避免污染本机配置
    try:
        p.reshow(original)
    except Exception:
        pass


def _in_screen(p):
    return (p.x() >= 0 and p.y() >= 0
            and p.x() + p.width() <= p.screenwidth
            and p.y() + p.height() <= p.screenheight)


def test_switch_persists_immediately(pilot_obj, app):
    """切换人物后应立即写入配置库，而不是等退出时。"""
    import sqlite3
    p = pilot_obj
    original = p.role_name
    target = next(r for r in p.store.list_roles() if r != original)
    try:
        p.reshow(target)
        conn = sqlite3.connect(p.config_store.db_path)
        try:
            row = conn.execute("SELECT value FROM kv WHERE key='role'").fetchone()
        finally:
            conn.close()
        assert row is not None, '配置库中没有 role 记录'
        assert target in row[0], f'切换后未落库：库中仍是 {row[0]}'
    finally:
        p.reshow(original)


def test_window_not_pinned_to_top_left(pilot_obj, app):
    """回归：setGeometry 参数错位会让窗口恒定在 (0, 400)。"""
    p = pilot_obj
    p.reshow(p.store.list_roles()[0])
    assert (p.x(), p.y()) != (0, 400), '窗口被写死在 (0, 400)，随机位置未生效'
    assert (p.x(), p.y()) == (p.pos_x, p.pos_y), '实际位置与记录的位置不一致'


def test_size_follows_character_scale(pilot_obj, app):
    """回归：setMask 抬高 minimumSize 导致大→小切换时尺寸不跟随。"""
    p = pilot_obj
    # 找一个大缩放与一个小缩放的角色
    scales = {r: p.config_store.frame_scale(r)[1] for r in p.store.list_roles()}
    big = max(scales, key=lambda r: scales[r])
    small = min(scales, key=lambda r: scales[r])
    if scales[big] == scales[small]:
        pytest.skip('所有人物缩放相同，无法验证')

    original = p.role_name
    try:
        p.reshow(big)
        w_big = p.width()
        assert abs(w_big - int(scales[big] * p.wt)) <= 2, \
            f'{big} 尺寸 {w_big} 与缩放 {scales[big]} 不符'
        p.reshow(small)
        w_small = p.width()
        assert abs(w_small - int(scales[small] * p.wt)) <= 2, \
            f'切到 {small} 后尺寸仍是 {w_small}（上一位是 {big}），setMask 未解除尺寸下限'
        # 再切回大的，验证双向都正常
        p.reshow(big)
        assert abs(p.width() - w_big) <= 2, '切回大缩放角色后尺寸未恢复'
    finally:
        p.reshow(original)


def test_switched_window_stays_on_screen(pilot_obj, app):
    """切换后窗口应完整落在屏幕内（大缩放角色尤其容易出屏）。"""
    p = pilot_obj
    original = p.role_name
    out_of_screen = []
    try:
        for role in p.store.list_roles():
            p.reshow(role)
            if not _in_screen(p):
                out_of_screen.append((role, p.x(), p.y(), p.width(), p.height()))
    finally:
        p.reshow(original)
    assert not out_of_screen, f'以下人物切换后超出屏幕：{out_of_screen[:5]}'


def test_repeated_switch_is_stable(pilot_obj, app):
    """反复切换同一人物不应出现尺寸漂移。"""
    p = pilot_obj
    original = p.role_name
    try:
        p.reshow('甘雨' if '甘雨' in p.store.list_roles() else original)
        first = (p.width(), p.height())
        for _ in range(5):
            p.reshow(p.role_name)
        assert (p.width(), p.height()) == first, \
            f'反复切换后尺寸漂移：{first} -> {(p.width(), p.height())}'
    finally:
        p.reshow(original)


def test_qlabelled_reused_not_leaked(pilot_obj, app):
    """回归：每次切换都新建 QLabel 会让已删除控件堆积。"""
    p = pilot_obj
    original = p.role_name
    try:
        p.reshow('七七' if '七七' in p.store.list_roles() else original)
        first = id(p.lbl)
        p.reshow(p.role_name)
        assert id(p.lbl) == first, '切换时重建了 QLabel，旧控件未复用'
        # 中央控件应当仍是同一个
        assert p.centralWidget() is p.lbl
    finally:
        p.reshow(original)


def test_act_cycles_through_all_frames(pilot_obj, app):
    """动画应遍历所有帧（含第 0 帧），且 1~2 帧的角色也能正常循环。"""
    p = pilot_obj
    original = p.role_name
    try:
        p.reshow('七七' if '七七' in p.store.list_roles() else original)
        total = len(p._frames)
        assert total > 2, '需要多帧角色才能验证循环'
        p._apply_frame(0)
        seen = set()
        for _ in range(total):
            p.act()
            seen.add(p.index)
        assert seen == set(range(total)), f'帧循环未覆盖全部帧：{sorted(seen)[:5]}...'
    finally:
        p.reshow(original)


def test_switching_character_greets(pilot_obj, app):
    """回归（v3.7）：切换人物后应按当前时段向新人物问好。

    v3.6 把问候改成「仅启动一次」，这里反向锁住：``reshow`` 必须触发问候。
    冷却用「把上次问候时间提前」绕开，才能确定性地断言切换确实调了问候。
    """
    import datetime

    import pilot as pilot_mod

    p = pilot_obj
    original = p.role_name
    played = []
    p._play_voice = lambda role, name, volume=1.0: played.append((role, name))
    try:
        p.audio_player = True
        # 清空冷却并确保新人物有问候语音（选有问候的角色）
        roles = [r for r in p.store.list_roles() if p.store.list_voices(r, 'greeting')]
        assert roles, '资源库里没有任何角色的问候语音'
        target = next(r for r in roles if r != original)
        p._last_greeting = None
        p.reshow(target)
        assert played, f'切换到 {target} 后应播放问候'
        role, name = played[0]
        assert role == target, f'应由新人物问好，实际是 {role}'
        assert pilot_mod.greeting_name(datetime.datetime.now().hour) in name, \
            f'问候内容应匹配当前时段，实际播了 {name}'
    finally:
        p._play_voice = pilot_mod.Pilot.__dict__['_play_voice'].__get__(p)
        p.reshow(original)
