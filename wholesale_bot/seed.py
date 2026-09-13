"""Load the deals already screened in the working-context notes.

Every number here comes from that history. Where the history recorded a
number that does not survive the buyer-side margin check, the deal is
seeded with its real inputs and the old figure is kept in `notes` so the
discrepancy is visible instead of quietly inherited.
"""

from __future__ import annotations

import sqlite3

from .db import log, now

# (deal fields, comps)
SEED_DEALS: tuple[tuple[dict, list[dict]], ...] = (
    (
        dict(
            address="8 Beacon Hill Commons #8", city="Pompton Lakes", county="Passaic",
            property_type="condo", asking=499_000, arv=530_000, repairs=12_500,
            repair_tier="cosmetic", assignment_fee=10_000, status="dead",
            source="zillow", description="Agent-listed. Well kept, no distress language.",
            notes="Passed: agent-listed, comps selling above ask, no distress signals. "
                  "Ceiling came out near $348,500 against a $499,000 ask.",
        ),
        [],
    ),
    (
        dict(
            address="506 Wanaque Ave #F6", city="Pompton Lakes", county="Passaic",
            property_type="condo", asking=250_000, arv=220_000, repairs=34_000,
            repair_tier="moderate", assignment_fee=10_000, status="negotiating",
            source="zillow",
            description="Condo in a small 8-unit building. Dated, needs work.",
            notes="ARV is soft: 8-unit building, thin comp pool, range $210-235K. "
                  "First pass opened at $160K, which was too high — corrected to a "
                  "ceiling near $110K. Open around $90K.",
        ),
        [],
    ),
    (
        dict(
            address="46 Walnut Street", city="Pompton Lakes", county="Passaic",
            property_type="twin", asking=390_000, arv=445_000, repairs=20_000,
            repair_tier="cosmetic", assignment_fee=10_000, status="negotiating",
            source="zillow",
            description="Semi-detached twin. Dated but structurally sound.",
            notes="Earlier working numbers on this deal were an opening of $335K and a "
                  "ceiling of $358K. Both sit ABOVE the margin-checked ceiling at a 70% "
                  "rule — re-check before repeating them to the agent.",
        ),
        [
            dict(address="48 Walnut Street (other half of twin)", sold_price=362_585,
                 sold_date="2023-06-01", same_street=True,
                 note="Other half of the same twin"),
            dict(address="Walnut St comparable, renovated", sold_price=459_000,
                 same_street=True, renovated=True,
                 note="Currently listed at $459K renovated — asking, not a sale"),
        ],
    ),
    (
        dict(
            address="5 Brookside Ave", city="Pequannock Twp.", county="Morris",
            property_type="single family", beds=4, baths=1.0, asking=484_900,
            arv=505_000, repairs=60_000, repair_tier="heavy", assignment_fee=10_000,
            vacant=1, status="contacted", source="zillow",
            description="Vacant. Deferred exterior maintenance, roof and siding staining. "
                        "Four bedrooms with one bath. Sold as-is.",
            notes="Best deal screened so far. Real distress signals and the math actually "
                  "pencils: ceiling $283,500, leaving roughly $10-12K of fee after the "
                  "buyer's own numbers. Outreach sent — follow up.",
        ),
        [
            dict(address="3 Brookside Ave", sold_price=484_000, same_street=True,
                 renovated=True, note="Same street, renovated — anchors the ARV"),
        ],
    ),
    (
        dict(
            address="520 Newark Pompton Tpk #C214", city="Pequannock", county="Morris",
            property_type="condo", asking=297_000, status="dead", source="zillow",
            description="Crestwood Park Condos. Fully renovated, staged, active amenities.",
            notes="Passed: renovated, staged, zero distress signals. Nothing to negotiate against.",
        ),
        [],
    ),
)

COLUMNS = (
    "address city state county property_type beds baths sqft asking arv repairs "
    "repair_tier assignment_fee buyer_discount closing_costs days_on_market "
    "price_cuts vacant fsbo agent_name agent_phone agent_email seller_name source "
    "listing_url description status contract_price notes"
).split()


def seed(conn: sqlite3.Connection, *, replace: bool = False) -> int:
    created = 0
    for fields, comps in SEED_DEALS:
        data = {k: fields.get(k) for k in COLUMNS}
        data["state"] = data["state"] or "NJ"
        data["status"] = data["status"] or "lead"
        data["price_cuts"] = data["price_cuts"] or 0
        data["vacant"] = data["vacant"] or 0
        data["fsbo"] = data["fsbo"] or 0
        data["closing_costs"] = data["closing_costs"] or 0

        existing = conn.execute(
            "SELECT id FROM deals WHERE address = ? AND city IS ?",
            (data["address"], data["city"]),
        ).fetchone()
        if existing and not replace:
            continue
        if existing:
            conn.execute("DELETE FROM deals WHERE id = ?", (existing["id"],))

        placeholders = ",".join("?" for _ in COLUMNS)
        cur = conn.execute(
            f"INSERT INTO deals ({','.join(COLUMNS)}, created_at, updated_at)"
            f" VALUES ({placeholders}, ?, ?)",
            (*[data[k] for k in COLUMNS], now(), now()),
        )
        deal_id = int(cur.lastrowid)
        created += 1
        for comp in comps:
            conn.execute(
                """INSERT INTO comps (deal_id, address, sold_price, sqft, sold_date,
                   same_building, same_street, renovated, note, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (
                    deal_id, comp["address"], comp["sold_price"], comp.get("sqft"),
                    comp.get("sold_date"), int(comp.get("same_building", False)),
                    int(comp.get("same_street", False)), int(comp.get("renovated", False)),
                    comp.get("note"), now(),
                ),
            )
        log(conn, deal_id=deal_id, kind="note", detail="Seeded from working-context history")
    conn.commit()
    return created
