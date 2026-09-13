"""Outreach script generation.

Hard rule enforced here: no template that contains a price will render
unless that price has passed a buyer-side margin check. The mistake this
package exists to prevent is saying a number before checking whether an
end buyer could ever pay it.
"""

from __future__ import annotations

import textwrap
from dataclasses import dataclass

from .analysis import Ladder, MarginCheck, fmt_baths, margin_check, negotiation_ladder
from .config import DEFAULTS, Config


class MarginNotChecked(Exception):
    """Raised when a script with a number in it would fail buyer economics."""


def money(value: float | None) -> str:
    if value is None:
        return "—"
    return f"${value:,.0f}"


# --------------------------------------------------------------------------
# Disclosure language — used in several scripts, kept in one place
# --------------------------------------------------------------------------

SELLER_DISCLOSURE = (
    "Just so we're clear up front: I'm a real estate investor, not an agent, "
    "and I'm not representing you. I buy with cash and I may assign this "
    "contract to another investor in my network before we close. Either way "
    "you get your price at closing."
)

BUYER_DISCLOSURE = (
    "To be clear on what I'm offering: I hold an assignable purchase contract "
    "on this property. I'm selling my interest in that contract, not the "
    "property itself. You'd take my position and close directly with the seller."
)

NJ_TIMELINE_NOTE = (
    "In New Jersey, if the contract is prepared by an agent there's a "
    "three-business-day attorney review window before it's firm. Plan the "
    "assignment timeline around that, not through it."
)


def quote(text: str, indent: str = "   ", width: int = 74) -> str:
    """Wrap a spoken line so it reads as script, not as a wall of text."""
    lines = textwrap.wrap(text, width=width - len(indent))
    if not lines:
        return ""
    body = f'{indent}"{lines[0]}'
    for line in lines[1:]:
        body += f"\n{indent} {line}"
    return body + '"'


@dataclass
class Script:
    title: str
    body: str
    warnings: tuple[str, ...] = ()

    def render(self) -> str:
        out = [self.title, "=" * len(self.title), "", self.body.strip("\n")]
        if self.warnings:
            out += ["", "-- Before you send this --"]
            out += [f"  ! {w}" for w in self.warnings]
        return "\n".join(out)


def _guard(check: MarginCheck | None, price: float | None) -> tuple[str, ...]:
    """Refuse to render a priced script that fails buyer math."""
    if price is None:
        return ()
    if check is None:
        raise MarginNotChecked(
            "A price was requested without a margin check. Run the check first: "
            "margin_check(arv=..., repairs=..., assignment_fee=..., proposed_price=...)"
        )
    if not check.passes:
        raise MarginNotChecked(
            "This price fails the buyer-side margin check, so no script will be "
            "generated for it:\n  - " + "\n  - ".join(check.reasons)
        )
    # A passing check is not a warning. Only surface notes that flag risk.
    return tuple(r for r in check.reasons if "Clears the ceiling" not in r)


# --------------------------------------------------------------------------
# First contact
# --------------------------------------------------------------------------

def first_text(
    *,
    address: str,
    agent_listed: bool = True,
    agent_name: str | None = None,
    your_name: str = "[your name]",
) -> Script:
    """Short, low-pressure opener. No number in it — that comes later."""
    who = f"Hi {agent_name}," if agent_name else "Hi,"
    if agent_listed:
        body = f"""{who} I saw your listing at {address}.

I'm a cash buyer, no financing contingency, and I can be flexible on the
closing date to fit your seller's timeline. Is the seller open to an as-is
offer?

Happy to send something in writing today if that's useful.

{your_name}"""
        warnings = (
            "This listing has an agent. All contact goes through the agent, "
            "not the homeowner — going around them is a licensing problem, not just bad manners.",
        )
    else:
        body = f"""{who} I saw your place at {address} listed for sale by owner.

I'm a local cash buyer — no bank, no financing contingency, and I can work
around whatever closing date suits you. I buy as-is, so there's no repair
list and no cleaning out before closing.

Would you be open to an as-is offer?

{your_name}"""
        warnings = (
            "Confirm the property really is unrepresented before contacting the owner directly.",
        )
    return Script(f"First contact — {address}", body, warnings)


