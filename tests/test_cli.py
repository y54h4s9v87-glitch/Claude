"""End-to-end tests driving the CLI against a throwaway database."""

import pytest

from wholesale_bot import compliance
from wholesale_bot.cli import main
from wholesale_bot.db import connect, init_db


@pytest.fixture()
def db(tmp_path):
    path = tmp_path / "deals.db"
    conn = connect(path)
    init_db(conn)
    conn.close()
    return str(path)


def run(db, *args) -> int:
    return main(["--db", db, *args])


def test_seed_then_list(db, capsys):
    run(db, "seed")
    run(db, "deal", "list", "--all")
    out = capsys.readouterr().out
    assert "5 Brookside Ave" in out
    assert "$283,500" in out          # the history's own ceiling
    assert "506 Wanaque Ave #F6" in out


def test_seed_is_idempotent(db, capsys):
    run(db, "seed")
    run(db, "seed")
    run(db, "deal", "list", "--all")
    assert capsys.readouterr().out.count("5 Brookside Ave") == 1


def test_add_and_show_a_deal(db, capsys):
    run(db, "deal", "add", "--address", "12 Test St", "--city", "Wayne",
        "--asking", "300000", "--arv", "320000", "--repair-tier", "cosmetic",
        "--description", "Vacant estate sale, sold as-is, needs work")
    capsys.readouterr()
    run(db, "deal", "show", "1")
    out = capsys.readouterr().out
    assert "12 Test St" in out
    assert "MOTIVATION: STRONG" in out
    # 320000*.7 - 20000 - 10000
    assert "$194,000" in out


def test_repair_tier_fills_in_repairs(db, capsys):
    run(db, "deal", "add", "--address", "1 A St", "--arv", "200000",
        "--repair-tier", "heavy")
    out = capsys.readouterr().out
    assert "$70,000" in out           # conservative end of the heavy tier


def test_duplicate_address_is_rejected(db):
    run(db, "deal", "add", "--address", "1 A St", "--city", "Wayne")
    with pytest.raises(SystemExit):
        run(db, "deal", "add", "--address", "1 A St", "--city", "Wayne")


def test_analyze_exits_nonzero_on_a_failing_price(db):
    with pytest.raises(SystemExit) as exc:
        run(db, "analyze", "--arv", "220000", "--repairs", "34000", "--price", "160000")
    assert exc.value.code == 2


def test_analyze_is_quiet_on_a_passing_price(db, capsys):
    assert run(db, "analyze", "--arv", "220000", "--repairs", "34000",
               "--price", "90000") == 0
    assert "MARGIN CHECK ON $90,000: PASS" in capsys.readouterr().out


def test_script_refuses_without_numbers(db):
    run(db, "deal", "add", "--address", "1 A St")
    with pytest.raises(SystemExit):
        run(db, "script", "1")


def test_script_renders_with_numbers(db, capsys):
    run(db, "deal", "add", "--address", "5 Brookside Ave", "--arv", "505000",
        "--repairs", "60000", "--asking", "484900")
    capsys.readouterr()
    run(db, "script", "1", "--kind", "call", "--your-name", "Sam")
    out = capsys.readouterr().out
    assert "Sam" in out
    assert "$283,500" in out
    assert "WALK AWAY" in out


def test_blast_requires_a_contract_price(db):
    run(db, "deal", "add", "--address", "1 A St", "--arv", "300000", "--repairs", "20000")
    with pytest.raises(SystemExit):
        run(db, "script", "1", "--kind", "blast")


def test_status_gate_blocks_under_contract(db, capsys):
    run(db, "deal", "add", "--address", "1 A St", "--arv", "300000", "--repairs", "20000")
    capsys.readouterr()
    with pytest.raises(SystemExit) as exc:
        run(db, "deal", "status", "1", "under_contract")
    assert exc.value.code == 3
    assert "blocking item" in capsys.readouterr().out


def test_status_gate_opens_once_items_are_done(db, capsys):
    run(db, "deal", "add", "--address", "1 A St", "--arv", "300000", "--repairs", "20000")
    for item in compliance.blocking_items("under_contract"):
        run(db, "checklist", "1", "--done", item.key)
    capsys.readouterr()
    run(db, "deal", "status", "1", "under_contract")
    assert "under_contract" in capsys.readouterr().out


def test_force_overrides_the_gate(db, capsys):
    run(db, "deal", "add", "--address", "1 A St", "--arv", "300000", "--repairs", "20000")
    capsys.readouterr()
    run(db, "deal", "status", "1", "under_contract", "--force")
    assert "under_contract" in capsys.readouterr().out


def test_early_statuses_are_not_gated(db, capsys):
    run(db, "deal", "add", "--address", "1 A St")
    capsys.readouterr()
    run(db, "deal", "status", "1", "contacted")
    assert "contacted" in capsys.readouterr().out


def test_deal_set_updates_fields(db, capsys):
    run(db, "deal", "add", "--address", "1 A St")
    run(db, "deal", "set", "1", "arv=400000", "repairs=30000", "city=Wayne")
    capsys.readouterr()
    run(db, "deal", "show", "1")
    out = capsys.readouterr().out
    assert "$240,000" in out          # 400000*.7 - 30000 - 10000
    assert "Wayne" in out


