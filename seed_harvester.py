import requests

# --- CONFIGURATION ---
OUTPUT_FILE = "seed_topics.txt"
# Official Google Shopping Taxonomy URL (Plain Text)
TAXONOMY_URL = "http://www.google.com/basepages/producttype/taxonomy.en-US.txt"


def harvest_products():
    print("==================================================")
    print("   PRODUCT HARVESTER - E-COMMERCE SEED GENERATOR")
    print("==================================================")

    print(f"[INFO] Downloading official Google Product Taxonomy...")

    try:
        response = requests.get(TAXONOMY_URL)
        response.raise_for_status()
        raw_data = response.text.splitlines()
    except Exception as e:
        print(f"[ERROR] Failed to download taxonomy: {e}")
        return

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

    # --- SAVE ---
    sorted_products = sorted(list(unique_products))

    with open(OUTPUT_FILE, "w") as f:
        for p in sorted_products:
            f.write(f"{p}\n")

    print("==================================================")
    print(f"[SUCCESS] Extracted {len(sorted_products)} unique product categories.")
    print(f"[EXAMPLE] {sorted_products[:5]}")
    print(f"[ACTION] Saved to '{OUTPUT_FILE}'.")
    print("[NEXT] Now run 'python trash_miner.py' to find universal negative keywords.")


if __name__ == "__main__":
    harvest_products()