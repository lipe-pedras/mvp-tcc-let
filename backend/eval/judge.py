"""LLM judge: answer correctness and faithfulness to the cited passages.

The model only *extracts* (expected facts found in the answer; answer claims with the literal
quote that supports each). The verdicts are computed here, deterministically, because small
local models are unreliable at holistic grading (see `--selftest`). A claim counts as supported
only if its quote really occurs in the cited passages AND every number/code in the claim occurs
in that quote.

    uv run python -m eval.judge --results eval/results/<run>-rag.csv --mode rag

The rubric is versioned in eval/prompts/. The judge model is configurable
(JUDGE_PROVIDER / JUDGE_MODEL; local Ollama by default). A small local model is a
noisy judge: use the `anotacao_humana` column to calibrate before trusting the numbers.
"""

import argparse
import csv
import json
import re
from pathlib import Path

from app.config import get_settings
from app.providers.llm import LLMProvider, get_judge_provider
from eval.metrics import mean
from eval.report import write_outputs

RUBRIC_PATH = Path(__file__).parent / "prompts" / "judge_rubric_v2.md"
RUBRIC_VERSION = RUBRIC_PATH.stem.rsplit("_", 1)[-1]

ACERTO = {"correta": 1.0, "parcial": 0.5, "incorreta": 0.0}
ANSWER_TYPES = {"com_resposta", "desatualizado"}  # questions that do have an answer in the corpus


def build_prompt(row: dict, rubric: str | None = None) -> str:
    rubric = rubric or RUBRIC_PATH.read_text(encoding="utf-8")
    values = {
        "pergunta": row["pergunta"],
        "resposta_esperada": row.get("resposta_esperada", "").strip() or "(vazia: a documentação não responde)",
        "resposta": row["resposta"],
        "trechos": row.get("trechos_citados", "").strip() or "(nenhum)",
    }
    for key, value in values.items():
        rubric = rubric.replace("{{" + key + "}}", value)
    return rubric


_NUMBER = re.compile(r"\d+(?:[.,]\d+)*")


def _norm(text: str) -> str:
    """Casefold, drop markdown emphasis, collapse whitespace: quotes are matched loosely on form, strictly on words."""
    return re.sub(r"\s+", " ", re.sub(r"[*_`]", "", text)).strip().casefold()


def _claim_supported(claim: dict, passages_norm: str) -> bool:
    quote = _norm(str(claim.get("citacao_literal", "")))
    if len(quote) < 8 or quote not in passages_norm:  # empty, trivial, or not literally in the passages
        return False
    # The quote must contain every number in the claim (catches "30 dias" supported by a quote about 45).
    quote_compact = quote.replace(" ", "")
    return all(n.replace(" ", "") in quote_compact for n in _NUMBER.findall(str(claim.get("afirmacao", ""))))


def score_extraction(data: dict, expected: str, passages: str) -> dict | None:
    """Turn the judge's extraction into verdicts. None when the extraction is unusable."""
    facts, claims = data.get("fatos_gabarito"), data.get("afirmacoes_resposta")
    if not isinstance(facts, list) or not isinstance(claims, list) or not isinstance(data.get("admite_desconhecimento"), bool):
        return None

    if not expected.strip():
        acerto = "correta" if data["admite_desconhecimento"] else "incorreta"
        notes = "gabarito vazio: " + ("admite desconhecimento" if acerto == "correta" else "afirmou fatos sem base")
    else:
        facts = [f for f in facts if isinstance(f, dict)]
        if not facts:
            return None
        found = [bool(f.get("na_resposta")) and not f.get("contradito") for f in facts]
        contradicted = any(f.get("contradito") for f in facts)
        if all(found):
            acerto = "correta"
        elif contradicted or not any(found):
            acerto = "incorreta"
        else:
            acerto = "parcial"
        notes = f"{sum(found)}/{len(facts)} fatos do gabarito" + (", com contradição" if contradicted else "")

    claims = [c for c in claims if isinstance(c, dict)]
    if not passages.strip() or not claims:
        fidelidade = "nao_aplicavel" if not passages.strip() else "suportada"
    else:
        norm = _norm(passages)
        bad = sum(not _claim_supported(c, norm) for c in claims)
        fidelidade = "suportada" if bad == 0 else ("nao_suportada" if bad == len(claims) else "parcial")
        notes += f"; {len(claims) - bad}/{len(claims)} afirmações sustentadas"
    return {"acerto": acerto, "fidelidade": fidelidade, "justificativa": notes}


def parse_extraction(text: str) -> dict | None:
    """Pull the JSON object out of the model's text (tolerates code fences and chatter)."""
    start = text.find("{")
    while start != -1:
        depth = 0
        for i in range(start, len(text)):
            depth += (text[i] == "{") - (text[i] == "}")
            if depth == 0:
                try:
                    data = json.loads(text[start : i + 1])
                except json.JSONDecodeError:
                    break
                if isinstance(data, dict) and "afirmacoes_resposta" in data:
                    return data
                break
        start = text.find("{", start + 1)
    return None