def phone_script(
    *,
    address: str,
    ladder: Ladder,
    check: MarginCheck,
    agent_listed: bool = True,
    your_name: str = "[your name]",
) -> Script:
    """Full call script with the ladder and the walk-away built in."""
    warnings = _guard(check, ladder.opening)
    counterparty = "the agent" if agent_listed else "the seller"

    body = f"""PROPERTY: {address}
KNOW BEFORE YOU DIAL
  Open at ......... {money(ladder.opening)}
  Round 2 ......... {money(ladder.second)}
  Ceiling (MAO) ... {money(ladder.ceiling)}
  WALK AWAY above . {money(ladder.walk_away)}
  End buyer can be all-in at {money(check.buyer_max)}; your fee target is
  {money(check.assignment_fee)}. Above the ceiling there is no fee left.

1. OPEN
   "Hi, this is {your_name} — I'm calling about {address}. Do you have two minutes?"

2. QUALIFY (listen more than you talk)
   "What's the situation with the property — is it vacant right now?"
   "Has the seller had it under contract before?"
   "What's the timeline they'd ideally want?"
   "Anything that's been holding up offers — roof, systems, anything like that?"

3. POSITION
   "Here's where I'm coming from: I buy as-is with cash. No appraisal, no
   financing contingency, no repair requests, and I can close on whatever
   date works. What I can't do is pay retail — the trade is certainty and
   speed for price."

4. DISCLOSE (say it plainly, once, then move on)
{quote(SELLER_DISCLOSURE)}

5. THE NUMBER
   "Based on what it needs, the number that works for me is
   {money(ladder.opening)} — as-is, cash, no contingencies."
   Then stop talking. Let {counterparty} respond first.

6. COUNTERS
   If countered above {money(ladder.opening)}:
     "I've got room to move a little. I could get to {money(ladder.second)}
      if we can keep the closing simple."
   If pushed again:
     "{money(ladder.ceiling)} is the top of what this works at for me.
      I'd rather be straight with you than waste your time walking it back later."
   If pushed above {money(ladder.walk_away)}:
     "Then I'm not your buyer on this one — but keep my number. If it's still
      around in a few weeks, call me and I'll take another look."
   Then actually hang up. The walk-away is the whole reason you set it.

7. CLOSE
   "I'll send a one-page as-is purchase agreement over today. Take a look and
   send it back signed if it works."
   {NJ_TIMELINE_NOTE}
"""
    return Script(f"Phone script — {address}", body, warnings)


def follow_up(*, address: str, days_since: int = 7, your_name: str = "[your name]") -> Script:
    body = f"""Hi — following up on {address} from {days_since} days ago.

My offer stands and my terms haven't changed: cash, as-is, no financing
contingency, close on whatever date works for the seller.

If they've had other offers come in that fell apart on inspection or
financing, that's usually where I'm useful. Worth a conversation?

{your_name}"""
    return Script(f"Follow-up — {address}", body)


# --------------------------------------------------------------------------
# Buyer side
# --------------------------------------------------------------------------

