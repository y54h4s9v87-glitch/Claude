"""Command line interface.

    python3 -m wholesale_bot --help
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

from . import analysis, buyers as buyers_mod, compliance, scripts
from .config import DEFAULTS
from .db import STATUSES, connect, default_db_path, init_db, log, now


# --------------------------------------------------------------------------
# Output helpers
# --------------------------------------------------------------------------

from .analysis import fmt_baths, fmt_money as money


def rule(char: str = "-", width: int = 66) -> str:
    return char * width


def heading(text: str) -> str:
    return f"\n{text}\n{rule('=', len(text))}"


def table(rows: list[list[str]], headers: list[str]) -> str:
    if not rows:
        return "(nothing yet)"
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(str(cell)))
    out = ["  ".join(h.ljust(widths[i]) for i, h in enumerate(headers)).rstrip()]
    out.append("  ".join("-" * w for w in widths))
    for row in rows:
        out.append("  ".join(str(c).ljust(widths[i]) for i, c in enumerate(row)).rstrip())
    return "\n".join(out)


# --------------------------------------------------------------------------
# Lookup
# --------------------------------------------------------------------------

def find_deal(conn: sqlite3.Connection, key: str) -> sqlite3.Row:
    """Find a deal by id or by a piece of its address."""
    if key.isdigit():
        row = conn.execute("SELECT * FROM deals WHERE id = ?", (int(key),)).fetchone()
        if row:
            return row
    rows = conn.execute(
        "SELECT * FROM deals WHERE address LIKE ? OR city LIKE ? ORDER BY id",
        (f"%{key}%", f"%{key}%"),
    ).fetchall()
    if not rows:
        raise SystemExit(f"No deal matches {key!r}. Try: wholesale deal list")
    if len(rows) > 1:
        listing = "\n".join(f"  {r['id']}: {r['address']}, {r['city'] or ''}" for r in rows)
        raise SystemExit(f"{key!r} matches several deals:\n{listing}\nUse the id.")
    return rows[0]


def deal_comps(conn: sqlite3.Connection, deal_id: int) -> list[analysis.Comp]:
    rows = conn.execute("SELECT * FROM comps WHERE deal_id = ? ORDER BY id", (deal_id,)).fetchall()
    return [
        analysis.Comp(
            address=r["address"],
            sold_price=r["sold_price"],
            sqft=r["sqft"],
            sold_date=r["sold_date"],
            same_building=bool(r["same_building"]),
            same_street=bool(r["same_street"]),
            renovated=bool(r["renovated"]),
            note=r["note"] or "",
        )
        for r in rows
    ]


def screen_row(conn: sqlite3.Connection, row: sqlite3.Row) -> analysis.Screen | None:
    if not row["arv"] or row["repairs"] is None:
        return None
    return analysis.screen_deal(
        arv=row["arv"],
        repairs=row["repairs"],
        asking=row["asking"],
        assignment_fee=row["assignment_fee"] or DEFAULTS.default_assignment_fee,
        buyer_discount=row["buyer_discount"] or DEFAULTS.buyer_discount,
        closing_costs=row["closing_costs"] or 0.0,
        description=row["description"] or "",
        days_on_market=row["days_on_market"],
        price_cuts=row["price_cuts"],
        beds=row["beds"],
        baths=row["baths"],
        vacant=bool(row["vacant"]),
        fsbo=bool(row["fsbo"]),
        comps=deal_comps(conn, row["id"]),
        subject_sqft=row["sqft"],
    )


# --------------------------------------------------------------------------
# Rendering a screen
# --------------------------------------------------------------------------

def render_screen(s: analysis.Screen, *, address: str = "") -> str:
    out: list[str] = []
    if address:
        out.append(heading(address))
    m = s.margin
    out.append("DEAL MATH")
    out.append(f"  ARV                    {money(m.arv)}")
    out.append(f"  Repairs                {money(m.repairs)}")
    if m.arv:
        out.append(f"  Buyer discount         {m.buyer_discount:.0%} of ARV")
    out.append(f"  Buyer's max all-in     {money(m.buyer_max)}")
    out.append(f"  Your assignment fee    {money(m.assignment_fee)}")
    out.append(f"  YOUR CEILING (MAO)     {money(m.ceiling)}")
    if s.asking:
        out.append(f"  Asking price           {money(s.asking)}")
    if s.gap_pct is not None:
        out.append(f"  Gap to asking          {s.gap_pct:+.0%}")

    out.append("")
    out.append("NEGOTIATION LADDER")
    for label, value in s.ladder.as_rows():
        out.append(f"  {label:<22} {money(value)}")

    out.append("")
    out.append(f"MOTIVATION: {s.motivation.upper()} (score {s.motivation_score})")
    for sig in s.signals:
        out.append(f"  + {sig.name} ({sig.note})")
    for sig in s.counter_signals:
        out.append(f"  - {sig.name} ({sig.note})")
    if not s.signals and not s.counter_signals:
        out.append("  (no listing text scored — paste the description with --description)")

    if s.comps:
        c = s.comps
        out.append("")
        out.append(f"COMPS: {c.count} on file")
        if c.suggested_arv:
            out.append(f"  Suggested ARV          {money(c.suggested_arv)}")
        if c.low and c.high:
            out.append(f"  Range                  {money(c.low)} – {money(c.high)}")
        if c.median_ppsf:
            out.append(f"  Median $/sqft          ${c.median_ppsf:,.2f}")
        out.append(f"  Same building/street   {c.proximity_count}")
        for w in c.warnings:
            out.append(f"  ! {w}")

    out.append("")
    out.append(f"VERDICT: {s.verdict}")
    for n in s.notes:
        out.append(f"  * {n}")
    return "\n".join(out)


# --------------------------------------------------------------------------
# Commands
# --------------------------------------------------------------------------

def cmd_init(args, conn):
    init_db(conn)
    print(f"Database ready at {args.db or default_db_path()}")
    print("Next: wholesale deal add --address '...' --asking 250000 --arv 230000 --repair-tier cosmetic")


def cmd_analyze(args, conn):
    repairs = args.repairs
    if repairs is None and args.repair_tier:
        repairs = analysis.repair_estimate(args.repair_tier)
    if repairs is None:
        raise SystemExit("Give --repairs or --repair-tier (" + analysis.REPAIR_TIER_HELP + ")")
    s = analysis.screen_deal(
        arv=args.arv,
        repairs=repairs,
        asking=args.asking,
        assignment_fee=args.fee,
        buyer_discount=args.discount,
        closing_costs=args.closing_costs,
        description=args.description or "",
        days_on_market=args.dom,
        price_cuts=args.price_cuts,
        beds=args.beds,
        baths=args.baths,
        vacant=args.vacant,
        fsbo=args.fsbo,
    )
    print(render_screen(s, address=args.address or "Quick analysis"))

    if args.price is not None:
        check = analysis.margin_check(
            arv=args.arv,
            repairs=repairs,
            assignment_fee=args.fee,
            buyer_discount=args.discount,
            closing_costs=args.closing_costs,
            proposed_price=args.price,
        )
        print("")
        print(f"MARGIN CHECK ON {money(args.price)}: {check.verdict}")
        for r in check.reasons:
            print(f"  - {r}")
        if not check.passes:
            sys.exit(2)


def cmd_deal_add(args, conn):
    repairs = args.repairs
    if repairs is None and args.repair_tier:
        repairs = analysis.repair_estimate(args.repair_tier)
    try:
        cur = conn.execute(
            """INSERT INTO deals (address, city, state, county, property_type, beds, baths,
               sqft, asking, arv, repairs, repair_tier, assignment_fee, buyer_discount,
               closing_costs, days_on_market, price_cuts, vacant, fsbo, agent_name,
               agent_phone, agent_email, seller_name, source, listing_url, description,
               status, notes, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                args.address, args.city, args.state, args.county, args.property_type,
                args.beds, args.baths, args.sqft, args.asking, args.arv, repairs,
                args.repair_tier, args.fee, args.discount, args.closing_costs,
                args.dom, args.price_cuts, int(args.vacant), int(args.fsbo),
                args.agent_name, args.agent_phone, args.agent_email, args.seller_name,
                args.source, args.url, args.description, args.status, args.notes,
                now(), now(),
            ),
        )
    except sqlite3.IntegrityError:
        raise SystemExit(f"{args.address} is already in the pipeline. Use: wholesale deal set")
    conn.commit()
    deal_id = int(cur.lastrowid)
    log(conn, deal_id=deal_id, kind="note", detail=f"Added to pipeline as {args.status}")
    print(f"Deal #{deal_id}: {args.address}")
    row = conn.execute("SELECT * FROM deals WHERE id = ?", (deal_id,)).fetchone()
    s = screen_row(conn, row)
    if s:
        print(render_screen(s))
    else:
        print("Add --arv and --repairs (or --repair-tier) to see the math.")


