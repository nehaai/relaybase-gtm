"""Field-level cleaning: emails, names, dates, phones, countries, company names, junk detection."""
import re
from datetime import datetime, timezone

PERSONAL_DOMAINS = {
    "gmail.com", "googlemail.com", "yahoo.com", "outlook.com", "hotmail.com", "icloud.com",
    "proton.me", "protonmail.com", "aol.com", "live.com", "me.com", "mail.ru",
}
DISPOSABLE_DOMAINS = {"tempmail.net", "mailinator.com", "10minutemail.com", "guerrillamail.com"}
INTERNAL_DOMAINS = {"relaybase.dev"}
TEST_DOMAINS = {"test.com", "asdf.com", "example.com"}
TEST_LOCALS = {"test", "asdf", "qa", "qa-bot", "a", "foo", "bar"}
SPAM_KEYWORDS = ("seo", "rank your site", "cheap", "buy ", "buy.", "crypto", "backlink", "leads cheap", "http")

COMPANY_SUFFIXES = r"\b(inc|incorporated|llc|ltd|limited|corp|corporation|co|company|group|gmbh|plc|n\.?a)\b\.?"

COUNTRY_MAP = {
    "us": "US", "usa": "US", "united states": "US", "united states of america": "US",
    "in": "IN", "india": "IN",
    "gb": "GB", "uk": "GB", "united kingdom": "GB", "england": "GB",
    "de": "DE", "germany": "DE",
    "ca": "CA", "canada": "CA",
    "sg": "SG", "singapore": "SG",
    "ru": "RU", "russia": "RU",
}

TITLE_MAP = {"vp eng": "VP Engineering", "swe ii": "Software Engineer II", "senior swe": "Senior Software Engineer"}

EMAIL_RE = re.compile(r"^[a-z0-9._%+\-]+@[a-z0-9.\-]+\.[a-z]{2,}$")


# ---------- email ----------
def clean_email(raw):
    """Return (canonical_email, raw_lowered) or (None, None) if invalid.
    Canonical: trimmed, lowercased, '+alias' stripped, gmail dots removed."""
    if not raw:
        return None, None
    e = raw.strip().lower()
    if not EMAIL_RE.match(e):
        return None, None
    local, dom = e.split("@", 1)
    local = local.split("+", 1)[0]
    if dom in ("gmail.com", "googlemail.com"):
        local = local.replace(".", "")
    return f"{local}@{dom}", e


def email_domain(email):
    return email.split("@", 1)[1] if email and "@" in email else None


def is_work_domain(dom):
    return bool(dom) and dom not in PERSONAL_DOMAINS and dom not in DISPOSABLE_DOMAINS \
        and dom not in INTERNAL_DOMAINS and dom not in TEST_DOMAINS


# ---------- names ----------
def _cap(token):
    # keep O'Brien / Müller sane
    return "'".join(p[:1].upper() + p[1:].lower() for p in token.split("'"))


def clean_name(first=None, last=None, full=None):
    """Return (first, last). Splits full_name if given. Title-cases. Empty -> None."""
    if full is not None:
        parts = [p for p in re.split(r"\s+", (full or "").strip()) if p]
        if not parts:
            return None, None
        first = parts[0]
        last = " ".join(parts[1:]) if len(parts) > 1 else None
    first = _cap(first.strip()) if first and first.strip() else None
    last = _cap(last.strip()) if last and last.strip() else None
    return first, last


# ---------- dates ----------
_DATE_FORMATS = ["%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d %H:%M:%S", "%m/%d/%Y %H:%M", "%d-%m-%Y", "%Y/%m/%d", "%Y-%m-%d"]


def parse_date(raw):
    """Parse any of the source formats into a UTC datetime. Returns None if unparseable."""
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    if s.isdigit() and len(s) >= 9:  # epoch seconds
        return datetime.fromtimestamp(int(s), tz=timezone.utc)
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


# ---------- phone / country / title / size ----------
def clean_phone(raw):
    digits = re.sub(r"\D", "", raw or "")
    if not digits or set(digits) == {"0"}:
        return None
    if len(digits) == 10:
        return "+1" + digits
    if len(digits) == 11 and digits.startswith("1"):
        return "+" + digits
    return None


def clean_country(raw):
    return COUNTRY_MAP.get((raw or "").strip().lower())


def clean_title(raw):
    t = (raw or "").strip()
    if not t:
        return None
    return TITLE_MAP.get(t.lower(), t)


def clean_company_size(raw):
    """Self-reported size -> (min, max) bucket label. Unreliable by nature; Clay overrides later."""
    s = (raw or "").replace(",", "").strip()
    if not s:
        return None
    if s.isdigit():
        n = int(s)
        for lo, hi, lbl in [(1, 10, "1-10"), (11, 50, "11-50"), (51, 200, "51-200"), (201, 1000, "201-1000"), (1001, 5000, "1001-5000")]:
            if lo <= n <= hi:
                return lbl
        return "5000+"
    return {"1000+": "1001+", "10005000": "1001-5000"}.get(s.replace("-", ""), s)


# ---------- company names ----------
def company_key(raw):
    """Normalize a company name or domain into a matching key: 'Acme Analytics Inc.' -> 'acmeanalytics'."""
    if not raw:
        return None
    s = raw.strip().lower()
    if s in ("", "n/a", "na", "none", "self", "freelance", "self employed", "test", "-"):
        return None
    s = re.sub(r"^https?://", "", s)
    s = re.sub(r"\.(com|io|ai|dev|co|org|net|app|so)$", "", s)
    s = re.sub(COMPANY_SUFFIXES, " ", s)
    s = re.sub(r"[^a-z0-9]", "", s)
    return s or None


def domain_root(domain):
    return company_key(domain)


# ---------- junk / spam ----------
def junk_reasons(email_raw, canon_email, first=None, company=None, message=None):
    """Return a list of reasons a record looks like test/spam/internal. Empty list = looks real."""
    reasons = []
    if not canon_email:
        reasons.append("invalid_email")
        return reasons
    local, dom = canon_email.split("@", 1)
    if dom in INTERNAL_DOMAINS:
        reasons.append("internal_domain")
    if dom in TEST_DOMAINS or local in TEST_LOCALS:
        reasons.append("test_account")
    if dom in DISPOSABLE_DOMAINS:
        reasons.append("disposable_domain")
    text = " ".join(filter(None, [local.replace(".", " "), first, company, message])).lower()
    hits = [k for k in SPAM_KEYWORDS if k in text]
    if hits:
        reasons.append("spam_keywords:" + ",".join(h.strip() for h in hits))
    if company and company.strip().lower().startswith("http"):
        reasons.append("url_as_company")
    return reasons
