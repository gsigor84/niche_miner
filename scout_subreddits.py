import argparse
import re
from typing import List, Set, Dict
from urllib.parse import urlencode, urlparse
import feedparser
import requests
from collections import Counter

USER_AGENT = "niche-scout/1.0 (polite; local-run)"

def search_subreddits(query: str, limit: int = 50) -> List[str]:
    """Search Reddit posts and extract unique subreddits."""
    print(f"[INFO] Scouting subreddits for query: '{query}'...")
    
    params = {
        "q": query,
        "type": "sr", # Try to find subreddits directly
        "limit": limit
    }
    # Reddit search RSS for posts related to the keyword
    url = f"https://www.reddit.com/search.rss?{urlencode({'q': query, 'sort': 'relevance', 't': 'year'})}"
    
    headers = {"User-Agent": USER_AGENT}
    try:
        r = requests.get(url, headers=headers, timeout=15)
        r.raise_for_status()
        feed = feedparser.parse(r.text)
    except Exception as e:
        print(f"[ERROR] RSS search failed: {e}")
        return []

    subs = []
    for entry in feed.entries:
        link = entry.get("link", "")
        # Link format: https://www.reddit.com/r/SUBREDDIT/comments/ID/SLUG/
        path = urlparse(link).path
        parts = [p for p in path.split("/") if p]
        if len(parts) >= 2 and parts[0] == "r":
            subs.append(parts[1])
            
    return subs

def main():
    parser = argparse.ArgumentParser(description="Reddit Subreddit Scout - Discover subreddits for a niche.")
    parser.add_argument("keywords", help="Comma-separated keywords or phrases")
    parser.add_argument("--limit", type=int, default=5, help="Number of top subreddits to return")
    parser.add_argument("--min_freq", type=int, default=1, help="Min appearances to count")

    args = parser.parse_args()
    
    all_subs = []
    keywords = [k.strip() for k in args.keywords.split(",") if k.strip()]
    
    for kw in keywords:
        found = search_subreddits(kw)
        all_subs.extend(found)
        
    counts = Counter(all_subs)
    # Filter common generic subs
    GENERIC_SUBS = {"all", "announcements", "funny", "askreddit", "pics", "news", "worldnews", "itookapicture"}
    
    filtered_counts = {s: c for s, c in counts.items() if s.lower() not in GENERIC_SUBS and c >= args.min_freq}
    top_subs = [s for s, c in sorted(filtered_counts.items(), key=lambda item: item[1], reverse=True)[:args.limit]]
    
    if top_subs:
        print(f"\n[SUCCESS] Top discovered subreddits: {', '.join(top_subs)}")
        print(f"To use with rss_miner: --subs {','.join(top_subs)}")
    else:
        print("\n[WARNING] No relevant subreddits found. Try broader keywords.")

if __name__ == "__main__":
    main()