FIELD_TYPES = {
    "city": str, "state": str, "county": str, "property_type": str,
    "beds": int, "baths": float, "sqft": int, "asking": float, "arv": float,
    "repairs": float, "repair_tier": str, "assignment_fee": float,
    "buyer_discount": float, "closing_costs": float, "days_on_market": int,
    "price_cuts": int, "vacant": int, "fsbo": int, "agent_name": str,
    "agent_phone": str, "agent_email": str, "seller_name": str, "source": str,
    "listing_url": str, "description": str, "contract_price": float, "notes": str,
}


def cmd_deal_set(args, conn):
    row = find_deal(conn, args.deal)
    updates: dict[str, object] = {}
    for pair in args.field:
        if "=" not in pair:
            raise SystemExit(f"Use field=value, got {pair!r}")
        key, value = pair.split("=", 1)
        key = key.strip().replace("-", "_")
        if key not in FIELD_TYPES:
            raise SystemExit(
                f"Unknown field {key!r}. Known: {', '.join(sorted(FIELD_TYPES))}"
            )
        caster = FIELD_TYPES[key]
        if value == "":
            updates[key] = None
        elif caster is int and value.lower() in ("true", "yes"):
            updates[key] = 1
        elif caster is int and value.lower() in ("false", "no"):
            updates[key] = 0
        else:
            try:
                updates[key] = caster(value)
            except ValueError:
                raise SystemExit(f"{key} expects {caster.__name__}, got {value!r}")
    if not updates:
        raise SystemExit("Nothing to update.")
    if "repair_tier" in updates and "repairs" not in updates:
        updates["repairs"] = analysis.repair_estimate(str(updates["repair_tier"]))
    sets = ", ".join(f"{k} = ?" for k in updates)
    conn.execute(
        f"UPDATE deals SET {sets}, updated_at = ? WHERE id = ?",
        (*updates.values(), now(), row["id"]),
    )
    conn.commit()
    log(conn, deal_id=row["id"], kind="note",
        detail="Updated " + ", ".join(updates))
    print(f"Updated #{row['id']} {row['address']}: {', '.join(updates)}")


