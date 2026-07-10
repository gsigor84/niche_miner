#!/usr/bin/env python3
"""
gap_analysis.py — Find structural gaps in topic networks using NetworkX

Takes normalized JSONL data → builds co-occurrence graph → identifies gaps.

Usage:
    python3 gap_analysis.py --input data/party_tickets_normalized.jsonl --output data/party_tickets_gaps.json
    python3 gap_analysis.py --input data/party_tickets_normalized.jsonl --viz --output data/party_tickets_gaps.png
"""

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

import networkx as nx
import numpy as np

# ── CLI ──────────────────────────────────────────────────────────────────────

def parse_args():
    p = argparse.ArgumentParser(description="Topic gap analysis with NetworkX")
    p.add_argument("--input", "-i", required=True, help="Normalized JSONL input file")
    p.add_argument("--output", "-o", default=None, help="JSON output file for gaps")
    p.add_argument("--viz", "-v", action="store_true", help="Generate PNG visualization")
    p.add_argument("--top", "-t", type=int, default=20, help="Number of top gaps to report")
    p.add_argument("--min-degree", "-d", type=int, default=2, help="Min degree to appear in graph")
    return p.parse_args()

# ── Text processing ───────────────────────────────────────────────────────────

STOPWORDS = {
    "i", "me", "my", "myself", "we", "our", "ours", "ourselves", "you", "your",
    "yours", "yourself", "yourselves", "he", "him", "his", "himself", "she",
    "her", "hers", "herself", "it", "its", "itself", "they", "them", "their",
    "theirs", "themselves", "what", "which", "who", "whom", "this", "that",
    "these", "those", "am", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "having", "do", "does", "did", "doing", "a", "an",
    "the", "and", "but", "if", "or", "because", "as", "until", "while", "of",
    "at", "by", "for", "with", "about", "against", "between", "into", "through",
    "during", "before", "after", "above", "below", "to", "from", "up", "down",
    "in", "out", "on", "off", "over", "under", "again", "further", "then",
    "once", "here", "there", "when", "where", "why", "how", "all", "each",
    "few", "more", "most", "other", "some", "such", "no", "nor", "not",
    "only", "own", "same", "so", "than", "too", "very", "s", "t", "can",
    "will", "just", "don", "should", "now", "d", "ll", "m", "o", "re", "ve",
    "y", "ain", "aren", "couldn", "didn", "doesn", "hadn", "hasn", "haven",
    "isn", "ma", "mightn", "mustn", "needn", "shan", "shouldn", "wasn",
    "weren", "won", "wouldn",
    # Extra noise
    "like", "just", "know", "think", "get", "got", "go", "going", "one",
    "would", "could", "also", "even", "really", "want", "need", "use",
    "used", "using", "make", "made", "said", "say", "says", "see", "look",
    "looking", "way", "thing", "things", "lot", "many", "much", "well",
    "back", "still", "take", "come", "came", "let", "first", "new", "good",
    "bad", "big", "small", "right", "wrong", "best", "worst", "high", "low",
    "sure", "maybe", "actually", "probably", "definitely", "always", "never",
}

def extract_keywords(text, top_n=50):
    """Extract significant word bigrams from text."""
    text = text.lower()
    # Remove URLs
    text = re.sub(r"https?://\S+", " ", text)
    # Remove noise patterns
    text = re.sub(r"[^a-z\s]", " ", text)
    words = [w for w in text.split() if len(w) > 3 and w not in STOPWORDS]
    # Bigrams (only if words are meaningful)
    bigrams = []
    for i in range(len(words) - 1):
        w1, w2 = words[i], words[i+1]
        # Skip if either word is mostly numeric or URL-like
        if not any(c.isdigit() for c in w1) and not any(c.isdigit() for c in w2):
            bigrams.append(f"{w1}_{w2}")
    # Count both
    unigram_counts = Counter(words)
    bigram_counts = Counter(bigrams)
    # Combine: unigrams + bigrams weighted
    combined = {}
    for w, c in unigram_counts.items():
        combined[w] = c
    for b, c in bigram_counts.items():
        combined[b] = c + combined.get(b, 0)
    # Return top keywords appearing at least 2 times
    return [k for k, v in sorted(combined.items(), key=lambda x: -x[1]) if v >= 2][:top_n]

