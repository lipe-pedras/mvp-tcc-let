"""Evaluation harness.

    cd backend
    uv run python -m eval.run --questions eval/questions.example.jsonl --mode so_busca

Modes:
  so_busca          retrieval only (Recall@k, MRR, leakage)         [implemented]
  rag               full system                                     [phase 3]
  sem_recuperacao   LLM answers with no passages (contamination)    [phase 3]
"""

import argparse
import csv
import statistics
import time
from datetime import datetime
from pathlib import Path

from sqlalchemy import select

from app.config import get_settings
from app.db import SessionLocal
from app.models import Document, Group
from app.providers.embeddings import get_embedding_provider
from app.services.retrieval.reranker import get_reranker
from app.services.retrieval.search import retrieve
from eval.dataset import Question, load_questions
from eval.metrics import RetrievedChunk, leaked_chunks, mean, recall_at_k, reciprocal_rank

KS = (1, 3, 5)
RESULTS_DIR = Path(__file__).parent / "results"


def run_so_busca(questions: list[Question]) -> tuple[list[dict], dict]:
    s = get_settings()
    embedder, reranker = get_embedding_provider(), get_reranker()
    rows = []
    with SessionLocal() as db:
        group_ids = {g.name: g.id for g in db.scalars(select(Group))}
        docs = {d.id: d for d in db.scalars(select(Document))}
        for q in questions:
            missing = [g for g in q.grupos if g not in group_ids]
            if missing:
                raise SystemExit(f"{q.id}: grupos inexistentes no banco: {missing}")
            profile = {group_ids[g] for g in q.grupos}

            t0 = time.perf_counter()
            hits = retrieve(
                db, q.pergunta, profile, embedder, reranker,
                candidates=s.retrieval_candidates, rerank_top_n=s.rerank_top_n,
            )
            elapsed_ms = (time.perf_counter() - t0) * 1000

            ranked = [
                RetrievedChunk(
                    doc_title=docs[h.chunk.document_id].title,
                    section_path=h.chunk.section_path,
                    chunk_group_ids=frozenset(h.chunk.group_ids),
                    doc_group_ids=frozenset(docs[h.chunk.document_id].group_ids),
                )
                for h in hits
            ]
            top_score = hits[0].rerank_score if hits else 0.0
            rows.append(
                {
                    "id": q.id,
                    "tipo": q.tipo,
                    "pergunta": q.pergunta,
                    **{f"recall@{k}": recall_at_k(ranked, q.evidencias, k) for k in KS},
                    "rr": reciprocal_rank(ranked, q.evidencias),
                    "vazamentos": leaked_chunks(ranked, profile),
                    "top_score": round(top_score, 4),
                    "recusaria": top_score < s.refusal_threshold,
                    "retrieval_ms": round(elapsed_ms),
                    "top_resultados": " | ".join(
                        f"{r.doc_title} > {r.section_path} ({h.rerank_score:.3f})"
                        for r, h in list(zip(ranked, hits))[:5]
                    ),
                    "evidencias_esperadas": "; ".join(f"{e['documento']} > {e.get('secao', '')}" for e in q.evidencias),
                }
            )
    return rows, summarize(rows)


def summarize(rows: list[dict]) -> dict:
    with_ev = [r for r in rows if r["rr"] is not None]
    by = lambda tipo: [r for r in rows if r["tipo"] == tipo]  # noqa: E731
    sem, com, vaz = by("sem_resposta"), by("com_resposta"), by("vazamento")
    latencies = [r["retrieval_ms"] for r in rows]
    return {
        "n_perguntas": len(rows),
        "n_com_evidencia": len(with_ev),
        **{f"recall@{k}": mean([r[f"recall@{k}"] for r in with_ev]) for k in KS},
        "mrr": mean([r["rr"] for r in with_ev]),
        # Refusal quality at the configured threshold, judged from the reranker score alone.
        "recusa_correta_sem_resposta": (sum(r["recusaria"] for r in sem) / len(sem)) if sem else None,
        "recusa_indevida_com_resposta": (sum(r["recusaria"] for r in com) / len(com)) if com else None,
        "perguntas_vazamento": len(vaz),
        "vazamentos_total": sum(r["vazamentos"] for r in rows),
        "taxa_vazamento": (sum(r["vazamentos"] > 0 for r in vaz) / len(vaz)) if vaz else None,
        "latencia_busca_ms_mediana": statistics.median(latencies) if latencies else None,
    }


def fmt(v) -> str:
    return "n/d" if v is None else (f"{v:.3f}" if isinstance(v, float) else str(v))


def write_outputs(rows: list[dict], summary: dict, mode: str, questions_path: Path) -> tuple[Path, Path]:
    s = get_settings()
    RESULTS_DIR.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    csv_path, md_path = RESULTS_DIR / f"{stamp}-{mode}.csv", RESULTS_DIR / f"{stamp}-{mode}.md"

    with csv_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]) + ["anotacao_humana"])
        w.writeheader()
        w.writerows(rows)

    lines = [
        f"# Avaliação — modo `{mode}`",
        "",
        f"- Data: {datetime.now():%Y-%m-%d %H:%M}",
        f"- Perguntas: `{questions_path}` ({summary['n_perguntas']})",
        f"- Embeddings: `{s.embedding_model}` | Reranker: `{s.reranker_model}`",
        f"- Limiar de recusa: {s.refusal_threshold} | top-k: {s.top_k} | candidatos: {s.retrieval_candidates} | rerank top-n: {s.rerank_top_n}",
        "",
        "## Métricas",
        "",
        "| Métrica | Valor |",
        "|---|---|",
    ]
    lines += [f"| {k} | {fmt(v)} |" for k, v in summary.items()]
    lines += [
        "",
        "> `taxa_vazamento` deve ser **0**. A recusa é estimada só pelo score do reranker contra o limiar.",
        "",
        "## Por pergunta",
        "",
        "| id | tipo | rr | top_score | vazamentos | recusaria |",
        "|---|---|---|---|---|---|",
    ]
    lines += [f"| {r['id']} | {r['tipo']} | {fmt(r['rr'])} | {r['top_score']} | {r['vazamentos']} | {r['recusaria']} |" for r in rows]
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return csv_path, md_path


def main() -> None:
    ap = argparse.ArgumentParser(prog="eval.run")
    ap.add_argument("--questions", type=Path, required=True)
    ap.add_argument("--mode", choices=["rag", "sem_recuperacao", "so_busca"], required=True)
    args = ap.parse_args()

    if args.mode != "so_busca":
        raise SystemExit(f"Modo '{args.mode}' será implementado na Fase 3.")
    questions = load_questions(args.questions)
    rows, summary = run_so_busca(questions)
    csv_path, md_path = write_outputs(rows, summary, args.mode, args.questions)
    print(md_path.read_text(encoding="utf-8").split("## Por pergunta")[0])
    print(f"CSV: {csv_path}\nResumo: {md_path}")
    if summary["vazamentos_total"]:
        raise SystemExit("FALHA: houve vazamento de trechos sem permissão.")


if __name__ == "__main__":
    main()
