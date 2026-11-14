"""Thin HubSpot CRM client: custom properties, batch upserts, associations.

Auth: service key (or private app token) as Bearer token, read from HUBSPOT_TOKEN.
Idempotent: re-running updates the same records instead of creating duplicates.
  - contacts upsert on `email` (HubSpot's native unique property)
  - companies upsert on `rb_company_key` (custom unique property = normalized domain),
    because HubSpot's `domain` field is NOT unique and can't be used as an upsert key.
"""
import time

import requests

BASE = "https://api.hubapi.com"
BATCH = 100


class HubSpot:
    def __init__(self, token, dry_run=False, log=print):
        self.dry_run = dry_run
        self.log = log
        self.s = requests.Session()
        self.s.headers.update({"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
        self.calls = []  # every request body, kept for dry-run inspection

    def _req(self, method, path, body=None, ok=(200, 201, 207)):
        self.calls.append({"method": method, "path": path, "body": body})
        if self.dry_run:
            return None
        for attempt in range(5):
            r = self.s.request(method, BASE + path, json=body, timeout=30)
            if r.status_code == 429 or r.status_code >= 500:
                wait = 2 ** attempt
                self.log(f"  {r.status_code} on {path}, retrying in {wait}s")
                time.sleep(wait)
                continue
            if r.status_code not in ok:
                raise RuntimeError(f"{method} {path} -> {r.status_code}: {r.text[:500]}")
            return r.json() if r.content else None
        raise RuntimeError(f"{method} {path} kept failing after retries")

    def check_auth(self):
        if self.dry_run:
            return
        self._req("GET", "/crm/v3/objects/contacts?limit=1", ok=(200,))

    # ---------- schema ----------
    def ensure_property(self, object_type, spec):
        """Create a custom property; skip if it already exists (409)."""
        if self.dry_run:
            self.calls.append({"method": "POST", "path": f"/crm/v3/properties/{object_type}", "body": spec})
            return
        r = self.s.post(f"{BASE}/crm/v3/properties/{object_type}", json=spec, timeout=30)
        if r.status_code in (200, 201):
            self.log(f"  + created {object_type}.{spec['name']}")
        elif r.status_code == 409:
            pass
        else:
            raise RuntimeError(f"property {object_type}.{spec['name']} -> {r.status_code}: {r.text[:300]}")

    # ---------- records ----------
    def batch_upsert(self, object_type, id_property, rows):
        """rows: list of property dicts, each containing id_property. Returns {id_value: hubspot_id}."""
        ids = {}
        for i in range(0, len(rows), BATCH):
            chunk = rows[i:i + BATCH]
            body = {"inputs": [{"idProperty": id_property, "id": r[id_property], "properties": r} for r in chunk]}
            res = self._req("POST", f"/crm/v3/objects/{object_type}/batch/upsert", body)
            if res:
                for item in res.get("results", []):
                    ids[item["properties"].get(id_property)] = item["id"]
                for err in res.get("errors", []):
                    self.log(f"  ! {object_type} error: {err.get('message')}")
        return ids

    def associate_contacts_to_companies(self, pairs):
        """pairs: list of (contact_id, company_id). Uses the default (primary) association."""
        for i in range(0, len(pairs), BATCH):
            chunk = pairs[i:i + BATCH]
            body = {"inputs": [{"from": {"id": c}, "to": {"id": co}} for c, co in chunk]}
            self._req("POST", "/crm/v4/associations/contact/company/batch/associate/default", body)


# ---------- property definitions ----------
def _p(name, label, type_, field, group, **extra):
    return {"name": name, "label": label, "type": type_, "fieldType": field, "groupName": group, **extra}


BOOL_OPTS = {"options": [{"label": "Yes", "value": "true"}, {"label": "No", "value": "false"}]}

CONTACT_PROPERTIES = [
    _p("rb_source_systems", "RB Source Systems", "string", "text", "contactinformation"),
    _p("rb_alt_emails", "RB Alternate Emails", "string", "text", "contactinformation"),
    _p("rb_user_ids", "RB Product User IDs", "string", "text", "contactinformation"),
    _p("rb_plan", "RB Product Plan", "string", "text", "contactinformation"),
    _p("rb_signup_date", "RB Signup Date", "datetime", "date", "contactinformation"),
    _p("rb_first_touch", "RB First Touch Source", "string", "text", "contactinformation"),
    _p("rb_latest_form", "RB Latest Form", "string", "text", "contactinformation"),
    _p("rb_form_message", "RB Latest Form Message", "string", "textarea", "contactinformation"),
    _p("rb_personal_email_signup", "RB Signed Up With Personal Email", "bool", "booleancheckbox", "contactinformation", **BOOL_OPTS),
    _p("rb_last_active", "RB Last Active", "datetime", "date", "contactinformation"),
    _p("rb_events_60d", "RB Product Events (60d)", "number", "number", "contactinformation"),
    _p("rb_pipeline_runs", "RB Pipeline Runs", "number", "number", "contactinformation"),
    _p("rb_teammates_invited", "RB Teammates Invited", "number", "number", "contactinformation"),
    _p("rb_pricing_views", "RB Pricing Page Views", "number", "number", "contactinformation"),
    _p("rb_hit_rate_limit", "RB Hit Free Tier Limit", "bool", "booleancheckbox", "contactinformation", **BOOL_OPTS),
    _p("rb_integrations", "RB Connected Integrations", "string", "text", "contactinformation"),
]

COMPANY_PROPERTIES = [
    _p("rb_company_key", "RB Company Key", "string", "text", "companyinformation", hasUniqueValue=True),
    _p("rb_known_contacts", "RB Known Contacts", "number", "number", "companyinformation"),
    _p("rb_active_users", "RB Active Product Users", "number", "number", "companyinformation"),
    _p("rb_total_events", "RB Total Product Events", "number", "number", "companyinformation"),
    _p("rb_paid_users", "RB Paid / Trial Users", "number", "number", "companyinformation"),
    _p("rb_demo_requested", "RB Demo Requested", "bool", "booleancheckbox", "companyinformation", **BOOL_OPTS),
]
