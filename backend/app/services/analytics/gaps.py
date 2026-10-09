"""Clustering of unanswered questions for the manager dashboard.

Privacy rule (k-anonymity): a cluster is returned only when it has at least K
occurrences, so a single person's one-off question can never be singled out.
Only the cluster's size, period and a few question texts leave this module;
no per-question rows, no user data (none exists in the gaps table).
"""

from dataclasses import dataclass
from datetime import date

import numpy as np


@dataclass(frozen=True)
class GapRecord:
    question: str
    embedding: np.ndarray
    day: date


@dataclass
class GapCluster:
    label: str  # the question closest to the cluster's centre
    count: int
    first_day: date
    last_day: date
    examples: list[str]  # distinct wordings, at most 3


def cluster_gaps(records: list[GapRecord], *, min_size: int, similarity: float, max_examples: int = 3) -> list[GapCluster]:
    """Greedy leader clustering by cosine similarity; returns clusters with >= min_size members."""
    if not records:
        return []
    vecs = np.array([r.embedding for r in records], dtype=np.float32)
    vecs /= np.linalg.norm(vecs, axis=1, keepdims=True).clip(min=1e-9)

    members: list[list[int]] = []
    centroids: list[np.ndarray] = []
    for i, v in enumerate(vecs):
        if centroids:
            sims = np.array(centroids) @ v
            best = int(sims.argmax())
            if sims[best] >= similarity:
                members[best].append(i)
                c = vecs[members[best]].mean(axis=0)
                centroids[best] = c / max(float(np.linalg.norm(c)), 1e-9)
                continue
        members.append([i])
        centroids.append(v)

    clusters = []
    for idx, centre in zip(members, centroids):
        if len(idx) < min_size:
            continue
        closest = idx[int((vecs[idx] @ centre).argmax())]
        texts = list(dict.fromkeys(records[i].question.strip() for i in idx))
        texts.remove(records[closest].question.strip())
        days = [records[i].day for i in idx]
        clusters.append(
            GapCluster(
                label=records[closest].question.strip(),
                count=len(idx),
                first_day=min(days),
                last_day=max(days),
                examples=texts[:max_examples],
            )
        )
    return sorted(clusters, key=lambda c: (-c.count, c.label))
