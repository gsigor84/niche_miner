import os
import sys
import tempfile
from pathlib import Path

import requests

# --- CONFIGURATION ---
OUTPUT_FILE = "seed_topics.txt"
# Official Google Shopping Taxonomy URL (Plain Text)
TAXONOMY_URL = "https://www.google.com/basepages/producttype/taxonomy.en-US.txt"


def write_seeds_atomic(path, products):
    """Write seeds atomically so a crash cannot truncate the prior file."""
    destination = Path(path)
    fd, tmp_name = tempfile.mkstemp(
        prefix=destination.name + ".",
        suffix=".tmp",
        dir=str(destination.parent or "."),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            for p in products:
                f.write(f"{p}\n")
        os.replace(tmp_name, destination)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def harvest_products():
    print("==================================================")
    print("   PRODUCT HARVESTER - E-COMMERCE SEED GENERATOR")
    print("==================================================")

    print(f"[INFO] Downloading official Google Product Taxonomy...")

    try:
        response = requests.get(TAXONOMY_URL, timeout=60)
        response.raise_for_status()
        raw_data = response.text.splitlines()
    except Exception as e:
        print(f"[ERROR] Failed to download taxonomy: {e}")
        if os.path.exists(OUTPUT_FILE):
            print(f"[ERROR] Preserving existing '{OUTPUT_FILE}'.")
        return 1

    unique_products = set()

    print(f"[INFO] Parsing {len(raw_data)} categories...")

    for line in raw_data:
        if not line or line.startswith("#"):
            continue

        # Line format: "Animals & Pet Supplies > Pet Supplies > Bird Supplies > Bird Cages & Stands"
        # We only want the LAST part: "Bird Cages & Stands"
        parts = line.split(">")
        leaf_node = parts[-1].strip()

        # Clean it up:
        # 1. Lowercase
        leaf_node = leaf_node.lower()
        # 2. Remove " & " (Bird Cages & Stands -> bird cages stands)
        leaf_node = leaf_node.replace(" & ", " ")
        # 3. Remove punctuation
        leaf_node = leaf_node.replace(",", "")

        # Add to set
        if len(leaf_node) > 3:
            unique_products.add(leaf_node)

    # Preserve any existing seed file when harvest produced nothing usable.
    # An empty/comment-only taxonomy response previously truncated this file.
    if not unique_products:
        if os.path.exists(OUTPUT_FILE):
            print(
                f"[ERROR] No product categories extracted from taxonomy. "
                f"Preserving existing '{OUTPUT_FILE}'."
            )
        else:
            print(
                "[ERROR] No product categories extracted from taxonomy. "
                f"Nothing written to '{OUTPUT_FILE}'."
            )
        return 1

    # --- SAVE ---
    sorted_products = sorted(list(unique_products))
    write_seeds_atomic(OUTPUT_FILE, sorted_products)

    print("==================================================")
    print(f"[SUCCESS] Extracted {len(sorted_products)} unique product categories.")
    print(f"[EXAMPLE] {sorted_products[:5]}")
    print(f"[ACTION] Saved to '{OUTPUT_FILE}'.")
    print("[NEXT] Now run 'python trash_miner.py' to find universal negative keywords.")
    return 0


if __name__ == "__main__":
    sys.exit(harvest_products() or 0)