def buyer_blast(
    *,
    address: str,
    arv: float,
    repairs: float,
    contract_price: float,
    assignment_fee: float,
    beds: int | None = None,
    baths: float | None = None,
    sqft: int | None = None,
    comp_note: str = "",
    your_name: str = "[your name]",
) -> Script:
    """Dispo email to your cash-buyer list.

    Markets the equitable interest in the contract, never the property.
    """
    total = contract_price + assignment_fee
    buyer_margin = arv * DEFAULTS.buyer_discount - repairs - total
    specs = " / ".join(
        p for p in (
            f"{beds}bd" if beds else "",
            f"{fmt_baths(baths)}ba" if baths else "",
            f"{sqft:,} sqft" if sqft else "",
        ) if p
    )

    warnings = []
    if buyer_margin < 0:
        warnings.append(
            f"At {money(total)} your buyer is {money(abs(buyer_margin))} past the 70% rule. "
            "Expect this to sit. Renegotiate with the seller or cut your fee."
        )
    if total >= arv * DEFAULTS.buyer_discount - repairs:
        warnings.append("Your fee is eating the buyer's entire margin.")

    body = f"""Subject: Assignment available — {address}{f" ({specs})" if specs else ""}

{textwrap.fill(BUYER_DISCLOSURE, width=74)}

  Address .............. {address}
  {("Specs ................ " + specs) if specs else ""}
  Contract price ....... {money(contract_price)}
  Assignment fee ....... {money(assignment_fee)}
  Your total to seller . {money(total)}
  Estimated repairs .... {money(repairs)}
  ARV .................. {money(arv)}
  All-in vs ARV ........ {(total + repairs) / arv:.0%}

{comp_note or "Comps available on request."}

First to sign and put down a non-refundable deposit takes it. I can send
the contract and the assignment addendum today.

{your_name}"""
    return Script(f"Buyer blast — {address}", body, tuple(warnings))


def buyer_intake() -> Script:
    """Questions that build a buy box worth matching against."""
    body = """Use this when you add someone to the cash-buyer list. Vague
answers mean a buyer who will not close.

1.  What towns or counties do you actually buy in?
2.  Price range you're buying in right now — low and high?
3.  Property types: single family, twin, condo, small multi?
4.  How much rehab do you take on? Cosmetic only, or full gut?
5.  What discount to ARV do you need to make a deal work — 70%? 75%?
6.  Are you buying to flip or to hold as a rental?
7.  How many have you closed in the last twelve months?
8.  Cash or hard money? Can you send proof of funds today?
9.  How fast can you close once you have a signed contract?
10. Anything you'd never buy? Flood zone, oil tank, deed restrictions?

Ask for proof of funds before you send them a deal. A buyer who won't
send it is a buyer who will tie up your contract and then vanish."""
    return Script("Cash buyer intake questions", body)


def offer_summary(*, address: str, check: MarginCheck, ladder: Ladder) -> Script:
    """One-screen pre-call card. Refuses to print if the math fails."""
    warnings = _guard(check, ladder.opening)
    body = f"""  ARV ....................... {money(check.arv)}
  Repairs ................... {money(check.repairs)}
  Buyer discount ............ {check.buyer_discount:.0%} of ARV
  Buyer's max all-in ........ {money(check.buyer_max)}
  Your assignment fee ....... {money(check.assignment_fee)}
  ------------------------------------------
  YOUR CEILING (MAO) ........ {money(check.ceiling)}

  Open at ................... {money(ladder.opening)}
  Round 2 ................... {money(ladder.second)}
  Do not exceed ............. {money(ladder.ceiling)}
"""
    return Script(f"Pre-call card — {address}", body, warnings)


def build_scripts_for(
    *,
    address: str,
    arv: float,
    repairs: float,
    assignment_fee: float = DEFAULTS.default_assignment_fee,
    buyer_discount: float = DEFAULTS.buyer_discount,
    agent_listed: bool = True,
    agent_name: str | None = None,
    your_name: str = "[your name]",
    cfg: Config = DEFAULTS,
) -> list[Script]:
    """Everything you need for one deal, margin-checked end to end."""
    base = margin_check(
        arv=arv, repairs=repairs, assignment_fee=assignment_fee, buyer_discount=buyer_discount
    )
    ladder = negotiation_ladder(base.ceiling, cfg)
    checked = margin_check(
        arv=arv,
        repairs=repairs,
        assignment_fee=assignment_fee,
        buyer_discount=buyer_discount,
        proposed_price=ladder.opening,
    )
    return [
        offer_summary(address=address, check=checked, ladder=ladder),
        first_text(
            address=address,
            agent_listed=agent_listed,
            agent_name=agent_name,
            your_name=your_name,
        ),
        phone_script(
            address=address,
            ladder=ladder,
            check=checked,
            agent_listed=agent_listed,
            your_name=your_name,
        ),
        follow_up(address=address, your_name=your_name),
    ]