# ── Graph building ─────────────────────────────────────────────────────────────

def build_graph(posts, min_degree=2):
    """Build co-occurrence graph from posts."""
    G = nx.Graph()
    keyword_sets = []
    
    for post in posts:
        # Extract real text: title + summary + comment texts
        parts = [post.get('title', ''), post.get('summary', '')]
        # Comments are a list of dicts with 'text' field — limit total text
        for comment in post.get('comments', []):
            if isinstance(comment, dict) and comment.get('text'):
                parts.append(comment['text'][:500])  # limit each comment
        text = ' '.join(parts)[:3000]  # cap total text per post
        keywords = extract_keywords(text)
        keyword_sets.append(set(keywords))
        for kw in keywords:
            G.add_node(kw, count=G.nodes.get(kw, {}).get("count", 0) + 1)
    
    # Co-occurrence edges
    for kws in keyword_sets:
        kws = list(kws)
        for i in range(len(kws)):
            for j in range(i + 1, len(kws)):
                w1, w2 = kws[i], kws[j]
                if G.has_edge(w1, w2):
                    G[w1][w2]["weight"] += 1
                else:
                    G.add_edge(w1, w2, weight=1)
    
    # Remove low-degree nodes
    for node in list(G.nodes()):
        if G.degree(node) < min_degree:
            G.remove_node(node)
    
    return G

# ── Gap detection ─────────────────────────────────────────────────────────────

def find_gaps(G):
    """Find structural gaps using fast degree + pagerank metrics."""
    if G.number_of_nodes() == 0:
        return []
    
    # Fast metrics only
    degree_dict = dict(G.degree())
    pagerank = nx.pagerank(G)
    
    max_degree = max(degree_dict.values()) or 1
    max_pr = max(pagerank.values()) or 1
    
    gaps = []
    for node in G.nodes():
        d = degree_dict[node]
        pr = pagerank[node]
        gaps.append({
            "keyword": node,
            "degree": d,
            "pagerank": round(pr, 6),
            "count": G.nodes[node].get("count", 1),
        })
    
    # Gap score: high importance (pagerank) but underserved (low degree)
    # = topics that matter but have little competition
    for g in gaps:
        g["degree_norm"] = round(g["degree"] / max_degree, 4)
        g["pagerank_norm"] = round(g["pagerank"] / max_pr, 4)
        # Gap = high relevance but low competition
        g["gap_score"] = round(g["pagerank_norm"] * (1 - g["degree_norm"]) * 100, 4)
    
    gaps.sort(key=lambda x: x["gap_score"], reverse=True)
    
    for g in gaps:
        g["cluster"] = -1
    
    return gaps

def find_dense_clusters(G):
    """Find the densest connected components."""
    if G.number_of_nodes() == 0:
        return {}
    
    # Largest connected component
    try:
        largest_cc = max(nx.connected_components(G), key=len)
        subgraph = G.subgraph(largest_cc).copy()
        largest_size = len(largest_cc)
        density = round(nx.density(subgraph), 6)
    except Exception:
        largest_size = G.number_of_nodes()
        density = round(nx.density(G), 6)
    
    # Skip expensive clique detection for large graphs
    return {
        "total_nodes": G.number_of_nodes(),
        "total_edges": G.number_of_edges(),
        "largest_component_size": largest_size,
        "density": density,
        "note": "clique detection skipped (too slow for large graphs)"
    }

# ── Visualization ───────────────────────────────────────────────────────────────

