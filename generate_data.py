"""
Messy GTM source data generator for "Relaybase" (fake PLG dev-tool company).

Outputs (in ./data):
  signups.csv          - product signups (product DB export)
  form_fills.csv       - marketing website forms (demo requests, contact us, webinar)
  usage_events.jsonl   - product usage events
  _answer_key.csv      - ground truth: which records belong to which real person/company
                         (do NOT feed into the pipeline; use it to grade dedupe/matching)

Deliberate mess:
  - same person across sources with different email casing / whitespace / plus-aliases
  - personal emails (gmail etc.) for people who actually work at a target company
  - company name variants: "Acme Inc", "ACME", "acme.io", "Acme Corporation "
  - typos in emails and names, missing fields, mixed date formats
  - inconsistent phone formats, country as code vs name
  - duplicate signups, test accounts, bot/spam form fills
  - usage events keyed by user_id (sometimes missing), some orphaned
"""
import csv
import json
import os
import random
from datetime import datetime, timedelta

random.seed(42)
OUT = "data"
os.makedirs(OUT, exist_ok=True)

NOW = datetime(2026, 11, 4, 12, 0, 0)

COMPANIES = [
    # (canonical name, domain, size, industry, variants)
    ("Acme Analytics", "acmeanalytics.com", 420, "SaaS", ["Acme Analytics Inc.", "ACME analytics", "acmeanalytics.com", "Acme"]),
    ("Northwind Logistics", "northwind.io", 1800, "Logistics", ["Northwind", "northwind logistics llc", "NorthWind Logistics", "Northwind Inc"]),
    ("Brightpath Health", "brightpathhealth.com", 950, "Healthcare", ["BrightPath", "Bright Path Health", "brightpath health inc"]),
    ("Kestrel AI", "kestrel.ai", 60, "AI/ML", ["kestrel", "Kestrel AI Labs", "KESTREL.AI"]),
    ("Lumen Finance", "lumenfi.com", 300, "Fintech", ["Lumen", "LumenFi", "Lumen Finance Corp", "lumen fin"]),
    ("Orbital Retail", "orbitalretail.com", 5200, "Retail", ["Orbital", "Orbital Retail Group", "orbital-retail"]),
    ("Paperplane", "paperplane.dev", 25, "Dev Tools", ["PaperPlane", "paper plane", "Paperplane Inc"]),
    ("Quanta Robotics", "quantarobotics.com", 700, "Hardware", ["Quanta", "Quanta Robotics Inc.", "quanta robotics"]),
    ("Sable Security", "sablesec.com", 150, "Security", ["Sable", "SableSec", "Sable Security, Inc."]),
    ("Tidewater Media", "tidewatermedia.com", 80, "Media", ["Tidewater", "TideWater Media", "tidewater media co"]),
    ("Vertex Cloud", "vertexcloud.io", 2600, "Cloud", ["Vertex", "VertexCloud", "Vertex Cloud Inc"]),
    ("Willow Education", "willowedu.org", 120, "EdTech", ["Willow", "Willow Edu", "willow education"]),
    ("Zephyr Energy", "zephyrenergy.com", 3100, "Energy", ["Zephyr", "Zephyr Energy Co.", "ZEPHYR ENERGY"]),
    ("Granite Insurance", "graniteins.com", 4400, "Insurance", ["Granite", "Granite Insurance Group", "granite ins"]),
    ("Helix Bio", "helixbio.com", 210, "Biotech", ["Helix", "Helix Biosciences", "helix bio inc"]),
    ("Cobalt Payments", "cobaltpay.com", 540, "Fintech", ["Cobalt", "CobaltPay", "Cobalt Payments Ltd"]),
    ("Mosaic Labs", "mosaiclabs.co", 35, "AI/ML", ["Mosaic", "mosaic labs", "MosaicLabs"]),
    ("Riverstone Bank", "riverstonebank.com", 8000, "Banking", ["Riverstone", "Riverstone Bank N.A.", "riverstone"]),
]

FIRST = ["Priya", "James", "Aisha", "Daniel", "Mei", "Carlos", "Sofia", "Liam", "Fatima", "Noah",
         "Ananya", "Ethan", "Grace", "Omar", "Hannah", "Ravi", "Chloe", "Marcus", "Yuki", "Elena",
         "Samuel", "Zara", "Lucas", "Ines", "Kenji", "Olivia", "Arjun", "Maya", "Diego", "Nora"]