def judge_one(llm: LLMProvider, row: dict, retries: int = 1) -> dict | None:
    prompt = build_prompt(row)
    for _ in range(retries + 1):
        text = "".join(llm.stream([{"role": "user", "content": prompt}]))
        data = parse_extraction(text)
        if data and (verdict := score_extraction(data, row.get("resposta_esperada", ""), row.get("trechos_citados", ""))):
            return verdict
    return None


def _is_true(v) -> bool:
    return v is True or str(v) == "True"


def judge_rows(rows: list[dict], mode: str, llm: LLMProvider, progress=print) -> list[dict]:
    """Add juiz_* columns. Refusals are scored by rule (no model call): refusing is right
    exactly when the expected answer is empty."""
    for row in rows:
        refused = mode == "rag" and _is_true(row.get("recusou"))
        if refused:
            should_refuse = not row.get("resposta_esperada", "").strip()
            verdict = {"acerto": "correta" if should_refuse else "incorreta", "fidelidade": "nao_aplicavel", "justificativa": "recusa (pontuada por regra, sem juiz)"}
        else:
            verdict = judge_one(llm, row)
            if verdict is None:
                verdict = {"acerto": "", "fidelidade": "", "justificativa": "falha: o juiz não devolveu JSON válido"}
        row.update(juiz_acerto=verdict["acerto"], juiz_fidelidade=verdict["fidelidade"], juiz_justificativa=verdict["justificativa"])
        progress(f"  {row['id']}: acerto={verdict['acerto'] or '?'} fidelidade={verdict['fidelidade'] or '?'}")
    return rows


def summarize_judged(rows: list[dict], mode: str) -> dict:
    ok = [r for r in rows if r.get("juiz_acerto")]
    has_answer = [r for r in ok if r["resposta_esperada"].strip()]
    no_answer = [r for r in ok if not r["resposta_esperada"].strip()]
    score = lambda rs: mean([ACERTO[r["juiz_acerto"]] for r in rs])  # noqa: E731
    out: dict = {"juiz_falhas": len(rows) - len(ok)}
    if mode == "rag":
        answered = [r for r in ok if not _is_true(r.get("recusou"))]
        faith = [r for r in answered if r["juiz_fidelidade"] != "nao_aplicavel"]
        out |= {
            "acerto_perguntas_com_resposta": score(has_answer),
            "comportamento_correto_sem_resposta": score(no_answer),
            "n_respondidas_julgadas": len(faith),
            "fidelidade_suportada": (sum(r["juiz_fidelidade"] == "suportada" for r in faith) / len(faith)) if faith else None,
            # Hallucination: an answer with any claim not supported by the passages it cites.
            "taxa_alucinacao": (sum(r["juiz_fidelidade"] in {"parcial", "nao_suportada"} for r in faith) / len(faith)) if faith else None,
            "taxa_nao_suportada": (sum(r["juiz_fidelidade"] == "nao_suportada" for r in faith) / len(faith)) if faith else None,
        }
    elif mode == "sem_recuperacao":
        out |= {
            # Share of corpus facts the model already "knew" without any retrieval.
            "contaminacao_acerto_total": (sum(r["juiz_acerto"] == "correta" for r in has_answer) / len(has_answer)) if has_answer else None,
            "contaminacao_acerto_medio": score(has_answer),
            # Share of unanswerable questions where the model invented specifics instead of admitting ignorance.
            "fabricacao_sem_resposta": (sum(r["juiz_acerto"] == "incorreta" for r in no_answer) / len(no_answer)) if no_answer else None,
        }
    return out


def judge_config_lines() -> list[str]:
    s = get_settings()
    return [f"- Juiz: `{s.judge_provider}` / `{s.judge_model or s.llm_model}` | rubrica: `{RUBRIC_PATH.name}` (versão {RUBRIC_VERSION})"]


def load_results(path: Path) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


