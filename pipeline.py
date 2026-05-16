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

def run(cmd, label, check=True):
    print(f"\n{'='*60}")
    print(f"  [{label}] {' '.join(cmd)}")
    print('='*60)
    result = subprocess.run(cmd, cwd=PROJECT, capture_output=False, text=True)
    if check and result.returncode != 0:
        print(f"[FAIL] {label} failed with code {result.returncode}")
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

def next_unfinished_phase(state, phases):
    """Return the next phase not yet marked 'done'."""
    for p in phases:
        if state.get(p) != "done":
            return p
    return None

# ── Phases ───────────────────────────────────────────────────────────────────

PHASES = ["seed", "scout", "fetch", "normalize", "gap"]

def run_phase_seed(args, run_id, state):
    """Phase 1: Generate seed keywords."""
    if args.keywords:
        print("[SKIP] Using provided keywords, skipping seed_factory")
        state["seed"] = "done"
        save_run_state(run_id, state)
        return
    if args.topic:
        cmd = [
            "python3", "seed_factory.py",
            "--source", "llm",
            "--topic", args.topic,
            "--count", str(args.seed_count),
        ]
    else:
        cmd = [
            "python3", "seed_factory.py",
            "--source", "google",
        ]
    run(cmd, "PHASE 1: seed_factory")
    state["seed"] = "done"
    save_run_state(run_id, state)

def run_phase_scout(args, run_id, state):
    """Phase 2: Scout subreddits from seeds."""
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

    print(f"\n[PHASE 2] Keywords: {keywords[:100]}...")
    cmd = [
        "python3", "scout_subreddits.py",
        keywords,
        "--limit", str(args.max_seeds),
    ]
    run(cmd, "PHASE 2: scout_subreddits")
    state["scout"] = "done"
    save_run_state(run_id, state)

def run_phase_fetch(args, run_id, state):
    """Phase 3: Fetch Reddit data via rss_miner."""
    cmd = [
        "python3", "rss_miner.py",
        "--mode", "fetch",
        "--niche_type", args.niche_type,
        "--subs", args.subs or args.niche_type,
        "--max_posts", str(args.max_posts),
        "--out", f"data/{args.run_id}_raw.jsonl",
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
    run(cmd, "PHASE 3: rss_miner")
    state["fetch"] = "done"
    save_run_state(run_id, state)

def run_phase_normalize(args, run_id, state):
    """Phase 4: Normalize raw JSONL."""
    raw = DATA / f"{args.run_id}_raw.jsonl"
    if not raw.exists():
        print(f"[ERROR] Raw file not found: {raw}")
        sys.exit(1)
    cmd = [
        "python3", "normalize_reddit_jsonl.py",
        "--input", str(raw),
        "--output", str(DATA / f"{args.run_id}_normalized.jsonl"),
    ]
    run(cmd, "PHASE 4: normalize")
    state["normalize"] = "done"
    save_run_state(run_id, state)

def run_phase_gap(args, run_id, state):
    """Phase 5: Gap analysis with NetworkX."""
    if args.input:
        normalized = Path(args.input)
    else:
        normalized = DATA / f"{args.run_id}_normalized.jsonl"
    if not normalized.exists():
        print(f"[ERROR] Normalized file not found: {normalized}")
        sys.exit(1)
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
    run(cmd, "PHASE 5: gap_analysis")
    state["gap"] = "done"
    save_run_state(run_id, state)

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
    p.add_argument("--only_pain_points", action="store_true", help="Only save pain-point-ish posts")
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

    # Sequential pipeline
    if args.keywords:
        # keywords provided: skip seed_factory
        state["seed"] = "done"
        save_run_state(args.run_id, state)

    ordered_phases = [
        ("seed", run_phase_seed, args.skip_seed or bool(args.keywords)),
        ("scout", run_phase_scout, args.skip_scout),
        ("fetch", run_phase_fetch, False),
        ("normalize", run_phase_normalize, False),
        ("gap", run_phase_gap, args.skip_gap),
    ]
    phases_to_run = [
        (phase_name, phase_fn)
        for phase_name, phase_fn, skip_phase in ordered_phases
        if not skip_phase and state.get(phase_name) != "done"
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
