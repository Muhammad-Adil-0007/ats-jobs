#!/usr/bin/env python3
"""
ats_jobs.py - Poll company ATS APIs *and* scrape HTML career pages for new
Data Science internship / working student jobs. Both sources feed one combined
"new jobs since last run" list.

Usage:
    pip install requests beautifulsoup4
    python ats_jobs.py            # show new jobs since last run
    python ats_jobs.py --all      # show all matching jobs (ignore seen-state)
    python ats_jobs.py --reset    # forget seen jobs

Supported types:
    API : workday, greenhouse, lever, smartrecruiters, ashby, personio
    HTML: successfactors (SAP career sites, e.g. jobs.siemens.com), html (generic, CSS selectors)
Add / fix companies in COMPANIES below. See "How to find the right config" at the bottom.
"""

import argparse
import json
import sys
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# CONFIG
# ---------------------------------------------------------------------------

# BROAD mode: any student / intern role in Germany is reported; data-related ones are marked with [*].
# STRICT mode: only roles whose title contains one of KEYWORDS.
STRICT = False

KEYWORDS = ["data", "machine learning", "ml ", "ml/", "ai ", "ai/", "artificial intelligence", "analytics", "analyst",
            "science", "scientist", "deep learning", "nlp", "llm", "computer vision", "statistic", "quant",
            "business intelligence", "bi ", "mlops", "research", "python", "software", "engineer", "developer",
            "backend", "cloud", "algorithm", "forecast", "modeling", "modelling", "optimization", "automation"]
ROLE_WORDS = ["werkstudent", "working student", "praktikum", "praktikant", "intern", "internship", "student",
              "studentische", "hilfskraft", "thesis", "masterarbeit", "bachelorarbeit", "abschlussarbeit",
              "trainee", "graduate", "entry level", "junior"]
LOCATION_WORDS = ["germany", "deutschland", " de", ", de", "nuremberg", "nürnberg", "erlangen", "herzogenaurach",
                  "fürth", "munich", "münchen", "berlin", "stuttgart", "frankfurt", "hamburg", "cologne", "köln",
                  "düsseldorf", "ingolstadt", "walldorf", "heidelberg", "karlsruhe", "remote"]
                  # set to [] to accept every location

STATE_FILE = Path(__file__).with_name("seen_jobs.json")
TIMEOUT = 20
USER_AGENT = "Mozilla/5.0 (job-alert-script; personal use)"