LAST = ["Sharma", "Okafor", "Nguyen", "Rodriguez", "Chen", "Patel", "Kim", "Johnson", "Haddad", "Silva",
        "Iyer", "Müller", "O'Brien", "Kowalski", "Tanaka", "Garcia", "Singh", "Rossi", "Ahmed", "Becker"]
TITLES = ["VP Engineering", "Head of Data", "Software Engineer", "Senior SWE", "CTO", "Data Engineer",
          "Engineering Manager", "Staff Engineer", "Director of Platform", "ML Engineer", "Founder",
          "Product Manager", "DevOps Lead", "vp eng", "SWE II", "Analytics Lead", ""]
PERSONAL = ["gmail.com", "yahoo.com", "outlook.com", "icloud.com", "hotmail.com", "proton.me"]
COUNTRIES = [("US", "United States"), ("US", "USA"), ("US", "united states"), ("IN", "India"),
             ("GB", "UK"), ("GB", "United Kingdom"), ("DE", "Germany"), ("CA", "Canada"), ("SG", "Singapore")]
UTM = ["google", "linkedin", "twitter", "hn", "newsletter", "partner", "", "", "(direct)", "Google", "LinkedIn"]
PLANS = ["free", "free", "free", "Free", "pro_trial", "pro", "team", "FREE"]


def ts_formats(dt):
    """Return dt in one of several inconsistent formats."""
    fmt = random.choice([
        "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d %H:%M:%S", "%m/%d/%Y %H:%M", "%d-%m-%Y", "%Y/%m/%d", "epoch",
    ])
    if fmt == "epoch":
        return str(int(dt.timestamp()))
    return dt.strftime(fmt)


def rand_dt(days_back=120):
    return NOW - timedelta(days=random.uniform(0, days_back), seconds=random.randint(0, 86400))


def phone():
    n = [random.randint(0, 9) for _ in range(10)]
    s = "".join(map(str, n))
    return random.choice([
        f"({s[:3]}) {s[3:6]}-{s[6:]}", f"+1{s}", f"{s[:3]}.{s[3:6]}.{s[6:]}", f"+1 {s[:3]} {s[3:6]} {s[6:]}",
        s, "", "", "n/a", "0000000000",
    ])


def typo(s):
    if len(s) < 4:
        return s
    i = random.randint(1, len(s) - 2)
    op = random.choice(["swap", "drop", "dup"])
    if op == "swap":
        return s[:i] + s[i + 1] + s[i] + s[i + 2:]
    if op == "drop":
        return s[:i] + s[i + 1:]
    return s[:i] + s[i] + s[i:]


def mess_email(email):
    local, dom = email.split("@")
    r = random.random()
    if r < 0.15:
        return email.upper() if random.random() < 0.3 else email.title()
    if r < 0.25:
        return f"  {email} "
    if r < 0.33:
        return f"{local}+{random.choice(['relay', 'test', 'work', 'signup'])}@{dom}"
    if r < 0.38:
        return f"{typo(local)}@{dom}"
    return email


# ---------- build ground-truth people ----------
people = []
pid = 0
for cname, dom, size, ind, variants in COMPANIES:
    n = max(2, min(14, int(size ** 0.33) + random.randint(-2, 2)))
    for _ in range(n):
        pid += 1
        f, l = random.choice(FIRST), random.choice(LAST)
        local = random.choice([f"{f}.{l}", f"{f[0]}{l}", f"{f}", f"{f}{l[0]}", f"{f}_{l}"]).lower()
        local = local.replace("'", "").replace("ü", "u")
        work_email = f"{local}@{dom}"
        uses_personal = random.random() < 0.18
        personal_email = f"{f.lower()}{l.lower().replace(chr(39), '')}{random.randint(1, 99)}@{random.choice(PERSONAL)}".replace("ü", "u")
        people.append({
            "person_id": f"P{pid:04d}", "first": f, "last": l, "title": random.choice(TITLES),
            "company": cname, "domain": dom, "variants": variants,
            "work_email": work_email, "personal_email": personal_email if uses_personal else "",
            "signup_email": personal_email if uses_personal else work_email,
            "country": random.choice(COUNTRIES),
        })

