"""Phase 1: messy sources -> clean, deduped Contacts + Companies -> HubSpot.

  python phase1.py            # dry run: clean, resolve, evaluate, write ./out (no HubSpot calls)
  python phase1.py --push     # same, then upsert into HubSpot (needs HUBSPOT_TOKEN in .env)
"""
import argparse
import csv
import json
import os

from pipeline import hubspot as hs
from pipeline.evaluate import evaluate
from pipeline.resolve import attach_usage, load_records, resolve

DATA = "data"
OUT = "out"
PAID_PLANS = {"pro", "pro_trial", "team"}
DEMO_FORMS = {"Demo Request", "Contact Sales"}


def ms(dt):
    return str(int(dt.timestamp() * 1000)) if dt else None


def contact_row(p):
    u = p["usage"]
    row = {
        "email": p["email"],
        "firstname": p["first"],
        "lastname": p["last"],
        "jobtitle": p["title"],
        "phone": p["phone"],
        "country": p["country"],
        "company": p.get("company_name"),
        "rb_source_systems": ";".join(p["sources"]),
        "rb_alt_emails": ";".join(p["alt_emails"]) or None,
        "rb_user_ids": ";".join(p["user_ids"]) or None,
        "rb_plan": p["plan"],
        "rb_signup_date": ms(p["signup_date"]),
        "rb_first_touch": p["first_touch"],
        "rb_latest_form": p["latest_form"],
        "rb_form_message": p["latest_form_message"],
        "rb_personal_email_signup": "true" if p["personal_email_signup"] else "false",
        "rb_last_active": ms(p["last_active"]),
        "rb_events_60d": str(sum(u.values())),
        "rb_pipeline_runs": str(u["pipeline_run"]),
        "rb_teammates_invited": str(u["invited_teammate"]),
        "rb_pricing_views": str(u["viewed_pricing"]),
        "rb_hit_rate_limit": "true" if u["hit_rate_limit"] else "false",
        "rb_integrations": ";".join(sorted(p["integrations"])) or None,
    }
    return {k: v for k, v in row.items() if v not in (None, "")}


def company_row(c, people_by_email):
    members = [people_by_email[e] for e in c["contacts"]]
    return {
        "rb_company_key": c["domain"],
        "name": c["name"],
        "domain": c["domain"],
        "rb_known_contacts": str(len(members)),
        "rb_active_users": str(sum(1 for p in members if sum(p["usage"].values()) > 0)),
        "rb_total_events": str(sum(sum(p["usage"].values()) for p in members)),
        "rb_paid_users": str(sum(1 for p in members if p["plan"] in PAID_PLANS)),
        "rb_demo_requested": "true" if any(f in DEMO_FORMS for p in members for f in p["forms"]) else "false",
    }


def write_csv(path, rows):
    keys = sorted({k for r in rows for k in r})
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--push", action="store_true", help="write to HubSpot (default: dry run)")
    args = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)

    # 1. load + normalize + resolve
    recs = load_records(DATA)
    people, companies, merge_log = resolve(recs)
    usage_stats = attach_usage(people, f"{DATA}/usage_events.jsonl")
    names = {c["domain"]: c["name"] for c in companies}
    for p in people:
        p["company_name"] = names.get(p["company_domain"])
    people_by_email = {p["email"]: p for p in people}

    contacts = [contact_row(p) for p in people]
    company_rows = [company_row(c, people_by_email) for c in companies]
    junk = [{"rid": r["rid"], "email": r["email_raw"].strip(), "reasons": ";".join(r["junk"])} for r in recs if r["junk"]]

    # 2. outputs for inspection
    write_csv(f"{OUT}/contacts_clean.csv", contacts)
    write_csv(f"{OUT}/companies_clean.csv", company_rows)
    write_csv(f"{OUT}/quarantine_junk.csv", junk)
    write_csv(f"{OUT}/merge_log.csv", [{"rule": a, "email_a": b, "email_b": c} for a, b, c in merge_log])

    # 3. evaluate against hidden answer key (only if present)
    key = f"{DATA}/_answer_key.csv"
    print(f"\nsource records: {len(recs)}  ->  contacts: {len(contacts)}  companies: {len(company_rows)}  quarantined: {len(junk)}")
    print(f"usage events: {dict(usage_stats)}")
    if os.path.exists(key):
        report = evaluate(recs, people, key)
        with open(f"{OUT}/eval_report.json", "w") as f:
            json.dump(report, f, indent=2, default=str)
        print("\n=== eval vs answer key ===")
        for k in ("junk", "people", "company"):
            print(f"{k:8} {report[k]}")
        if report["_missed_examples"]:
            print("missed merges (sample):", report["_missed_examples"][:4])
        if report["_wrong_examples"]:
            print("wrong merges (sample):", report["_wrong_examples"][:4])

    # 4. HubSpot
    token = os.getenv("HUBSPOT_TOKEN") or _from_dotenv()
    if args.push and not token:
        raise SystemExit("HUBSPOT_TOKEN not found in environment or .env")
    client = hs.HubSpot(token or "dry-run", dry_run=not args.push)
    print(f"\n=== HubSpot ({'PUSH' if args.push else 'dry run'}) ===")
    client.check_auth()
    for spec in hs.CONTACT_PROPERTIES:
        client.ensure_property("contacts", spec)
    for spec in hs.COMPANY_PROPERTIES:
        client.ensure_property("companies", spec)

    company_ids = client.batch_upsert("companies", "rb_company_key", company_rows)
    contact_ids = client.batch_upsert("contacts", "email", contacts)
    pairs = [(contact_ids[p["email"]], company_ids[p["company_domain"]])
             for p in people if p["email"] in contact_ids and p["company_domain"] in company_ids]
    client.associate_contacts_to_companies(pairs)

    if args.push:
        print(f"upserted {len(company_ids)} companies, {len(contact_ids)} contacts, {len(pairs)} associations")
    else:
        with open(f"{OUT}/hubspot_payloads.json", "w") as f:
            json.dump(client.calls, f, indent=2)
        print(f"{len(client.calls)} API calls planned -> {OUT}/hubspot_payloads.json  (run with --push to send)")


def _from_dotenv():
    try:
        from dotenv import load_dotenv
        load_dotenv()
        return os.getenv("HUBSPOT_TOKEN")
    except ImportError:
        return None


if __name__ == "__main__":
    main()
