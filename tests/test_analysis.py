"""Tests for the deal math.

The cases below are the deals from the working-context history. If these
stop passing, the tool is giving different advice than it gave before.
"""

import pytest

from wholesale_bot import analysis
from wholesale_bot.config import DEFAULTS


# --------------------------------------------------------------------------
# The margin check
# --------------------------------------------------------------------------

def test_buyer_max_and_ceiling():
    c = analysis.margin_check(arv=505_000, repairs=60_000, assignment_fee=10_000)
    assert c.buyer_max == pytest.approx(293_500)
    assert c.ceiling == pytest.approx(283_500)


def test_ceiling_is_buyer_max_minus_fee():
    c = analysis.margin_check(arv=400_000, repairs=50_000, assignment_fee=15_000)
    assert c.ceiling == pytest.approx(c.buyer_max - c.assignment_fee)


def test_closing_costs_reduce_what_a_buyer_can_pay():
    without = analysis.margin_check(arv=300_000, repairs=20_000)
    with_costs = analysis.margin_check(arv=300_000, repairs=20_000, closing_costs=8_000)
    assert with_costs.buyer_max == pytest.approx(without.buyer_max - 8_000)


def test_price_above_ceiling_fails():
    """The exact mistake this tool exists to prevent: $160K on the Wanaque condo."""
    c = analysis.margin_check(
        arv=220_000, repairs=34_000, assignment_fee=10_000, proposed_price=160_000
    )
    assert not c.passes
    assert c.verdict == "FAIL"
    assert any("ABOVE your ceiling" in r for r in c.reasons)


def test_corrected_price_passes():
    c = analysis.margin_check(
        arv=220_000, repairs=34_000, assignment_fee=10_000, proposed_price=90_000
    )
    assert c.passes
    assert c.spread == pytest.approx(30_000)


def test_price_exactly_at_ceiling_passes():
    c = analysis.margin_check(
        arv=505_000, repairs=60_000, assignment_fee=10_000, proposed_price=283_500
    )
    assert c.passes
    assert c.spread == pytest.approx(10_000)


def test_a_dollar_over_the_ceiling_fails():
    c = analysis.margin_check(
        arv=505_000, repairs=60_000, assignment_fee=10_000, proposed_price=283_501
    )
    assert not c.passes


def test_repairs_can_erase_the_deal():
    c = analysis.margin_check(arv=200_000, repairs=150_000, assignment_fee=10_000)
    assert not c.passes
    assert c.ceiling < 0


@pytest.mark.parametrize("bad", [
    dict(arv=0, repairs=10_000),
    dict(arv=-1, repairs=10_000),
    dict(arv=200_000, repairs=-5),
    dict(arv=200_000, repairs=10_000, buyer_discount=0),
    dict(arv=200_000, repairs=10_000, buyer_discount=1.5),
])
def test_invalid_inputs_raise(bad):
    with pytest.raises(ValueError):
        analysis.margin_check(**bad)


# --------------------------------------------------------------------------
# Ladder
# --------------------------------------------------------------------------

def test_ladder_is_ordered_and_capped():
    ladder = analysis.negotiation_ladder(283_500)
    assert ladder.opening < ladder.second < ladder.ceiling
    assert ladder.ceiling <= 283_500
    assert ladder.walk_away == ladder.ceiling


def test_rounding_never_pushes_past_the_ceiling():
    for ceiling in (99_999, 283_501, 110_499, 1_234_567):
        ladder = analysis.negotiation_ladder(ceiling)
        assert ladder.ceiling <= ceiling
        assert ladder.opening <= ceiling


def test_ladder_on_a_dead_deal_is_zero():
    ladder = analysis.negotiation_ladder(-5_000)
    assert ladder.opening == 0 and ladder.ceiling == 0


# --------------------------------------------------------------------------
# Repairs
# --------------------------------------------------------------------------

def test_repair_tier_is_conservative_by_default():
    assert analysis.repair_estimate("cosmetic") == 20_000
    assert analysis.repair_estimate("cosmetic", conservative=False) == 10_000


def test_unknown_repair_tier_raises():
    with pytest.raises(ValueError):
        analysis.repair_estimate("light-ish")


# --------------------------------------------------------------------------
# Motivation signals
# --------------------------------------------------------------------------

def test_distress_language_scores():
    score, found, _ = analysis.score_signals(
        "Estate sale. Property is vacant and sold as-is. Needs work throughout."
    )
    assert score >= 10
    assert analysis.motivation_label(score) == "strong"
    assert len(found) >= 3


def test_turnkey_language_scores_against():
    score, _, against = analysis.score_signals(
        "Fully renovated and staged, move-in ready, multiple offers received."
    )
    assert score < 0
    assert against


def test_structured_signals_count():
    score, found, _ = analysis.score_signals(
        "", days_on_market=120, price_cuts=2, beds=4, baths=1.0, vacant=True
    )
    names = " ".join(s.name for s in found)
    assert "120 days on market" in names
    assert "2 price cuts" in names
    assert "functional obsolescence" in names
    assert score > 0


