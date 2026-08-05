#!/usr/bin/env python3
"""NYC events digest scraper.

Pulls upcoming events from:
  1. NYC Tourism (nyctourism.com) - curated citywide events, all categories
  2. Eventbrite - music + performing & visual arts + LGBTQ+, date-filtered
  3. Playbill - Broadway shows now playing
  4. City Parks Foundation - SummerStage + free park events (tribe API)

LGBT events from any source are gathered under an "LGBTQ+ & Pride" section by keyword.

Usage:
  python3 scrape.py [--days N]   # default: next 14 days

Outputs (in the script's directory):
  events.json   - all scraped events, normalized
  digest.html   - rendered digest page
  index.html    - same page wrapped for GitHub Pages
  nyct_cache.json - per-slug cache of NYC Tourism event pages
"""
import argparse
import datetime as dt
import html
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).parent
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36",
      "Accept-Language": "en-US"}

CACHE_MAX_AGE_DAYS = 30


def get(url, retries=2):
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.read().decode("utf-8", errors="replace")
        except Exception as e:
            if attempt == retries:
                print(f"  ! failed {url}: {e}", file=sys.stderr)
                return None
            time.sleep(1 + attempt)


def strip_tags(s):
    return html.unescape(re.sub(r"<[^>]+>", " ", s or "")).strip()


LGBT_RE = re.compile(
    r"\b(lgbtq?|lgbtqia?|pride|queer|gay|lesbian|sapphic|transgender|nonbinary|non-binary|"
    r"voguing|drag show|dragshow|drag queen|drag king|drag brunch|drag bingo|drag race|"
    r"underwear party|jockstrap|jock strap|circuit party|leather night|bear night|"
    r"kink|fetish|bathhouse|sex party)\b",
    re.I)


def tag_lgbt(events):
    """Gather LGBT events from every source under one section, by keyword."""
    n = 0
    for e in events:
        if e["category"] == "LGBTQ+ & Pride":
            continue
        if LGBT_RE.search(f'{e["title"]} {e["subcategory"]} {e["description"]}'):
            e["category"] = "LGBTQ+ & Pride"
            n += 1
    print(f"  lgbt keyword pass: {n} recategorized", file=sys.stderr)
    return events


def classify(text):
    """Keyword classifier -> digest category."""
    t = text.lower()
    def any_of(*words):
        return any(w in t for w in words)
    if any_of("broadway", "musical", "theatre", "theater", "off-broadway", "play ", "ballet",
              "dance", "opera", "comedy", "stand-up", "standup", "cabaret", "circus"):
        return "Stage & Performing Arts"
    if any_of("concert", "music", "dj", "band", "jazz", "hip-hop", "hip hop", "orchestra",
              "symphony", "choir", "rapper", "singer", "summerstage"):
        return "Music"
    if any_of("exhibit", "museum", "gallery", "art show", "installation", "photograph"):
        return "Museums & Exhibitions"
    if any_of("festival", "parade", "fair", "market", "week ", "celebration", "powwow",
              "block party"):
        return "Festivals & Fairs"
    if any_of("restaurant", "food", "dining", "tasting", "beer", "wine", "cocktail", "brunch"):
        return "Food & Drink"
    if any_of("yankees", "mets ", "knicks", "nets ", "liberty", "rangers", "soccer", "tennis",
              "marathon", "baseball", "basketball", "world cup", "boxing", "wrestling",
              "race", "cycling"):
        return "Sports"
    if any_of("kids", "family", "children"):
        return "Family"
    return "City Life & More"


# ---------------------------------------------------------------- nyc tourism
def nyct_slugs():
    body = get("https://www.nyctourism.com/server-sitemap.xml")
    if body is None:
        return []
    urls = re.findall(r"<loc>(https://www\.nyctourism\.com/events/[^<]+)</loc>", body)
    return [u for u in urls if "/events/fbws-" not in u]


