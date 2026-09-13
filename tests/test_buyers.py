"""Tests for buy-box matching."""

from wholesale_bot.buyers import BuyBox, match_deal


def box(**kwargs) -> BuyBox:
    base = dict(
        name="Test Buyer",
        markets=["pequannock twp.", "morris"],
        property_types=["single family", "twin"],
        min_price=100_000,
        max_price=350_000,
        max_repairs=80_000,
        buyer_discount=0.70,
        proof_of_funds=True,
        deals_closed=3,
    )
    base.update(kwargs)
    return BuyBox(**base)


def deal(**kwargs):
    base = dict(
        city="Pequannock Twp.", county="Morris", property_type="single family",
        arv=505_000, repairs=60_000, price_to_buyer=280_000,
    )
    base.update(kwargs)
    return base


def test_a_good_fit_matches():
    m = match_deal(box(), **deal())
    assert m.fits
    assert m.headroom == 13_500       # 505000*.7 - 60000 - 280000
    assert m.score > 10


def test_wrong_market_blocks():
    m = match_deal(box(markets=["newark", "essex"]), **deal())
    assert not m.fits
    assert any("market mismatch" in b for b in m.blockers)


def test_wrong_property_type_blocks():
    m = match_deal(box(), **deal(property_type="condo"))
    assert not m.fits
    assert any("property type" in b for b in m.blockers)


def test_over_their_price_ceiling_blocks():
    m = match_deal(box(max_price=200_000), **deal())
    assert not m.fits
    assert any("above their ceiling" in b for b in m.blockers)


def test_too_much_rehab_blocks():
    m = match_deal(box(max_repairs=25_000), **deal())
    assert not m.fits
    assert any("rehab too heavy" in b for b in m.blockers)


def test_their_own_discount_rule_decides():
    """A buyer at 75% can pay more than a buyer at 70% on the same deal."""
    strict = match_deal(box(buyer_discount=0.70), **deal(price_to_buyer=300_000))
    loose = match_deal(box(buyer_discount=0.75), **deal(price_to_buyer=300_000))
    assert not strict.fits
    assert loose.fits
    assert loose.buyer_max > strict.buyer_max


def test_razor_thin_headroom_is_called_out():
    m = match_deal(box(), **deal(price_to_buyer=291_000))
    assert m.fits
    assert any("razor thin" in r for r in m.reasons)


def test_inactive_buyer_never_fits():
    m = match_deal(box(active=False), **deal())
    assert not m.fits


def test_missing_proof_of_funds_is_surfaced():
    m = match_deal(box(proof_of_funds=False), **deal())
    assert any("no proof of funds" in r for r in m.reasons)


def test_no_market_restriction_does_not_block():
    m = match_deal(box(markets=[]), **deal(city="Anywhere", county="Nowhere"))
    assert m.fits
