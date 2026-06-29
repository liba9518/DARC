from datetime import datetime
from zoneinfo import ZoneInfo

from scripts.push_intraday_monitor import evaluate_alert


def test_alert_requires_meaningful_move():
    alert = evaluate_alert(
        code="测试",
        name="测试公司",
        current_price=102.5,
        day_change=2.5,
        signal_price=100,
        previous_alert_price=100,
        last_alert_at=None,
        now=datetime.now(ZoneInfo("Asia/Shanghai")),
    )
    assert alert is not None
    assert "继续" in alert["conclusion"]


def test_alert_ignores_small_noise():
    alert = evaluate_alert(
        code="测试",
        name="测试公司",
        current_price=100.5,
        day_change=0.5,
        signal_price=100,
        previous_alert_price=100,
        last_alert_at=None,
        now=datetime.now(ZoneInfo("Asia/Shanghai")),
    )
    assert alert is None

