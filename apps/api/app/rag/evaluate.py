"""Measure retrieval quality against a labelled question set.

    python -m app.rag.evaluate [--dataset ../../tests/fixtures/rag_eval.yml] [--k 5]

Metrics (document level: a hit is any returned chunk from the expected source):
  hit@1, hit@k   share of questions whose expected document is ranked 1st / in top k
  MRR            mean reciprocal rank of the expected document (0 if not in top k)
  threshold recall   share of questions whose expected document also clears the
                     similarity threshold (what the agent actually receives)
  off-topic clean    share of off-topic questions that return nothing above the
                     threshold (empty retrieval instead of irrelevant context)
"""

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

import yaml

from app.config import get_settings
from app.rag.retrieval import RetrievalService


@dataclass
class EvalReport:
    questions: int
    k: int
    threshold: float
    hit_at_1: float
    hit_at_k: float
    mrr: float
    threshold_recall: float
    off_topic_clean: float
    misses: list[dict] = field(default_factory=list)


def reciprocal_rank(sources: list[str], expected: str) -> float:
    for rank, source in enumerate(sources, start=1):
        if source == expected:
            return 1.0 / rank
    return 0.0


async def evaluate(
    service: RetrievalService, dataset: dict, k: int, threshold: float
) -> EvalReport:
    relevant = dataset["relevant"]
    hits1 = hitsk = rr = above = 0.0
    misses = []
    for case in relevant:
        ranked = await service.retrieve(
            case["question"], top_k=k, min_score=0.0, services=case.get("services")
        )
        sources = list(dict.fromkeys(c.source for c in ranked))  # first occurrence order
        score = reciprocal_rank(sources, case["expected"])
        rr += score
        hits1 += score == 1.0
        hitsk += score > 0
        best = max((c.score for c in ranked if c.source == case["expected"]), default=0.0)
        above += best >= threshold
        if score < 1.0:
            misses.append(
                {"question": case["question"], "expected": case["expected"], "got": sources[:3]}
            )

    clean = 0
    for question in dataset.get("off_topic", []):
        clean += not await service.retrieve(question, top_k=k, min_score=threshold)

    n = len(relevant)
    off = len(dataset.get("off_topic", [])) or 1
    return EvalReport(
        questions=n,
        k=k,
        threshold=threshold,
        hit_at_1=round(hits1 / n, 3),
        hit_at_k=round(hitsk / n, 3),
        mrr=round(rr / n, 3),
        threshold_recall=round(above / n, 3),
        off_topic_clean=round(clean / off, 3),
        misses=misses,
    )


async def _main(dataset_path: Path, k: int) -> EvalReport:
    from app.db.session import build_engine, build_session_factory
    from app.rag.embeddings import build_embedder

    settings = get_settings()
    dataset = yaml.safe_load(dataset_path.read_text(encoding="utf-8"))
    engine = build_engine(settings)
    try:
        async with build_session_factory(engine)() as session:
            service = RetrievalService(session, build_embedder(settings), settings)
            return await evaluate(service, dataset, k, settings.rag_similarity_threshold)
    finally:
        await engine.dispose()


def _log_to_stderr() -> None:
    """Keep stdout for the JSON report so it can be piped (e.g. into jq)."""
    import sys

    import structlog

    structlog.configure(logger_factory=structlog.PrintLoggerFactory(sys.stderr))


def main() -> None:
    _log_to_stderr()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=Path("../../tests/fixtures/rag_eval.yml"))
    parser.add_argument("--k", type=int, default=5)
    args = parser.parse_args()
    report = asyncio.run(_main(args.dataset, args.k))
    print(json.dumps(asdict(report), indent=2))  # noqa: T201 - CLI output


if __name__ == "__main__":
    main()