def test_one_bath_four_beds_is_obsolescence():
    _, found, _ = analysis.score_signals("", beds=4, baths=1.0)
    assert any("obsolescence" in s.name for s in found)
    _, found2, _ = analysis.score_signals("", beds=4, baths=2.5)
    assert not any("obsolescence" in s.name for s in found2)


def test_signals_are_deduped():
    _, found, _ = analysis.score_signals("as-is, as is, sold as-is, AS-IS")
    assert sum(1 for s in found if s.name == "sold as-is") == 1


# --------------------------------------------------------------------------
# Comps
# --------------------------------------------------------------------------

def test_no_comps_warns():
    result = analysis.analyze_comps([])
    assert result.count == 0
    assert result.warnings


def test_thin_pool_is_flagged():
    result = analysis.analyze_comps([
        analysis.Comp("506 Wanaque Ave #B2", 215_000, same_building=True),
    ])
    assert any("Thin comp pool" in w for w in result.warnings)


def test_no_nearby_comps_is_flagged():
    comps = [analysis.Comp(f"{i} Far Away Rd", 200_000 + i) for i in range(4)]
    result = analysis.analyze_comps(comps)
    assert any("same-building or same-street" in w for w in result.warnings)


def test_arv_from_price_per_sqft():
    comps = [
        analysis.Comp("1 A St", 300_000, sqft=1_500, same_street=True),
        analysis.Comp("2 A St", 320_000, sqft=1_600, same_street=True),
        analysis.Comp("3 A St", 280_000, sqft=1_400, same_street=True),
    ]
    result = analysis.analyze_comps(comps, subject_sqft=2_000)
    assert result.median_ppsf == pytest.approx(200.0, abs=1)
    assert result.suggested_arv == pytest.approx(400_000, abs=500)


def test_mixed_renovation_state_warns():
    comps = [
        analysis.Comp("1 A St", 300_000, same_street=True, renovated=True),
        analysis.Comp("2 A St", 240_000, same_street=True),
        analysis.Comp("3 A St", 250_000, same_street=True),
    ]
    result = analysis.analyze_comps(comps)
    assert any("renovated and unrenovated" in w for w in result.warnings)


def test_old_comps_are_flagged():
    comps = [
        analysis.Comp("48 Walnut St", 362_585, sold_date="2023-06-01", same_street=True),
        analysis.Comp("50 Walnut St", 370_000, same_street=True),
        analysis.Comp("52 Walnut St", 380_000, same_street=True),
    ]
    result = analysis.analyze_comps(comps)
    assert any("older than 12 months" in w for w in result.warnings)


# --------------------------------------------------------------------------
# Full screen and verdicts
# --------------------------------------------------------------------------

def test_brookside_screens_as_a_long_shot_with_real_signals():
    s = analysis.screen_deal(
        arv=505_000, repairs=60_000, asking=484_900,
        description="Vacant, sold as-is, deferred maintenance, estate sale",
        beds=4, baths=1.0, vacant=True,
    )
    assert s.margin.ceiling == pytest.approx(283_500)
    assert s.motivation == "strong"
    assert s.verdict.startswith("LONG SHOT")


def test_beacon_hill_screens_as_a_pass():
    """Agent-listed, comps above ask, no distress: the history's own verdict."""
    s = analysis.screen_deal(
        arv=530_000, repairs=12_500, asking=499_000,
        description="Well maintained unit in a desirable complex.",
    )
    assert s.margin.ceiling == pytest.approx(348_500)
    assert s.verdict.startswith("PASS")


def test_huge_gap_without_distress_is_a_pass():
    s = analysis.screen_deal(arv=220_000, repairs=34_000, asking=250_000)
    assert s.verdict.startswith("PASS")
    assert s.gap_pct > DEFAULTS.unrealistic_gap


def test_huge_gap_with_distress_is_a_long_shot_not_a_pass():
    s = analysis.screen_deal(
        arv=220_000, repairs=34_000, asking=250_000,
        description="Vacant estate sale, as-is, needs work, motivated seller, foreclosure",
    )
    assert s.verdict.startswith("LONG SHOT")


def test_asking_below_ceiling_is_strong():
    s = analysis.screen_deal(arv=505_000, repairs=60_000, asking=250_000)
    assert s.verdict.startswith("STRONG")


def test_arv_far_from_comps_is_called_out():
    comps = [
        analysis.Comp("1 A St", 300_000, same_street=True),
        analysis.Comp("2 A St", 305_000, same_street=True),
        analysis.Comp("3 A St", 295_000, same_street=True),
    ]
    s = analysis.screen_deal(arv=450_000, repairs=20_000, asking=350_000, comps=comps)
    assert any("off the comp-suggested" in n for n in s.notes)


def test_heavy_rehab_is_called_out():
    s = analysis.screen_deal(arv=400_000, repairs=110_000, asking=200_000)
    assert any("Heavy-rehab buyers" in n for n in s.notes)


def test_money_formatting_handles_negatives():
    assert analysis.fmt_money(-40_000) == "-$40,000"
    assert analysis.fmt_money(40_000) == "$40,000"
    assert analysis.fmt_money(None) == "—"
