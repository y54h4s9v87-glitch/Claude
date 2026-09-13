"""Deal math.

The single most important function in this package is `margin_check`.
It answers the only question that matters before you say a number out
loud: can my end buyer actually pay this, and is there anything left
over for me?

    Buyer's max all-in price = (ARV * discount) - repairs
    Your contract ceiling    = buyer's max - your assignment fee

The second line is the MAO. An "opening offer" is never safe just
because it sounds low; it is safe only when it sits below the ceiling.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable, Sequence

from .config import DEFAULTS, Config



def fmt_baths(value: float | None) -> str:
    """1.0 -> '1', 1.5 -> '1.5'."""
    if value is None:
        return "?"
    return str(int(value)) if float(value).is_integer() else str(value)


def fmt_money(value: float | None) -> str:
    """Format dollars so negatives read as -$40,000, not $-40,000."""
    if value is None:
        return "—"
    sign = "-" if value < 0 else ""
    return f"{sign}${abs(value):,.0f}"

# --------------------------------------------------------------------------
# Repair estimating
# --------------------------------------------------------------------------

REPAIR_TIERS = {
    "none": (0, 0),
    "cosmetic": (10_000, 20_000),
    "moderate": (25_000, 45_000),
    "heavy": (50_000, 70_000),
    "gut": (75_000, 120_000),
}

REPAIR_TIER_HELP = ", ".join(
    f"{name} (${lo:,}-${hi:,})" for name, (lo, hi) in REPAIR_TIERS.items()
)


def repair_estimate(tier: str, *, conservative: bool = True) -> float:
    """Turn a verbal repair tier into a dollar figure.

    Conservative means take the top of the range. Under-estimating
    repairs is how a wholesale deal turns into a deal nobody buys.
    """
    key = (tier or "").strip().lower()
    if key not in REPAIR_TIERS:
        raise ValueError(
            f"unknown repair tier {tier!r}; expected one of {', '.join(REPAIR_TIERS)}"
        )
    low, high = REPAIR_TIERS[key]
    return float(high if conservative else low)


# --------------------------------------------------------------------------
# Motivated-seller signals
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class Signal:
    name: str
    weight: int
    note: str


# Weights are deliberately coarse. They rank leads against each other;
# they are not a probability of anything.
TEXT_SIGNALS: tuple[tuple[str, int, str], ...] = (
    (r"\bas[- ]is\b", 3, "sold as-is"),
    (r"\bestate sale\b|\bprobate\b|\binherited\b|\bheirs?\b", 4, "estate / inherited"),
    (r"\bvacant\b|\bunoccupied\b|\bempty\b", 3, "vacant property"),
    (r"\bmotivated\b|\bmust sell\b|\bneeds? a quick\b", 4, "stated motivation"),
    (r"\bforeclosure\b|\bpre[- ]foreclosure\b|\bshort sale\b|\bauction\b", 4, "distressed financing"),
    (r"\bcash (?:only|buyers?)\b|\binvestor\b|\bhandyman\b|\bcontractor special\b", 3, "aimed at investors"),
    (r"\bneeds? (?:work|tlc|updating|renovat)", 3, "needs work"),
    (r"\bfixer\b|\bfix(?:er)?[- ]upper\b|\bteardown\b|\bgut\b", 3, "fixer / gut"),
    (r"\bbring (?:all|us) offers?\b|\ball offers considered\b|\bmake an offer\b", 3, "soliciting offers"),
    (r"\bprice (?:reduced|improved|drop)\b|\breduced\b|\bnew price\b", 2, "price reduction"),
    (r"\brelocat\w+\b|\bjob transfer\b|\bdivorce\b|\bdownsiz\w+\b", 3, "life-event pressure"),
    (r"\btenant[- ]occupied\b|\bsquatter\b|\beviction\b", 2, "occupancy problem"),
    (r"\bno heat\b|\bwater damage\b|\bmold\b|\broof leak\b|\bfire damage\b", 3, "known defect"),
    (r"\bback on (?:the )?market\b|\bbuyer (?:fell|backed) (?:through|out)\b", 2, "prior deal collapsed"),
    (r"\bfsbo\b|\bfor sale by owner\b|\bowner will\b", 2, "for sale by owner"),
    (r"\bbelow (?:market|appraisal)\b|\bpriced to sell\b", 1, "priced-to-sell language"),
    (r"\btax (?:lien|delinquen\w+)\b|\bliens?\b", 3, "tax / lien pressure"),
    (r"\bold (?:roof|boiler|furnace)\b|\bdated\b|\boriginal condition\b", 2, "deferred maintenance"),
)

# Language that argues against motivation. These subtract.
COUNTER_SIGNALS: tuple[tuple[str, int, str], ...] = (
    (r"\b(?:fully|newly|completely|just) renovated\b|\bturn[- ]?key\b", 3, "renovated / turnkey"),
    (r"\bstaged\b|\bmove[- ]in ready\b|\bimmaculate\b|\bpristine\b", 2, "presented move-in ready"),
    (r"\bmultiple offers?\b|\bhighest and best\b|\bbidding war\b", 3, "competitive bidding"),
    (r"\bbrand new\b|\bnew construction\b", 2, "new construction"),
    (r"\bluxury\b|\bhigh[- ]end\b|\bdesigner\b", 1, "luxury positioning"),
)


def score_signals(
    description: str = "",
    *,
    days_on_market: int | None = None,
    price_cuts: int | None = None,
    beds: int | None = None,
    baths: float | None = None,
    vacant: bool = False,
    fsbo: bool = False,
    cfg: Config = DEFAULTS,
) -> tuple[int, list[Signal], list[Signal]]:
    """Score motivation from listing text plus structured facts.

    Returns (net score, positive signals, counter signals).
    """
    text = (description or "").lower()
    found: list[Signal] = []
    against: list[Signal] = []

    for pattern, weight, note in TEXT_SIGNALS:
        if re.search(pattern, text):
            found.append(Signal(note, weight, "listing language"))
    for pattern, weight, note in COUNTER_SIGNALS:
        if re.search(pattern, text):
            against.append(Signal(note, weight, "listing language"))

    if days_on_market is not None and days_on_market >= cfg.stale_days_on_market:
        found.append(Signal(f"{days_on_market} days on market", 3, "stale listing"))
    if price_cuts:
        found.append(
            Signal(f"{price_cuts} price cut{'s' if price_cuts > 1 else ''}", 2 * min(price_cuts, 3), "price history")
        )
    if vacant:
        found.append(Signal("confirmed vacant", 3, "field note"))
    if fsbo:
        found.append(Signal("for sale by owner", 2, "listing type"))
    if beds is not None and baths is not None and beds >= 3 and baths <= 1:
        found.append(
            Signal(f"functional obsolescence: {beds}bd / {baths}ba", 3, "layout")
        )

    # De-duplicate by note, keeping the highest weight for each.
    def dedupe(items: list[Signal]) -> list[Signal]:
        best: dict[str, Signal] = {}
        for s in items:
            if s.name not in best or s.weight > best[s.name].weight:
                best[s.name] = s
        return sorted(best.values(), key=lambda s: -s.weight)

    found, against = dedupe(found), dedupe(against)
    score = sum(s.weight for s in found) - sum(s.weight for s in against)
    return score, found, against


def motivation_label(score: int) -> str:
    if score >= 10:
        return "strong"
    if score >= 6:
        return "moderate"
    if score >= 3:
        return "weak"
    if score >= 0:
        return "none"
    return "negative"


# --------------------------------------------------------------------------
# Comps
# --------------------------------------------------------------------------

@dataclass
class Comp:
    address: str
    sold_price: float
    sqft: int | None = None
    sold_date: str | None = None   # ISO date string
    same_building: bool = False
    same_street: bool = False
    renovated: bool = False
    note: str = ""

    @property
    def price_per_sqft(self) -> float | None:
        if self.sqft and self.sqft > 0:
            return self.sold_price / self.sqft
        return None


@dataclass
class CompAnalysis:
    count: int
    suggested_arv: float | None
    low: float | None
    high: float | None
    median_ppsf: float | None
    proximity_count: int
    warnings: list[str] = field(default_factory=list)


def _median(values: Sequence[float]) -> float | None:
    vals = sorted(values)
    if not vals:
        return None
    mid = len(vals) // 2
    if len(vals) % 2:
        return vals[mid]
    return (vals[mid - 1] + vals[mid]) / 2


def analyze_comps(
    comps: Iterable[Comp],
    *,
    subject_sqft: int | None = None,
    cfg: Config = DEFAULTS,
) -> CompAnalysis:
    """Suggest an ARV from comps, and say plainly when the pool is too thin.

    A thin comp pool is not a reason to skip the deal. It is a reason to
    say the number is soft, which is exactly what small condo buildings
    and one-off twins require.
    """
    comps = list(comps)
    warnings: list[str] = []
    if not comps:
        return CompAnalysis(0, None, None, None, None, 0, ["No comps recorded — ARV is a guess."])

    prices = [c.sold_price for c in comps]
    ppsf_values = [c.price_per_sqft for c in comps if c.price_per_sqft]
    median_ppsf = _median([p for p in ppsf_values if p is not None])

    suggested: float | None
    if subject_sqft and median_ppsf:
        suggested = median_ppsf * subject_sqft
    else:
        suggested = _median(prices)
        if subject_sqft and not median_ppsf:
            warnings.append("No comp square footage — ARV uses median sale price, not $/sqft.")

    proximity = sum(1 for c in comps if c.same_building or c.same_street)

    if len(comps) < cfg.thin_comp_pool:
        warnings.append(
            f"Thin comp pool: {len(comps)} comp(s). Treat the ARV as a range, not a number."
        )
    if proximity == 0:
        warnings.append(
            "No same-building or same-street comps. In small buildings and twins this ARV can be off badly."
        )
    if any(c.renovated for c in comps) and not all(c.renovated for c in comps):
        warnings.append(
            "Comp pool mixes renovated and unrenovated sales — make sure the ARV reflects post-rehab condition."
        )
    stale = [c for c in comps if _is_stale(c.sold_date)]
    if stale:
        warnings.append(
            f"{len(stale)} comp(s) older than 12 months — weight recent sales more heavily."
        )

    return CompAnalysis(
        count=len(comps),
        suggested_arv=round(suggested, -2) if suggested else None,
        low=min(prices),
        high=max(prices),
        median_ppsf=round(median_ppsf, 2) if median_ppsf else None,
        proximity_count=proximity,
        warnings=warnings,
    )


def _is_stale(sold_date: str | None, *, months: int = 12) -> bool:
    if not sold_date:
        return False
    from datetime import date

    try:
        parts = [int(p) for p in re.split(r"[-/]", sold_date)[:3]]
        while len(parts) < 3:
            parts.append(1)
        sold = date(parts[0], parts[1], parts[2])
    except (ValueError, IndexError):
        return False
    today = date.today()
    age_months = (today.year - sold.year) * 12 + (today.month - sold.month)
    return age_months > months


# --------------------------------------------------------------------------
# The margin check
# --------------------------------------------------------------------------

@dataclass
class MarginCheck:
    """The answer to 'can I actually say this number?'"""

    arv: float
    repairs: float
    assignment_fee: float
    buyer_discount: float
    buyer_max: float          # what the end buyer can be all-in for
    ceiling: float            # MAO — your highest contract price
    proposed_price: float | None = None
    spread: float | None = None      # fee you'd actually earn at proposed_price
    passes: bool = True
    reasons: list[str] = field(default_factory=list)

    @property
    def verdict(self) -> str:
        return "PASS" if self.passes else "FAIL"


def margin_check(
    *,
    arv: float,
    repairs: float,
    assignment_fee: float = DEFAULTS.default_assignment_fee,
    proposed_price: float | None = None,
    buyer_discount: float = DEFAULTS.buyer_discount,
    closing_costs: float = 0.0,
) -> MarginCheck:
    """Check a price against end-buyer economics. Never skip this.

    `closing_costs` covers anything that comes out of the deal before the
    buyer's margin: double-close fees, holding, title. It reduces what the
    buyer can pay, exactly like repairs do.
    """
    if arv <= 0:
        raise ValueError("ARV must be positive")
    if repairs < 0 or assignment_fee < 0 or closing_costs < 0:
        raise ValueError("repairs, fee and closing costs cannot be negative")
    if not 0 < buyer_discount <= 1:
        raise ValueError("buyer_discount must be between 0 and 1")

    buyer_max = arv * buyer_discount - repairs - closing_costs
    ceiling = buyer_max - assignment_fee

    check = MarginCheck(
        arv=arv,
        repairs=repairs,
        assignment_fee=assignment_fee,
        buyer_discount=buyer_discount,
        buyer_max=round(buyer_max, 2),
        ceiling=round(ceiling, 2),
        proposed_price=proposed_price,
    )

    if ceiling <= 0:
        check.passes = False
        check.reasons.append(
            "No deal exists at these inputs: repairs and fee exceed what a buyer can pay. "
            "Re-check the ARV and the repair number before going further."
        )

    if proposed_price is not None:
        spread = buyer_max - proposed_price
        check.spread = round(spread, 2)
        if proposed_price > ceiling:
            check.passes = False
            over = proposed_price - ceiling
            check.reasons.append(
                f"{fmt_money(proposed_price)} is {fmt_money(over)} ABOVE your ceiling of "
                f"{fmt_money(ceiling)}. Saying it out loud caps your fee at {fmt_money(max(spread, 0))}."
            )
        if spread < assignment_fee:
            check.passes = False
            check.reasons.append(
                f"Assignment margin at this price is {fmt_money(spread)}, short of your "
                f"{fmt_money(assignment_fee)} target."
            )
        if spread <= 0:
            check.reasons.append(
                "Negative spread: the end buyer cannot pay this and hit their own numbers."
            )
        if check.passes:
            check.reasons.append(
                f"Clears the ceiling with {fmt_money(spread)} of assignment margin."
            )
    else:
        if check.passes:
            check.reasons.append(
                f"Buyer can be all-in at {fmt_money(buyer_max)}. Your contract must land at "
                f"or below {fmt_money(ceiling)}."
            )
    return check


def round_offer(value: float, increment: int = DEFAULTS.offer_rounding) -> float:
    """Round an offer down to a deliberate-sounding increment.

    Always rounds down so rounding never pushes a number past a ceiling.
    """
    if increment <= 0:
        return float(value)
    return float(int(value // increment) * increment)


@dataclass
class Ladder:
    opening: float
    second: float
    ceiling: float
    walk_away: float

    def as_rows(self) -> list[tuple[str, float]]:
        return [
            ("Open at", self.opening),
            ("Round 2", self.second),
            ("Ceiling (MAO)", self.ceiling),
            ("Walk away above", self.walk_away),
        ]


def negotiation_ladder(ceiling: float, cfg: Config = DEFAULTS) -> Ladder:
    """Build the three rungs, plus the walk-away number.

    Know the walk-away before the call. It is the margin-checked ceiling,
    not a number that merely sounds low.
    """
    if ceiling <= 0:
        return Ladder(0.0, 0.0, 0.0, 0.0)
    opening = round_offer(ceiling * cfg.opening_offer_ratio, cfg.offer_rounding)
    second = round_offer(ceiling * cfg.second_round_ratio, cfg.offer_rounding)
    top = round_offer(ceiling, cfg.offer_rounding)
    return Ladder(opening=opening, second=second, ceiling=top, walk_away=top)


# --------------------------------------------------------------------------
# Full screen
# --------------------------------------------------------------------------

@dataclass
class Screen:
    margin: MarginCheck
    ladder: Ladder
    asking: float | None
    gap_pct: float | None
    motivation_score: int
    motivation: str
    signals: list[Signal]
    counter_signals: list[Signal]
    comps: CompAnalysis | None
    verdict: str
    notes: list[str] = field(default_factory=list)


def screen_deal(
    *,
    arv: float,
    repairs: float,
    asking: float | None = None,
    assignment_fee: float = DEFAULTS.default_assignment_fee,
    buyer_discount: float = DEFAULTS.buyer_discount,
    closing_costs: float = 0.0,
    description: str = "",
    days_on_market: int | None = None,
    price_cuts: int | None = None,
    beds: int | None = None,
    baths: float | None = None,
    vacant: bool = False,
    fsbo: bool = False,
    comps: Iterable[Comp] | None = None,
    subject_sqft: int | None = None,
    cfg: Config = DEFAULTS,
) -> Screen:
    """Screen a deal end to end: math, motivation, comps, verdict."""
    margin = margin_check(
        arv=arv,
        repairs=repairs,
        assignment_fee=assignment_fee,
        buyer_discount=buyer_discount,
        closing_costs=closing_costs,
    )
    ladder = negotiation_ladder(margin.ceiling, cfg)
    score, signals, counters = score_signals(
        description,
        days_on_market=days_on_market,
        price_cuts=price_cuts,
        beds=beds,
        baths=baths,
        vacant=vacant,
        fsbo=fsbo,
        cfg=cfg,
    )
    comp_analysis = (
        analyze_comps(comps, subject_sqft=subject_sqft, cfg=cfg) if comps is not None else None
    )

    gap = None
    notes: list[str] = []
    if asking and asking > 0:
        gap = (asking - margin.ceiling) / asking

    label = motivation_label(score)

    if margin.ceiling <= 0:
        verdict = "PASS — no margin exists at these inputs"
    elif gap is not None and gap >= cfg.unrealistic_gap and score < 6:
        verdict = "PASS — unrealistic gap, no real distress"
        notes.append(
            f"Your ceiling is {gap:.0%} under asking and motivation reads {label}. "
            "Opening at raw MAO here burns the agent relationship for nothing."
        )
    elif gap is not None and gap >= cfg.no_motivation_gap and score < cfg.weak_motivation_score:
        verdict = "PASS — no motivation behind the gap"
        notes.append(
            f"You need {gap:.0%} off asking and the listing gives no reason to think "
            "the seller will move. Discount alone is not a reason to believe."
        )
    elif gap is not None and gap >= cfg.unrealistic_gap:
        verdict = "LONG SHOT — big gap but real distress signals"
        notes.append(
            f"Ceiling is {gap:.0%} under asking. Only worth the call because motivation reads {label}. "
            "Lead with the as-is / certainty pitch, not the number."
        )
    elif gap is not None and gap <= 0:
        verdict = "STRONG — asking is at or below your ceiling"
        notes.append("Asking price already clears your math. Move fast and verify repairs on site.")
    elif score >= 6:
        verdict = "PURSUE — math works and seller shows motivation"
    else:
        verdict = "WORKABLE — math works, motivation is thin"
        notes.append("Negotiation will carry this one; the listing is not doing you any favors.")

    if comp_analysis and comp_analysis.suggested_arv:
        drift = abs(comp_analysis.suggested_arv - arv) / arv
        if drift >= 0.10:
            notes.append(
                f"Your ARV of ${arv:,.0f} is {drift:.0%} off the comp-suggested "
                f"${comp_analysis.suggested_arv:,.0f}. Reconcile before offering."
            )

    if repairs and arv and repairs / arv >= 0.25:
        notes.append(
            "Repairs exceed a quarter of ARV. Heavy-rehab buyers are a smaller pool — line one up before you sign."
        )

    return Screen(
        margin=margin,
        ladder=ladder,
        asking=asking,
        gap_pct=gap,
        motivation_score=score,
        motivation=label,
        signals=signals,
        counter_signals=counters,
        comps=comp_analysis,
        verdict=verdict,
        notes=notes,
    )
