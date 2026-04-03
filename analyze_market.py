import json
import os
import requests
import argparse
from datetime import datetime

# --- CONFIGURATION ---
INPUT_FILE = "data/reddit_threads_normalized.jsonl"
OUTPUT_DIR = "reports"
OLLAMA_URL = "http://127.0.0.1:11434/api/generate"
DEFAULT_MODEL = "llama3.2:3b"

PROMPT_TEMPLATE = """
Act as a Senior Product Manager and Market Research Expert. 
Analyze the following Reddit threads for a specific niche. 
Identify the recurring themes and extract the following:
1. TOP PAIN POINTS: What are the main frustrations or problems?
2. FEATURE REQUESTS/DESIRES: What are people asking for or wish existed?
3. COMPETITORS MENTIONED: List any tools or companies discussed.
4. "TRASH" CATEGORIES: Any common irrelevant topics that should be filtered out?

THREADS DATA:
{threads_text}

Format your response in clean Markdown with clear headings.
"""

def load_normalized_data(file_path):
    if not os.path.exists(file_path):
        print(f"[ERROR] '{file_path}' not found. Run normalize_reddit_jsonl.py first.")
        return []
    
    threads = []
    with open(file_path, "r", encoding="utf-8") as f:
        for line in f:
            try:
                threads.append(json.loads(line))
            except:
                continue
    return threads

def analyze_batch(batch, model):
    # Prepare text representation for the batch
    threads_text = ""
    for i, t in enumerate(batch):
        threads_text += f"-- THREAD {i+1} --\n"
        threads_text += f"Title: {t.get('title', 'N/A')}\n"
        threads_text += f"Summary: {t.get('summary', 'N/A')[:500]}...\n" # Limit summary length
        if t.get('comments'):
            threads_text += "Top Comments Highlights:\n"
            for c in t['comments'][:3]: # Top 3 comments
                threads_text += f"- {c.get('text', '')[:200]}\n"
        threads_text += "\n"

    try:
        r = requests.post(
            OLLAMA_URL,
            json={
                "model": model,
                "prompt": PROMPT_TEMPLATE.format(threads_text=threads_text),
                "stream": False
            },
            timeout=120
        )
        r.raise_for_status()
        return r.json().get("response", "No response from LLM.")
    except Exception as e:
        return f"Error during analysis: {e}"

def generate_report(threads, model, batch_size=10):
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = os.path.join(OUTPUT_DIR, f"market_intelligence_{timestamp}.md")
    
    print(f"[INFO] Analyzing {len(threads)} threads in batches of {batch_size}...")
    
    all_analyses = []
    # Only analyze first 50 threads to save time/cost in this demo, or process all if requested
    # For this script we will process 3 batches (up to 30 threads) as a deep dive
    max_threads = min(len(threads), 30) 
    
    for i in range(0, max_threads, batch_size):
        batch = threads[i:i+batch_size]
        print(f"  [>] Processing batch {i//batch_size + 1} ({len(batch)} threads)...")
        analysis = analyze_batch(batch, model)
        all_analyses.append(analysis)

    # Final summary of summaries
    print("[INFO] Generating final consolidated report...")
    
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(f"# Market Intelligence Report\n")
        f.write(f"*Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*\n")
        f.write(f"*Source: {len(threads)} Reddit Threads (Deep Dive on Top {max_threads})*\n\n")
        
        f.write("## 🚀 Executive Summary of Findings\n")
        f.write("Combined insights from multiple community discussions.\n\n")
        
        for i, analysis in enumerate(all_analyses):
            f.write(f"### Batch Dive {i+1}\n")
            f.write(analysis)
            f.write("\n\n---\n\n")

    print(f"[SUCCESS] Report saved to: {report_path}")
    return report_path

def main():
    parser = argparse.ArgumentParser(description="AI Market Analyzer - Extract insights from Reddit data.")
    parser.add_argument("--input", default=INPUT_FILE, help="Path to normalized JSONL file")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Ollama model to use")
    parser.add_argument("--batch_size", type=int, default=10, help="Number of threads per LLM call")
    
    args = parser.parse_args()
    
    threads = load_normalized_data(args.input)
    if not threads:
        return
        
    generate_report(threads, args.model, args.batch_size)

if __name__ == "__main__":
    main()
