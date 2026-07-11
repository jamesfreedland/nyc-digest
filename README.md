# NYC Events Digest

**Live digest:** https://jamesfreedland.github.io/nyc-digest/ (no login needed)

On a new machine: `git clone https://github.com/jamesfreedland/nyc-digest.git`

Scrapes upcoming New York City events — live music, Broadway, performing
arts, museum exhibitions, festivals, and more — and renders them into a
single filterable digest page. Sister project of
[stockholm-digest](https://github.com/jamesfreedland/stockholm-digest).

## Requirements

Python 3.9+. Standard library only — no pip installs, no API keys.

## Usage

```sh
python3 scrape.py            # next 14 days
python3 scrape.py --days 30  # wider window
```

Outputs, written next to the script:

- `events.json` — all scraped events, normalized
- `digest.html` — the rendered digest (open in a browser, or publish as a
  Claude Code Artifact)
- `index.html` — same page, committed so GitHub Pages serves it
- `nyct_cache.json` — per-slug cache of NYC Tourism pages (30-day TTL), so
  the first run fetches ~370 pages but later runs only fetch new events

The page has client-side filters: category chips, date ranges
(today / this weekend / next 7 days), a free-events toggle, and search.

## Sources

| Source | What | How |
|---|---|---|
| NYC Tourism | Curated citywide events, all categories | Sitemap slugs + per-page schema.org Event JSON |
| Eventbrite | Music + performing & visual arts, availability signals | Date-filtered SSR listing pages (`__SERVER_DATA__` + ld+json) |
| Playbill | Broadway shows now playing | Server-rendered show cards |
| City Parks Foundation | SummerStage + free park events, cost field | `wp-json/tribe/events/v1/events` API |

Notes: the Met (429) and MoMA (403) block plain fetches, MSG buries its
calendar feed, and nyctourism.com's Algolia search runs server-side only —
big museum shows and arena concerts still largely appear via the curated
NYC Tourism pages. Eventbrite is capped at 3 pages per category to keep
the digest curated rather than exhaustive.

## Event schema

Same as stockholm-digest: id, title, category, subcategory, start, end,
venue, address, url, info_url, description, price ("Free" | text | ""),
availability ("sold_out" | "few_left" | ""), source.

## Scheduled refresh

A Claude Code scheduled task refreshes the digest weekly and pushes
`index.html` so the GitHub Pages URL stays current. Scheduled tasks are
per-machine — recreate on a new machine by asking Claude Code to schedule
a weekly run of scrape.py in ~/nyc-digest that republishes the artifact
and pushes to GitHub.
