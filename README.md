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
| Source records → contacts | 184 → 121 (118 real people) |
| Junk/spam quarantined | 11/11 caught, 0 false positives |
| Person matching (pairwise) | precision 0.94, recall 0.94 |
| Company assignment | 98.3% correct, 0 wrong, 3 unassigned |
| Usage events attributed | 1,086 / 1,157 (67 orphaned, 4 malformed) |

## Design decisions

**Identity resolution rules (union-find over records):**
- **R1 canonical email:** trim, lowercase, strip `+alias`, remove gmail dots.
- **R2 email typo:** same work domain + local part within 1 edit, names don't conflict, same first letter (`jsmith` vs `msmith` are different people, not a typo).
- **R3 name + company:** same first + last name at the same resolved company. Links the same person across different emails, e.g. a personal and a work address on two separate form fills.

**Company resolution:** work email domain is the key (strongest signal). Free-text company names only resolve by matching aliases learned from domain-backed records ("Vertex" → `vertexcloud.io`), never by creating new companies from free text.

**Why a custom `rb_company_key`:** HubSpot's `domain` field isn't unique, so it can't be an upsert key. A unique custom property makes company sync idempotent.

**Known misses (by design, left for Phase 2):** 4 people who signed up with a personal email and gave no usable name/company. Only person-level enrichment (Clay) can link `hannahrossi70@gmail.com` to `hannah.rossi@kestrel.ai`. The 4 "wrong merges" are a generator artifact: two fake people were given the identical mailbox `ravi@vertexcloud.io`.

## Outputs (`./out`)
- `contacts_clean.csv`, `companies_clean.csv`: what gets pushed
- `quarantine_junk.csv`: rejected records + reasons
- `merge_log.csv`: every fuzzy merge (R2/R3), for audit
- `eval_report.json`: full metrics
- `hubspot_payloads.json`: exact API calls (dry run only)
