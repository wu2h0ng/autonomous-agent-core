"""Shared metric name aliases for rule-based NLP modules.

Single source of truth for metric keyword <-> display-name translations, consumed by the
conversation and NL-query modules.
"""

from __future__ import annotations

METRIC_DISPLAY_NAMES: dict[str, str] = {
    "gmv": "GMV",
    "roi": "ROI",
    "revenue": "revenue",
    "conversion_rate": "conversion rate",
    "spend": "ad spend",
    "cac": "CAC",
    "orders": "orders",
    "customer_count": "customer count",
}

DISPLAY_TO_METRIC: dict[str, str] = {}
for _k, _v in METRIC_DISPLAY_NAMES.items():
    DISPLAY_TO_METRIC[_v.lower()] = _k
    DISPLAY_TO_METRIC[_k] = _k
DISPLAY_TO_METRIC.update(
    {
        "advertising spend": "spend",
        "ad cost": "spend",
        "广告花费": "spend",
        "花费": "spend",
        "投入产出比": "roi",
        "转化率": "conversion_rate",
        "成交额": "gmv",
        "销售额": "gmv",
        "营收": "revenue",
        "订单": "orders",
        "客户数": "customer_count",
    }
)
