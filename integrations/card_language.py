"""Keep all user-visible Feishu card text plain, decisive and Chinese-only."""

from __future__ import annotations

import re
from copy import deepcopy
from typing import Any


US_NAME_MAP = {
    "NVDA": "英伟达",
    "MSFT": "微软",
    "GOOGL": "谷歌",
    "AMZN": "亚马逊",
    "META": "元宇宙平台公司",
    "AVGO": "博通",
    "AMD": "超威半导体",
    "ANET": "安移通网络",
    "VRT": "维谛技术",
    "MU": "美光科技",
    "TSM": "台积电",
    "PLTR": "帕兰提尔",
    "AAPL": "苹果公司",
    "FORM": "福姆法克",
    "CAMT": "康特科技",
    "AMKR": "安靠科技",
    "ICHR": "艾科控股",
    "AEHR": "艾尔测试系统",
    "UCTT": "超科林半导体",
    "ETN": "伊顿",
    "TT": "特灵科技",
}


def stock_display_name(code: str, name: str = "") -> str:
    value = str(code or "").strip().upper()
    candidate = str(name or "").strip()
    if value in US_NAME_MAP:
        return US_NAME_MAP[value]
    if candidate and not re.search(r"[A-Za-z]", candidate):
        return candidate
    return f"海外公司{sum(ord(char) for char in value) % 1000:03d}"


def confidence_text(value: str) -> str:
    return {"A": "高", "B": "较高", "C": "一般"}.get(str(value).upper(), "一般")


def chinese_visible_text(value: Any) -> str:
    text = str(value or "")
    protected_tickers: dict[str, str] = {}

    def protect_ticker(match: re.Match[str]) -> str:
        placeholder = f"占位符{len(protected_tickers)}结束"
        protected_tickers[placeholder] = match.group(0)
        return placeholder

    # User-facing US stock labels intentionally retain the ticker, e.g. 台积电（TSM）.
    text = re.sub(r"（[A-Z][A-Z0-9.\-]{0,9}）", protect_ticker, text)
    replacements = {
        "A股": "沪深股票",
        "AI": "人工智能",
        "RSI": "强弱指标",
        "PE": "市盈率",
        "PB": "市净率",
        "DPI": "场外空头占比",
        "ETF": "交易型基金",
        "Quiver News": "另类财经消息",
        "Quiver Quant": "另类数据平台",
        "Chokepoint Atlas": "供应链瓶颈研究",
        "API": "数据接口",
        "HBM": "高带宽存储",
        "NVIDIA DSX AI Factory": "英伟达人工智能工厂",
        "HBM test and advanced packaging support tools": "高带宽存储测试与先进封装设备",
        "Power distribution and liquid cooling": "供配电与液冷",
        "AI factory power train": "人工智能工厂供电系统",
        "HBM-related test throughput and advanced-packaging inspection remain gating layers.": "测试产能和先进封装检测仍是扩产关键。",
        "Power-density upgrades and liquid-cooling deployment become gating layers once compute demand outruns site readiness.": "算力需求快速增长后，供电升级和液冷落地成为关键限制。",
        "Next quarterly earnings": "下一次季度业绩",
        "Lead-time language, AI demand mix, HBM / advanced packaging commentary": "重点看交付周期、人工智能需求和先进封装进展",
        "Purchase": "买入",
        "Sale": "卖出",
        "High-priority lane": "高优先级方向",
        "Very high-priority lane": "最高优先级方向",
        "Watch closely": "重点跟踪",
        "Lower-priority lane for now": "暂缓关注",
    }
    for source, target in sorted(replacements.items(), key=lambda item: len(item[0]), reverse=True):
        text = text.replace(source, target)
    for ticker, name in US_NAME_MAP.items():
        text = re.sub(rf"\b{re.escape(ticker)}\b", name, text)
    text = re.sub(r"\[([^\]]+)\]\(https?://[^)]+\)", r"\1", text)
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"[A-Za-z]+", "", text)
    for placeholder, ticker in protected_tickers.items():
        text = text.replace(placeholder, ticker)
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r" *([｜：，。；（）]) *", r"\1", text)
    return text.strip()


def sanitize_card(card: dict[str, Any]) -> dict[str, Any]:
    """Sanitize only visible title/content fields; preserve Feishu protocol tags."""
    result = deepcopy(card)

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key == "content" and isinstance(value, str):
                    node[key] = chinese_visible_text(value)
                else:
                    walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(result)
    return result


def visible_card_text(card: dict[str, Any]) -> str:
    values: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if isinstance(node.get("content"), str):
                values.append(node["content"])
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(card)
    return "\n".join(values)
