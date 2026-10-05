"""角色问好（greeting）测试。

锁住 v3.6 修复的三个缺陷：
1. 语音分类器只认「早上好.mp3」这类**全等**文件名，导致「早上好问候菲谢尔.mp3」
   被归为无分类，问候找不到文件；
2. 时段表有 7 个小时（0~3、15~17 点）完全静默；
3. 缺少对应时段语音时直接取文件会抛 FileNotFoundError。
"""

import os

import pytest

from pilot import greeting_name, pick_greeting, GREETING_SCHEDULE
from resource_store import _classify_voice


# ---------- 分类器 ----------

@pytest.mark.parametrize('name', ['早上好.mp3', '中午好.mp3', '晚上好.mp3', '晚安.mp3'])
def test_classify_plain_greetings(name):
    assert _classify_voice(name) == 'greeting'


@pytest.mark.parametrize('name', ['早上好问候菲谢尔.mp3', '早上好问候奥兹.mp3',
                                  '中午好罐头.mp3', '中午好异响.mp3'])
def test_classify_suffixed_greetings(name):
    """回归：带后缀的问候语曾被判为无分类（category=None）。"""
    assert _classify_voice(name) == 'greeting'


def test_classify_other_categories_unchanged():
    assert _classify_voice('闲聊彼方之人.mp3') == 'chat'
    assert _classify_voice('想要了解菲谢尔其一.mp3') == 'know'
    # 不属于任何类别的语音（如「初次见面.mp3」）仍返回 None
    assert _classify_voice('初次见面.mp3') is None


# ---------- 时段表 ----------

def test_greeting_covers_all_24_hours():
    """回归：原先 0~3 点与 15~17 点返回 False，一天有 7 小时静默。"""
    missing = [h for h in range(24) if not greeting_name(h)]
    assert not missing, f'这些小时没有问候：{missing}'


@pytest.mark.parametrize('hour,expected', [
    (0, '晚安'), (3, '晚安'), (4, '晚安'),      # 深夜与凌晨
    (7, '早上好'), (10, '早上好'),
    (12, '中午好'), (14, '中午好'),
    (16, '晚上好'), (19, '晚上好'), (22, '晚上好'),  # 下午过渡到晚间
    (23, '晚安'),                                  # 深夜
])
def test_greeting_by_hour(hour, expected):
    assert greeting_name(hour) == expected


def test_greeting_accepts_out_of_range_hour():
    """小时越界（如 datetime 异常值）不应抛异常。"""
    assert greeting_name(24) == greeting_name(0)
    assert greeting_name(-1) is not None


def test_schedule_ranges_are_wellformed():
    for (start, end), _name in GREETING_SCHEDULE:
        assert 0 <= start <= 23 and 0 <= end <= 24
        assert start != end


# ---------- 挑选逻辑 ----------

ALL = ['早上好.mp3', '中午好.mp3', '晚上好.mp3', '晚安.mp3']


def test_pick_standard_character():
    for hour, expect in ((7, '早上好.mp3'), (12, '中午好.mp3'),
                         (19, '晚上好.mp3'), (2, '晚安.mp3')):
        assert pick_greeting(ALL, hour) == expect


def test_pick_suffixed_file():
    """菲谢尔没有标准「早上好.mp3」，应选中带后缀的那条。"""
    fei = ['中午好.mp3', '晚上好.mp3', '晚安.mp3',
           '早上好问候奥兹.mp3', '早上好问候菲谢尔.mp3']
    picked = pick_greeting(fei, 7)
    assert picked and '早上好' in picked, '早上应命中带后缀的问候'
    # 其余时段仍取标准文件
    assert pick_greeting(fei, 12) == '中午好.mp3'
    assert pick_greeting(fei, 2) == '晚安.mp3'


def test_pick_falls_back_when_keyword_absent():
    """该时段的声音没有时，降级到其它时段的声音，而不是返回 None。"""
    only_evening = ['晚上好.mp3']
    assert pick_greeting(only_evening, 7) == '晚上好.mp3'
    assert pick_greeting(['晚安.mp3'], 7) == '晚安.mp3'