def nyct_parse_page(url, body):
    m = re.search(r'<script type="application/ld\+json"[^>]*>(.*?)</script>', body, re.S)
    if not m:
        return None
    try:
        graph = json.loads(m.group(1)).get("@graph", [])
    except json.JSONDecodeError:
        return None
    ev = next((g for g in graph if g.get("@type") == "Event"), None)
    if not ev or not ev.get("startDate"):
        return None
    loc = ev.get("location") or {}
    addr = loc.get("address") or {}
    venue = loc.get("name") or ""
    # venue name often only in page markup; fall back to street address
    street = addr.get("streetAddress") or ""
    borough = addr.get("addressLocality") or ""
    return {
        "title": ev.get("name", "").strip(),
        "description": (ev.get("description") or "")[:300],
        "start": ev["startDate"][:10],
        "end": (ev.get("endDate") or ev["startDate"])[:10],
        "venue": venue or street,
        "address": ", ".join(x for x in (street, borough) if x),
        "url": url,
    }


def scrape_nyctourism(date_from, date_to):
    cache_file = HERE / "nyct_cache.json"
    cache = {}
    if cache_file.exists():
        try:
            cache = json.loads(cache_file.read_text())
        except json.JSONDecodeError:
            cache = {}
    now = time.time()
    slugs = nyct_slugs()
    print(f"  nyctourism: {len(slugs)} curated event pages", file=sys.stderr)
    fetched = 0
    for url in slugs:
        c = cache.get(url)
        if c and now - c.get("fetched_at", 0) < CACHE_MAX_AGE_DAYS * 86400:
            continue
        body = get(url)
        fetched += 1
        parsed = nyct_parse_page(url, body) if body else None
        cache[url] = {"fetched_at": now, "event": parsed}
        time.sleep(0.15)
    # prune slugs no longer in the sitemap
    cache = {u: v for u, v in cache.items() if u in set(slugs)}
    cache_file.write_text(json.dumps(cache))
    events = []
    for url, c in cache.items():
        p = c.get("event")
        if not p:
            continue
        if p["end"] < date_from or p["start"] > date_to:
            continue
        events.append({
            "id": f"nyct-{url}",
            "title": p["title"],
            "category": classify(p["title"] + " " + p["description"]),
            "subcategory": "",
            "start": max(p["start"], date_from), "end": p["end"],
            "venue": p["venue"], "address": p["address"],
            "url": p["url"], "info_url": p["url"],
            "description": p["description"],
            "price": "", "availability": "",
            "source": "NYC Tourism",
        })
    print(f"  nyctourism: fetched {fetched} pages, {len(events)} in window", file=sys.stderr)
    return events


# ---------------------------------------------------------------- eventbrite
EB_CATEGORIES = {
    "music--events": "Music",
    "performing-and-visual-arts--events": "Stage & Performing Arts",
    "lgbtq--events": "LGBTQ+ & Pride",
    # nightlife feeds the keyword pass: underwear/jockstrap/kink parties often
    # list there without the LGBTQ category tag
    "nightlife--events": "City Life & More",
}
EB_PAGES = 3  # 20 hits/page per category