# NOTE: tenant / board names below are best-effort. If a company returns 0 jobs or an error,
# verify its config using the instructions at the bottom of this file.
COMPANIES = [
    # --- Workday: {"type": "workday", "host": "<tenant>.wdN.myworkdayjobs.com", "tenant": "...", "site": "...", "query": "student"}
    #     "query" is optional; it is only used to keep large boards (thousands of jobs) manageable.
    {"name": "adidas",              "type": "workday", "host": "adidas.wd3.myworkdayjobs.com",        "tenant": "adidas",        "site": "adidas_careers", "query": "student"},
    {"name": "Puma",                "type": "workday", "host": "puma.wd3.myworkdayjobs.com",          "tenant": "puma",          "site": "puma_careers", "query": "student"},
    {"name": "Siemens Healthineers","type": "workday", "host": "siemenshealthineers.wd3.myworkdayjobs.com", "tenant": "siemenshealthineers", "site": "careers"},
    {"name": "Infineon",            "type": "workday", "host": "infineon.wd3.myworkdayjobs.com",      "tenant": "infineon",      "site": "External", "query": "student"},
    {"name": "Allianz",             "type": "workday", "host": "allianz.wd3.myworkdayjobs.com",       "tenant": "allianz",       "site": "External", "query": "student"},
    {"name": "Brainlab",            "type": "workday", "host": "brainlab.wd3.myworkdayjobs.com",      "tenant": "brainlab",      "site": "Brainlab", "query": "student"},

    # --- Greenhouse: {"type": "greenhouse", "board": "<board token>"}
    {"name": "Celonis",             "type": "greenhouse", "board": "celonis"},
    {"name": "Personio",            "type": "greenhouse", "board": "personio"},
    {"name": "Delivery Hero",       "type": "greenhouse", "board": "deliveryhero"},
    {"name": "Scout24",             "type": "greenhouse", "board": "scout24"},

    # --- Lever: {"type": "lever", "company": "<slug>"}
    # {"name": "Example",           "type": "lever", "company": "example"},

    # --- SmartRecruiters: {"type": "smartrecruiters", "company": "<company id>"}
    {"name": "SUSE",                "type": "smartrecruiters", "company": "SUSE"},
    {"name": "Check24",             "type": "smartrecruiters", "company": "CHECK24"},

    # --- SAP SuccessFactors career sites (HTML scraping)
    #     {"type": "successfactors", "base": "https://jobs.<company>.com", "query": "student"}
    {"name": "Siemens",             "type": "successfactors", "base": "https://jobs.siemens.com",         "query": "student"},
    {"name": "Schaeffler",          "type": "successfactors", "base": "https://jobs.schaeffler.com",      "query": "student"},
    {"name": "Bosch",               "type": "successfactors", "base": "https://jobs.bosch.com",           "query": "student"},
    {"name": "Continental",         "type": "successfactors", "base": "https://jobs.continental.com",     "query": "student"},
    {"name": "Audi",                "type": "successfactors", "base": "https://jobs.audi.com",            "query": "student"},
    {"name": "Deutsche Bahn",       "type": "successfactors", "base": "https://karriere.deutschebahn.com","query": "student"},
    {"name": "SAP",                 "type": "successfactors", "base": "https://jobs.sap.com",             "query": "student"},

    # =======================================================================
    # STARTUPS / SCALE-UPS (Germany). ATS names are best-effort - verify if a
    # company errors or returns 0 jobs (see notes at the bottom).
    # =======================================================================
    # --- Greenhouse
    {"name": "GetYourGuide",        "type": "greenhouse", "board": "getyourguide"},
    {"name": "HelloFresh",          "type": "greenhouse", "board": "hellofresh"},
    {"name": "N26",                 "type": "greenhouse", "board": "n26"},
    {"name": "Trade Republic",      "type": "greenhouse", "board": "traderepublic"},
    {"name": "Contentful",          "type": "greenhouse", "board": "contentful"},
    {"name": "DeepL",               "type": "greenhouse", "board": "deepl"},
    {"name": "Helsing",             "type": "greenhouse", "board": "helsing"},
    {"name": "Scalable Capital",    "type": "greenhouse", "board": "scalablecapital"},
    {"name": "Taxfix",              "type": "greenhouse", "board": "taxfix"},
    {"name": "Babbel",              "type": "greenhouse", "board": "babbel"},
    {"name": "Raisin",              "type": "greenhouse", "board": "raisin"},
    {"name": "Sennder",             "type": "greenhouse", "board": "sennder"},
    {"name": "Forto",               "type": "greenhouse", "board": "forto"},
    {"name": "Solaris",             "type": "greenhouse", "board": "solarisbank"},
    {"name": "Konux",               "type": "greenhouse", "board": "konux"},
    {"name": "Wefox",               "type": "greenhouse", "board": "wefox"},
    {"name": "Holidu",              "type": "greenhouse", "board": "holidu"},
    {"name": "Enpal",               "type": "greenhouse", "board": "enpal"},
    {"name": "Aleph Alpha",         "type": "greenhouse", "board": "alephalpha"},

    # --- Ashby: {"type": "ashby", "board": "<company slug>"}
    {"name": "QuantCo",             "type": "ashby", "board": "quantco"},
    {"name": "Parloa",              "type": "ashby", "board": "parloa"},
    {"name": "Black Forest Labs",   "type": "ashby", "board": "blackforestlabs"},
    {"name": "Merantix Momentum",   "type": "ashby", "board": "merantix"},

    # --- Personio ATS (very common with German startups):
    #     {"type": "personio", "company": "<subdomain of *.jobs.personio.de>"}
    {"name": "FINN",                "type": "personio", "company": "finn"},
    {"name": "Isar Aerospace",      "type": "personio", "company": "isaraerospace"},
    {"name": "Agile Robots",        "type": "personio", "company": "agile-robots"},
    {"name": "Freeletics",          "type": "personio", "company": "freeletics"},
    {"name": "Limehome",            "type": "personio", "company": "limehome"},
    {"name": "Paessler",            "type": "personio", "company": "paessler"},      # Nuremberg
    {"name": "tado",                "type": "personio", "company": "tado"},

    # --- SmartRecruiters
    {"name": "Flix",                "type": "smartrecruiters", "company": "Flix"},
    {"name": "Zalando",             "type": "smartrecruiters", "company": "Zalando"},
    {"name": "Tier Mobility",       "type": "smartrecruiters", "company": "TIERMobility"},

    # --- Generic HTML (any page): give CSS selectors for the job cards
    #     "item": selector for one job card, "title": selector inside card (text),
    #     "link": selector inside card (href), "location": selector inside card (optional)
    # {"name": "Example", "type": "html", "url": "https://example.com/jobs?q=data",
    #  "item": "li.job", "title": "h3", "link": "a", "location": ".loc"},
]

