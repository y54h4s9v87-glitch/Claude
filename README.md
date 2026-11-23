# Wholesale assistant

A command-line bot for wholesaling real estate: screen deals, check every
number against end-buyer economics *before* you say it out loud, track a
pipeline, match deals to cash buyers, and generate outreach scripts and a
New Jersey compliance checklist.

Pure Python 3.11 standard library. No dependencies, no install, no API keys.

```bash
./wholesale init      # create the database
./wholesale seed      # load the five deals already screened
./wholesale pipeline  # what to do next
```

## The rule the tool enforces

An opening offer is not safe because it sounds low. It is safe when an end
buyer can actually pay it and leave you a fee:

```
Buyer's max all-in  = (ARV x 70%) - repairs - closing costs
Your ceiling (MAO)  = buyer's max - your assignment fee
```

Any command that would print a price runs that check first. If the number
fails, no script is generated and the tool says why. `analyze --price`
exits non-zero on a failure so it can gate a script or a workflow.

```
$ ./wholesale analyze --arv 220000 --repairs 34000 --price 160000

MARGIN CHECK ON $160,000: FAIL
  - $160,000 is $50,000 ABOVE your ceiling of $110,000. Saying it out
    loud caps your fee at $0.
  - Assignment margin at this price is -$40,000, short of your $10,000 target.
  - Negative spread: the end buyer cannot pay this and hit their own numbers.
```

That is the corrected Wanaque Avenue condo from the working notes. The tool
refuses the number that was almost given.

## Commands

| Command | What it does |
|---|---|
| `analyze` | Run the numbers on anything, save nothing |
| `deal add / list / show / set / status / rm` | Manage the pipeline |
| `comp add / list` | Comparable sales, with thin-pool warnings |
| `buyer add / list` | Cash-buyer list and buy boxes |
| `match <deal>` | Rank buyers against one deal, by *their* discount rule |
| `script <deal>` | Margin-checked outreach: card, text, call, followup, blast, intake |
| `checklist <deal>` | New Jersey compliance items for the current stage |
| `pipeline` | Status counts, fee potential, next actions |
| `log <deal>` | Record a call, text, offer or note |

Run `./wholesale <command> --help` for the full flags on any of them.

### Screening a new lead

Paste the real listing description. The motivation score reads it for
distress language, and a summary in your own words will score lower than
the agent's actual copy.

```bash
./wholesale deal add \
  --address "5 Brookside Ave" --city "Pequannock Twp." --county Morris \
  --property-type "single family" --beds 4 --baths 1 \
  --asking 484900 --arv 505000 --repair-tier heavy \
  --vacant --dom 75 --price-cuts 1 \
  --description "Vacant. Sold as-is. Deferred exterior maintenance."
```

Repair tiers, if you would rather not guess a dollar figure:
`none`, `cosmetic` ($10-20K), `moderate` ($25-45K), `heavy` ($50-70K),
`gut` ($75-120K). The conservative end of the range is used, because an
under-estimated repair number is how a deal becomes unassignable.

### Verdicts

| Verdict | Meaning |
|---|---|
| `STRONG` | Asking is already at or below your ceiling |
| `PURSUE` | Math works and the seller shows real motivation |
| `WORKABLE` | Math works, motivation is thin, negotiation carries it |
| `LONG SHOT` | Big gap, but real distress makes the call worth making |
| `PASS` | No margin, or a gap with nothing behind it |

A 30% discount request against a seller showing no motivation is a pass,
not an opportunity. The tool says so rather than letting you burn an agent
relationship on it.

### Comps

```bash
./wholesale comp add 4 --address "3 Brookside Ave" --price 484000 \
  --same-street --renovated --date 2026-03-10
```

Comps flag themselves when the pool is thin, when nothing is on the same
street or in the same building, when renovated and unrenovated sales are
mixed, and when sales are older than twelve months. Small condo buildings
and one-off twins produce soft ARVs, and the tool says so instead of
printing a confident number.

### Buyers

Matching scores each buyer against *their* discount rule, not yours. A
buyer who works on 75% of ARV can pay more than one who works on 70%, and
the tool ranks accordingly.

```bash
./wholesale buyer add --name "Rina Patel" \
  --markets "Pequannock Twp.,Morris,Pompton Lakes" \
  --property-types "single family,twin" \
  --max-price 350000 --max-repairs 80000 --discount 0.70 --proof-of-funds

./wholesale match 4
```

`script <deal> --kind intake` prints the ten questions that build a buy box
worth matching against.

### Compliance

`checklist` tracks seventeen New Jersey items across four stages. Moving a
deal to `under_contract`, `marketing` or `assigned` is blocked until that
stage's blocking items are marked done; `--force` overrides.

The items that block are the ones that turn a wholesale deal into a
problem: assignment consent in writing rather than "and/or assigns"
boilerplate, disclosure of your intent to assign, the three-business-day
attorney review window, marketing your equitable interest rather than the
property, and disclosure to the end buyer.

**Not legal advice.** New Jersey has no wholesaling-specific statute; the
activity sits on contract law and the New Jersey Real Estate License Act
(Title 45, Ch. 15). A licensing bill, S3824, has been proposed — the
checklist includes an item to confirm its current status. Have a New Jersey
attorney review your contract package before using it on a live deal.

## Configuration

The database lives at `~/.wholesale/deals.db`. Override with `WHOLESALE_DB`
or `--db`.

Defaults for the 70% rule, the default assignment fee, the ladder ratios
and the verdict thresholds are in `wholesale_bot/config.py`. Per-deal
overrides: `--discount`, `--fee`, `--closing-costs`.

## What this does not do

It does not scrape Zillow or any other listing site. Deals go in by hand or
by script. It does not send texts or emails; it writes them for you to send.
It does not generate contracts.

## Tests

```bash
pytest
```

92 tests. The screening cases are the deals from the working notes, so a
change that alters the advice the tool gives will fail them.

## Layout

```
wholesale_bot/
  analysis.py     deal math, motivation scoring, comps, verdicts
  scripts.py      outreach generation, with the margin guard
  compliance.py   New Jersey checklist and stage gates
  buyers.py       buy boxes and matching
  db.py           SQLite schema and storage
  cli.py          command line interface
  seed.py         the deals from the working notes
  config.py       tunable defaults
```

---

## Also in this repo: video upload bot

`./uploader` queues videos for every YouTube / TikTok / Instagram / Facebook /
X account you run and writes briefs for Claude in Chrome to upload and
schedule them. See [upload_bot/README.md](upload_bot/README.md).