def scrape_eventbrite(date_from, date_to):
    events = {}
    for slug, cat in EB_CATEGORIES.items():
        for page in range(1, EB_PAGES + 1):
            url = (f"https://www.eventbrite.com/d/ny--new-york/{slug}/"
                   f"?start_date={date_from}&end_date={date_to}&page={page}")
            body = get(url)
            if body is None:
                break
            # structured list of events
            lds = re.findall(r'<script type="application/ld\+json"[^>]*>(.*?)</script>',
                             body, re.S)
            items = []
            for ld in lds:
                try:
                    d = json.loads(ld)
                except json.JSONDecodeError:
                    continue
                for block in (d if isinstance(d, list) else [d]):
                    if isinstance(block, dict):
                        items += [x["item"] for x in block.get("itemListElement", [])
                                  if isinstance(x, dict) and "item" in x]
            # urgency signals live in the server data blob
            urgency = {}
            m = re.search(r"window\.__SERVER_DATA__\s*=\s*(\{.*)", body)
            if m:
                txt, depth, end = m.group(1), 0, 0
                for i, ch in enumerate(txt):
                    if ch == "{":
                        depth += 1
                    elif ch == "}":
                        depth -= 1
                        if depth == 0:
                            end = i + 1
                            break
                try:
                    sd = json.loads(txt[:end])
                    results = (sd.get("search_data") or sd.get("event_data", {}).get(
                        "active_search", {})).get("events", {}).get("results", [])
                    if isinstance(sd.get("search_data"), dict):
                        results = sd["search_data"].get("events", {}).get("results", results)
                    for r in results:
                        sig = (r.get("urgency_signals") or {}).get("messages") or []
                        sub = next((t["display_name"] for t in r.get("tags", [])
                                    if t.get("prefix") == "EventbriteSubCategory"), "")
                        urgency[r.get("url") or ""] = (sig, sub, r.get("is_cancelled"))
                except (json.JSONDecodeError, AttributeError):
                    pass
            for it in items:
                if it.get("@type") != "Event":
                    continue
                url_e = it.get("url", "")
                key = url_e or it.get("name")
                if key in events:
                    continue
                start = (it.get("startDate") or "")[:10]
                end = (it.get("endDate") or start)[:10]
                if not start or end < date_from or start > date_to:
                    continue
                loc = it.get("location") or {}
                addr = (loc.get("address") or {})
                sig, sub, cancelled = urgency.get(url_e, ([], "", False))
                if cancelled:
                    continue
                avail = ""
                if "fewTickets" in sig:
                    avail = "few_left"
                if "salesEnded" in sig or "soldOut" in sig:
                    avail = "sold_out"
                events[key] = {
                    "id": f"eb-{url_e[-14:]}",
                    "title": it.get("name", "").strip(),
                    "category": cat,
                    "subcategory": sub,
                    "start": max(start, date_from), "end": end,
                    "venue": loc.get("name") or "",
                    "address": ", ".join(x for x in (
                        addr.get("streetAddress"), addr.get("addressLocality")) if x),
                    "url": url_e, "info_url": url_e,
                    "description": (it.get("description") or "")[:300],
                    "price": "Free" if re.search(r"\bfree\b", it.get("name", "").lower()) else "",
                    "availability": avail,
                    "source": "Eventbrite",
                }
        print(f"  eventbrite/{slug}: done", file=sys.stderr)
    return list(events.values())


# ---------------------------------------------------------------- playbill
def scrape_playbill(date_from, date_to):
    body = get("https://playbill.com/shows/broadway")
    if body is None:
        return []
    events = []
    seen = set()
    for m in re.finditer(
            r'<article[^>]*data-title="([^"]*)"[^>]*>.*?href="(/production/[^"]+)"(.*?)</article>',
            body, re.S):
        data_title, href, inner = m.groups()
        if href in seen:
            continue
        seen.add(href)
        nm = re.search(r'"show_name&quot;:&quot;([^&]*)&quot;|"show_name":"([^"]*)"', inner)
        name_m = re.search(r'show_name&quot;:&quot;(.*?)&quot;', m.group(0))
        title = html.unescape(name_m.group(1)) if name_m else data_title.title()
        # theatre name appears as plain text in the card
        th = re.search(r'>([^<]*(?:Theatre|Theater|Playhouse|Hall)[^<]*)<', inner)
        events.append({
            "id": f"pb-{href}",
            "title": title,
            "category": "Broadway",
            "subcategory": "Now playing",
            "start": date_from, "end": date_to,
            "venue": html.unescape(th.group(1)).strip() if th else "",
            "address": "",
            "url": "https://playbill.com" + href,
            "info_url": "https://playbill.com" + href,
            "description": "",
            "price": "", "availability": "",
            "source": "Playbill",
        })
    print(f"  playbill: {len(events)} broadway shows", file=sys.stderr)
    return events


