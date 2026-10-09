"""Evaluation harness.

    cd backend
    uv run python -m eval.run --questions eval/questions.example.jsonl --mode rag

Modes:
  so_busca          retrieval only (Recall@k, MRR, leakage, refusal estimated from the reranker score)
  rag               the full system (retrieval + LLM + citation validation)
  sem_recuperacao   the LLM answers with no passages: measures what the model already "knows"
                    about the corpus (prior-knowledge contamination)
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
from app.models import Chunk, Document, Group
from app.providers.embeddings import get_embedding_provider
from app.providers.llm import get_llm_provider
from app.services.chat.pipeline import chat
from app.services.chat.prompts import NO_CONTEXT_SYSTEM_PROMPT
from app.services.retrieval.reranker import get_reranker
from app.services.retrieval.search import retrieve
from eval.dataset import Question, load_questions
from eval.metrics import RetrievedChunk, leaked_chunks, mean, recall_at_k, reciprocal_rank

KS = (1, 3, 5)
RESULTS_DIR = Path(__file__).parent / "results"
SHOULD_REFUSE = {"sem_resposta", "vazamento"}  # question types for which refusing is correct


class Env:
    """Database lookups shared by all modes."""

    def __init__(self, db):
        self.db = db
        self.group_ids = {g.name: g.id for g in db.scalars(select(Group))}
        self.docs = {d.id: d for d in db.scalars(select(Document))}

    def profile(self, q: Question) -> set[int]:
        missing = [g for g in q.grupos if g not in self.group_ids]
        if missing:
            raise SystemExit(f"{q.id}: grupos inexistentes no banco: {missing}")
        return {self.group_ids[g] for g in q.grupos}

    def retrieved(self, chunk: Chunk) -> RetrievedChunk:
        doc = self.docs[chunk.document_id]
        return RetrievedChunk(
            doc_title=doc.title,
            section_path=chunk.section_path,
            chunk_group_ids=frozenset(chunk.group_ids),
            doc_group_ids=frozenset(doc.group_ids),
        )


def _expected(q: Question) -> str:
    return "; ".join(f"{e['documento']} > {e.get('secao', '')}" for e in q.evidencias)


def _retrieval_metrics(ranked: list[RetrievedChunk], q: Question) -> dict:
    return {
        **{f"recall@{k}": recall_at_k(ranked, q.evidencias, k) for k in KS},
        "rr": reciprocal_rank(ranked, q.evidencias),
    }


# --- so_busca -------------------------------------------------------------------------------------

def run_so_busca(questions: list[Question]) -> tuple[list[dict], dict]:
    s = get_settings()
    embedder, reranker = get_embedding_provider(), get_reranker()
    rows = []
    with SessionLocal() as db:
        env = Env(db)
        for q in questions:
            profile = env.profile(q)
            t0 = time.perf_counter()
            hits = retrieve(
                db, q.pergunta, profile, embedder, reranker,
                candidates=s.retrieval_candidates, rerank_top_n=s.rerank_top_n,
            )
            elapsed_ms = (time.perf_counter() - t0) * 1000
            ranked = [env.retrieved(h.chunk) for h in hits]
            top_score = hits[0].rerank_score if hits else 0.0
            rows.append(
                {
                    "id": q.id, "tipo": q.tipo, "pergunta": q.pergunta,
                    **_retrieval_metrics(ranked, q),
                    "vazamentos": leaked_chunks(ranked, profile),
                    "top_score": round(top_score, 4),
                    "recusaria": top_score < s.refusal_threshold,
                    "retrieval_ms": round(elapsed_ms),
                    "top_resultados": " | ".join(
                        f"{r.doc_title} > {r.section_path} ({h.rerank_score:.3f})" for r, h in list(zip(ranked, hits))[:5]
                    ),
                    "evidencias_esperadas": _expected(q),
                }
            )
    return rows, summarize_retrieval(rows, refusal_key="recusaria")


def _rate(rows: list[dict], key: str) -> float | None:
    return sum(bool(r[key]) for r in rows) / len(rows) if rows else None


def summarize_retrieval(rows: list[dict], refusal_key: str) -> dict:
    with_ev = [r for r in rows if r["rr"] is not None]
    by = lambda *tipos: [r for r in rows if r["tipo"] in tipos]  # noqa: E731
    vaz = by("vazamento")
    return {
        "n_perguntas": len(rows),
        "n_com_evidencia": len(with_ev),
        **{f"recall@{k}": mean([r[f"recall@{k}"] for r in with_ev]) for k in KS},
        "mrr": mean([r["rr"] for r in with_ev]),
        "recusa_correta_sem_resposta": _rate(by("sem_resposta"), refusal_key),
        "recusa_correta_vazamento": _rate(vaz, refusal_key),
        "recusa_indevida_com_resposta": _rate(by("com_resposta", "desatualizado"), refusal_key),
        "perguntas_vazamento": len(vaz),
        "vazamentos_total": sum(r["vazamentos"] for r in rows),
        "taxa_vazamento": (sum(r["vazamentos"] > 0 for r in vaz) / len(vaz)) if vaz else None,
    }


# --- rag ------------------------------------------------------------------------------------------

def run_rag(questions: list[Question]) -> tuple[list[dict], dict]:
    embedder, reranker, llm = get_embedding_provider(), get_reranker(), get_llm_provider()
    rows = []
    with SessionLocal() as db:
        env = Env(db)
        for q in questions:
            profile = env.profile(q)
            result = list(chat(db, q.pergunta, profile, embedder=embedder, reranker=reranker, llm=llm, record=False))[-1][1]
            context = [env.retrieved(c) for c in result.context_chunks]
            cited = [env.retrieved(db.get(Chunk, src.chunk_id)) for src in result.sources]
            expected_refusal = q.tipo in SHOULD_REFUSE
            rows.append(
                {
                    "id": q.id, "tipo": q.tipo, "pergunta": q.pergunta,
                    "recusou": result.status == "refused",
                    "motivo_recusa": result.refusal_reason or "",
                    "resposta": result.answer,
                    "resposta_bruta": result.raw_answer,
                    "resposta_esperada": q.resposta_esperada,
                    **_retrieval_metrics(context, q),  # over the passages actually sent to the model
                    "citou_evidencia": (
                        any(
                            any(c.doc_title.lower() == e["documento"].lower() and e.get("secao", "").lower() in c.section_path.lower() for c in cited)
                            for e in q.evidencias
                        )
                        if q.evidencias and result.status == "answered" else None
                    ),
                    "fontes": "; ".join(f"[{s.n}] {s.title} > {s.section_path} (v{s.version})" for s in result.sources),
                    "avisos": " ".join(result.warnings),
                    "responsavel_sugerido": result.responsible.name if result.responsible else "",
                    "vazamentos": leaked_chunks(context, profile),
                    "top_score": round(result.top_score, 4),
                    "ttft_ms": round(result.ttft_ms) if result.ttft_ms is not None else None,
                    "total_ms": round(result.total_ms),
                    "evidencias_esperadas": _expected(q),
                    "recusa_esperada": expected_refusal,
                }
            )
    summary = summarize_retrieval(rows, refusal_key="recusou")
    answered_ev = [r for r in rows if r["citou_evidencia"] is not None]
    stale = [r for r in rows if r["tipo"] == "desatualizado" and not r["recusou"]]
    ttfts = [r["ttft_ms"] for r in rows if r["ttft_ms"] is not None]
    summary |= {
        "citou_evidencia_esperada": _rate(answered_ev, "citou_evidencia"),
        "aviso_revisao_em_desatualizado": _rate([{"w": bool(r["avisos"])} for r in stale], "w"),
        "ttft_ms_mediana": statistics.median(ttfts) if ttfts else None,
        "tempo_total_ms_mediana": statistics.median(r["total_ms"] for r in rows) if rows else None,
        "alucinacao_e_acerto": "n/d (requer o juiz LLM: ver README)",
    }
    return rows, summary


# --- sem_recuperacao ------------------------------------------------------------------------------

def run_sem_recuperacao(questions: list[Question]) -> tuple[list[dict], dict]:
    """No passages at all. Answers are meant to be compared with `resposta_esperada` (by the LLM
    judge or by humans): a correct answer here means the model already knew the "private" fact."""
    llm = get_llm_provider()
    rows = []
    for q in questions:
        t0 = time.perf_counter()
        ttft, pieces = None, []
        for piece in llm.stream(
            [{"role": "system", "content": NO_CONTEXT_SYSTEM_PROMPT}, {"role": "user", "content": q.pergunta}]
        ):
            if ttft is None:
                ttft = (time.perf_counter() - t0) * 1000
            pieces.append(piece)
        rows.append(
            {
                "id": q.id, "tipo": q.tipo, "pergunta": q.pergunta,
                "resposta": "".join(pieces).strip(),
                "resposta_esperada": q.resposta_esperada,
                "ttft_ms": round(ttft) if ttft is not None else None,
                "total_ms": round((time.perf_counter() - t0) * 1000),
            }
        )
    ttfts = [r["ttft_ms"] for r in rows if r["ttft_ms"] is not None]
    return rows, {
        "n_perguntas": len(rows),
        "ttft_ms_mediana": statistics.median(ttfts) if ttfts else None,
        "tempo_total_ms_mediana": statistics.median(r["total_ms"] for r in rows) if rows else None,
        "contaminacao": "n/d (requer o juiz LLM ou anotação humana: comparar `resposta` e `resposta_esperada`)",
    }


MODES = {"so_busca": run_so_busca, "rag": run_rag, "sem_recuperacao": run_sem_recuperacao}
TABLE_COLUMNS = {
    "so_busca": ["rr", "top_score", "vazamentos", "recusaria"],
    "rag": ["rr", "recusou", "motivo_recusa", "citou_evidencia", "vazamentos", "ttft_ms", "total_ms"],
    "sem_recuperacao": ["ttft_ms", "total_ms"],
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

    cols = TABLE_COLUMNS[mode]
    lines = [
        f"# Avaliação — modo `{mode}`",
        "",
        f"- Data: {datetime.now():%Y-%m-%d %H:%M}",
        f"- Perguntas: `{questions_path}` ({len(rows)})",
        f"- Provedor/modelo LLM: `{s.llm_provider}` / `{s.llm_model}` (temperatura {s.llm_temperature}, contexto {s.llm_num_ctx})",
        f"- Embeddings: `{s.embedding_model}` | Reranker: `{s.reranker_model}`",
        f"- Limiar de recusa: {s.refusal_threshold} | top-k: {s.top_k} | candidatos: {s.retrieval_candidates} | rerank top-n: {s.rerank_top_n}",
        "",
        "## Métricas",
        "",
        "| Métrica | Valor |",
        "|---|---|",
        *[f"| {k} | {fmt(v)} |" for k, v in summary.items()],
        "",
        "> `taxa_vazamento` deve ser **0**.",
        "",
        "## Por pergunta",
        "",
        "| id | tipo | " + " | ".join(cols) + " |",
        "|---|---|" + "---|" * len(cols),
        *[f"| {r['id']} | {r['tipo']} | " + " | ".join(fmt(r[c]) for c in cols) + " |" for r in rows],
    ]
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return csv_path, md_path


def main() -> None:
    ap = argparse.ArgumentParser(prog="eval.run")
    ap.add_argument("--questions", type=Path, required=True)
    ap.add_argument("--mode", choices=sorted(MODES), required=True)
    args = ap.parse_args()

    rows, summary = MODES[args.mode](load_questions(args.questions))
    csv_path, md_path = write_outputs(rows, summary, args.mode, args.questions)
    print(md_path.read_text(encoding="utf-8").split("## Por pergunta")[0])
    print(f"CSV: {csv_path}\nResumo: {md_path}")
    if summary.get("vazamentos_total"):
        raise SystemExit("FALHA: houve vazamento de trechos sem permissão.")


if __name__ == "__main__":
    main()
