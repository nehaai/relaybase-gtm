"""Identity resolution: turn raw source rows into deduped People and Companies.

Rules (applied in order, all via union-find over source records):
  R1  same canonical email                         -> same person   (case, whitespace, +alias, gmail dots)
  R2  same work domain + email local within 1 edit  -> same person   (typos), unless last names conflict
  R3  same first+last name + same resolved company  -> same person   (links gmail signup <-> work-email form fill)

Company resolution:
  C1  work email domain is the company key (strongest signal)
  C2  else match the free-text company name against aliases learned from C1 records
  C3  else unique prefix match on alias keys ("Vertex" -> vertexcloud.io)
"""
import csv
import json
from collections import Counter, defaultdict

from . import normalize as n


class UnionFind:
    def __init__(self):
        self.p = {}

    def find(self, x):
        self.p.setdefault(x, x)
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[max(ra, rb)] = min(ra, rb)


def edit_distance_le1(a, b):
    if a == b:
        return True
    if abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        diffs = [i for i in range(len(a)) if a[i] != b[i]]
        if len(diffs) == 1:
            return True
        # adjacent transposition
        return len(diffs) == 2 and diffs[1] == diffs[0] + 1 and a[diffs[0]] == b[diffs[1]] and a[diffs[1]] == b[diffs[0]]
    s, l = (a, b) if len(a) < len(b) else (b, a)
    i = j = 0
    skipped = False
    while i < len(s) and j < len(l):
        if s[i] != l[j]:
            if skipped:
                return False
            skipped = True
            j += 1
        else:
            i += 1
            j += 1
    return True


