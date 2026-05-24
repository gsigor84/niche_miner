#!/usr/bin/env python3
"""
POD Reddit RSS Miner (No API Key)

- Builds subreddit search RSS URLs for your keywords + "commercial intent" query packs
- Fetches posts from RSS feeds (Top/New/Search)
- Optionally fetches comments RSS for each post
- Saves results to JSONL
- Dedupe via seen_post_ids.txt

Usage examples:

1) Dry run: print all URLs (no fetching)
   python pod_reddit_rss.py --mode urls

2) Fetch posts (search + top + new), no comments
   python pod_reddit_rss.py --mode fetch --t month --max_posts 25

3) Fetch with comments (first 10)
   python pod_reddit_rss.py --mode fetch --include_comments --max_comments 10

"""

import argparse
import json
import random
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlencode, urlparse

import feedparser
import requests
from bs4 import BeautifulSoup

# -----------------------------
# CONFIG
# -----------------------------

SEED_TOPICS_FILE = "seed_topics.txt"
QUERY_PACKS_FILE = "config/query_packs.json"


def load_keywords(path: str = SEED_TOPICS_FILE, prefix: Optional[str] = None) -> List[str]:
    """Read seed topics and optionally add a prefix."""
    filepath = Path(path)
    if not filepath.exists():
        print(f"[ERROR] Seed file not found: {filepath}")
        return []
    
    keywords = []
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            topic = line.strip()
            if not topic or topic.startswith("#"):
                continue
            if prefix:
                keywords.append(f"{prefix} {topic}")
            else:
                keywords.append(topic)
    return keywords

def parse_keyword_arg(raw: Optional[str], prefix: Optional[str] = None) -> List[str]:
    """Parse explicit CLI keywords, mirroring seed file prefix handling."""
    if not raw:
        return []
    keywords = []
    for topic in raw.split(","):
        topic = topic.strip()
        if not topic:
            continue
        keywords.append(f"{prefix} {topic}" if prefix else topic)
    return keywords


def load_query_templates(niche_type: str) -> List[str]:
    """Load query templates for the specified niche type from JSON config."""
    path = Path(QUERY_PACKS_FILE)
    if not path.exists():
        print(f"[WARNING] Query packs file not found: {path}. Using default templates.")
        return ["{kw} best", "{kw} review"]
    
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data.get(niche_type, {}).get("templates", ["{kw} best", "{kw} review"])
    except Exception as e:
        print(f"[ERROR] Failed to load query packs: {e}")
        return ["{kw} best", "{kw} review"]


# Default subreddits if none provided
DEFAULT_SUBREDDITS = [
    "entrepreneur",
    "startup",
    "business",
    "sideproject",
]

# kw_short is auto-derived from the keyword by stripping the prefix.

USER_AGENT = "pod-rss-miner/0.2 (no-api; polite; local-run)"
SESSION = requests.Session()
SESSION.headers.update({"User-Agent": USER_AGENT})

POST_ID_RE = re.compile(r"/comments/([a-z0-9]{5,10})/", re.I)

# "Pain-point-ish" filters (optional; can be toggled on CLI)
PAIN_PATTERNS = [
    r"\bhow do i\b", r"\bhow can i\b", r"\bany advice\b", r"\bany tips\b",
    r"\bhelp\b", r"\bstruggling\b", r"\bstuck\b", r"\bissue\b", r"\bproblem\b",
    r"\bdoes anyone\b", r"\bwhy is\b", r"\bwhat's the best\b",
]


# -----------------------------
# Helpers
# -----------------------------

def now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def html_to_text(html: str) -> str:
    soup = BeautifulSoup(html or "", "html.parser")
    return soup.get_text(" ", strip=True)

def polite_sleep(base: float) -> None:
    time.sleep(base + random.random() * 0.35)

def fetch_text(url: str, timeout: int = 20, retries: int = 5, base_sleep: float = 1.0) -> str:
    for attempt in range(retries):
        r = SESSION.get(url, timeout=timeout)
        if r.status_code == 429:
            # exponential backoff
            sleep_s = base_sleep * (2 ** attempt) + random.random()
            time.sleep(sleep_s)
            continue
        r.raise_for_status()
        return r.text
    raise RuntimeError(f"Too many 429s fetching: {url}")

def parse_feed(url: str) -> feedparser.FeedParserDict:
    raw = fetch_text(url)
    return feedparser.parse(raw)

def extract_post_id(url: str) -> Optional[str]:
    m = POST_ID_RE.search(url or "")
    return m.group(1) if m else None

def extract_subreddit_from_url(url: str) -> Optional[str]:
    path = urlparse(url).path  # /r/SUB/comments/ID/slug/
    parts = [p for p in path.split("/") if p]
    if len(parts) >= 2 and parts[0].lower() == "r":
        return parts[1]
    return None