# ---------------------------------------------------------------------------
# ADAPTERS - each returns a list of dicts: {id, title, location, url, posted}
# ---------------------------------------------------------------------------

session = requests.Session()
session.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json"})


def fetch_workday(c):
    url = f"https://{c['host']}/wday/cxs/{c['tenant']}/{c['site']}/jobs"
    jobs, offset, limit = [], 0, 20
    while True:
        body = {"appliedFacets": {}, "limit": limit, "offset": offset, "searchText": c.get("query", "")}
        r = session.post(url, json=body, timeout=TIMEOUT)
        r.raise_for_status()
        data = r.json()
        for p in data.get("jobPostings", []):
            path = p.get("externalPath", "")
            jobs.append({
                "id": f"{c['name']}:{path}",
                "title": p.get("title", ""),
                "location": p.get("locationsText", ""),
                "url": f"https://{c['host']}/{c['site']}{path}",
                "posted": p.get("postedOn", ""),
            })
        offset += limit
        if offset >= data.get("total", 0) or offset > 1000:
            break
    return jobs


def fetch_greenhouse(c):
    url = f"https://boards-api.greenhouse.io/v1/boards/{c['board']}/jobs"
    r = session.get(url, timeout=TIMEOUT)
    r.raise_for_status()
    return [{
        "id": f"{c['name']}:{j['id']}",
        "title": j.get("title", ""),
        "location": (j.get("location") or {}).get("name", ""),
        "url": j.get("absolute_url", ""),
        "posted": j.get("updated_at", ""),
    } for j in r.json().get("jobs", [])]


def fetch_lever(c):
    url = f"https://api.lever.co/v0/postings/{c['company']}?mode=json"
    r = session.get(url, timeout=TIMEOUT)
    r.raise_for_status()
    return [{
        "id": f"{c['name']}:{j['id']}",
        "title": j.get("text", ""),
        "location": (j.get("categories") or {}).get("location", ""),
        "url": j.get("hostedUrl", ""),
        "posted": "",
    } for j in r.json()]


def fetch_smartrecruiters(c):
    jobs, offset = [], 0
    while True:
        url = f"https://api.smartrecruiters.com/v1/companies/{c['company']}/postings?limit=100&offset={offset}"
        r = session.get(url, timeout=TIMEOUT)
        r.raise_for_status()
        data = r.json()
        for j in data.get("content", []):
            loc = j.get("location") or {}
            jobs.append({
                "id": f"{c['name']}:{j['id']}",
                "title": j.get("name", ""),
                "location": ", ".join(x for x in [loc.get("city"), loc.get("country")] if x),
                "url": f"https://jobs.smartrecruiters.com/{c['company']}/{j['id']}",
                "posted": j.get("releasedDate", ""),
            })
        offset += 100
        if offset >= data.get("totalFound", 0):
            break
    return jobs