# ---------------------------------------------------------------- city parks foundation
def scrape_cityparks(date_from, date_to):
    events = []
    page = 1
    while True:
        url = (f"https://cityparksfoundation.org/wp-json/tribe/events/v1/events"
               f"?start_date={date_from}&end_date={date_to}&per_page=50&page={page}")
        body = get(url)
        if body is None:
            break
        data = json.loads(body)
        for e in data.get("events", []):
            title = strip_tags(e.get("title", ""))
            venue = (e.get("venue") or {})
            cost = (e.get("cost") or "").strip()
            cats = " ".join(c.get("name", "") for c in e.get("categories", []))
            events.append({
                "id": f"cpf-{e.get('id')}",
                "title": title,
                "category": classify(title + " " + cats),
                "subcategory": strip_tags(cats)[:40],
                "start": (e.get("start_date") or "")[:10],
                "end": (e.get("end_date") or e.get("start_date") or "")[:10],
                "venue": strip_tags(venue.get("venue") or ""),
                "address": strip_tags(venue.get("address") or ""),
                "url": e.get("url") or "",
                "info_url": e.get("url") or "",
                "description": strip_tags(e.get("description") or "")[:300],
                "price": "Free" if cost.lower() == "free" else cost,
                "availability": "",
                "source": "City Parks Foundation",
            })
        if page >= int(data.get("total_pages") or 1):
            break
        page += 1
    print(f"  cityparks: {len(events)} in window", file=sys.stderr)
    return events


# ---------------------------------------------------------------- digest rendering
CATEGORY_ORDER = ["Music", "Broadway", "Stage & Performing Arts", "Museums & Exhibitions",
                  "Festivals & Fairs", "LGBTQ+ & Pride", "Food & Drink", "Sports", "Family",
                  "City Life & More"]
CATEGORY_LABELS = {
    "Music": "Live music & concerts",
    "Broadway": "Broadway",
    "Stage & Performing Arts": "Stage & performing arts",
    "Museums & Exhibitions": "Museums & exhibitions",
    "Festivals & Fairs": "Festivals & fairs",
    "LGBTQ+ & Pride": "LGBTQ+ & Pride",
    "Food & Drink": "Food & drink",
    "Sports": "Sports",
    "Family": "Family",
    "City Life & More": "City life & more",
}


def dedupe(events):
    seen, out = {}, []
    for e in sorted(events, key=lambda e: 0 if e["source"] == "NYC Tourism" else 1):
        key = (re.sub(r"\W+", "", e["title"].lower())[:40], e["start"])
        kept = seen.get(key)
        if kept:
            for field in ("price", "availability"):
                if not kept[field] and e.get(field):
                    kept[field] = e[field]
            continue
        seen[key] = e
        out.append(e)
    return out


def fmt_range(start, end, date_from, date_to):
    if start == date_from and end >= date_to:
        return "Now playing"
    s = dt.date.fromisoformat(start)
    e = dt.date.fromisoformat(end or start)
    if s == e:
        return s.strftime("%a %b %-d")
    if s.month == e.month:
        return f"{s.strftime('%b %-d')}–{e.strftime('%-d')}"
    return f"{s.strftime('%b %-d')} – {e.strftime('%b %-d')}"


