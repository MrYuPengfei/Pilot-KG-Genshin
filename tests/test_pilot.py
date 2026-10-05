"""pilot 模块中与角色问候相关的单元测试。

问候逻辑的完整测试见 ``tests/test_greeting.py``：v3.6 起时段表与挑选逻辑
拆成了 ``greeting_name`` / ``pick_greeting`` 两个纯函数，便于单独测试。
本文件只保留最小可用性检查，避免同一逻辑在两处重复断言。
"""

from pilot import greeting_name, pick_greeting


def test_greeting_name_basic_ranges():
    assert greeting_name(4) == '晚安'
    assert greeting_name(7) == '早上好'
    assert greeting_name(12) == '中午好'
    assert greeting_name(19) == '晚上好'
    assert greeting_name(23) == '晚安'


def test_pick_greeting_uses_available_files():
    available = ['早上好.mp3', '晚上好.mp3', '晚安.mp3']
    assert pick_greeting(available, 7) == '早上好.mp3'
    # 没有中午好，应降级到其它已有问候，而不是报错或返回 None
    assert pick_greeting(available, 12) == '早上好.mp3'
