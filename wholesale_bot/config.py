"""Tunable defaults for deal math.

Every number here is a default, not a law. Override per deal or per buyer
when a particular investor's buy box says something different.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    # The classic "70% rule". This is the fraction of ARV a cash buyer is
    # willing to be all-in for, before repairs.
    buyer_discount: float = 0.70

    # Default assignment fee you are trying to earn on a deal.
    default_assignment_fee: float = 10_000.0

    # Opening offer as a fraction of your ceiling. Leaves room for the
    # 1-2 rounds of counters the negotiation ladder assumes.
    opening_offer_ratio: float = 0.82

    # Middle rung of the ladder, as a fraction of the ceiling.
    second_round_ratio: float = 0.91

    # Round offer numbers to this increment so they sound deliberate.
    offer_rounding: int = 500

    # If (asking - ceiling) / asking is at or above this and the listing
    # shows no real distress, the deal gets flagged as unrealistic
    # instead of being opened at raw MAO.
    unrealistic_gap: float = 0.40

    # A narrower gap still fails when nothing about the listing suggests
    # the seller will move. Discount alone is not a reason to believe.
    no_motivation_gap: float = 0.25

    # Motivation score below this reads as "no real signal".
    weak_motivation_score: int = 3

    # A comp pool smaller than this is called out as thin.
    thin_comp_pool: int = 3

    # Days on market at or above this counts as a motivation signal.
    stale_days_on_market: int = 60


DEFAULTS = Config()