def fetch_ashby(c):
    url = f"https://api.ashbyhq.com/posting-api/job-board/{c['board']}"
    r = session.get(url, timeout=TIMEOUT)
    r.raise_for_status()
    return [{
        "id": f"{c['name']}:{j['id']}",
        "title": j.get("title", ""),
        "location": j.get("location", ""),
        "url": j.get("jobUrl", ""),
        "posted": j.get("publishedAt", ""),
    } for j in r.json().get("jobs", [])]


def fetch_personio(c):
    """Personio career pages expose an XML feed at https://<company>.jobs.personio.de/xml"""
    import xml.etree.ElementTree as ET
    url = f"https://{c['company']}.jobs.personio.de/xml"
    r = session.get(url, timeout=TIMEOUT, headers={"Accept": "application/xml"})
    r.raise_for_status()
    root = ET.fromstring(r.content)
    jobs = []
    for pos in root.iter("position"):
        jid = (pos.findtext("id") or "").strip()
        jobs.append({
            "id": f"{c['name']}:{jid}",
            "title": (pos.findtext("name") or "").strip(),
            "location": (pos.findtext("office") or "").strip(),
            "url": f"https://{c['company']}.jobs.personio.de/job/{jid}",
            "posted": (pos.findtext("createdAt") or "").strip(),
        })
    return jobs


def _get_html(url):
    r = session.get(url, timeout=TIMEOUT, headers={"Accept": "text/html"})
    r.raise_for_status()
    return BeautifulSoup(r.text, "html.parser")


def fetch_successfactors(c):
    """SAP SuccessFactors career sites share a common HTML layout."""
    jobs, start = [], 0
    while True:
        url = f"{c['base']}/search/?q={requests.utils.quote(c.get('query', ''))}&startrow={start}"
        soup = _get_html(url)
        rows = soup.select("tr.data-row")
        if not rows:
            break
        for row in rows:
            a = row.select_one("a.jobTitle-link")
            if not a:
                continue
            href = a.get("href", "")
            full = href if href.startswith("http") else c["base"] + href
            loc = row.select_one("span.jobLocation, .jobLocation")
            date = row.select_one("span.jobDate, .jobDate")
            jobs.append({
                "id": f"{c['name']}:{href.split('?')[0]}",
                "title": a.get_text(strip=True),
                "location": loc.get_text(strip=True) if loc else "",
                "url": full,
                "posted": date.get_text(strip=True) if date else "",
            })
        start += len(rows)
        if len(rows) < 25 or start > 1000:
            break
        time.sleep(1)
    return jobs


def fetch_html(c):
    """Generic scraper driven by CSS selectors in the config."""
    soup = _get_html(c["url"])
    base = c.get("base") or c["url"].split("/", 3)[0] + "//" + c["url"].split("/", 3)[2]
    jobs = []
    for card in soup.select(c["item"]):
        t = card.select_one(c["title"])
        a = card.select_one(c["link"])
        if not t or not a:
            continue
        href = a.get("href", "")
        full = href if href.startswith("http") else base + href
        loc = card.select_one(c["location"]) if c.get("location") else None
        jobs.append({
            "id": f"{c['name']}:{href.split('?')[0]}",
            "title": t.get_text(strip=True),
            "location": loc.get_text(strip=True) if loc else "",
            "url": full,
            "posted": "",
        })
    return jobs


FETCHERS = {
    "successfactors": fetch_successfactors,
    "html": fetch_html,
    "workday": fetch_workday,
    "greenhouse": fetch_greenhouse,
    "lever": fetch_lever,
    "smartrecruiters": fetch_smartrecruiters,
    "ashby": fetch_ashby,
    "personio": fetch_personio,
}

