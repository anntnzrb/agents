from __future__ import annotations

from datetime import date

from .models import FlightOption


def rank_options(
    options: list[FlightOption],
    *,
    max_budget: float | None,
    prefer_nonstop: bool,
) -> list[FlightOption]:
    for option in options:
        score, reasons, hints = _score_option(
            option,
            max_budget=max_budget,
            prefer_nonstop=prefer_nonstop,
        )
        option.score = score
        option.reasons = reasons
        option.hints = hints

    return sorted(
        options,
        key=lambda item: (-item.score, item.effective_price, item.depart_date),
    )


def _score_option(
    option: FlightOption,
    *,
    max_budget: float | None,
    prefer_nonstop: bool,
) -> tuple[float, list[str], list[str]]:
    reasons: list[str] = []
    hints: list[str] = []

    score = _price_anchor(option.effective_price)
    reasons.append("price_anchor")

    if max_budget is not None:
        if option.effective_price <= max_budget:
            score += 0.22
            reasons.append("within_budget")
        else:
            overshoot = (option.effective_price - max_budget) / max(max_budget, 1.0)
            score -= min(0.7, overshoot)
            reasons.append("over_budget_penalty")

    depart_weekday = option.depart_date.weekday()
    match depart_weekday:
        case 1 | 2 | 3:
            score += 0.14
            reasons.append("weekday_departure_bonus")
            hints.append("Weekday departure tends cheaper (Tue-Thu bias).")
        case 4 | 5 | 6:
            score -= 0.16
            reasons.append("weekend_departure_penalty")
            hints.append("Weekend departure penalty applied; try Tue-Thu.")

    if option.return_date is not None and _is_weekendish(option.return_date):
        score -= 0.08
        reasons.append("weekend_return_penalty")
        hints.append("Weekend return often pricier; midweek return can cut fare.")

    if prefer_nonstop:
        if option.nonstop:
            score += 0.08
            reasons.append("nonstop_preferred_bonus")
        else:
            score -= 0.2
            reasons.append("nonstop_preferred_penalty")

    return score, reasons, hints


def _price_anchor(price: float) -> float:
    return 1.0 / (1.0 + (price / 700.0))


def _is_weekendish(day: date) -> bool:
    return day.weekday() >= 4
