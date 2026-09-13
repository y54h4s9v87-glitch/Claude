"""Cash-buyer list and deal-to-buyer matching.

A wholesale deal is only worth what your buyer list will pay for it.
Matching happens against a buy box, and every match is scored against
that buyer's own discount requirement — not yours.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .config import DEFAULTS


def _split(value: str | None) -> list[str]:
    if not value:
        return []
    return [p.strip().lower() for p in value.split(",") if p.strip()]


@dataclass
class BuyBox:
    name: str
    markets: list[str] = field(default_factory=list)
    property_types: list[str] = field(default_factory=list)
    min_price: float = 0.0
    max_price: float | None = None
    max_repairs: float | None = None
    buyer_discount: float = DEFAULTS.buyer_discount
    proof_of_funds: bool = False
    deals_closed: int = 0
    active: bool = True

    @classmethod
    def from_row(cls, row) -> "BuyBox":
        return cls(
            name=row["name"],
            markets=_split(row["markets"]),
            property_types=_split(row["property_types"]),
            min_price=row["min_price"] or 0.0,
            max_price=row["max_price"],
            max_repairs=row["max_repairs"],
            buyer_discount=row["buyer_discount"] or DEFAULTS.buyer_discount,
            proof_of_funds=bool(row["proof_of_funds"]),
            deals_closed=row["deals_closed"] or 0,
            active=bool(row["active"]),
        )


@dataclass
class Match:
    buyer_name: str
    fits: bool
    score: int
    buyer_max: float | None
    headroom: float | None      # buyer_max - (your price + fee)
    reasons: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)


def match_deal(
    box: BuyBox,
    *,
    city: str | None,
    county: str | None,
    property_type: str | None,
    arv: float | None,
    repairs: float | None,
    price_to_buyer: float | None,
) -> Match:
    """Score one buyer against one deal.

    `price_to_buyer` is what the buyer would actually pay: your contract
    price plus your assignment fee.
    """
    reasons: list[str] = []
    blockers: list[str] = []
    score = 0

    if not box.active:
        blockers.append("buyer marked inactive")

    # Market fit
    places = {p for p in (city, county) if p}
    places_lower = {p.lower() for p in places}
    if box.markets:
        if places_lower & set(box.markets):
            score += 3
            reasons.append("buys in this market")
        else:
            blockers.append(
                f"market mismatch: buys {', '.join(box.markets)}"
            )
    else:
        reasons.append("no market restriction on file")

    # Property type
    if box.property_types and property_type:
        if property_type.lower() in box.property_types:
            score += 2
            reasons.append(f"takes {property_type}")
        else:
            blockers.append(
                f"property type mismatch: takes {', '.join(box.property_types)}"
            )

    # Price band
    if price_to_buyer is not None:
        if price_to_buyer < box.min_price:
            blockers.append(f"below their floor of ${box.min_price:,.0f}")
        elif box.max_price and price_to_buyer > box.max_price:
            blockers.append(f"above their ceiling of ${box.max_price:,.0f}")
        else:
            score += 2
            reasons.append("inside their price band")

    # Repair appetite
    if repairs is not None and box.max_repairs is not None:
        if repairs > box.max_repairs:
            blockers.append(
                f"rehab too heavy: they cap at ${box.max_repairs:,.0f}"
            )
        else:
            score += 1
            reasons.append("rehab within their appetite")

    # The part that actually decides it: their own margin math
    buyer_max = None
    headroom = None
    if arv and repairs is not None:
        buyer_max = arv * box.buyer_discount - repairs
        if price_to_buyer is not None:
            headroom = buyer_max - price_to_buyer
            if headroom < 0:
                blockers.append(
                    f"${abs(headroom):,.0f} over their max of ${buyer_max:,.0f} "
                    f"at their {box.buyer_discount:.0%} rule"
                )
            elif headroom < 5_000:
                score += 2
                reasons.append(
                    f"only ${headroom:,.0f} under their ${buyer_max:,.0f} max — "
                    "razor thin, expect them to push back"
                )
            else:
                score += 4
                reasons.append(
                    f"${headroom:,.0f} of room under their ${buyer_max:,.0f} max"
                )

    if box.proof_of_funds:
        score += 2
        reasons.append("proof of funds on file")
    else:
        reasons.append("no proof of funds on file — collect it before committing")

    score += min(box.deals_closed, 5)
    if box.deals_closed:
        reasons.append(f"{box.deals_closed} closed deal(s) with you")

    return Match(
        buyer_name=box.name,
        fits=not blockers,
        score=score,
        buyer_max=round(buyer_max, 2) if buyer_max is not None else None,
        headroom=round(headroom, 2) if headroom is not None else None,
        reasons=reasons,
        blockers=blockers,
    )
