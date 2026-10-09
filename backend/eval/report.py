"""Markdown/CSV output shared by the run and judge commands."""

import csv
from datetime import datetime
from pathlib import Path

from app.config import get_settings

RESULTS_DIR = Path(__file__).parent / "results"

TABLE_COLUMNS = {
    "so_busca": ["rr", "top_score", "vazamentos", "recusaria"],
    "rag": ["rr", "recusou", "motivo_recusa", "citou_evidencia", "vazamentos", "juiz_acerto", "juiz_fidelidade", "ttft_ms", "total_ms"],
    "sem_recuperacao": ["juiz_acerto", "ttft_ms", "total_ms"],
}


def fmt(v) -> str:
    return "n/d" if v is None else (f"{v:.3f}" if isinstance(v, float) else str(v))


def write_outputs(
    rows: list[dict], summary: dict, mode: str, questions_path: Path, *, extra_config: list[str] | None = None, suffix: str = ""
) -> tuple[Path, Path]:
    s = get_settings()
    RESULTS_DIR.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    csv_path, md_path = RESULTS_DIR / f"{stamp}-{mode}{suffix}.csv", RESULTS_DIR / f"{stamp}-{mode}{suffix}.md"

    fields = list(rows[0])
    if "anotacao_humana" not in fields:
        fields.append("anotacao_humana")
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)

    cols = [c for c in TABLE_COLUMNS[mode] if c in rows[0]]
    lines = [
        f"# Avaliação — modo `{mode}`",
        "",
        f"- Data: {datetime.now():%Y-%m-%d %H:%M}",
        f"- Perguntas: `{questions_path}` ({len(rows)})",
        f"- Provedor/modelo LLM: `{s.llm_provider}` / `{s.llm_model}` (temperatura {s.llm_temperature}, contexto {s.llm_num_ctx})",
        f"- Embeddings: `{s.embedding_model}` | Reranker: `{s.reranker_model}`",
        f"- Limiar de recusa: {s.refusal_threshold} | top-k: {s.top_k} | candidatos: {s.retrieval_candidates} | rerank top-n: {s.rerank_top_n}",
        *(extra_config or []),
        "",
        "## Métricas",
        "",
        "| Métrica | Valor |",
        "|---|---|",
        *[f"| {k} | {fmt(v)} |" for k, v in summary.items()],
        "",
        "> `taxa_vazamento` deve ser **0**. Métricas do juiz LLM são estimativas: calibre contra anotação humana (coluna `anotacao_humana` do CSV).",
        "",
        "## Por pergunta",
        "",
        "| id | tipo | " + " | ".join(cols) + " |",
        "|---|---|" + "---|" * len(cols),
        *[f"| {r['id']} | {r['tipo']} | " + " | ".join(fmt(r[c]) for c in cols) + " |" for r in rows],
    ]
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return csv_path, md_path