def cmd_deal_status(args, conn):
    row = find_deal(conn, args.deal)
    if args.status not in STATUSES:
        raise SystemExit(f"Status must be one of: {', '.join(STATUSES)}")

    # Advancing to under_contract without the blocking pre-offer items done
    # is the moment things go wrong, so say so.
    if args.status in ("under_contract", "marketing", "assigned"):
        done = {
            r["item_key"] for r in conn.execute(
                "SELECT item_key FROM checklist WHERE deal_id = ? AND done = 1", (row["id"],)
            )
        }
        missing = [i for i in compliance.blocking_items(args.status) if i.key not in done]
        if missing and not args.force:
            print(f"Hold on. {len(missing)} blocking item(s) are not done for {args.status}:")
            for i in missing:
                print(f"  [ ] {i.key}: {i.text}")
                print(f"      why: {i.why}")
            print("\nMark them with: wholesale checklist <deal> --done <key>")
            print("Or override with --force if you have already handled them elsewhere.")
            sys.exit(3)

    conn.execute(
        "UPDATE deals SET status = ?, updated_at = ? WHERE id = ?",
        (args.status, now(), row["id"]),
    )
    conn.commit()
    log(conn, deal_id=row["id"], kind="status",
        detail=f"{row['status']} -> {args.status}")
    print(f"#{row['id']} {row['address']}: {row['status']} -> {args.status}")


def cmd_deal_list(args, conn):
    query = "SELECT * FROM deals"
    params: list[object] = []
    if args.status:
        query += " WHERE status = ?"
        params.append(args.status)
    elif not args.all:
        query += " WHERE status != 'dead'"
    query += " ORDER BY CASE status " + " ".join(
        f"WHEN '{s}' THEN {i}" for i, s in enumerate(STATUSES)
    ) + " END, id"
    rows = conn.execute(query, params).fetchall()

    out = []
    for r in rows:
        s = screen_row(conn, r)
        ceiling = money(s.margin.ceiling) if s else "—"
        verdict = s.verdict.split(" — ")[0] if s else "needs numbers"
        out.append([
            str(r["id"]),
            (r["address"] or "")[:34],
            (r["city"] or "")[:14],
            r["status"],
            money(r["asking"]),
            ceiling,
            verdict,
        ])
    print(table(out, ["ID", "Address", "City", "Status", "Asking", "Ceiling", "Verdict"]))
    if rows and not args.all and not args.status:
        print("\n(dead deals hidden — use --all)")


