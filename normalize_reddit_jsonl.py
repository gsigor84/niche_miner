#!/usr/bin/env python3
"""
normalize_reddit_jsonl.py — Normalize mixed-schema Reddit JSONL to a single consistent schema.

Usage:
    python3 normalize_reddit_jsonl.py
    python3 normalize_reddit_jsonl.py --input data/reddit_threads.jsonl --output data/reddit_threads_normalized.jsonl
    python3 normalize_reddit_jsonl.py --dedupe --add_derived_fields
    python3 normalize_reddit_jsonl.py --strict
"""

import argparse
import json
import sys
from pathlib import Path

REQUIRED_KEYS = (
    "fetched_at", "feed", "title", "url", "summary",
    "author", "published", "post_id", "subreddit",
    "is_pain_point", "comments",
)

ALLOWED_FEEDS = {"top", "new", "search", "unknown"}


def normalize_comment(c):
    if not isinstance(c, dict):
        return None
    return {
        "author":    c.get("author"),
        "published": c.get("published"),
        "url":       c.get("url"),
        "text":      (c.get("text") or "").strip(),
    }


def normalize_record(obj):
    feed = obj.get("feed") or obj.get("feed_type") or "search"
    if feed not in ALLOWED_FEEDS:
        feed = "search"

    subreddit = obj.get("subreddit") or obj.get("subreddit_feed") or ""
    subreddit = subreddit.strip()

    raw_comments = obj.get("comments")
    if not isinstance(raw_comments, list):
        raw_comments = []
    comments = [nc for c in raw_comments if (nc := normalize_comment(c)) is not None]

    return {
        "fetched_at":    obj.get("fetched_at") or "",
        "feed":          feed,
        "title":         (obj.get("title") or "").strip(),
        "url":           obj.get("url") or "",
        "summary":       (obj.get("summary") or "").strip(),
        "author":        obj.get("author"),
        "published":     obj.get("published"),
        "post_id":       obj.get("post_id") or "",
        "subreddit":     subreddit,
        "is_pain_point": bool(obj.get("is_pain_point")),
        "comments":      comments,
    }


def main():
    ap = argparse.ArgumentParser(description="Normalize Reddit JSONL schema.")
    ap.add_argument("--input",  default="data/reddit_threads.jsonl")
    ap.add_argument("--output", default="data/reddit_threads_normalized.jsonl")
    ap.add_argument("--dedupe", action="store_true", help="Deduplicate by post_id (fallback: url)")
    ap.add_argument("--add_derived_fields", action="store_true", help="Add comment_count, has_comments")
    ap.add_argument("--strict", action="store_true", help="Abort on any JSON parse error")
    args = ap.parse_args()

    inpath  = Path(args.input)
    outpath = Path(args.output)

    if not inpath.exists():
        print(f"ERROR: not found: {inpath}", file=sys.stderr)
        sys.exit(1)

    records       = []
    total_read    = 0
    bad_json      = 0
    feed_fixed    = 0

    with open(inpath, "r", encoding="utf-8") as fh:
        for lineno, raw in enumerate(fh, start=1):
            total_read += 1
            line = raw.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as e:
                if args.strict:
                    print(f"ERROR: line {lineno}: {e}", file=sys.stderr)
                    sys.exit(2)
                print(f"WARN: skipping line {lineno}: {e}", file=sys.stderr)
                bad_json += 1
                continue

            if "feed" not in obj:
                feed_fixed += 1

            records.append(normalize_record(obj))

    # ── dedupe ──────────────────────────────────────────────────────────
    dupes_removed = 0
    if args.dedupe:
        seen = {}
        unique = []
        for rec in records:
            key = rec["post_id"] or rec["url"] or id(rec)
            if key not in seen:
                seen[key] = True
                unique.append(rec)
        dupes_removed = len(records) - len(unique)
        records = unique

    # ── derived fields ──────────────────────────────────────────────────
    if args.add_derived_fields:
        for rec in records:
            rec["comment_count"] = len(rec["comments"])
            rec["has_comments"]  = len(rec["comments"]) > 0

    # ── write ───────────────────────────────────────────────────────────
    outpath.parent.mkdir(parents=True, exist_ok=True)
    with open(outpath, "w", encoding="utf-8") as out:
        for rec in records:
            out.write(json.dumps(rec, ensure_ascii=False) + "\n")

    # ── stats ───────────────────────────────────────────────────────────
    with_comments = sum(1 for r in records if r["comments"])

    print("═══════════════════════════════════════")
    print("        Normalization Report")
    print("═══════════════════════════════════════")
    print(f"  Lines read:           {total_read}")
    print(f"  Lines written:        {len(records)}")
    print(f"  Missing feed fixed:   {feed_fixed}")
    print(f"  Duplicates removed:   {dupes_removed}")
    print(f"  Bad lines skipped:    {bad_json}")
    print(f"  Threads w/ comments:  {with_comments}")
    print("═══════════════════════════════════════")


if __name__ == "__main__":
    main()
