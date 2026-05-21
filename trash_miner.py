import sys
import json
import requests
import collections
import time
import os

# --- SETTINGS ---
SEED_FILE = "seed_topics.txt"
OUTPUT_FILE = "suggested_trash_candidates.txt"
GOOGLE_AUTO_URL = "http://suggestqueries.google.com/complete/search"
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
        response = requests.get(
            GOOGLE_AUTO_URL,
            params={"client": "chrome", "q": query},
            timeout=5,
        )
        response.raise_for_status()
        data = response.json()
        # [query, [suggestions, ...], [extra_info, ...]]
        return data[1] if len(data) > 1 else []
    except Exception as e:
        print(f"  [WARN] Failed query '{query}': {e}")
        return []

def mine_trash():
    print("==================================================")
    print("   TRASH MINER - SEARCH INTENT INTELLIGENCE")
    print("==================================================")
    
    seeds = load_seeds()
    if not seeds:
        return

    print(f"[INFO] Initializing search for {len(seeds)} topics...")
    all_suggestions = []
    
    for i, seed in enumerate(seeds):
        print(f"[{i+1}/{len(seeds)}] Mining: {seed}...", end="\r")
        suggestions = get_autocomplete(seed)
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

    # --- SAVE ---
    print(f"[INFO] Writing {len(top_candidates)} candidates to '{OUTPUT_FILE}'...")
    with open(OUTPUT_FILE, "w") as f:
        f.write("# SUGGESTED TRASH INTENT CANDIDATES\n")
        f.write(f"# Based on analysis of {len(seeds)} topics.\n")
        f.write("# Format: Word (Frequency)\n")
        f.write("# Copy the ones you want to ban into 'trash_intent.txt'\n\n")
        for word, count in top_candidates:
            f.write(f"{word}\t({count})\n")

    print("==================================================")
    print(f"[SUCCESS] Mining complete. Check '{OUTPUT_FILE}' for insights.")
    print("==================================================")

if __name__ == "__main__":
    mine_trash()
