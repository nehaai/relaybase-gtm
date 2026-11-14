"""Remove pipeline records from HubSpot that are no longer in the current dataset.

Only touches records this pipeline created:
  - companies that have an rb_company_key not in out/companies_clean.csv
  - contacts that have rb_source_systems set and an email not in out/contacts_clean.csv
Anything else in the portal (manually created records, other imports) is left alone.

  python phase1.py              # first, so ./out reflects the current data
  python cleanup.py             # dry run: lists what would be archived
  python cleanup.py --apply     # archives them (recoverable from HubSpot's recycle bin for 90 days)
"""
import argparse
import csv
import os

from pipeline.hubspot import BASE, HubSpot

OUT = "out"


def list_all(client, object_type, props):
    rows, after = [], None
    while True:
        url = f"/crm/v3/objects/{object_type}?limit=100&properties={','.join(props)}" + (f"&after={after}" if after else "")
        res = client._req("GET", url, ok=(200,))
        rows += res.get("results", [])
        after = (res.get("paging") or {}).get("next", {}).get("after")
        if not after:
            return rows


def keep_set(path, col):
    with open(path, encoding="utf-8") as f:
        return {r[col].strip().lower() for r in csv.DictReader(f) if r.get(col)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    from dotenv import load_dotenv
    load_dotenv()
    token = os.getenv("HUBSPOT_TOKEN")
    if not token:
        raise SystemExit("HUBSPOT_TOKEN not found in .env")
    if not os.path.exists(f"{OUT}/contacts_clean.csv"):
        raise SystemExit("run `python phase1.py` first so ./out has the current data")

    client = HubSpot(token)  # reads always hit the API; deletes only with --apply
    keep_emails = keep_set(f"{OUT}/contacts_clean.csv", "email")
    keep_keys = keep_set(f"{OUT}/companies_clean.csv", "rb_company_key")

    stale_companies = [c for c in list_all(client, "companies", ["name", "rb_company_key"])
                       if c["properties"].get("rb_company_key")
                       and c["properties"]["rb_company_key"].lower() not in keep_keys]
    stale_contacts = [c for c in list_all(client, "contacts", ["email", "rb_source_systems"])
                      if c["properties"].get("rb_source_systems")
                      and (c["properties"].get("email") or "").lower() not in keep_emails]

    print(f"stale companies: {len(stale_companies)}")
    for c in stale_companies:
        print(f"  - {c['properties'].get('name')} ({c['properties'].get('rb_company_key')})")
    print(f"stale contacts: {len(stale_contacts)}")
    for c in stale_contacts[:10]:
        print(f"  - {c['properties'].get('email')}")
    if len(stale_contacts) > 10:
        print(f"  ... and {len(stale_contacts) - 10} more")

    if not args.apply:
        print("\ndry run, nothing deleted. Re-run with --apply to archive these.")
        return
    for object_type, rows in (("contacts", stale_contacts), ("companies", stale_companies)):
        for i in range(0, len(rows), 100):
            body = {"inputs": [{"id": r["id"]} for r in rows[i:i + 100]]}
            client._req("POST", f"/crm/v3/objects/{object_type}/batch/archive", body, ok=(200, 204))
    print(f"\narchived {len(stale_contacts)} contacts and {len(stale_companies)} companies")


if __name__ == "__main__":
    main()
