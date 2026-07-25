import sys
import requests
import collections
import time
import os
import tempfile
from pathlib import Path
from urllib.parse import quote_plus

# --- SETTINGS ---
SEED_FILE = "seed_topics.txt"
OUTPUT_FILE = "suggested_trash_candidates.txt"
GOOGLE_AUTO_URL = "https://suggestqueries.google.com/complete/search?client=chrome&q={}"
# Words to exclude from frequency count (common stop words)
STOP_WORDS = {"and", "for", "the", "with", "are", "what", "how", "you", "does", "can", "near"}

def load_seeds():
    if not os.path.exists(SEED_FILE):
        print(f"[ERROR] '{SEED_FILE}' not found. Please run seed_factory.py first.")
        return []
    with open(SEED_FILE, "r") as f:
        return [line.strip().lower() for line in f if line.strip() and not line.startswith("#")]

def get_autocomplete(query):
    try:
        response = requests.get(GOOGLE_AUTO_URL.format(quote_plus(query)), timeout=5)
        response.raise_for_status()
        data = response.json()
        # [query, [suggestions, ...], [extra_info, ...]]
        return data[1] if len(data) > 1 else []
    except Exception as e:
        print(f"  [WARN] Failed query '{query}': {e}")
        return None  # distinguish hard failure from empty suggestions

def write_candidates_atomic(path, seeds_count, top_candidates):
    """Write candidates atomically so a crash cannot truncate the prior report."""
    destination = Path(path)
    fd, tmp_name = tempfile.mkstemp(
        prefix=destination.name + ".",
        suffix=".tmp",
        dir=str(destination.parent or "."),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write("# SUGGESTED TRASH INTENT CANDIDATES\n")
            f.write(f"# Based on analysis of {seeds_count} topics.\n")
            f.write("# Format: Word (Frequency)\n")
            f.write("# Copy the ones you want to ban into 'trash_intent.txt'\n\n")
            for word, count in top_candidates:
                f.write(f"{word}\t({count})\n")
        os.replace(tmp_name, destination)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise

def mine_trash():
    print("==================================================")
    print("   TRASH MINER - SEARCH INTENT INTELLIGENCE")
    print("==================================================")
    
    seeds = load_seeds()
    if not seeds:
        return 1

    print(f"[INFO] Initializing search for {len(seeds)} topics...")
    all_suggestions = []
    query_failures = 0
    
    for i, seed in enumerate(seeds):
        print(f"[{i+1}/{len(seeds)}] Mining: {seed}...", end="\r")
        suggestions = get_autocomplete(seed)
        if suggestions is None:
            query_failures += 1
            continue
        all_suggestions.extend(suggestions)
        # Be nice to Google
        time.sleep(0.5)
    
    print("\n[INFO] Processing candidate words...")
    
    # Analyze the suggestions to find frequently occurring words 
    # that are NOT the seeds themselves.
    word_freq = collections.Counter()
    seed_words = set()
    for s in seeds:
        seed_words.update(s.split())

    for sugg in all_suggestions:
        words = sugg.lower().split()
        for w in words:
            # Clean punctuation
            w = "".join(filter(str.isalnum, w))
            if not w: continue
            
            # If the word is NOT part of the original seeds and NOT a stop word
            if w not in seed_words and w not in STOP_WORDS and len(w) > 2:
                word_freq[w] += 1

    # Get top 200
    top_candidates = word_freq.most_common(200)

    # Preserve any existing report when mining produced nothing usable.
    # A total outage or full throttle previously truncated this file to a header.
    if not top_candidates:
        if os.path.exists(OUTPUT_FILE):
            print(
                f"[ERROR] No candidates mined "
                f"({query_failures}/{len(seeds)} queries failed). "
                f"Preserving existing '{OUTPUT_FILE}'."
            )
        else:
            print(
                f"[ERROR] No candidates mined "
                f"({query_failures}/{len(seeds)} queries failed). "
                f"Nothing written to '{OUTPUT_FILE}'."
            )
        return 1

    # --- SAVE ---
    print(f"[INFO] Writing {len(top_candidates)} candidates to '{OUTPUT_FILE}'...")
    write_candidates_atomic(OUTPUT_FILE, len(seeds), top_candidates)

    print("==================================================")
    print(f"[SUCCESS] Mining complete. Check '{OUTPUT_FILE}' for insights.")
    print("==================================================")
    return 0

if __name__ == "__main__":
    sys.exit(mine_trash() or 0)
