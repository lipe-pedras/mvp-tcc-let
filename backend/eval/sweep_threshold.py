"""Sweep the refusal threshold to see the trade-off between refusing correctly and refusing wrongly.

    uv run python -m eval.sweep_threshold --results eval/results/<run>-so_busca.csv
    uv run python -m eval.sweep_threshold --questions eval/questions.jsonl     # runs so_busca first

It only needs each question's best reranker score (`top_score`), which the so_busca run
records, so sweeping many thresholds costs nothing after one retrieval pass.
"""

import argparse
import csv
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from eval.report import RESULTS_DIR

SHOULD_REFUSE = {"sem_resposta", "vazamento"}
SHOULD_ANSWER = {"com_resposta", "desatualizado"}


@dataclass(frozen=True)
class Point:
    threshold: float
    correct_refusal: float | None  # share of should-refuse questions that would be refused
    wrong_refusal: float | None  # share of should-answer questions that would be refused

    @property
    def score(self) -> float:
        """Youden's J: correct refusals minus wrong refusals (higher is better)."""
        return (self.correct_refusal or 0.0) - (self.wrong_refusal or 0.0)


def sweep(rows: list[dict], thresholds: list[float]) -> list[Point]:
    refuse = [float(r["top_score"]) for r in rows if r["tipo"] in SHOULD_REFUSE]
    answer = [float(r["top_score"]) for r in rows if r["tipo"] in SHOULD_ANSWER]
    share = lambda scores, t: (sum(s < t for s in scores) / len(scores)) if scores else None  # noqa: E731
    return [Point(t, share(refuse, t), share(answer, t)) for t in thresholds]


def recommend(points: list[Point]) -> tuple[float, float]:
    """The range of thresholds with the best score; the middle of it is the suggestion
    (the safest point on a plateau, away from both edges)."""
    best = max(p.score for p in points)
    plateau = [p.threshold for p in points if abs(p.score - best) < 1e-9]
    return min(plateau), max(plateau)


def render(points: list[Point], rows: list[dict], current: float | None) -> str:
    lo, hi = recommend(points)
    n_ref = sum(r["tipo"] in SHOULD_REFUSE for r in rows)
    n_ans = sum(r["tipo"] in SHOULD_ANSWER for r in rows)
    pct = lambda v: "n/d" if v is None else f"{v:.0%}"  # noqa: E731
    lines = [
        "# Varredura do limiar de recusa",
        "",
        f"- Data: {datetime.now():%Y-%m-%d %H:%M}",
        f"- Perguntas que deveriam ser recusadas (`sem_resposta` + `vazamento`): {n_ref}",
        f"- Perguntas que deveriam ser respondidas (`com_resposta` + `desatualizado`): {n_ans}",
        f"- Limiar atual: {current if current is not None else 'n/d'}",
        f"- **Faixa com melhor compromisso: {lo:.2f} a {hi:.2f}** (ponto médio: {(lo + hi) / 2:.2f}). "
        + (
            "O limiar atual está dentro da faixa."
            if current is not None and lo <= current <= hi
            else "O limiar atual está **fora** da faixa: reavalie."
        ),
        "- Dentro da faixa, limiares mais altos recusam mais: menos risco de resposta errada, mais perguntas encaminhadas ao responsável. Escolha conforme o custo de cada erro na sua empresa.",
        "",
        "| Limiar | Recusa correta | Recusa indevida | Score (correta − indevida) |",
        "|---|---|---|---|",
    ]
    for p in points:
        mark = " ◀ faixa ideal" if lo <= p.threshold <= hi else ""
        lines.append(f"| {p.threshold:.2f} | {pct(p.correct_refusal)} | {pct(p.wrong_refusal)} | {p.score:+.2f}{mark} |")
    lines += ["", "> Poucas perguntas dão uma curva em degraus. Com o conjunto real (30–50 perguntas) a faixa fica mais confiável.", ""]
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(prog="eval.sweep_threshold")
    ap.add_argument("--results", type=Path, help="CSV do modo so_busca (coluna top_score)")
    ap.add_argument("--questions", type=Path, help="se não houver --results, roda o so_busca nestas perguntas")
    ap.add_argument("--step", type=float, default=0.05)
    args = ap.parse_args()
    if not args.results and not args.questions:
        ap.error("informe --results ou --questions")

    from app.config import get_settings

    if args.results:
        with args.results.open(encoding="utf-8", newline="") as f:
            rows = list(csv.DictReader(f))
    else:
        from eval.dataset import load_questions
        from eval.run import run_so_busca

        rows, _ = run_so_busca(load_questions(args.questions))
    if not rows or "top_score" not in rows[0]:
        raise SystemExit("O CSV precisa vir do modo so_busca (coluna top_score).")

    n = round(1 / args.step)
    points = sweep(rows, [round(i * args.step, 4) for i in range(n + 1)])
    md = render(points, rows, get_settings().refusal_threshold)
    RESULTS_DIR.mkdir(exist_ok=True)
    out = RESULTS_DIR / f"{datetime.now():%Y%m%d-%H%M%S}-varredura-limiar.md"
    out.write_text(md, encoding="utf-8")
    print(md)
    print(f"Resumo: {out}")


if __name__ == "__main__":
    main()