# a few unaffiliated / solo devs
for _ in range(12):
    pid += 1
    f, l = random.choice(FIRST), random.choice(LAST)
    pe = f"{f.lower()}.{l.lower().replace(chr(39), '')}{random.randint(1, 999)}@{random.choice(PERSONAL)}".replace("ü", "u")
    people.append({
        "person_id": f"P{pid:04d}", "first": f, "last": l, "title": random.choice(["Founder", "Freelancer", "Student", ""]),
        "company": "", "domain": "", "variants": [""], "work_email": "", "personal_email": pe,
        "signup_email": pe, "country": random.choice(COUNTRIES),
    })

answer_key = []

# ---------- signups.csv ----------
signups = []
user_ids = {}
sid = 1000
for p in people:
    if random.random() < 0.72:
        sid += 1
        uid = f"usr_{random.getrandbits(40):010x}"
        user_ids[p["person_id"]] = uid
        name = f"{p['first']} {p['last']}"
        name = random.choice([name, name, name.lower(), p["first"], "", name.upper(), typo(name)])
        comp = random.choice(p["variants"] + [p["company"]]) if p["company"] else random.choice(["", "", "self", "N/A", "Freelance"])
        if random.random() < 0.15:
            comp = ""
        created = rand_dt()
        row = {
            "signup_id": sid, "user_id": uid, "email": mess_email(p["signup_email"]), "full_name": name,
            "company": comp, "plan": random.choice(PLANS), "created_at": ts_formats(created),
            "utm_source": random.choice(UTM), "referrer": random.choice(["", "", "https://news.ycombinator.com", "google.com", "https://www.linkedin.com/"]),
        }
        signups.append(row)
        answer_key.append({"source": "signups", "record_id": sid, "person_id": p["person_id"], "company": p["company"], "domain": p["domain"]})
        # duplicate signup (re-registered, different casing / email variant)
        if random.random() < 0.08:
            sid += 1
            dup = dict(row, signup_id=sid, user_id=f"usr_{random.getrandbits(40):010x}",
                       email=mess_email(p["work_email"] or p["signup_email"]),
                       created_at=ts_formats(created + timedelta(days=random.randint(1, 30))))
            signups.append(dup)
            answer_key.append({"source": "signups", "record_id": sid, "person_id": p["person_id"], "company": p["company"], "domain": p["domain"]})

# test accounts / junk
for e in ["test@test.com", "asdf@asdf.com", "neha+test1@relaybase.dev", "qa-bot@relaybase.dev", "a@b.c"]:
    sid += 1
    signups.append({"signup_id": sid, "user_id": f"usr_{random.getrandbits(40):010x}", "email": e, "full_name": random.choice(["test", "", "QA"]),
                    "company": random.choice(["test", "", "Relaybase"]), "plan": "free", "created_at": ts_formats(rand_dt()),
                    "utm_source": "", "referrer": ""})
    answer_key.append({"source": "signups", "record_id": sid, "person_id": "JUNK", "company": "", "domain": ""})

random.shuffle(signups)

# ---------- form_fills.csv ----------
forms = []
fid = 5000
FORM_TYPES = ["Demo Request", "Contact Sales", "Webinar: Scaling Pipelines", "Pricing Page", "demo request", "Whitepaper Download"]
for p in people:
    if p["company"] and random.random() < 0.35 or (not p["company"] and random.random() < 0.1):
        for _ in range(random.choice([1, 1, 1, 2])):
            fid += 1
            email = p["work_email"] or p["personal_email"]
            if random.random() < 0.1 and p["personal_email"]:
                email = p["personal_email"]
            cc = p["country"]
            forms.append({
                "submission_id": fid, "submitted_at": ts_formats(rand_dt(90)),
                "form_name": random.choice(FORM_TYPES),
                "first_name": random.choice([p["first"], p["first"].lower(), p["first"].upper(), f" {p['first']}"]),
                "last_name": random.choice([p["last"], p["last"], "", p["last"].lower()]),
                "email": mess_email(email),
                "company_name": random.choice(p["variants"] + [p["company"], ""]) if p["company"] else random.choice(["", "Self employed"]),
                "job_title": random.choice([p["title"], p["title"], ""]),
                "phone": phone(),
                "country": random.choice([cc[0], cc[1]]),
                "company_size": random.choice(["", "1-10", "11-50", "51-200", "201-1000", "1000+", "1,000-5,000", str(random.randint(10, 9000))]),
                "message": random.choice(["", "", "Interested in pricing for our team", "Need SSO + SOC2 docs", "we're evaluating vendors for Q1",
                                          "Can we get a demo next week?", "Using the free plan, want to talk about enterprise", "pls call"]),
                "utm_campaign": random.choice(["", "q4-webinar", "linkedin-abm-tier1", "brand", "Q4_Webinar", "retargeting"]),
            })
            answer_key.append({"source": "form_fills", "record_id": fid, "person_id": p["person_id"], "company": p["company"], "domain": p["domain"]})

