# Trash Miner

**Print-on-Demand niche research toolkit.** Discovers product niches, mines Reddit for pain points, and normalizes data for AI/LLM analysis — all without API keys.

---

## Project Structure

```
trash_miner/
├── seed_topics.txt                  # Product topics (one per line)
├── seed_harvester.py                # Generates seed_topics.txt from Google taxonomy
├── trash_miner.py                   # Mines Google autocomplete for negative keywords
├── rss_miner.py                     # Scrapes Reddit RSS for pain-point threads
├── normalize_reddit_jsonl.py        # Normalizes mixed-schema JSONL output
├── data/
│   ├── reddit_threads.jsonl         # Raw mined Reddit threads
│   ├── reddit_threads_normalized.jsonl  # Cleaned output
│   └── seen_post_ids.txt            # Dedup tracker for rss_miner
└── suggested_trash_candidates.txt   # Output from trash_miner
```

---

## Setup

### Requirements

- **Python 3.10+**
- Install dependencies:

```bash
pip install requests feedparser beautifulsoup4
```

> `normalize_reddit_jsonl.py` and `trash_miner.py` use only the standard library — no extra deps needed for those.

---

## Pipeline

The scripts run in order. Each step feeds the next.

### Step 1 — Seed Topics

Edit `seed_topics.txt` directly (one product topic per line), or auto-generate it from Google's product taxonomy:

```bash
python3 seed_harvester.py
```

**Output:** `seed_topics.txt` — clean list of product categories.

**Format:**
```
# Lines starting with # are ignored
shirts tops
mugs
posters prints visual artwork
yoga pilates mats
```

---

### Step 2 — Trash Mining (Negative Keywords)

Discovers irrelevant/negative search terms across your product topics using Google Autocomplete:

```bash
python3 trash_miner.py
```

**Output:** `suggested_trash_candidates.txt` — ranked list of words to potentially exclude from campaigns.

---

### Step 3 — Reddit RSS Mining

Scrapes Reddit subreddits for pain-point threads using RSS (no API key needed). Reads keywords from `seed_topics.txt` automatically.

```bash
# Dry run — preview all URLs without fetching
python3 rss_miner.py --mode urls

# Fetch search results (default)
python3 rss_miner.py --mode fetch

# Fetch search + top + new feeds, last month
python3 rss_miner.py --mode fetch --include_search --include_top --include_new --t month

# Fetch with comments, only pain points
python3 rss_miner.py --mode fetch --include_comments --max_comments 10 --only_pain_points

# Full run — all feeds, with comments, 25 posts per feed
python3 rss_miner.py --mode fetch \
    --include_search --include_top --include_new \
    --include_comments --max_comments 10 \
    --max_posts 25 --t month
```

| Flag | Default | Description |
|------|---------|-------------|
| `--mode` | *required* | `urls` (dry run) or `fetch` (scrape) |
| `--t` | `month` | Time window: `day`, `week`, `month`, `year`, `all` |
| `--sort` | `top` | Search sort: `top`, `new`, `relevance`, `comments` |
| `--max_posts` | `20` | Max posts per feed |
| `--include_comments` | off | Also fetch comment RSS per post |
| `--max_comments` | `10` | Max comments per post |
| `--only_pain_points` | off | Filter to pain-point threads only |
| `--sleep` | `0.9` | Delay between requests (be polite) |
| `--include_top` | off | Include subreddit `/top.rss` feeds |
| `--include_new` | off | Include subreddit `/new/.rss` feeds |
| `--include_search` | off* | Include search RSS queries (*default if none selected) |
| `--out` | `data/reddit_threads.jsonl` | Output file |
| `--seen` | `data/seen_post_ids.txt` | Dedup tracker |

**Output:** `data/reddit_threads.jsonl` — one JSON object per line.

---

### Step 4 — Normalize JSONL

Fixes inconsistent schemas from different miner versions (e.g., `feed` vs `feed_type`, `subreddit` vs `subreddit_feed`) into a single clean schema.

```bash
# Basic run
python3 normalize_reddit_jsonl.py

# With dedup and derived fields
python3 normalize_reddit_jsonl.py --dedupe --add_derived_fields

# Strict mode (abort on bad JSON)
python3 normalize_reddit_jsonl.py --strict
```

| Flag | Default | Description |
|------|---------|-------------|
| `--input` | `data/reddit_threads.jsonl` | Input JSONL |
| `--output` | `data/reddit_threads_normalized.jsonl` | Output JSONL |
| `--dedupe` | off | Remove duplicate `post_id` entries |
| `--add_derived_fields` | off | Add `comment_count` and `has_comments` |
| `--strict` | off | Abort on any JSON parse error |

**Output schema** (every line guaranteed):
```json
{
  "fetched_at": "2026-02-20T18:00:00+00:00",
  "feed": "search",
  "title": "...",
  "url": "https://...",
  "summary": "...",
  "author": "/u/...",
  "published": "2026-02-19T12:00:00+00:00",
  "post_id": "abc123",
  "subreddit": "printondemand",
  "is_pain_point": true,
  "comments": [
    {"author": "...", "published": "...", "url": "...", "text": "..."}
  ]
}
```

---

## Quick Start (Full Pipeline)

```bash
# 1. Install deps
pip install requests feedparser beautifulsoup4

# 2. Mine Reddit (uses seed_topics.txt)
python3 rss_miner.py --mode fetch --include_search --include_top --t month

# 3. Normalize the output
python3 normalize_reddit_jsonl.py --dedupe --add_derived_fields

# 4. Your clean data is ready at:
#    data/reddit_threads_normalized.jsonl
```
