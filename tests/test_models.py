from __future__ import annotations

from codefuel.models import Metric, UsageSnapshot


def test_worst_metric_ignores_amount_rows():
    snap = UsageSnapshot(
        provider_id="x",
        display_name="X",
        metrics=[
            Metric(label="周限额", used_percent=64.0),
            Metric(label="总余额 (¥)", used_percent=0.0, kind="amount", text="¥999.00"),
        ],
    )
    # amount 行 used_percent=0 但不应被当成 worst；percent 行才算
    assert snap.worst_metric is not None
    assert snap.worst_metric.label == "周限额"


def test_worst_metric_none_when_only_amounts():
    snap = UsageSnapshot(
        provider_id="x",
        display_name="X",
        metrics=[
            Metric(label="总余额 (¥)", used_percent=0.0, kind="amount", text="¥10.00"),
        ],
    )
    assert snap.worst_metric is None