def looks_like_pain_point(title: str, body: str) -> bool:
    text = f"{title}\n{body}".lower()
    return any(re.search(pat, text) for pat in PAIN_PATTERNS)

def load_seen_ids(path: Path) -> set:
    if not path.exists():
        return set()
    return set(line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip())

def append_seen_id(path: Path, post_id: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(post_id + "\n")

def append_jsonl(path: Path, obj: Dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")


# -----------------------------
# RSS URL Builders
# -----------------------------

def subreddit_top_feed(sub: str, t: str) -> str:
    return f"https://www.reddit.com/r/{sub}/top.rss?{urlencode({'t': t})}"

def subreddit_new_feed(sub: str) -> str:
    return f"https://www.reddit.com/r/{sub}/new/.rss?{urlencode({'sort': 'new'})}"

def subreddit_search_feed(sub: str, query: str, sort: str, t: str) -> str:
    params = {
        "q": query,
        "restrict_sr": 1,
        "sort": sort,
        "t": t,
    }
    return f"https://www.reddit.com/r/{sub}/search.rss?{urlencode(params)}"

def comments_feed(sub: str, post_id: str) -> str:
    return f"https://www.reddit.com/r/{sub}/comments/{post_id}/.rss"


# -----------------------------
# Query Generation
# -----------------------------

def derive_kw_short(kw: str, prefix: Optional[str] = None) -> str:
    """Auto-derive short product name by stripping the prefix."""
    if prefix:
        base = kw.lower().replace(prefix.lower(), "").strip()
        return base if base else kw
    return kw

def build_queries_for_keyword(kw: str, templates: List[str], prefix: Optional[str] = None) -> List[str]:
    kw_short = derive_kw_short(kw, prefix)
    queries = []
    for tmpl in templates:
        try:
            q = tmpl.format(kw=kw, kw_short=kw_short)
            # Keep queries compact; Reddit search sometimes hates punctuation-heavy queries
            q = q.replace("  ", " ").strip()
            queries.append(q)
        except Exception:
            # If template has unknown keys, just use basic format
            queries.append(f"{kw} best")
    # remove duplicates, preserve order
    seen = set()
    out = []
    for q in queries:
        if q.lower() in seen:
            continue
        seen.add(q.lower())
        out.append(q)
    return out


# -----------------------------
# Fetch + Parse
# -----------------------------

def entry_to_post(entry) -> Dict:
    title = getattr(entry, "title", "").strip()
    link = getattr(entry, "link", "").strip()
    summary = html_to_text(getattr(entry, "summary", ""))
    author = getattr(entry, "author", None)
    published = getattr(entry, "published", None)

    return {
        "title": title,
        "url": link,
        "summary": summary,
        "author": author,
        "published": published,
        "post_id": extract_post_id(link),
        "subreddit": extract_subreddit_from_url(link),
    }

def collect_comments(sub: str, post_id: str, max_comments: int, sleep_s: float) -> List[Dict]:
    url = comments_feed(sub, post_id)
    feed = parse_feed(url)

    comments: List[Dict] = []
    for entry in feed.entries[:max_comments]:
        comments.append({
            "author": getattr(entry, "author", None),
            "published": getattr(entry, "published", None),
            "url": getattr(entry, "link", None),
            "text": html_to_text(getattr(entry, "summary", "")),
        })
        polite_sleep(sleep_s)

    return comments


# -----------------------------
# Main
# -----------------------------

def generate_all_feed_urls(
    subs: List[str],
    keywords: List[str],
    templates: List[str],
    t: str,
    sort: str,
    include_top: bool,
    include_new: bool,
    include_search: bool,
    prefix: Optional[str] = None
) -> List[Tuple[str, str, str]]:
    """
    Returns list of (subreddit, feed_type, url).
    feed_type: "top" | "new" | "search"
    """
    urls: List[Tuple[str, str, str]] = []

    for sub in subs:
        if include_top:
            urls.append((sub, "top", subreddit_top_feed(sub, t)))
        if include_new:
            urls.append((sub, "new", subreddit_new_feed(sub)))

        if include_search:
            for kw in keywords:
                for q in build_queries_for_keyword(kw, templates, prefix):
                    urls.append((sub, "search", subreddit_search_feed(sub, q, sort=sort, t=t)))

    return urls


def run_fetch(args):
    out_path = Path(args.out)
    seen_path = Path(args.seen)
    seen_ids = load_seen_ids(seen_path)

    feeds = generate_all_feed_urls(
        subs=args.subs,
        keywords=args.keywords,
        templates=args.templates,
        t=args.t,
        sort=args.sort,
        include_top=args.include_top,
        include_new=args.include_new,
        include_search=args.include_search,
        prefix=args.prefix
    )

    print(f"Feeds to fetch: {len(feeds)}")
    print(f"Output JSONL: {out_path}")
    print(f"Seen IDs: {seen_path}")

    for sub, feed_type, url in feeds:
        print(f"\n[{sub}] {feed_type}: {url}")
        try:
            feed = parse_feed(url)
        except Exception as e:
            print(f"  ! feed error: {e}")
            polite_sleep(args.sleep)
            continue

        polite_sleep(args.sleep)

        entries = feed.entries[:args.max_posts]
        print(f"  entries: {len(entries)}")

        for entry in entries:
            post = entry_to_post(entry)
            post_id = post.get("post_id")
            if not post_id:
                continue
            if post_id in seen_ids:
                continue

            title = post.get("title", "")
            summary = post.get("summary", "")

            is_pain = looks_like_pain_point(title, summary)
            if args.only_pain_points and not is_pain:
                continue

            record = {
                "fetched_at": now_utc_iso(),
                "source": "reddit_rss",
                "subreddit_feed": sub,
                "feed_type": feed_type,
                "matched_query": None,     # optional: can be filled if you want to track query later
                "is_pain_point": is_pain,
                **post,
                "comments": [],
            }

            # Fetch comments RSS only if we can confidently get the subreddit
            if args.include_comments and post.get("subreddit"):
                try:
                    record["comments"] = collect_comments(
                        sub=post["subreddit"],
                        post_id=post_id,
                        max_comments=args.max_comments,
                        sleep_s=args.sleep,
                    )
                except Exception as e:
                    record["comments_error"] = str(e)

            append_jsonl(out_path, record)
            append_seen_id(seen_path, post_id)
            seen_ids.add(post_id)

            print(f"  saved: {post_id} | {title[:90]}")
            polite_sleep(args.sleep)

    print("\nDone.")


def main():
    ap = argparse.ArgumentParser(description="Universal Niche RSS Miner (No API Key).")

    ap.add_argument("--mode", choices=["urls", "fetch"], required=True, help="Print URLs or fetch data")
    ap.add_argument("--niche_type", default="ecommerce", help="Niche type for query packs (saas, ecommerce, services, learning)")
    ap.add_argument("--prefix", default=None, help="Optional keyword prefix (e.g. 'print on demand')")
    ap.add_argument("--keywords", default=None, help="Comma-separated keywords to use instead of seed_topics.txt")
    ap.add_argument("--subs", help="Comma-separated list of subreddits to target")
    
    ap.add_argument("--t", default="month", choices=["day", "week", "month", "year", "all"], help="Top/Search time window")
    ap.add_argument("--sort", default="top", choices=["top", "new", "relevance", "comments"], help="Search sort mode")

    ap.add_argument("--max_posts", type=int, default=20, help="Max posts per feed request")
    ap.add_argument("--include_comments", action="store_true", help="Fetch comments RSS for each post")
    ap.add_argument("--max_comments", type=int, default=10, help="Max comments per post")
    ap.add_argument("--only_pain_points", action="store_true", help="Only save pain-point-ish posts")
    ap.add_argument("--sleep", type=float, default=0.9, help="Delay between requests")

    ap.add_argument("--out", default="data/reddit_threads.jsonl", help="Output JSONL")
    ap.add_argument("--seen", default="data/seen_post_ids.txt", help="Dedupe file")

    # toggles
    ap.add_argument("--include_top", action="store_true", help="Include subreddit top.rss")
    ap.add_argument("--include_new", action="store_true", help="Include subreddit new/.rss")
    ap.add_argument("--include_search", action="store_true", help="Include subreddit search.rss queries")

    args = ap.parse_args()

    # Load templates from config
    args.templates = load_query_templates(args.niche_type)
    
    # Determine subreddits
    if args.subs:
        args.subs = [s.strip() for s in args.subs.split(",") if s.strip()]
    else:
        args.subs = DEFAULT_SUBREDDITS

    if args.keywords:
        args.keywords = parse_keyword_arg(args.keywords, prefix=args.prefix)
    else:
        args.keywords = load_keywords(prefix=args.prefix)

    # If user didn't specify any feed types, default to search-only (most useful)
    if not (args.include_top or args.include_new or args.include_search):
        args.include_search = True

    if args.include_search and not args.keywords:
        print("[ERROR] No keywords available for search feeds.", file=sys.stderr)
        sys.exit(1)

    print(f"[INFO] Niche Type: {args.niche_type}")
    print(f"[INFO] Loaded {len(args.keywords)} keywords")
    print(f"[INFO] Target Subreddits: {args.subs}")

    feeds = generate_all_feed_urls(
        subs=args.subs,
        keywords=args.keywords,
        templates=args.templates,
        t=args.t,
        sort=args.sort,
        include_top=args.include_top,
        include_new=args.include_new,
        include_search=args.include_search,
        prefix=args.prefix
    )

    if args.mode == "urls":
        print(f"Total URLs: {len(feeds)}\n")
        for sub, feed_type, url in feeds:
            print(f"{sub}\t{feed_type}\t{url}")
        return

    run_fetch(args)


if __name__ == "__main__":
    main()