def test_deal_set_rejects_unknown_fields(db):
    run(db, "deal", "add", "--address", "1 A St")
    with pytest.raises(SystemExit):
        run(db, "deal", "set", "1", "vibes=good")


def test_deal_set_rejects_bad_types(db):
    run(db, "deal", "add", "--address", "1 A St")
    with pytest.raises(SystemExit):
        run(db, "deal", "set", "1", "arv=lots")


def test_lookup_by_address_fragment(db, capsys):
    run(db, "seed")
    capsys.readouterr()
    run(db, "deal", "show", "Brookside")
    assert "5 Brookside Ave" in capsys.readouterr().out


def test_ambiguous_lookup_asks_for_an_id(db):
    run(db, "seed")
    with pytest.raises(SystemExit) as exc:
        run(db, "deal", "show", "Pompton Lakes")
    assert "matches several" in str(exc.value)


def test_unknown_deal_errors(db):
    with pytest.raises(SystemExit):
        run(db, "deal", "show", "nothing here")


def test_comps_drive_the_suggested_arv(db, capsys):
    run(db, "deal", "add", "--address", "1 A St", "--sqft", "2000")
    run(db, "comp", "add", "1", "--address", "2 A St", "--price", "300000",
        "--sqft", "1500", "--same-street")
    run(db, "comp", "add", "1", "--address", "3 A St", "--price", "310000",
        "--sqft", "1550", "--same-street")
    run(db, "comp", "add", "1", "--address", "4 A St", "--price", "290000",
        "--sqft", "1450", "--same-street")
    capsys.readouterr()
    run(db, "comp", "list", "1")
    assert "Suggested ARV" in capsys.readouterr().out


def test_match_needs_buyers(db, capsys):
    run(db, "deal", "add", "--address", "1 A St", "--arv", "300000", "--repairs", "20000")
    capsys.readouterr()
    run(db, "match", "1")
    assert "No buyers on the list yet" in capsys.readouterr().out


def test_match_ranks_a_fitting_buyer_first(db, capsys):
    run(db, "deal", "add", "--address", "5 Brookside Ave", "--city", "Pequannock Twp.",
        "--property-type", "single family", "--arv", "505000", "--repairs", "60000")
    run(db, "deal", "set", "1", "contract_price=270000")
    run(db, "buyer", "add", "--name", "Good Fit", "--markets", "Pequannock Twp.",
        "--property-types", "single family", "--max-price", "350000", "--proof-of-funds")
    run(db, "buyer", "add", "--name", "Wrong Market", "--markets", "Newark",
        "--max-price", "150000")
    capsys.readouterr()
    run(db, "match", "1")
    out = capsys.readouterr().out
    assert out.index("Good Fit") < out.index("Wrong Market")
    assert "FIT  Good Fit" in out


def test_checklist_shows_the_current_stage(db, capsys):
    run(db, "deal", "add", "--address", "1 A St")
    capsys.readouterr()
    run(db, "checklist", "1")
    out = capsys.readouterr().out
    assert "margin_checked" in out
    assert "Not legal advice" in out


def test_checklist_marks_items_done(db, capsys):
    run(db, "deal", "add", "--address", "1 A St")
    run(db, "checklist", "1", "--done", "margin_checked")
    capsys.readouterr()
    run(db, "checklist", "1")
    assert "[x] margin_checked" in capsys.readouterr().out


def test_checklist_rejects_unknown_keys(db):
    run(db, "deal", "add", "--address", "1 A St")
    with pytest.raises(SystemExit):
        run(db, "checklist", "1", "--done", "be_cool")


def test_pipeline_reports_next_actions(db, capsys):
    run(db, "seed")
    capsys.readouterr()
    run(db, "pipeline")
    out = capsys.readouterr().out
    assert "NEXT ACTIONS" in out
    assert "5 Brookside Ave" in out


def test_pipeline_on_an_empty_database(db, capsys):
    run(db, "pipeline")
    assert "Pipeline is empty" in capsys.readouterr().out


def test_delete_requires_confirmation(db):
    run(db, "deal", "add", "--address", "1 A St")
    with pytest.raises(SystemExit) as exc:
        run(db, "deal", "rm", "1")
    assert "--yes" in str(exc.value)


def test_delete_with_confirmation_works(db, capsys):
    run(db, "deal", "add", "--address", "1 A St")
    run(db, "deal", "rm", "1", "--yes")
    capsys.readouterr()
    run(db, "deal", "list", "--all")
    assert "1 A St" not in capsys.readouterr().out


def test_activity_is_logged(db, capsys):
    run(db, "deal", "add", "--address", "1 A St")
    run(db, "log", "1", "call", "Left a voicemail with the agent", "--amount", "90000")
    capsys.readouterr()
    run(db, "deal", "show", "1")
    out = capsys.readouterr().out
    assert "Left a voicemail" in out
    assert "$90,000" in out
