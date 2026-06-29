import json
import re

from integrations.a_stock_direct import is_a_share
from integrations.chokepoint_atlas import collect_chokepoint_lanes
from scripts.push_strategy_digest import build_message, parse_tickers


def test_parse_tickers_deduplicates_and_normalizes():
    assert parse_tickers("aapl, AAPL，600519") == ["AAPL", "600519"]


def test_a_share_detection():
    assert is_a_share("600519")
    assert is_a_share("300750")
    assert not is_a_share("AAPL")


def test_digest_formats_quiver_and_a_share_sections():
    message = build_message(
        ["AAPL", "600519"],
        {
            "国会交易": [
                {
                    "Ticker": "AAPL",
                    "Transaction": "Purchase",
                    "Representative": "Example",
                    "Party": "I",
                    "Range": "$1,001 - $15,000",
                    "TransactionDate": "2026-06-20T00:00:00Z",
                }
            ],
            "内部人交易": [],
            "政府合同": [],
            "场外/暗池": [],
            "Quiver新闻": [],
        },
        [
            {
                "name": "贵州茅台",
                "code": "600519",
                "price": 1500.0,
                "pct_change": 1.2,
                "pe_ttm": 22.0,
                "pb": 7.5,
                "turnover": 0.3,
            }
        ],
        max_items=5,
        errors=[],
    )
    assert "国会交易" in message
    assert "苹果公司" in message
    assert "沪深股票直连行情" in message
    assert "600519" in message
    assert re.search(r"[A-Za-z]", message) is None


def test_collects_chokepoint_lane_and_renders_digest(tmp_path):
    payload = {
        "meta": {
            "pack_id": "ai-power",
            "title": "AI power lane",
            "as_of_date": "2026-06-20",
        },
        "thesis": {
            "lane": "Power distribution and liquid cooling",
            "end_system": "AI factory",
            "bottleneck_call": "Power density and cooling deployment",
        },
        "companies": [
            {
                "ticker": "VRT",
                "constraint_score": 5,
                "evidence_score": 4,
                "consensus_score": 3,
                "mispricing_score": 3,
                "catalyst_score": 4,
            }
        ],
        "catalysts": [{"label": "Earnings", "watch_for": "AI backlog and lead times"}],
    }
    source = tmp_path / "research_pack.json"
    source.write_text(json.dumps(payload), encoding="utf-8")

    lanes, errors = collect_chokepoint_lanes([tmp_path])

    assert errors == []
    assert lanes[0].top_names == ("VRT",)
    message = build_message(
        ["VRT"],
        {},
        [],
        chokepoint_lanes=lanes,
        max_items=5,
        errors=[],
    )
    assert "人工智能供应链瓶颈研究" in message
    assert "供配电与液冷" in message
    assert "维谛技术" in message
    assert re.search(r"[A-Za-z]", message) is None
