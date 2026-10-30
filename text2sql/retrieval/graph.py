"""One-hop outgoing-FK expansion over the unchanged hybrid retriever."""

import math
import re



HYBRID_SEED_COUNT = 10
FIXED_FK_BONUS = 0.20


def extract_outgoing_fk_targets(document_text):
    """Return targets from explicit outgoing FOREIGN KEY declarations only."""
    parts = re.split(r"(?:^|\n)Relationships:\s*\n", document_text, maxsplit=1)
    if len(parts) != 2:
        return []
    return re.findall(
        r"FOREIGN\s+KEY\s*\([^)]*\)\s+REFERENCES\s+"
        r"([A-Za-z0-9_]+\.[A-Za-z0-9_]+)",
        parts[1],
        flags=re.IGNORECASE,
    )


def build_outgoing_adjacency(documents):
    """Build source -> distinct indexed, non-self outgoing neighbors."""
    indexed_tables = {document["full_name"] for document in documents}
    adjacency = {}
    for document in documents:
        source = document["full_name"]
        targets = {
            target
            for target in extract_outgoing_fk_targets(document["text"])
            if target in indexed_tables and target != source
        }
        adjacency[source] = tuple(sorted(targets))
    return adjacency


def graph_signal(seed_rank, seed_hybrid_score):
    """Fixed rank-discounted signal from one directly referencing seed."""
    return seed_hybrid_score / math.log2(seed_rank + 1)


def expand_one_hop(seed_results, adjacency):
    """Collect seeds and direct outgoing neighbors without further traversal."""
    candidates = {result["full_name"] for result in seed_results}
    sources_by_candidate = {}
    for seed_rank, seed in enumerate(seed_results, start=1):
        source = seed["full_name"]
        for target in adjacency.get(source, ()):
            candidates.add(target)
            sources_by_candidate.setdefault(target, []).append({
                "table": source,
                "rank": seed_rank,
                "hybrid_score": seed["combined_score"],
            })
    return candidates, sources_by_candidate


def rank_expanded_candidates(
    all_hybrid_results,
    seed_results,
    adjacency,
    top_k,
):
    """Apply the fixed graph boost and enforce the requested final top_k."""
    if top_k <= 0:
        return [], 0

    by_name = {
        result["full_name"]: result
        for result in all_hybrid_results
    }
    seed_names = {result["full_name"] for result in seed_results}
    candidate_names, sources_by_candidate = expand_one_hop(
        seed_results,
        adjacency,
    )

    ranked = []
    for name in candidate_names:
        hybrid_result = by_name[name]
        sources = sorted(
            sources_by_candidate.get(name, []),
            key=lambda source: (source["rank"], source["table"]),
        )
        source_signals = [
            graph_signal(source["rank"], source["hybrid_score"])
            for source in sources
        ]
        best_signal = max(source_signals, default=0.0)
        best_source = None
        if source_signals:
            best_index = source_signals.index(best_signal)
            best_source = sources[best_index]
        bonus_contribution = FIXED_FK_BONUS * best_signal

        result = dict(hybrid_result)
        result.update({
            "hybrid_score": hybrid_result["combined_score"],
            "graph_signal": best_signal,
            "fk_bonus_contribution": bonus_contribution,
            "final_score": hybrid_result["combined_score"] + bonus_contribution,
            "is_hybrid_seed": name in seed_names,
            "source_seed_tables": [source["table"] for source in sources],
            "best_source_seed_rank": best_source["rank"] if best_source else None,
            "best_source_seed_hybrid_score": (
                best_source["hybrid_score"] if best_source else None
            ),
        })
        ranked.append(result)

    ranked.sort(
        key=lambda result: (
            result["final_score"],
            result["hybrid_score"],
            result["full_name"],
        ),
        reverse=True,
    )
    return ranked[:top_k], len(candidate_names)