# spam / bots
for i in range(6):
    fid += 1
    forms.append({
        "submission_id": fid, "submitted_at": ts_formats(rand_dt(30)), "form_name": "Contact Sales",
        "first_name": random.choice(["SEO", "John", "asdkjh", "Crypto"]), "last_name": random.choice(["Services", "", "Bot"]),
        "email": random.choice(["seo.rank.boost@mail.ru", "x9k2@tempmail.net", "buy.links@gmail.com", "info@cheapleads.biz"]),
        "company_name": random.choice(["Best SEO Agency", "", "http://cheapleads.biz"]), "job_title": "",
        "phone": phone(), "country": random.choice(["", "RU", "N/A"]), "company_size": "",
        "message": random.choice(["We can rank your site #1 on Google!!!", "Buy 10k leads cheap http://cheapleads.biz", "hello"]),
        "utm_campaign": "",
    })
    answer_key.append({"source": "form_fills", "record_id": fid, "person_id": "SPAM", "company": "", "domain": ""})

random.shuffle(forms)

# ---------- usage_events.jsonl ----------
EVENTS = ["login", "project_created", "api_key_created", "pipeline_run", "pipeline_run", "pipeline_run",
          "invited_teammate", "viewed_pricing", "viewed_pricing", "connected_integration", "hit_rate_limit",
          "exported_data", "sso_settings_viewed"]
events = []
for p in people:
    uid = user_ids.get(p["person_id"])
    if not uid:
        continue
    # activity level varies: many dormant, a few power users
    level = random.choices([0, 3, 15, 60], weights=[0.3, 0.35, 0.25, 0.1])[0]
    for _ in range(level + random.randint(0, 3)):
        ev = random.choice(EVENTS)
        e = {"event": ev, "ts": ts_formats(rand_dt(60))}
        # sometimes keyed by user_id, sometimes email, sometimes both, sometimes neither
        r = random.random()
        if r < 0.75:
            e["user_id"] = uid
        elif r < 0.92:
            e["email"] = mess_email(p["signup_email"])
        elif r < 0.97:
            e["user_id"] = uid
            e["email"] = p["signup_email"]
        props = {}
        if ev == "pipeline_run":
            props = {"rows": random.choice([10, 200, 5000, 120000, None]), "status": random.choice(["success", "success", "failed"])}
        elif ev == "invited_teammate":
            props = {"invitee_domain": p["domain"] or random.choice(PERSONAL)}
        elif ev == "connected_integration":
            props = {"integration": random.choice(["snowflake", "postgres", "bigquery", "s3", "Snowflake"])}
        elif ev == "hit_rate_limit":
            props = {"limit": "free_tier_1000_runs"}
        if props:
            e["properties"] = props
        events.append(e)

# orphaned events from deleted/unknown users + malformed
for _ in range(25):
    events.append({"event": random.choice(EVENTS), "ts": ts_formats(rand_dt(60)), "user_id": f"usr_{random.getrandbits(40):010x}"})
for _ in range(4):
    events.append({"event": "", "ts": "", "user_id": None})

random.shuffle(events)


def write_csv(path, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


write_csv(f"{OUT}/signups.csv", signups)
write_csv(f"{OUT}/form_fills.csv", forms)
with open(f"{OUT}/usage_events.jsonl", "w", encoding="utf-8") as f:
    for e in events:
        f.write(json.dumps(e) + "\n")
write_csv(f"{OUT}/_answer_key.csv", answer_key)

real_people = len([p for p in people])
print(f"people (ground truth): {real_people}")
print(f"companies: {len(COMPANIES)}")
print(f"signups: {len(signups)}  form_fills: {len(forms)}  usage_events: {len(events)}")
