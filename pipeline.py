#!/usr/bin/env python3
"""
pipeline.py — Full trash miner pipeline orchestrator

Runs: seed_factory → scout_subreddits → rss_miner → normalize → gap_analysis

Usage:
    python3 pipeline.py --niche "party tickets" --niche_type events
    python3 pipeline.py --niche "AI agents" --niche_type saas
    python3 pipeline.py --resume --run_id 20260403_party_tickets
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

# ── Config ────────────────────────────────────────────────────────────────────

PROJECT = Path(__file__).parent
DATA = PROJECT / "data"
RUNS = PROJECT / "runs"
SEED_FILE = PROJECT / "seed_topics.txt"

NICHE_TYPES = ["saas", "ecommerce", "services", "learning", "events"]

# ── Helpers ───────────────────────────────────────────────────────────────────

def run(cmd, label, check=True, run_id=None, state=None, phase=None):
    print(f"\n{'='*60}")
    print(f"  [{label}] {' '.join(cmd)}")
    print('='*60)
    result = subprocess.run(cmd, cwd=PROJECT, capture_output=False, text=True)
    if check and result.returncode != 0:
        print(f"[FAIL] {label} failed with code {result.returncode}")
        if run_id and state is not None and phase:
            state[phase] = "failed"
            save_run_state(run_id, state)
        sys.exit(1)
    print(f"[OK] {label} done")
    return result

def ensure_dir(path):
    path.mkdir(parents=True, exist_ok=True)

def load_run_state(run_id):
    state_file = RUNS / run_id / "state.json"
    if state_file.exists():
        return json.loads(state_file.read_text())
    return {}

def save_run_state(run_id, state):
    ensure_dir(RUNS / run_id)
    (RUNS / run_id / "state.json").write_text(json.dumps(state, indent=2))

def discovered_subs_path(run_id):
    return RUNS / run_id / "subreddits.txt"

def parse_scout_subs(output):
    """Extract the machine-readable --subs value printed by scout_subreddits."""
    match = re.search(r"--subs\s+([A-Za-z0-9_,.-]+)", output or "")
    if not match:
        return []
    return [s.strip() for s in match.group(1).split(",") if s.strip()]

def load_discovered_subs(run_id):
    path = discovered_subs_path(run_id)
    if not path.exists():
        return []
    return [s.strip() for s in path.read_text(encoding="utf-8").split(",") if s.strip()]

def mark_phase_done(run_id, state, phase):
    state[phase] = "done"
    save_run_state(run_id, state)

def fail_phase(run_id, state, phase, message, code=1):
    print(message)
    state[phase] = "failed"
    save_run_state(run_id, state)
    sys.exit(code or 1)

# ── Phases ───────────────────────────────────────────────────────────────────

PHASES = ["seed", "scout", "fetch", "normalize", "gap"]

def run_phase_seed(args, run_id, state):
    """Phase 1: Generate seed keywords."""
    if args.keywords:
        print("[SKIP] Using provided keywords, skipping seed_factory")
        mark_phase_done(run_id, state, "seed")
        return
    if args.topic:
        cmd = [
            "python3", "seed_factory.py",
            "--source", "llm",
            "--topic", args.topic,
            "--count", str(args.seed_count),
            "--append",
        ]
    else:
        cmd = [
            "python3", "seed_factory.py",
            "--source", "google",
            "--append",
        ]
    run(cmd, "PHASE 1: seed_factory", run_id=run_id, state=state, phase="seed")
    mark_phase_done(run_id, state, "seed")

def run_phase_scout(args, run_id, state):
    """Phase 2: Scout subreddits from seeds."""
    if args.subs:
        print("[SKIP] Using provided subreddits, skipping subreddit scout")
        mark_phase_done(run_id, state, "scout")
        return

    if args.keywords:
        keywords = args.keywords
        print(f"[PHASE 2] Using provided keywords: {keywords[:80]}...")
    else:
        if not SEED_FILE.exists():
            print("[ERROR] seed_topics.txt not found. Run seed phase first.")
            sys.exit(1)
        seeds = [l.strip() for l in SEED_FILE.read_text().splitlines()
                 if l.strip() and not l.startswith("#")]
        keywords = ",".join(seeds[: args.max_seeds])

    if not keywords:
        fail_phase(run_id, state, "scout", "[ERROR] No keywords available for subreddit scouting.")

    cmd = ["python3", "scout_subreddits.py", keywords, "--limit", str(args.max_seeds)]
    print(f"\n[PHASE 2] Keywords: {keywords[:100]}...")
    result = subprocess.run(cmd, cwd=PROJECT, capture_output=True, text=True)
    print(result.stdout[-2000:] if result.stdout else "")
    if result.returncode != 0:
        fail_phase(run_id, state, "scout", f"[FAIL] scout_subreddits returned {result.returncode}", result.returncode)

    discovered = parse_scout_subs(result.stdout)
    if not discovered:
        fail_phase(run_id, state, "scout", "[ERROR] No subreddits discovered; refusing to fetch from a fallback subreddit.")

    ensure_dir(RUNS / run_id)
    discovered_subs_path(run_id).write_text(",".join(discovered), encoding="utf-8")
    print(f"[OK] Saved discovered subreddits: {','.join(discovered)}")
    mark_phase_done(run_id, state, "scout")

def run_phase_fetch(args, run_id, state):
    """Phase 3: Fetch Reddit data via rss_miner."""
    discovered_subs = load_discovered_subs(run_id)
    subs = args.subs or ",".join(discovered_subs) or args.niche_type
    cmd = [
        "python3", "rss_miner.py",
        "--mode", "fetch",
        "--niche_type", args.niche_type,
        "--subs", subs,
        "--max_posts", str(args.max_posts),
        "--out", str(DATA / f"{run_id}_raw.jsonl"),
        "--seen", str(DATA / f"{run_id}_seen_post_ids.txt"),
        "--include_comments",
        "--include_top",
        "--include_search",
        "--t", "month",
        "--sleep", "1.5",
    ]
    if args.prefix:
        cmd.extend(["--prefix", args.prefix])
    if args.keywords:
        cmd.extend(["--keywords", args.keywords])
    if args.only_pain_points:
        cmd.append("--only_pain_points")

    result = subprocess.run(cmd, cwd=PROJECT, capture_output=True, text=True)
    print(result.stdout[-3000:] if result.stdout else "")
    if result.returncode != 0:
        fail_phase(run_id, state, "fetch", f"[FAIL] rss_miner returned {result.returncode}", result.returncode)
    mark_phase_done(run_id, state, "fetch")

def run_phase_normalize(args, run_id, state):
    """Phase 4: Normalize raw JSONL."""
    raw = DATA / f"{run_id}_raw.jsonl"
    if not raw.exists():
        fail_phase(run_id, state, "normalize", f"[ERROR] Raw file not found: {raw}")
    cmd = [
        "python3", "normalize_reddit_jsonl.py",
        "--input", str(raw),
        "--output", str(DATA / f"{run_id}_normalized.jsonl"),
    ]
    run(cmd, "PHASE 4: normalize", run_id=run_id, state=state, phase="normalize")
    mark_phase_done(run_id, state, "normalize")

def run_phase_gap(args, run_id, state):
    """Phase 5: Gap analysis with NetworkX."""
    if args.input:
        normalized = Path(args.input)
    else:
        normalized = DATA / f"{args.run_id}_normalized.jsonl"
    if not normalized.exists():
        fail_phase(run_id, state, "gap", f"[ERROR] Normalized file not found: {normalized}")
    gap_output = DATA / f"{args.run_id}_gaps.json"
    cmd = [
        "python3", "gap_analysis.py",
        "--input", str(normalized),
        "--output", str(gap_output),
        "--top", str(args.top_gaps),
        "--min-degree", str(args.min_degree),
    ]
    if args.viz:
        cmd.append("--viz")
    run(cmd, "PHASE 5: gap_analysis", run_id=run_id, state=state, phase="gap")
    mark_phase_done(run_id, state, "gap")

# ── CLI ──────────────────────────────────────────────────────────────────────

def parse_args():
    p = argparse.ArgumentParser(description="Trash Miner Pipeline Orchestrator")
    p.add_argument("--run_id", default=None, help="Unique run ID (auto-generated if omitted)")
    p.add_argument("--topic", default=None, help="Topic for seed_factory (LLM brainstorming)")
    p.add_argument("--keywords", default=None, help="Comma-separated keywords for Reddit scouting (bypasses seed_factory)")
    p.add_argument("--niche_type", default="saas",
                   choices=NICHE_TYPES, help="Niche type for query packs")
    p.add_argument("--prefix", default=None, help="Optional keyword prefix")
    p.add_argument("--subs", default=None, help="Comma-separated subreddits to target")
    p.add_argument("--resume", action="store_true", help="Resume from last incomplete phase")
    p.add_argument("--phase", default=None, choices=PHASES, help="Run only a specific phase")
    # seed phase
    p.add_argument("--seed_count", type=int, default=10, help="Number of seeds to generate")
    p.add_argument("--max_seeds", type=int, default=20, help="Max seeds to use for scouting")
    # fetch phase
    p.add_argument("--max_posts", type=int, default=10, help="Max posts per subreddit")
    p.add_argument("--only_pain_points", action="store_true", help="Only save pain-point-ish Reddit posts")
    # gap phase
    p.add_argument("--top_gaps", type=int, default=20, help="Number of top gaps to report")
    p.add_argument("--min_degree", type=int, default=3, help="Min keyword degree for gap graph")
    p.add_argument("--viz", action="store_true", help="Generate PNG visualization")
    p.add_argument("--input", default=None, help="Override input file for gap phase")
    p.add_argument("--skip_seed", action="store_true", help="Skip seed phase")
    p.add_argument("--skip_gap", action="store_true", help="Skip gap analysis")
    p.add_argument("--skip_scout", action="store_true", help="Skip scout phase")
    return p.parse_args()

# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    args = parse_args()
    ensure_dir(DATA)
    ensure_dir(RUNS)

    # Generate run_id
    if args.resume or args.phase:
        if not args.run_id:
            print("[ERROR] --run_id required with --resume or --phase")
            sys.exit(1)
    else:
        import datetime
        ts = datetime.datetime.now().strftime("%Y%m%d")
        topic_slug = args.topic.lower().replace(" ", "_")[:20] if args.topic else args.niche_type
        args.run_id = args.run_id or f"{ts}_{topic_slug}"

    print(f"\n{'='*60}")
    print(f"  TRASH MINER PIPELINE — {args.run_id}")
    print(f"{'='*60}")
    print(f"  Topic:      {args.topic or '(from seeds)'}")
    print(f"  Niche type: {args.niche_type}")
    print(f"  Subs:       {args.subs or args.niche_type}")
    print(f"  Run ID:     {args.run_id}")
    print(f"  Output dir: {DATA}")
    print(f"  Viz:        {args.viz}")
    print('='*60)

    if args.resume:
        state = load_run_state(args.run_id)
        if not state:
            print(f"[WARN] No saved state for {args.run_id}, starting fresh")
            state = {}
    else:
        state = {}

    # Phase routing
    if args.phase:
        phase_fn = {
            "seed": run_phase_seed,
            "scout": run_phase_scout,
            "fetch": run_phase_fetch,
            "normalize": run_phase_normalize,
            "gap": run_phase_gap,
        }
        print(f"\n[RUNNING SINGLE PHASE]: {args.phase}")
        phase_fn[args.phase](args, args.run_id, state)
        print(f"\n[DONE] Phase {args.phase} complete")
        sys.exit(0)

    phase_fns = {
        "seed": run_phase_seed,
        "scout": run_phase_scout,
        "fetch": run_phase_fetch,
        "normalize": run_phase_normalize,
        "gap": run_phase_gap,
    }
    skipped = set()
    if args.skip_seed:
        skipped.add("seed")
    if args.skip_scout:
        skipped.add("scout")
    if args.skip_gap:
        skipped.add("gap")

    # Sequential pipeline. State is updated after each phase, so fresh runs do
    # not stop early because downstream phases were planned from stale state.
    phases_to_run = [
        (phase, phase_fns[phase])
        for phase in PHASES
        if phase not in skipped and state.get(phase) != "done"
    ]

    if not phases_to_run:
        print("[INFO] All phases already complete. Use --resume to re-run gap analysis.")
        print(f"\nResults:")
        print(f"  Normalized data: {DATA}/{args.run_id}_normalized.jsonl")
        print(f"  Gaps:            {DATA}/{args.run_id}_gaps.json")
        sys.exit(0)

    for phase_name, phase_fn in phases_to_run:
        print(f"\n\n{'#'*60}")
        print(f"# PHASE: {phase_name.upper()}")
        print(f"{'#'*60}")
        phase_fn(args, args.run_id, state)
        time.sleep(0.5)

    print(f"\n\n{'='*60}")
    print(f"  PIPELINE COMPLETE — {args.run_id}")
    print(f"{'='*60}")
    print(f"\nOutputs:")
    print(f"  Raw:     {DATA}/{args.run_id}_raw.jsonl")
    print(f"  Normal:  {DATA}/{args.run_id}_normalized.jsonl")
    print(f"  Gaps:    {DATA}/{args.run_id}_gaps.json")
    if args.viz:
        print(f"  Graph:   {DATA}/{args.run_id}_gaps.png")
    print(f"\nState saved: {RUNS}/{args.run_id}/state.json")
    print(f"\nResume: python3 pipeline.py --resume --run_id {args.run_id}")

if __name__ == "__main__":
    main()
