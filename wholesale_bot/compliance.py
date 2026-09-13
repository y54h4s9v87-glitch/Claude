"""New Jersey wholesaling checklist.

This is an operational checklist, not legal advice. New Jersey has no
wholesaling-specific statute; the activity sits on contract law (the
equitable conversion doctrine) and the New Jersey Real Estate License
Act, Title 45, Chapter 15. Have a New Jersey real estate attorney review
your contract package before you use it on a live deal.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Item:
    key: str
    stage: str
    text: str
    why: str
    blocking: bool = False   # cannot advance past this stage without it


NJ_CHECKLIST: tuple[Item, ...] = (
    Item(
        "disclose_investor_seller",
        "before_offer",
        "Tell the seller in writing that you are an investor, not a licensed agent, and are not representing them.",
        "Acting like an agent without a license is what turns wholesaling into unlicensed brokering under Title 45, Ch. 15.",
        blocking=True,
    ),
    Item(
        "margin_checked",
        "before_offer",
        "Run the buyer-side margin check on the exact number you plan to say.",
        "An offer that no end buyer can pay is a contract you cannot assign.",
        blocking=True,
    ),
    Item(
        "agent_channel",
        "before_offer",
        "If the property is agent-listed, route every contact through the agent.",
        "Going around a listing agent to the homeowner invites a license complaint.",
    ),
    Item(
        "assignment_clause",
        "contract",
        "Use an explicit assignment addendum with the seller's written consent — not 'and/or assigns' boilerplate.",
        "New Jersey contracts are not automatically assignable. Boilerplate is not consent.",
        blocking=True,
    ),
    Item(
        "disclose_intent_assign",
        "contract",
        "State in the contract that you intend to assign it, and for a fee.",
        "Undisclosed assignment is the fastest route to a rescinded deal.",
        blocking=True,
    ),
    Item(
        "attorney_review",
        "contract",
        "Build the three-business-day attorney review window into the timeline on any agent-prepared residential contract.",
        "During review either side's attorney can cancel. An assignment scheduled through that window can evaporate.",
        blocking=True,
    ),
    Item(
        "inspection_window",
        "contract",
        "Keep an inspection or due-diligence window long enough to find a buyer.",
        "It is your exit if the assignment does not come together.",
    ),
    Item(
        "earnest_money",
        "contract",
        "Keep earnest money small and deposited with an attorney or title company.",
        "It is the money at risk if you cannot assign.",
    ),
    Item(
        "title_search",
        "contract",
        "Open title early — check liens, judgments, unpaid taxes, and any oil tank record.",
        "Buried liens kill assignments late, when you have no time left.",
    ),
    Item(
        "market_interest_only",
        "marketing",
        "Advertise your equitable interest in the contract, never the property itself.",
        "Marketing the property is brokering it. Marketing your contract position is not.",
        blocking=True,
    ),
    Item(
        "disclose_to_buyer",
        "marketing",
        "Tell the end buyer plainly that they are taking an assignment of your contract, and what your fee is.",
        "Disclosure on both sides is what keeps the transaction clean.",
        blocking=True,
    ),
    Item(
        "buyer_proof_of_funds",
        "marketing",
        "Collect proof of funds before you take the property off the market for a buyer.",
        "A buyer who cannot show funds will not close, and your deposit is the thing at risk.",
    ),
    Item(
        "assignment_agreement",
        "assignment",
        "Sign a written assignment agreement naming the fee, the deposit, and the closing date.",
        "A verbal assignment is not a fee you can collect.",
        blocking=True,
    ),
    Item(
        "nonrefundable_deposit",
        "assignment",
        "Take a non-refundable assignment deposit.",
        "It is the only thing separating a committed buyer from a tire-kicker.",
    ),
    Item(
        "closing_disclosure",
        "assignment",
        "Make sure the assignment fee appears on the closing statement and that all parties see it.",
        "Fees that appear only off the settlement sheet are how deals unwind afterward.",
        blocking=True,
    ),
    Item(
        "attorney_reviewed_package",
        "assignment",
        "Have a New Jersey attorney review your contract and assignment addendum before you use them again.",
        "One review of the template protects every deal that uses it.",
    ),
    Item(
        "check_s3824",
        "ongoing",
        "Confirm the current status of New Jersey bill S3824 and any successor licensing bill.",
        "A licensing requirement for wholesalers has been proposed. If it passes, the rules above change.",
    ),
)

STAGES = ("before_offer", "contract", "marketing", "assignment", "ongoing")

STAGE_LABELS = {
    "before_offer": "Before you make an offer",
    "contract": "Getting it under contract",
    "marketing": "Marketing the contract",
    "assignment": "Assigning and closing",
    "ongoing": "Ongoing",
}

# Which checklist stages are relevant at each pipeline status.
STATUS_STAGES = {
    "lead": ("before_offer",),
    "screening": ("before_offer",),
    "contacted": ("before_offer",),
    "negotiating": ("before_offer", "contract"),
    "under_contract": ("contract", "marketing"),
    "marketing": ("marketing",),
    "assigned": ("assignment",),
    "closed": ("assignment",),
    "dead": (),
}

DISCLAIMER = (
    "Not legal advice. New Jersey has no wholesaling-specific statute; this "
    "activity is governed by contract law and the New Jersey Real Estate "
    "License Act (Title 45, Ch. 15). Have a New Jersey attorney review your "
    "contract package before using it on a live deal."
)


def items_for_stage(stage: str) -> tuple[Item, ...]:
    return tuple(i for i in NJ_CHECKLIST if i.stage == stage)


def items_for_status(status: str) -> tuple[Item, ...]:
    stages = STATUS_STAGES.get(status, STAGES)
    return tuple(i for i in NJ_CHECKLIST if i.stage in stages)


# Stages whose blocking items must be done BEFORE a deal may enter a
# status. Deliberately narrower than STATUS_STAGES: you cannot have
# disclosed to an end buyer before you have one.
ENTRY_GATES = {
    "under_contract": ("before_offer", "contract"),
    "marketing": ("marketing",),
    "assigned": ("assignment",),
    "closed": ("assignment",),
}


def blocking_items(status: str) -> tuple[Item, ...]:
    """Blocking items that must be done before entering `status`."""
    stages = ENTRY_GATES.get(status)
    if stages is None:
        return ()
    return tuple(i for i in NJ_CHECKLIST if i.stage in stages and i.blocking)


def by_key(key: str) -> Item | None:
    for item in NJ_CHECKLIST:
        if item.key == key:
            return item
    return None