def visualize(G, gaps, output_path="gaps.png"):
    """Generate PNG visualization of the topic network."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.patches as mpatches
    except ImportError:
        print("matplotlib not installed. Run: pip install matplotlib")
        return
    
    fig, ax = plt.subplots(1, 1, figsize=(16, 12))
    
    # For large graphs, limit to top 100 nodes by degree for readability
    n = G.number_of_nodes()
    if n > 100:
        print(f"Limiting visualization to top 100 nodes (from {n})")
        top_nodes = sorted(G.nodes(), key=lambda x: G.degree(x), reverse=True)[:100]
        G = G.subgraph(top_nodes).copy()
    
    # Layout — use spring for small graphs, circular for large ones
    if G.number_of_nodes() <= 200:
        pos = nx.spring_layout(G, k=1.5, iterations=30, seed=42)
    else:
        print(f"Using circular layout for {G.number_of_nodes()} nodes")
        pos = nx.circular_layout(G)
    
    # Color by gap score
    gap_dict = {g["keyword"]: g["gap_score"] for g in gaps}
    max_gap = max(gap_dict.values()) if gap_dict else 1
    
    node_colors = []
    node_sizes = []
    for node in G.nodes():
        score = gap_dict.get(node, 0)
        # Red = high gap opportunity, Blue = well-connected
        node_colors.append(score / max_gap if max_gap > 0 else 0)
        node_sizes.append(300 + score * 2000)
    
    # Edges
    edge_weights = [G[u][v].get("weight", 1) * 0.3 for u, v in G.edges()]
    
    nx.draw_networkx_edges(G, pos, alpha=0.2, width=edge_weights, ax=ax)
    
    # Nodes
    scatter = nx.draw_networkx_nodes(
        G, pos,
        node_color=node_colors,
        node_size=node_sizes,
        cmap=plt.cm.RdYlBu_r,
        alpha=0.8,
        ax=ax
    )
    
    # Labels for top gap keywords only
    top_kw = {g["keyword"]: g["keyword"].replace("_", " ") for g in gaps[:15]}
    nx.draw_networkx_labels(G, pos, labels=top_kw, font_size=8, ax=ax)
    
    plt.colorbar(scatter, label="Gap Opportunity Score", ax=ax)
    ax.set_title("Topic Network — Structural Gaps (red = gap opportunity)", fontsize=14)
    ax.axis("off")
    
    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches="tight")
    print(f"Visualization saved to {output_path}")

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    args = parse_args()
    
    # Load posts
    posts = []
    with open(args.input, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                posts.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    
    if not posts:
        print(f"No posts loaded from {args.input}")
        sys.exit(1)
    
    print(f"Loaded {len(posts)} posts")
    
    # Build graph
    print("Building co-occurrence graph...")
    G = build_graph(posts, min_degree=args.min_degree)
    print(f"Graph: {G.number_of_nodes()} nodes, {G.number_of_edges()} edges")
    
    # Find gaps
    print("Finding structural gaps...")
    gaps = find_gaps(G)
    
    # Cluster analysis
    cluster_info = find_dense_clusters(G)
    print(f"\nGraph stats: {cluster_info.get('total_nodes',0)} nodes, {cluster_info.get('total_edges',0)} edges")
    print(f"Density: {cluster_info.get('density',0)}")
    
    # Top gaps
    print(f"\n=== TOP {args.top} GAP OPPORTUNITIES ===")
    print(f"{'Rank':<5} {'Keyword':<30} {'Gap Score':<12} {'Pagerank':<12} {'Degree':<8}")
    print("-" * 70)
    for i, g in enumerate(gaps[:args.top], 1):
        print(f"{i:<5} {g['keyword']:<30} {g['gap_score']:<12} {g['pagerank']:<12} {g['degree']:<8}")
    
    # Save
    result = {
        "total_posts": len(posts),
        "graph_stats": {
            "nodes": G.number_of_nodes(),
            "edges": G.number_of_edges(),
        },
        "cluster_analysis": cluster_info,
        "top_gaps": gaps[:args.top],
        "all_gaps": gaps,
    }
    
    if args.output:
        output_path = args.output
        with open(output_path, "w") as f:
            json.dump(result, f, indent=2)
        print(f"\nResults saved to {output_path}")
    
    # Visualize
    if args.viz:
        viz_path = args.output.replace(".json", ".png") if args.output else "gaps.png"
        visualize(G, gaps, viz_path)
    
    print("\nDone.")

if __name__ == "__main__":
    main()