# ---------------------------------------------------------------------------
# FILTER / STATE / MAIN
# ---------------------------------------------------------------------------


def is_data_role(job):
    return any(k in job["title"].lower() for k in KEYWORDS)


def matches(job):
    t = job["title"].lower()
    loc = job["location"].lower()
    if not any(k in t for k in ROLE_WORDS):
        return False
    if STRICT and not is_data_role(job):
        return False
    if LOCATION_WORDS and not any(k in loc for k in LOCATION_WORDS):
        return False
    return True


def load_seen():
    if STATE_FILE.exists():
        return set(json.loads(STATE_FILE.read_text()))
    return set()


def save_seen(seen):
    STATE_FILE.write_text(json.dumps(sorted(seen), indent=1))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true", help="show all matches, not only new ones")
    ap.add_argument("--reset", action="store_true", help="clear seen-jobs state and exit")
    args = ap.parse_args()

    if args.reset:
        STATE_FILE.unlink(missing_ok=True)
        print("State cleared.")
        return

    seen = load_seen()
    new_jobs, errors = [], []

    for c in COMPANIES:
        fetcher = FETCHERS.get(c["type"])
        if not fetcher:
            errors.append(f"{c['name']}: unknown type {c['type']}")
            continue
        try:
            jobs = fetcher(c)
        except Exception as e:  # network / config errors shouldn't kill the run
            errors.append(f"{c['name']}: {e}")
            continue
        hits = [j for j in jobs if matches(j)]
        print(f"{c['name']:<22} ({c['type']:<15}) {len(jobs):>4} jobs, {len(hits):>3} match", file=sys.stderr)
        for j in hits:
            if args.all or j["id"] not in seen:
                j["company"] = c["name"]
                j["source"] = "HTML" if c["type"] in ("successfactors", "html") else "API"
                new_jobs.append(j)
            seen.add(j["id"])
        time.sleep(1)  # be polite

    # data-related roles first, then everything else
    new_jobs.sort(key=lambda j: (not is_data_role(j), j["company"], j["title"]))

    print("\n" + "=" * 70)
    if not new_jobs:
        print("No new matching jobs.")
    for j in new_jobs:
        star = "[*] " if is_data_role(j) else ""
        print(f"{star}[{j['company']} | {j['source']}] {j['title']}")
        print(f"    {j['location']}  {j['posted']}")
        print(f"    {j['url']}\n")

    if errors:
        print("Errors (check config for these companies):", file=sys.stderr)
        for e in errors:
            print("  " + e, file=sys.stderr)

    if not args.all:
        save_seen(seen)


if __name__ == "__main__":
    main()

# ---------------------------------------------------------------------------
# How to find the right config for a company
# ---------------------------------------------------------------------------
# 1. Open the company's careers page, run a search, open browser DevTools -> Network tab (XHR/Fetch).
# 2. Look at the request URLs:
#    - ".../wday/cxs/<tenant>/<site>/jobs"        -> workday: host = domain, tenant, site from the path
#    - "boards-api.greenhouse.io/v1/boards/<x>"   -> greenhouse: board = x
#    - "api.lever.co/v0/postings/<x>"             -> lever: company = x
#    - "api.smartrecruiters.com/v1/companies/<x>" -> smartrecruiters: company = x
#    - "api.ashbyhq.com/posting-api/job-board/<x>" or jobs.ashbyhq.com/<x> -> ashby: board = x
#    - "<x>.jobs.personio.de" or "<x>.jobs.personio.com"                  -> personio: company = x
#    - "jobs.<company>.com/search/?q=..." (SAP SuccessFactors) -> successfactors: base = "https://jobs.<company>.com"
#    - anything else -> html: open the listing page, right-click a job card -> Inspect, and copy CSS selectors
#      for the card, title, link and location. Pages that load jobs via JavaScript need Playwright instead.
# 3. Schedule daily: crontab -e  ->  0 8 * * * /usr/bin/python3 /path/to/ats_jobs.py >> jobs.log 2>&1