# Known-good and known-bad answers, to check that a judge model can tell them apart before
# trusting its numbers. Each case lists the verdicts that are acceptable.
SELFTEST_CASES = [
    {
        "nome": "resposta correta e fiel",
        "row": {"pergunta": "Com quantos dias de antecedência peço férias?", "resposta_esperada": "45 dias de antecedência.", "resposta": "Com pelo menos 45 dias de antecedência [1].", "trechos_citados": "[1] Férias > Como solicitar: O pedido deve ser feito com pelo menos 45 dias de antecedência."},
        "acerto": {"correta"}, "fidelidade": {"suportada"},
    },
    {
        "nome": "valor errado, contradiz o trecho",
        "row": {"pergunta": "Com quantos dias de antecedência peço férias?", "resposta_esperada": "45 dias de antecedência.", "resposta": "Com 30 dias de antecedência [1].", "trechos_citados": "[1] Férias > Como solicitar: O pedido deve ser feito com pelo menos 45 dias de antecedência."},
        "acerto": {"incorreta"}, "fidelidade": {"nao_suportada", "parcial"},
    },
    {
        "nome": "fato certo + afirmação inventada",
        "row": {"pergunta": "Qual o valor do auxílio home office?", "resposta_esperada": "R$ 142,00 por mês.", "resposta": "O auxílio é de R$ 142,00 por mês [1], pago também em dobro em dezembro.", "trechos_citados": "[1] Home Office > Auxílio: Quem trabalha em regime híbrido recebe R$ 142,00 por mês para internet e energia."},
        "acerto": {"correta", "parcial"}, "fidelidade": {"parcial", "nao_suportada"},
    },
    {
        "nome": "sem resposta no corpus, mas o modelo inventa",
        "row": {"pergunta": "Como funciona o plano odontológico?", "resposta_esperada": "", "resposta": "O plano odontológico cobre consultas e limpezas, com coparticipação de 30%.", "trechos_citados": ""},
        "acerto": {"incorreta"}, "fidelidade": {"nao_aplicavel", "nao_suportada"},
    },
    {
        "nome": "sem resposta no corpus, o modelo admite",
        "row": {"pergunta": "Como funciona o plano odontológico?", "resposta_esperada": "", "resposta": "Não tenho essa informação.", "trechos_citados": ""},
        "acerto": {"correta"}, "fidelidade": {"nao_aplicavel"},
    },
    {
        "nome": "resposta incompleta (falta um dos fatos)",
        "row": {"pergunta": "Quantos dias de home office e quais dias são presenciais?", "resposta_esperada": "Até 3 dias por semana; terças e quintas são presenciais.", "resposta": "Até 3 dias por semana [1].", "trechos_citados": "[1] Home Office > Modelo híbrido: Até 3 dias por semana em home office. As terças e quintas-feiras são presenciais."},
        "acerto": {"parcial", "incorreta"}, "fidelidade": {"suportada"},
    },
    {
        "nome": "documentos divergem e a resposta mostra só uma versão",
        "row": {"pergunta": "Em quantos dias peço reembolso?", "resposta_esperada": "Documentos divergem: 15 dias corridos (Reembolso) e 10 dias corridos (Viagens). O ideal é apontar a divergência.", "resposta": "Em até 15 dias corridos após a despesa [1].", "trechos_citados": "[1] Reembolso > Prazo: O pedido deve ser feito em até 15 dias corridos após a despesa."},
        "acerto": {"parcial", "incorreta"}, "fidelidade": {"suportada"},
    },
]


def selftest(llm: LLMProvider) -> int:
    """Run the judge on SELFTEST_CASES; return how many verdicts were acceptable."""
    passed = 0
    for case in SELFTEST_CASES:
        v = judge_one(llm, case["row"])
        ok = bool(v) and v["acerto"] in case["acerto"] and v["fidelidade"] in case["fidelidade"]
        passed += ok
        got = f"{v['acerto']}/{v['fidelidade']}" if v else "sem JSON"
        print(f"  [{'ok' if ok else 'FALHOU'}] {case['nome']}: {got} (aceitável: {sorted(case['acerto'])}/{sorted(case['fidelidade'])})")
    print(f"Autoteste do juiz: {passed}/{len(SELFTEST_CASES)}")
    return passed


def main() -> None:
    ap = argparse.ArgumentParser(prog="eval.judge", description="Julga com o LLM juiz um CSV gerado pelo eval.run (modos rag ou sem_recuperacao).")
    ap.add_argument("--results", type=Path)
    ap.add_argument("--mode", choices=["rag", "sem_recuperacao"])
    ap.add_argument("--selftest", action="store_true", help="só testa se o juiz distingue respostas boas de ruins")
    args = ap.parse_args()

    if args.selftest:
        raise SystemExit(0 if selftest(get_judge_provider()) == len(SELFTEST_CASES) else 1)
    if not args.results or not args.mode:
        ap.error("informe --results e --mode (ou --selftest)")

    rows = judge_rows(load_results(args.results), args.mode, get_judge_provider())
    summary = {"n_perguntas": len(rows), **summarize_judged(rows, args.mode)}
    csv_path, md_path = write_outputs(rows, summary, args.mode, args.results, extra_config=judge_config_lines(), suffix="-julgado")
    print(md_path.read_text(encoding="utf-8").split("## Por pergunta")[0])
    print(f"CSV: {csv_path}\nResumo: {md_path}")


if __name__ == "__main__":
    main()