def cmd_deal_show(args, conn):
    row = find_deal(conn, args.deal)
    print(heading(f"#{row['id']} {row['address']}"))
    facts = [
        ("City", f"{row['city'] or '—'}, {row['state'] or ''} {row['county'] or ''}".strip(" ,")),
        ("Type", row["property_type"] or "—"),
        ("Layout", f"{row['beds'] or '?'}bd / {fmt_baths(row['baths'])}ba / {row['sqft'] or '?'} sqft"),
        ("Status", row["status"]),
        ("Source", row["source"] or "—"),
        ("Agent", row["agent_name"] or ("FSBO" if row["fsbo"] else "—")),
        ("Contact", " ".join(x for x in (row["agent_phone"], row["agent_email"]) if x) or "—"),
        ("Days on market", str(row["days_on_market"]) if row["days_on_market"] else "—"),
        ("Price cuts", str(row["price_cuts"] or 0)),
    ]
    for label, value in facts:
        print(f"  {label:<16} {value}")
    if row["listing_url"]:
        print(f"  {'Listing':<16} {row['listing_url']}")
    if row["notes"]:
        print(f"  {'Notes':<16} {row['notes']}")

    s = screen_row(conn, row)
    if s:
        print("")
        print(render_screen(s))
    else:
        print("\nNo math yet — set arv and repairs:")
        print(f"  wholesale deal set {row['id']} arv=250000 repair_tier=cosmetic")

    acts = conn.execute(
        "SELECT * FROM activity WHERE deal_id = ? ORDER BY id DESC LIMIT 8", (row["id"],)
    ).fetchall()
    if acts:
        print("\nRECENT ACTIVITY")
        for a in acts:
            amount = f" {money(a['amount'])}" if a["amount"] else ""
            print(f"  {a['created_at'][:16]}  {a['kind']:<8}{amount} {a['detail'] or ''}")


def cmd_deal_rm(args, conn):
    row = find_deal(conn, args.deal)
    if not args.yes:
        raise SystemExit(
            f"This deletes #{row['id']} {row['address']} and its comps and history. "
            "Re-run with --yes to confirm, or mark it dead instead:\n"
            f"  wholesale deal status {row['id']} dead"
        )
    conn.execute("DELETE FROM deals WHERE id = ?", (row["id"],))
    conn.commit()
    print(f"Deleted #{row['id']} {row['address']}")