def test_pick_returns_none_when_no_greetings():
    assert pick_greeting([], 7) is None
    assert pick_greeting(None, 7) is None


def test_pick_deterministic_for_multiple_same_keyword():
    """同一关键词有多个版本时，结果应稳定（取列表首个）。"""
    two = ['早上好问候甲.mp3', '早上好问候乙.mp3', '晚安.mp3']
    assert pick_greeting(two, 7) == '早上好问候甲.mp3'
    assert pick_greeting(two, 7) == pick_greeting(two, 7)


@pytest.mark.skipif(not os.path.isfile(os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'assets.db')),
    reason='需要真实 assets.db')
def test_every_character_has_a_greeting():
    """回归：菲谢尔曾因缺「早上好」在早上问候失败。"""
    from resource_store import ResourceStore
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    store = ResourceStore(root)
    try:
        for role in store.list_roles():
            available = store.list_voices(role, 'greeting')
            assert available, f'{role} 没有任何问候语音'
            # 每个时段都应能挑到一条
            for hour in (2, 7, 12, 16, 22):
                assert pick_greeting(available, hour), f'{role} 在 {hour} 点无问候'
    finally:
        store.close()


# ============ v3.7：切换人物时按时段问候 ============

import datetime                                              # noqa: E402

from pilot import GREETING_COOLDOWN                          # noqa: E402


class _StubPilot:
    """只提供 play_greeting 所需成员的最小替身（不构造真实窗口）。"""

    def __init__(self, voices=('早上好问候菲谢尔.mp3', '中午好.mp3',
                              '晚上好.mp3', '晚安.mp3'), store_error=False):
        import pilot as pilot_mod
        self.audio_player = True
        self.role_name = '菲谢尔'
        self._last_greeting = None
        self.played = []
        self._voices = list(voices)
        self._store_error = store_error
        self.store = self
        self._play_voice = lambda role, name, volume=1.0: self.played.append(name)
        # 直接复用真实方法，保证测的是产品代码
        self.greet = pilot_mod.Pilot.play_greeting.__get__(self)

    def list_voices(self, role, category=None):
        if self._store_error:
            raise RuntimeError('数据库被占用')
        return list(self._voices)



@pytest.fixture
def stub(monkeypatch):
    return _StubPilot()


def _freeze_hour(monkeypatch, hour):
    """把 pilot 模块里 datetime.datetime.now() 固定到指定小时。

    只替换模块内的 ``datetime`` **属性**（pilot 里写的是 ``datetime.datetime.now()``），
    整个替换成类会让后续 ``datetime.datetime`` 取不到。
    """
    import pilot as pilot_mod
    real = datetime.datetime

    class Frozen(real):
        @classmethod
        def now(cls, tz=None):
            return real(2026, 10, 5, hour, 0, 0)

    monkeypatch.setattr(pilot_mod.datetime, 'datetime', Frozen)


@pytest.mark.parametrize('hour, keyword', [
    (7, '早上好'), (10, '早上好'),                    # 早上
    (12, '中午好'), (14, '中午好'),                  # 中午
    (16, '晚上好'), (20, '晚上好'),                  # 下午 / 晚上
    (23, '晚安'), (2, '晚安'), (4, '晚安'),           # 深夜与凌晨
])
def test_greeting_follows_current_hour(stub, monkeypatch, hour, keyword):
    """回归（v3.7）：问候按**调用时刻**的小时判定，而非启动时的固定值。"""
    _freeze_hour(monkeypatch, hour)
    stub.greet()
    assert stub.played, f'{hour} 点应播放问候'
    assert keyword in stub.played[0]


