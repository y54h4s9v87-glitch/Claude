"""Tests for outreach generation.

The rule under test: a script containing a price will not render unless
that price survives the buyer-side margin check.
"""

import re

import pytest

from wholesale_bot import analysis, scripts


def flat(text: str) -> str:
    """Lowercase with runs of whitespace collapsed, so line wrapping
    does not break assertions about what a script actually says."""
    return re.sub(r"\s+", " ", text).lower()


def test_priced_script_refuses_a_failing_number():
    check = analysis.margin_check(
        arv=220_000, repairs=34_000, assignment_fee=10_000, proposed_price=160_000
    )
    ladder = analysis.Ladder(160_000, 165_000, 170_000, 170_000)
    with pytest.raises(scripts.MarginNotChecked):
        scripts.phone_script(address="506 Wanaque Ave #F6", ladder=ladder, check=check)


def test_priced_script_refuses_when_no_check_was_run():
    ladder = analysis.Ladder(90_000, 100_000, 110_000, 110_000)
    with pytest.raises(scripts.MarginNotChecked):
        scripts.offer_summary(address="x", check=None, ladder=ladder)


def test_passing_number_renders():
    check = analysis.margin_check(
        arv=505_000, repairs=60_000, assignment_fee=10_000, proposed_price=232_000
    )
    ladder = analysis.negotiation_ladder(check.ceiling)
    s = scripts.phone_script(address="5 Brookside Ave", ladder=ladder, check=check)
    body = s.render()
    assert "$232,000" in body
    assert "$283,500" in body
    assert "WALK AWAY" in body


def test_a_passing_check_produces_no_warnings():
    check = analysis.margin_check(
        arv=505_000, repairs=60_000, assignment_fee=10_000, proposed_price=232_000
    )
    ladder = analysis.negotiation_ladder(check.ceiling)
    assert scripts.offer_summary(address="x", check=check, ladder=ladder).warnings == ()


def test_full_set_is_margin_checked_end_to_end():
    built = scripts.build_scripts_for(
        address="5 Brookside Ave", arv=505_000, repairs=60_000, assignment_fee=10_000
    )
    assert len(built) == 4
    for s in built:
        s.render()


def test_build_refuses_an_impossible_deal():
    with pytest.raises(scripts.MarginNotChecked):
        scripts.build_scripts_for(address="x", arv=200_000, repairs=150_000)


# --------------------------------------------------------------------------
# Disclosure content
# --------------------------------------------------------------------------

def test_phone_script_discloses_investor_status_and_assignment():
    check = analysis.margin_check(arv=505_000, repairs=60_000, proposed_price=232_000)
    ladder = analysis.negotiation_ladder(check.ceiling)
    body = flat(scripts.phone_script(address="x", ladder=ladder, check=check).render())
    assert "not an agent" in body
    assert "assign this" in body


def test_agent_listed_warns_against_going_around_the_agent():
    s = scripts.first_text(address="x", agent_listed=True)
    assert any("through the agent" in w for w in s.warnings)


def test_fsbo_text_has_no_agent_warning():
    s = scripts.first_text(address="x", agent_listed=False)
    assert not any("through the agent" in w for w in s.warnings)


def test_first_text_carries_no_price():
    body = scripts.first_text(address="x").render()
    assert "$" not in body


def test_buyer_blast_markets_the_contract_not_the_property():
    s = scripts.buyer_blast(
        address="5 Brookside Ave", arv=505_000, repairs=60_000,
        contract_price=270_000, assignment_fee=10_000,
    )
    body = flat(s.render())
    assert "not the property itself" in body
    assert "assignment" in body


def test_buyer_blast_warns_when_the_fee_kills_the_margin():
    s = scripts.buyer_blast(
        address="x", arv=505_000, repairs=60_000,
        contract_price=290_000, assignment_fee=25_000,
    )
    assert any("past the 70% rule" in w for w in s.warnings)


def test_buyer_blast_is_quiet_when_the_math_is_fine():
    s = scripts.buyer_blast(
        address="x", arv=505_000, repairs=60_000,
        contract_price=250_000, assignment_fee=10_000,
    )
    assert s.warnings == ()


def test_quote_wraps_long_lines():
    out = scripts.quote("word " * 60)
    assert all(len(line) <= 80 for line in out.splitlines())
    assert out.startswith('   "') and out.endswith('"')