def cmd_comp_add(args, conn):
    row = find_deal(conn, args.deal)
    conn.execute(
        """INSERT INTO comps (deal_id, address, sold_price, sqft, sold_date,
           same_building, same_street, renovated, note, created_at)
           VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (
            row["id"], args.address, args.price, args.sqft, args.date,
            int(args.same_building), int(args.same_street), int(args.renovated),
            args.note, now(),
        ),
    )
    conn.commit()
    comps = deal_comps(conn, row["id"])
    result = analysis.analyze_comps(comps, subject_sqft=row["sqft"])
    print(f"Comp added to #{row['id']} {row['address']} ({result.count} total)")
    if result.suggested_arv:
        print(f"  Suggested ARV: {money(result.suggested_arv)}")
    for w in result.warnings:
        print(f"  ! {w}")


def cmd_comp_list(args, conn):
    row = find_deal(conn, args.deal)
    rows = conn.execute("SELECT * FROM comps WHERE deal_id = ? ORDER BY id", (row["id"],)).fetchall()
    out = []
    for c in rows:
        tags = ",".join(
            t for t, on in (
                ("same-bldg", c["same_building"]),
                ("same-st", c["same_street"]),
                ("renovated", c["renovated"]),
            ) if on
        )
        ppsf = f"${c['sold_price'] / c['sqft']:,.0f}" if c["sqft"] else "—"
        out.append([str(c["id"]), c["address"][:30], money(c["sold_price"]),
                    str(c["sqft"] or "—"), ppsf, c["sold_date"] or "—", tags])
    print(table(out, ["ID", "Address", "Sold", "Sqft", "$/sqft", "Date", "Tags"]))
    result = analysis.analyze_comps(deal_comps(conn, row["id"]), subject_sqft=row["sqft"])
    if result.suggested_arv:
        print(f"\nSuggested ARV: {money(result.suggested_arv)}")
    for w in result.warnings:
        print(f"  ! {w}")


def cmd_buyer_add(args, conn):
    try:
        cur = conn.execute(
            """INSERT INTO buyers (name, company, phone, email, markets, property_types,
               min_price, max_price, max_repairs, buyer_discount, proof_of_funds,
               deals_closed, notes, active, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,1,?)""",
            (
                args.name, args.company, args.phone, args.email, args.markets,
                args.property_types, args.min_price, args.max_price, args.max_repairs,
                args.discount, int(args.proof_of_funds), args.deals_closed,
                args.notes, now(),
            ),
        )
    except sqlite3.IntegrityError:
        raise SystemExit(f"{args.name} is already on the buyer list.")
    conn.commit()
    print(f"Buyer #{cur.lastrowid}: {args.name}")
    if not args.proof_of_funds:
        print("  ! No proof of funds on file. Collect it before you send them a deal.")


def cmd_buyer_list(args, conn):
    rows = conn.execute("SELECT * FROM buyers ORDER BY deals_closed DESC, id").fetchall()
    out = [[
        str(r["id"]), r["name"][:22], (r["markets"] or "any")[:26],
        f"{money(r['min_price'])}–{money(r['max_price'])}" if r["max_price"] else "any",
        f"{(r['buyer_discount'] or DEFAULTS.buyer_discount):.0%}",
        "yes" if r["proof_of_funds"] else "NO",
        str(r["deals_closed"] or 0),
    ] for r in rows]
    print(table(out, ["ID", "Name", "Markets", "Price band", "Rule", "POF", "Closed"]))


def cmd_match(args, conn):
    row = find_deal(conn, args.deal)
    if not row["arv"] or row["repairs"] is None:
        raise SystemExit("Set arv and repairs on the deal first.")
    fee = row["assignment_fee"] or DEFAULTS.default_assignment_fee
    base = row["contract_price"] if row["contract_price"] else None
    if base is None:
        check = analysis.margin_check(
            arv=row["arv"], repairs=row["repairs"], assignment_fee=fee,
            buyer_discount=row["buyer_discount"] or DEFAULTS.buyer_discount,
        )
        base = check.ceiling
        source = "your ceiling (no contract price set)"
    else:
        source = "your contract price"
    price_to_buyer = base + fee

    print(heading(f"Buyer matches — {row['address']}"))
    print(f"  Price to buyer: {money(price_to_buyer)} = {money(base)} ({source}) + {money(fee)} fee\n")

    rows = conn.execute("SELECT * FROM buyers").fetchall()
    if not rows:
        print("No buyers on the list yet. Add one:")
        print("  wholesale buyer add --name 'Name' --markets 'Pompton Lakes,Passaic' --max-price 300000")
        return
    results = [
        buyers_mod.match_deal(
            buyers_mod.BuyBox.from_row(b),
            city=row["city"], county=row["county"],
            property_type=row["property_type"], arv=row["arv"],
            repairs=row["repairs"], price_to_buyer=price_to_buyer,
        )
        for b in rows
    ]
    results.sort(key=lambda m: (not m.fits, -m.score))
    for m in results:
        mark = "FIT " if m.fits else "no  "
        print(f"{mark} {m.buyer_name}  (score {m.score}, headroom {money(m.headroom)})")
        for r in m.reasons:
            print(f"       + {r}")
        for b in m.blockers:
            print(f"       - {b}")
        print("")


def cmd_script(args, conn):
    row = find_deal(conn, args.deal)
    if not row["arv"] or row["repairs"] is None:
        raise SystemExit("Set arv and repairs before generating scripts — no number goes out unchecked.")
    fee = row["assignment_fee"] or DEFAULTS.default_assignment_fee
    discount = row["buyer_discount"] or DEFAULTS.buyer_discount
    agent_listed = not row["fsbo"]

    try:
        if args.kind == "blast":
            price = row["contract_price"]
            if price is None:
                raise SystemExit(
                    "A buyer blast needs a signed contract price:\n"
                    f"  wholesale deal set {row['id']} contract_price=283500"
                )
            comps = deal_comps(conn, row["id"])
            comp_note = ""
            if comps:
                comp_note = "Recent comps: " + "; ".join(
                    f"{c.address} {money(c.sold_price)}" for c in comps[:4]
                )
            out = [scripts.buyer_blast(
                address=row["address"], arv=row["arv"], repairs=row["repairs"],
                contract_price=price, assignment_fee=fee, beds=row["beds"],
                baths=row["baths"], sqft=row["sqft"], comp_note=comp_note,
                your_name=args.your_name,
            )]
        elif args.kind == "intake":
            out = [scripts.buyer_intake()]
        else:
            built = scripts.build_scripts_for(
                address=row["address"], arv=row["arv"], repairs=row["repairs"],
                assignment_fee=fee, buyer_discount=discount,
                agent_listed=agent_listed, agent_name=row["agent_name"],
                your_name=args.your_name,
            )
            names = {"card": 0, "text": 1, "call": 2, "followup": 3}
            out = built if args.kind == "all" else [built[names[args.kind]]]
    except scripts.MarginNotChecked as exc:
        print("No script generated.\n")
        print(str(exc))
        sys.exit(2)

    for i, s in enumerate(out):
        if i:
            print("\n" + rule())
        print(s.render())
    log(conn, deal_id=row["id"], kind="note", detail=f"Generated {args.kind} script")


def cmd_checklist(args, conn):
    row = find_deal(conn, args.deal)
    if args.done:
        item = compliance.by_key(args.done)
        if not item:
            raise SystemExit(
                f"Unknown item {args.done!r}. Keys: "
                + ", ".join(i.key for i in compliance.NJ_CHECKLIST)
            )
        conn.execute(
            "INSERT INTO checklist (deal_id, item_key, done, done_at) VALUES (?,?,1,?)"
            " ON CONFLICT(deal_id, item_key) DO UPDATE SET done=1, done_at=excluded.done_at",
            (row["id"], item.key, now()),
        )
        conn.commit()
        log(conn, deal_id=row["id"], kind="note", detail=f"Checklist: {item.key} done")
        print(f"Done: {item.key} — {item.text}")
        return

    done = {
        r["item_key"] for r in conn.execute(
            "SELECT item_key FROM checklist WHERE deal_id = ? AND done = 1", (row["id"],)
        )
    }
    items = compliance.NJ_CHECKLIST if args.all else compliance.items_for_status(row["status"])
    print(heading(f"NJ checklist — #{row['id']} {row['address']} [{row['status']}]"))
    current_stage = None
    for item in items:
        if item.stage != current_stage:
            current_stage = item.stage
            print(f"\n{compliance.STAGE_LABELS[current_stage]}")
        box = "[x]" if item.key in done else "[ ]"
        flag = " (blocking)" if item.blocking and item.key not in done else ""
        print(f"  {box} {item.key}{flag}")
        print(f"      {item.text}")
        if item.key not in done:
            print(f"      why: {item.why}")
    print(f"\n{compliance.DISCLAIMER}")
    if not args.all:
        print("\n(showing this stage only — use --all for the full checklist)")


def cmd_pipeline(args, conn):
    rows = conn.execute("SELECT * FROM deals ORDER BY id").fetchall()
    if not rows:
        print("Pipeline is empty. Add a deal or run: wholesale seed")
        return
    counts: dict[str, int] = {}
    potential = 0.0
    for r in rows:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
        if r["status"] in ("under_contract", "marketing", "assigned"):
            potential += r["assignment_fee"] or DEFAULTS.default_assignment_fee

    print(heading("Pipeline"))
    out = [[s, str(counts.get(s, 0))] for s in STATUSES if counts.get(s)]
    print(table(out, ["Status", "Deals"]))
    print(f"\nFee potential in live deals: {money(potential)}")

    live = [r for r in rows if r["status"] not in ("dead", "closed")]
    actionable = []
    for r in live:
        s = screen_row(conn, r)
        if not s:
            actionable.append((r, "needs ARV and repair numbers"))
        elif s.verdict.startswith("PASS"):
            actionable.append((r, "math says pass — mark it dead and move on"))
        elif r["status"] in ("lead", "screening"):
            actionable.append((r, f"ready for outreach — open at {money(s.ladder.opening)}"))
        elif r["status"] == "contacted":
            actionable.append((r, "follow up"))
        elif r["status"] == "under_contract":
            actionable.append((r, "get it in front of buyers — wholesale match / script blast"))
    if actionable:
        print("\nNEXT ACTIONS")
        for r, what in actionable:
            print(f"  #{r['id']:<3} {r['address'][:38]:<38} {what}")


def cmd_seed(args, conn):
    from .seed import seed
    created = seed(conn, replace=args.replace)
    print(f"Seeded {created} deal(s) from the working-context history.")
    print("Run: wholesale deal list")


def cmd_log(args, conn):
    row = find_deal(conn, args.deal)
    log(conn, deal_id=row["id"], kind=args.kind, detail=args.detail, amount=args.amount)
    print(f"Logged {args.kind} on #{row['id']} {row['address']}")


# --------------------------------------------------------------------------
# Parser
# --------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="wholesale",
        description="Wholesale real estate assistant: screen deals, check margins "
                    "before you speak a number, track a pipeline, match cash buyers.",
        epilog="Not legal or financial advice.",
    )
    p.add_argument("--db", help="database path (default: ~/.wholesale/deals.db)")
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("init", help="create the database").set_defaults(func=cmd_init)

    # analyze
    a = sub.add_parser("analyze", help="run the numbers without saving anything")
    a.add_argument("--address", help="label for the output")
    a.add_argument("--arv", type=float, required=True, help="after-repair value")
    a.add_argument("--repairs", type=float, help="repair dollars")
    a.add_argument("--repair-tier", help=f"instead of --repairs: {analysis.REPAIR_TIER_HELP}")
    a.add_argument("--asking", type=float)
    a.add_argument("--price", type=float, help="a specific number you want to say — margin-checked")
    a.add_argument("--fee", type=float, default=DEFAULTS.default_assignment_fee)
    a.add_argument("--discount", type=float, default=DEFAULTS.buyer_discount)
    a.add_argument("--closing-costs", type=float, default=0.0)
    a.add_argument("--description", help="listing text, scored for motivation signals")
    a.add_argument("--dom", type=int, help="days on market")
    a.add_argument("--price-cuts", type=int)
    a.add_argument("--beds", type=int)
    a.add_argument("--baths", type=float)
    a.add_argument("--vacant", action="store_true")
    a.add_argument("--fsbo", action="store_true")
    a.set_defaults(func=cmd_analyze)

    # deal
    d = sub.add_parser("deal", help="manage deals").add_subparsers(dest="sub", required=True)

    da = d.add_parser("add", help="add a deal to the pipeline")
    da.add_argument("--address", required=True)
    da.add_argument("--city")
    da.add_argument("--state", default="NJ")
    da.add_argument("--county")
    da.add_argument("--property-type", help="single family, twin, condo, multi")
    da.add_argument("--beds", type=int)
    da.add_argument("--baths", type=float)
    da.add_argument("--sqft", type=int)
    da.add_argument("--asking", type=float)
    da.add_argument("--arv", type=float)
    da.add_argument("--repairs", type=float)
    da.add_argument("--repair-tier", help=analysis.REPAIR_TIER_HELP)
    da.add_argument("--fee", type=float, default=DEFAULTS.default_assignment_fee)
    da.add_argument("--discount", type=float, default=DEFAULTS.buyer_discount)
    da.add_argument("--closing-costs", type=float, default=0.0)
    da.add_argument("--dom", type=int)
    da.add_argument("--price-cuts", type=int, default=0)
    da.add_argument("--vacant", action="store_true")
    da.add_argument("--fsbo", action="store_true")
    da.add_argument("--agent-name")
    da.add_argument("--agent-phone")
    da.add_argument("--agent-email")
    da.add_argument("--seller-name")
    da.add_argument("--source", default="zillow")
    da.add_argument("--url")
    da.add_argument("--description")
    da.add_argument("--notes")
    da.add_argument("--status", default="lead", choices=STATUSES)
    da.set_defaults(func=cmd_deal_add)

    dl = d.add_parser("list", help="list deals")
    dl.add_argument("--status", choices=STATUSES)
    dl.add_argument("--all", action="store_true", help="include dead deals")
    dl.set_defaults(func=cmd_deal_list)

    ds = d.add_parser("show", help="full detail on one deal")
    ds.add_argument("deal")
    ds.set_defaults(func=cmd_deal_show)

    dse = d.add_parser("set", help="update fields: wholesale deal set 3 arv=460000 repairs=20000")
    dse.add_argument("deal")
    dse.add_argument("field", nargs="+")
    dse.set_defaults(func=cmd_deal_set)

    dst = d.add_parser("status", help="move a deal through the pipeline")
    dst.add_argument("deal")
    dst.add_argument("status", choices=STATUSES)
    dst.add_argument("--force", action="store_true", help="skip the blocking-item check")
    dst.set_defaults(func=cmd_deal_status)

    dr = d.add_parser("rm", help="delete a deal")
    dr.add_argument("deal")
    dr.add_argument("--yes", action="store_true")
    dr.set_defaults(func=cmd_deal_rm)

    # comp
    c = sub.add_parser("comp", help="manage comps").add_subparsers(dest="sub", required=True)
    ca = c.add_parser("add", help="add a comparable sale")
    ca.add_argument("deal")
    ca.add_argument("--address", required=True)
    ca.add_argument("--price", type=float, required=True)
    ca.add_argument("--sqft", type=int)
    ca.add_argument("--date", help="YYYY-MM-DD")
    ca.add_argument("--same-building", action="store_true")
    ca.add_argument("--same-street", action="store_true")
    ca.add_argument("--renovated", action="store_true")
    ca.add_argument("--note")
    ca.set_defaults(func=cmd_comp_add)

    cl = c.add_parser("list", help="list comps for a deal")
    cl.add_argument("deal")
    cl.set_defaults(func=cmd_comp_list)

    # buyer
    b = sub.add_parser("buyer", help="cash buyer list").add_subparsers(dest="sub", required=True)
    ba = b.add_parser("add", help="add a cash buyer")
    ba.add_argument("--name", required=True)
    ba.add_argument("--company")
    ba.add_argument("--phone")
    ba.add_argument("--email")
    ba.add_argument("--markets", help="comma separated towns and counties")
    ba.add_argument("--property-types", help="comma separated")
    ba.add_argument("--min-price", type=float, default=0.0)
    ba.add_argument("--max-price", type=float)
    ba.add_argument("--max-repairs", type=float)
    ba.add_argument("--discount", type=float, default=DEFAULTS.buyer_discount,
                    help="their ARV rule, e.g. 0.75")
    ba.add_argument("--proof-of-funds", action="store_true")
    ba.add_argument("--deals-closed", type=int, default=0)
    ba.add_argument("--notes")
    ba.set_defaults(func=cmd_buyer_add)

    bl = b.add_parser("list", help="show the buyer list")
    bl.set_defaults(func=cmd_buyer_list)

    m = sub.add_parser("match", help="match a deal against your buyer list")
    m.add_argument("deal")
    m.set_defaults(func=cmd_match)

    s = sub.add_parser("script", help="generate margin-checked outreach")
    s.add_argument("deal")
    s.add_argument("--kind", default="all",
                   choices=["all", "card", "text", "call", "followup", "blast", "intake"])
    s.add_argument("--your-name", default="[your name]")
    s.set_defaults(func=cmd_script)

    ch = sub.add_parser("checklist", help="NJ compliance checklist for a deal")
    ch.add_argument("deal")
    ch.add_argument("--done", help="mark an item done by key")
    ch.add_argument("--all", action="store_true", help="show every stage")
    ch.set_defaults(func=cmd_checklist)

    sub.add_parser("pipeline", help="pipeline summary and next actions").set_defaults(func=cmd_pipeline)

    sd = sub.add_parser("seed", help="load the deals from the working-context history")
    sd.add_argument("--replace", action="store_true", help="overwrite existing seeded deals")
    sd.set_defaults(func=cmd_seed)

    lg = sub.add_parser("log", help="log a call, text or offer against a deal")
    lg.add_argument("deal")
    lg.add_argument("kind", choices=["call", "text", "email", "offer", "note"])
    lg.add_argument("detail")
    lg.add_argument("--amount", type=float)
    lg.set_defaults(func=cmd_log)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    conn = connect(Path(args.db) if args.db else None)
    if args.command != "init":
        init_db(conn)   # idempotent, keeps first run from failing
    try:
        args.func(args, conn)
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