def test_cooldown_blocks_rapid_switch(stub, monkeypatch):
    """连点切换人物时问候应被冷却拦住（不刷屏）。"""
    _freeze_hour(monkeypatch, 10)
    stub.greet()
    assert len(stub.played) == 1
    for _ in range(5):
        stub.greet()
    assert len(stub.played) == 1, '冷却期内的重复切换不应再播'


def test_cooldown_expires_and_greets_again(stub, monkeypatch):
    """冷却期过后再次问候同一人物应能正常播。"""
    _freeze_hour(monkeypatch, 10)
    stub.greet()
    when, role, slot = stub._last_greeting
    stub._last_greeting = (when - datetime.timedelta(seconds=GREETING_COOLDOWN + 1),
                           role, slot)
    stub.greet()
    assert len(stub.played) == 2


def test_switching_another_role_bypasses_cooldown(stub, monkeypatch):
    """回归（v3.7 修正）：冷却只针对同一人，换人必须立即问候。

    v3.7 首版把冷却做成全局时间戳，导致启动问候后 60 秒内**切换任何人物都被拦掉**
    ——用户反馈「托盘更改人物后没有问好」即源于此。
    """
    _freeze_hour(monkeypatch, 10)
    stub.greet()                      # 先给当前人物问候一次
    assert len(stub.played) == 1
    for other in ('七七', '刻晴', '甘雨'):
        stub.role_name = other
        stub.greet()                  # 换人，冷却期内也必须播
    assert len(stub.played) == 4, '换人时的问候被冷却错误地拦掉了'


def test_new_time_slot_bypasses_cooldown(stub, monkeypatch):
    """跨时段（如早上好→中午好）无需等冷却。"""
    _freeze_hour(monkeypatch, 10)
    stub.greet()
    assert len(stub.played) == 1
    _freeze_hour(monkeypatch, 12)      # 同一人物，但时段关键词变了
    stub.greet()
    assert len(stub.played) == 2, '跨时段应立即播新问候'


def test_repeated_same_role_same_slot_is_throttled(stub, monkeypatch):
    """同一人 + 同一时段连点才需要冷却（防刷屏）。"""
    _freeze_hour(monkeypatch, 10)
    for _ in range(6):
        stub.greet()
    assert len(stub.played) == 1, '连点同一人应只播一次'
    # 但交替换人每次都播
    stub.role_name = '七七'; stub.greet()
    stub.role_name = '菲谢尔'; stub.greet()
    assert len(stub.played) == 3


def test_force_bypasses_cooldown(stub, monkeypatch):
    """force=True（启动时）应跳过冷却。"""
    _freeze_hour(monkeypatch, 10)
    stub.greet()
    stub.greet(force=True)
    assert len(stub.played) == 2


def test_no_greeting_when_audio_disabled(stub, monkeypatch):
    """语音关闭时不问候，也不记时间戳。"""
    _freeze_hour(monkeypatch, 10)
    stub.audio_player = False
    stub.greet()
    assert stub.played == []
    assert stub._last_greeting is None


def test_no_greeting_voices_is_silent(monkeypatch):
    """角色没有任何问候语音时静默跳过，不抛异常。"""
    _freeze_hour(monkeypatch, 10)
    s = _StubPilot(voices=())
    s.greet()
    assert s.played == []


def test_store_error_is_silent(monkeypatch):
    """资源库异常不应让切换人物崩溃。"""
    _freeze_hour(monkeypatch, 10)
    s = _StubPilot(store_error=True)   # list_voices 会抛 RuntimeError
    s.greet()                       # 不应抛
    assert s.played == []


def test_play_failure_does_not_record_timestamp(monkeypatch):
    """播放失败不更新时间戳，否则冷却会误锁死后续问候。"""
    _freeze_hour(monkeypatch, 10)
    s = _StubPilot()

    def boom(role, name, volume=1.0):
        raise FileNotFoundError(name)

    s._play_voice = boom
    s.greet()
    assert s._last_greeting is None
    s._play_voice = lambda role, name, volume=1.0: s.played.append(name)
    s.greet()
    assert len(s.played) == 1