# ---------- load + normalize ----------
def load_records(data_dir):
    """Read signups + form fills into one normalized record list. Each record keeps its source id."""
    recs = []
    with open(f"{data_dir}/signups.csv", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            canon, raw = n.clean_email(r["email"])
            first, last = n.clean_name(full=r["full_name"])
            recs.append({
                "rid": f"signups:{r['signup_id']}", "source": "signups", "source_id": r["signup_id"],
                "user_id": r["user_id"], "email": canon, "email_raw": r["email"],
                "first": first, "last": last, "title": None, "phone": None, "country": None,
                "company_raw": r["company"].strip() or None, "company_size_reported": None,
                "plan": (r["plan"] or "").strip().lower() or None,
                "ts": n.parse_date(r["created_at"]), "utm": (r["utm_source"] or "").strip().lower() or None,
                "form_name": None, "message": None,
                "junk": n.junk_reasons(r["email"], canon, first, r["company"]),
            })
    with open(f"{data_dir}/form_fills.csv", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            canon, raw = n.clean_email(r["email"])
            first, last = n.clean_name(first=r["first_name"], last=r["last_name"])
            recs.append({
                "rid": f"form_fills:{r['submission_id']}", "source": "form_fills", "source_id": r["submission_id"],
                "user_id": None, "email": canon, "email_raw": r["email"],
                "first": first, "last": last, "title": n.clean_title(r["job_title"]),
                "phone": n.clean_phone(r["phone"]), "country": n.clean_country(r["country"]),
                "company_raw": r["company_name"].strip() or None,
                "company_size_reported": n.clean_company_size(r["company_size"]),
                "plan": None, "ts": n.parse_date(r["submitted_at"]),
                "utm": (r["utm_campaign"] or "").strip().lower().replace("_", "-") or None,
                "form_name": (r["form_name"] or "").strip().title() or None, "message": r["message"].strip() or None,
                "junk": n.junk_reasons(r["email"], canon, first, r["company_name"], r["message"]),
            })
    return recs


# ---------- companies ----------
def build_company_index(recs):
    """Learn company aliases from records that have a work-domain email."""
    alias_to_domain = {}
    names_by_domain = defaultdict(Counter)
    for r in recs:
        if r["junk"]:
            continue
        dom = n.email_domain(r["email"])
        if not n.is_work_domain(dom):
            continue
        alias_to_domain.setdefault(n.domain_root(dom), dom)
        if r["company_raw"]:
            names_by_domain[dom][r["company_raw"]] += 1
            k = n.company_key(r["company_raw"])
            if k:
                alias_to_domain.setdefault(k, dom)
    return alias_to_domain, names_by_domain


def match_company_name(raw, alias_to_domain):
    k = n.company_key(raw)
    if not k:
        return None, None
    if k in alias_to_domain:
        return alias_to_domain[k], "C2_alias"
    if len(k) >= 4:
        doms = {d for a, d in alias_to_domain.items() if a.startswith(k) or k.startswith(a)}
        if len(doms) == 1:
            return doms.pop(), "C3_prefix"
    return None, None


def display_company_name(domain, names_counter):
    """Pick a human display name: most common variant by key, prefer properly cased, non-domain strings."""
    import re
    looks_like_domain = re.compile(r"^[\w\-]+\.[a-z]{2,}$", re.I)
    cands = [nm.strip() for nm in (names_counter or {}) if nm.strip() and not looks_like_domain.match(nm.strip())]
    if not cands:
        return n.domain_root(domain).title()
    # Prefer human-typed casing (mixed case), then the most complete name. Strip legal suffixes for display.
    def score(nm):
        mixed = not nm.isupper() and not nm.islower()
        return (mixed, len(nm.split()), names_counter.get(nm, 0))
    best = max(cands, key=score)
    best = re.sub(r",?\s+(Inc\.?|LLC|Ltd\.?|Corp\.?|Co\.?|N\.A\.)$", "", best, flags=re.I)
    return best if not best.islower() else best.title()


# ---------- people ----------
def resolve(recs):
    alias_to_domain, names_by_domain = build_company_index(recs)

    # company per record
    for r in recs:
        dom = n.email_domain(r["email"])
        if r["junk"]:
            r["company_domain"], r["company_rule"] = None, None
        elif n.is_work_domain(dom):
            r["company_domain"], r["company_rule"] = dom, "C1_email_domain"
        else:
            r["company_domain"], r["company_rule"] = match_company_name(r["company_raw"], alias_to_domain)

    uf = UnionFind()
    good = [r for r in recs if not r["junk"]]
    for r in good:
        uf.find(r["rid"])
    merge_log = []

    # R1: canonical email
    by_email = defaultdict(list)
    for r in good:
        by_email[r["email"]].append(r)
    for email, rs in by_email.items():
        for x in rs[1:]:
            uf.union(rs[0]["rid"], x["rid"])

    # R2: typo'd local part, same work domain, names don't conflict
    by_dom = defaultdict(list)
    for email, rs in by_email.items():
        dom = n.email_domain(email)
        if n.is_work_domain(dom):
            by_dom[dom].append((email.split("@")[0], rs[0]))
    for dom, items in by_dom.items():
        for i in range(len(items)):
            for j in range(i + 1, len(items)):
                (la, ra), (lb, rb) = items[i], items[j]
                # a different first letter (jsmith vs msmith) is a different person's initial, not a typo
                if la[0] != lb[0]:
                    continue
                if min(len(la), len(lb)) >= 5 and edit_distance_le1(la, lb) and not names_conflict(ra, rb):
                    uf.union(ra["rid"], rb["rid"])
                    merge_log.append(("R2_email_typo", ra["email"], rb["email"]))

    # R3: full name + company
    by_name_co = defaultdict(list)
    for r in good:
        if r["first"] and r["last"] and r["company_domain"]:
            by_name_co[(r["first"].lower(), r["last"].lower(), r["company_domain"])].append(r)
    for key, rs in by_name_co.items():
        for x in rs[1:]:
            if uf.find(rs[0]["rid"]) != uf.find(x["rid"]):
                merge_log.append(("R3_name_company", rs[0]["email"], x["email"]))
            uf.union(rs[0]["rid"], x["rid"])

    clusters = defaultdict(list)
    for r in good:
        clusters[uf.find(r["rid"])].append(r)

    people = [build_person(rs) for rs in clusters.values()]
    companies = build_companies(people, names_by_domain)
    return people, companies, merge_log


def names_conflict(a, b):
    if a["last"] and b["last"] and a["last"].lower() != b["last"].lower():
        return not edit_distance_le1(a["last"].lower(), b["last"].lower())
    if a["first"] and b["first"] and a["first"].lower() != b["first"].lower():
        return not edit_distance_le1(a["first"].lower(), b["first"].lower())
    return False


def _mode(values):
    vals = [v for v in values if v]
    return Counter(vals).most_common(1)[0][0] if vals else None


def build_person(rs):
    rs = sorted(rs, key=lambda r: (r["ts"] is None, r["ts"]))
    emails = [r["email"] for r in rs]
    work = [e for e in emails if n.is_work_domain(n.email_domain(e))]
    primary = _mode(work) or _mode(emails)
    # prefer the longest well-formed name we saw (a full name beats a first name only)
    named = [r for r in rs if r["first"]]
    best = max(named, key=lambda r: (bool(r["last"]), len((r["first"] or "") + (r["last"] or ""))), default=None)
    signups = [r for r in rs if r["source"] == "signups"]
    forms = [r for r in rs if r["source"] == "form_fills"]
    return {
        "email": primary,
        "alt_emails": sorted(set(emails) - {primary}),
        "first": best["first"] if best else None,
        "last": best["last"] if best else None,
        "title": _mode(r["title"] for r in rs),
        "phone": _mode(r["phone"] for r in rs),
        "country": _mode(r["country"] for r in rs),
        "company_domain": _mode(r["company_domain"] for r in rs),
        "user_ids": sorted({r["user_id"] for r in signups}),
        "plan": signups[-1]["plan"] if signups else None,
        "signup_date": signups[0]["ts"] if signups else None,
        "first_seen": rs[0]["ts"],
        "first_touch": _mode([rs[0]["utm"]]) if rs[0]["utm"] else None,
        "sources": sorted({r["source"] for r in rs}),
        "forms": [r["form_name"] for r in forms],
        "latest_form": forms[-1]["form_name"] if forms else None,
        "latest_form_message": next((r["message"] for r in reversed(forms) if r["message"]), None),
        "personal_email_signup": bool(signups) and not n.is_work_domain(n.email_domain(signups[0]["email"])),
        "rids": [r["rid"] for r in rs],
        "company_size_reported": _mode(r["company_size_reported"] for r in rs),
    }


def build_companies(people, names_by_domain):
    comps = {}
    for p in people:
        d = p["company_domain"]
        if not d:
            continue
        c = comps.setdefault(d, {"domain": d, "name": display_company_name(d, names_by_domain.get(d)), "contacts": []})
        c["contacts"].append(p["email"])
    return list(comps.values())


# ---------- usage ----------
def attach_usage(people, events_path):
    by_uid, by_email = {}, {}
    for p in people:
        for u in p["user_ids"]:
            by_uid[u] = p
        for e in [p["email"]] + p["alt_emails"]:
            by_email[e] = p
        p["usage"] = Counter()
        p["last_active"] = None
        p["integrations"] = set()

    stats = Counter()
    with open(events_path, encoding="utf-8") as f:
        for line in f:
            ev = json.loads(line)
            if not ev.get("event"):
                stats["malformed"] += 1
                continue
            p = by_uid.get(ev.get("user_id"))
            if p:
                stats["matched_user_id"] += 1
            else:
                canon, _ = n.clean_email(ev.get("email"))
                p = by_email.get(canon)
                stats["matched_email" if p else "orphaned"] += 1
            if not p:
                continue
            p["usage"][ev["event"]] += 1
            ts = n.parse_date(ev.get("ts"))
            if ts and (p["last_active"] is None or ts > p["last_active"]):
                p["last_active"] = ts
            integ = (ev.get("properties") or {}).get("integration")
            if integ:
                p["integrations"].add(integ.lower())
    return stats