def render_html(events, date_from, date_to):
    by_cat = {}
    for e in events:
        by_cat.setdefault(e["category"], []).append(e)
    for lst in by_cat.values():
        lst.sort(key=lambda e: (e["start"], e["title"]))

    cats = [c for c in CATEGORY_ORDER if c in by_cat]
    cats += [c for c in sorted(by_cat) if c not in cats]

    nav = (f'<button class="navchip active" data-cat="all">All '
           f'<span class="count">{len(events)}</span></button>')
    nav += "".join(
        f'<button class="navchip" data-cat="{re.sub(r"[^a-z]+", "-", c.lower())}">'
        f'{html.escape(CATEGORY_LABELS.get(c, c))} <span class="count">{len(by_cat[c])}</span></button>'
        for c in cats)

    sections = []
    for c in cats:
        anchor_c = re.sub(r"[^a-z]+", "-", c.lower())
        rows = []
        for e in by_cat[c]:
            sub = f'<span class="sub">{html.escape(e["subcategory"])}</span>' if e["subcategory"] else ""
            tags = ""
            if e.get("availability") == "sold_out":
                tags += '<span class="tag tag-sold">Sold out</span>'
            elif e.get("availability") == "few_left":
                tags += '<span class="tag tag-few">Few tickets left</span>'
            if e.get("price") == "Free":
                tags += '<span class="tag tag-free">Free</span>'
            elif e.get("price"):
                tags += f'<span class="tag tag-price">{html.escape(e["price"])}</span>'
            venue = html.escape(e["venue"] or e["address"] or "")
            desc = html.escape(e["description"])
            link = html.escape(e["url"] or e["info_url"])
            avail_text = {"sold_out": "sold out", "few_left": "few tickets"}.get(
                e.get("availability", ""), "")
            haystack = html.escape(
                f'{e["title"]} {e["venue"]} {e["subcategory"]} {e["description"]} '
                f'{e.get("price", "")} {avail_text}'.lower())
            is_free = "1" if e.get("price") == "Free" else "0"
            rows.append(f"""
      <div class="event" data-cat="{anchor_c}" data-start="{e["start"]}" data-end="{e["end"] or e["start"]}" data-free="{is_free}" data-text="{haystack}">
        <div class="when">{fmt_range(e["start"], e["end"], date_from, date_to)}</div>
        <div class="what">
          <a href="{link}" target="_blank" rel="noopener">{html.escape(e["title"])}</a>
          {sub}{tags}
          <div class="where">{venue}</div>
          {f'<div class="desc">{desc}</div>' if desc else ''}
        </div>
      </div>""")
        sections.append(
            f'<section id="{anchor_c}"><h2>{html.escape(CATEGORY_LABELS.get(c, c))}'
            f'<span class="count">{len(by_cat[c])}</span></h2>{"".join(rows)}</section>')

    generated = dt.datetime.now().strftime("%B %-d, %Y at %H:%M")
    s, e = dt.date.fromisoformat(date_from), dt.date.fromisoformat(date_to)
    window = f"{s.strftime('%B %-d')} – {e.strftime('%B %-d, %Y')}"

    tpl = (HERE / "template.html").read_text()
    return (tpl.replace("{{TODAY}}", date_from)
               .replace("{{WINDOW}}", window)
               .replace("{{GENERATED}}", generated)
               .replace("{{TOTAL}}", str(len(events)))
               .replace("{{NAV}}", nav)
               .replace("{{SECTIONS}}", "".join(sections)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=14, help="days ahead to include")
    args = ap.parse_args()

    today = dt.date.today()
    date_from = today.isoformat()
    date_to = (today + dt.timedelta(days=args.days)).isoformat()
    print(f"Scraping NYC events {date_from} → {date_to}", file=sys.stderr)

    events = []
    events += scrape_nyctourism(date_from, date_to)
    events += scrape_eventbrite(date_from, date_to)
    events += scrape_playbill(date_from, date_to)
    events += scrape_cityparks(date_from, date_to)
    events = tag_lgbt(events)
    events = dedupe(events)
    print(f"Total after dedupe: {len(events)}", file=sys.stderr)

    (HERE / "events.json").write_text(
        json.dumps(events, indent=1, ensure_ascii=False))
    page = render_html(events, date_from, date_to)
    (HERE / "digest.html").write_text(page)
    (HERE / "index.html").write_text(
        "<!doctype html>\n<html>\n<head></head>\n<body>\n" + page + "\n</body>\n</html>\n")
    print(f"Wrote {HERE / 'events.json'}, digest.html and index.html", file=sys.stderr)


if __name__ == "__main__":
    main()
