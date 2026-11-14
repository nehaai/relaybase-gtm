# Relaybase GTM Data Engine — Phase 1

Messy product + marketing data → clean, deduplicated Contacts and Companies in HubSpot, with an eval harness that scores the identity resolution against ground truth.

```
signups.csv ──┐
form_fills.csv┼─→ normalize ─→ quarantine junk ─→ resolve people ─→ resolve companies ─→ HubSpot
usage_events ─┘   (email, name,   (test, spam,     (union-find,      (domain first,       (upsert on email /
                   dates, phone)   internal)        3 merge rules)    then alias match)    rb_company_key)
                                                          │
                                                   eval vs answer key
```

## Run

```bash
pip install -r requirements.txt
cp .env.example .env          # paste your HubSpot service key
python phase1.py              # dry run: writes ./out, no HubSpot calls
python phase1.py --push       # upsert into HubSpot (safe to re-run; idempotent)
```

Regenerate the source data with `python generate_data.py` (seeded, so it's deterministic).

## Results (current data)

| Metric | Value |
|---|---|
| Source records → contacts | 234 → 154 (148 real people) |
| Junk/spam quarantined | 11/11 caught, 0 false positives |
| Person matching (pairwise) | precision 1.00, recall 0.90 |
| Company assignment | 96.9% correct, 0 wrong, 7 unassigned |
| Usage events attributed | 1,469 / 1,553 (80 orphaned, 4 malformed) |

## About the data

The 18 companies are **real** (Vercel, Stripe, Datadog, Ramp, ...) so Phase 2 can enrich them with public firmographics. **Every person is synthetic**: names, emails, phone numbers, titles and product usage are generated. Never enroll these contacts in email sends or sequences, and never run person-level enrichment on them; a fake name at a real domain can collide with a real employee.

## Design decisions

**Identity resolution rules (union-find over records), strictest first:**
- **R1 canonical email:** trim, lowercase, strip `+alias`, remove gmail dots.
- **R2 email typo:** same work domain + local part within 1 edit, names don't conflict. Two guards learned from eval failures:
  - different first letter (`jsmith` vs `msmith`) = different people's initials, not a typo
  - difference only in the last character (`fatima` vs `fatimao`) = first-name vs first-name-plus-initial conventions, usually two people
- **R3 name + company:** same first + last name at the same resolved company. Links a person across different emails, e.g. Elena Ahmed's hotmail signup and her `@stripe.com` demo request become one contact.

Wrong merges cost more than missed ones (a rep contacts the wrong person with the wrong context), so the rules favor precision.

**Company resolution:** work email domain is the key. Free-text company names only resolve by matching aliases learned from domain-backed records ("DataDog" → `datadoghq.com`); free text never creates a company. The 7 unassigned records are all personal emails with a blank company field; the pipeline leaves them unassigned rather than guessing.

**Why a custom `rb_company_key`:** HubSpot's `domain` field isn't unique, so it can't be an upsert key. A unique custom property makes company sync idempotent.

**Known misses:** 9 record pairs, each linking a personal email (gmail, icloud, ...) to the same person's work email. The personal-email record is missing the last name or the company, so no rule has enough evidence to merge them safely.

## Resetting HubSpot after changing the data

```bash
python phase1.py              # rebuild ./out from current data
python cleanup.py             # dry run: lists pipeline records no longer in the data
python cleanup.py --apply     # archives them (recoverable for 90 days)
python phase1.py --push
```
`cleanup.py` only touches records the pipeline created (those with `rb_company_key` / `rb_source_systems`).

## Outputs (`./out`)
- `contacts_clean.csv`, `companies_clean.csv`: what gets pushed
- `quarantine_junk.csv`: rejected records + reasons
- `merge_log.csv`: every fuzzy merge (R2/R3), for audit
- `eval_report.json`: full metrics
- `hubspot_payloads.json`: exact API calls (dry run only)
