"""Offline comparisons; changes in value are not investment returns."""
from __future__ import annotations

import math

from .errors import SaxoError


def _scope(snapshot: dict) -> tuple:
    return (
        snapshot["environment"], snapshot["client_key"], snapshot["currency"],
        tuple(sorted(account["AccountKey"] for account in snapshot["accounts"])),
    )


def analyze(snapshots: list[dict], threshold: float = 3.0) -> dict:
    if not math.isfinite(threshold) or threshold <= 0:
        raise SaxoError("Alert threshold must be positive and finite.")
    result = {
        "threshold_pct": threshold, "triggered": False, "alerts": [],
        "comparison": None, "reason": "no_snapshots", "captured_at": None,
        "notice": "Value changes are not returns: cash flows, trading and FX are not neutralized.",
    }
    if not snapshots:
        return result
    current = snapshots[0]
    result["captured_at"] = current["captured_at"]
    result["reason"] = "no_previous_snapshot"
    if len(snapshots) > 1:
        previous = snapshots[1]
        if _scope(current) != _scope(previous):
            result["reason"] = "different_environment_client_currency_or_accounts"
        else:
            delta = current["total_value"] - previous["total_value"]
            pct = 100 * delta / abs(previous["total_value"]) if previous["total_value"] else None
            result["reason"] = "zero_baseline" if pct is None else "comparable"
            result["comparison"] = {
                "previous_captured_at": previous["captured_at"], "delta": delta,
                "change_pct": pct, "currency": current["currency"],
            }
            if pct is not None and abs(pct) >= threshold:
                result["alerts"].append({"kind": "portfolio_value_change", "change_pct": pct})
    for position in current["netpositions"]:
        view = position.get("NetPositionView") or {}
        pct = view.get("InstrumentPriceDayPercentChange")
        if isinstance(pct, bool) or not isinstance(pct, (int, float)) or not math.isfinite(pct):
            continue
        if abs(pct) >= threshold:
            display = position.get("DisplayAndFormat") or {}
            result["alerts"].append({
                "kind": "instrument_daily_price_change",
                "instrument": display.get("Symbol") or position.get("NetPositionId") or "Unknown",
                "change_pct": pct, "price_delay_minutes": view.get("CurrentPriceDelayMinutes"),
            })
    result["triggered"] = bool(result["alerts"])
    return result


def _safe_text(value: object) -> str:
    return "".join(ch if ch.isprintable() else " " for ch in str(value))[:160].replace("`", "'")


def render_report(snapshots: list[dict], threshold: float = 3.0) -> str:
    analysis = analyze(snapshots, threshold)
    if not snapshots:
        return "No snapshots. Run saxo-readonly snapshot first."
    current = snapshots[0]
    currency = _safe_text(current["currency"])
    lines = [
        f"# Saxo {current['environment']} — saved snapshot",
        f"Captured (UTC): {_safe_text(current['captured_at'])}",
        f"Total value: {current['total_value']:,.2f} {currency}",
        f"Accounts: {len(current['accounts'])}; net positions: {len(current['netpositions'])}",
    ]
    comparison = analysis["comparison"]
    if comparison:
        change = comparison["change_pct"]
        suffix = f" ({change:+.2f}%)" if change is not None else " (zero baseline)"
        lines.append(f"Value change: {comparison['delta']:+,.2f} {currency}{suffix}")
    else:
        lines.append(f"Comparison unavailable: {analysis['reason']}.")
    lines.append(f"Alerts at {threshold:g}%: {len(analysis['alerts'])}")
    for alert in analysis["alerts"]:
        instrument = _safe_text(alert.get("instrument", "Portfolio value"))
        lines.append(f"- {instrument}: {alert['change_pct']:+.2f}% ({alert['kind']})")
    lines.extend(["", analysis["notice"], "Offline report; saved observations may be stale or delayed."])
    return "\n".join(lines)
