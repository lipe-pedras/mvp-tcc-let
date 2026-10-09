import json

import pytest

from eval.judge import RUBRIC_VERSION, build_prompt, judge_one, judge_rows, parse_extraction, score_extraction, summarize_judged
from eval.sweep_threshold import Point, recommend, sweep
from tests.fakes import FakeLLM

PASSAGE = "[1] Férias > Como solicitar: O pedido deve ser feito com pelo menos **45 dias** de antecedência."


def extraction(facts, claims, admits=False):
    return {"fatos_gabarito": facts, "afirmacoes_resposta": claims, "admite_desconhecimento": admits}


def fact(found=True, contradicted=False):
    return {"fato": "f", "na_resposta": found, "contradito": contradicted}


def claim(text, quote):
    return {"afirmacao": text, "citacao_literal": quote}


GOOD = extraction([fact()], [claim("45 dias de antecedência", "pelo menos 45 dias de antecedência")])


def test_parse_extraction_tolerates_fences_and_chatter():
    text = "Claro!\n```json\n" + json.dumps(GOOD) + "\n```\nEspero ter ajudado."
    assert parse_extraction(text)["admite_desconhecimento"] is False
    assert parse_extraction("sem json") is None
    assert parse_extraction('{"outro": 1}') is None


def test_correct_and_faithful_answer():
    v = score_extraction(GOOD, "45 dias", PASSAGE)
    assert (v["acerto"], v["fidelidade"]) == ("correta", "suportada")


def test_contradicted_fact_is_incorrect_and_wrong_number_is_not_supported():
    bad = extraction([fact(found=False, contradicted=True)], [claim("30 dias de antecedência", "pelo menos 45 dias de antecedência")])
    v = score_extraction(bad, "45 dias", PASSAGE)
    assert (v["acerto"], v["fidelidade"]) == ("incorreta", "nao_suportada")  # quote exists, but 30 is not in it


def test_missing_fact_is_partial_and_nothing_found_is_incorrect():
    assert score_extraction(extraction([fact(), fact(found=False)], []), "a; b", PASSAGE)["acerto"] == "parcial"
    assert score_extraction(extraction([fact(False), fact(False)], []), "a; b", PASSAGE)["acerto"] == "incorreta"


def test_claim_without_literal_quote_in_passages_is_unsupported():
    claims = [claim("45 dias", "pelo menos 45 dias de antecedência"), claim("pago em dobro em dezembro", "pago em dobro em dezembro")]
    v = score_extraction(extraction([fact()], claims), "45 dias", PASSAGE)
    assert v["fidelidade"] == "parcial"  # one of two claims has a quote that is not in the passages
    all_bad = extraction([fact()], [claim("x", "frase inventada que não está nos trechos")])
    assert score_extraction(all_bad, "45 dias", PASSAGE)["fidelidade"] == "nao_suportada"


def test_trivial_quotes_do_not_count():
    assert score_extraction(extraction([fact()], [claim("dias", "dias")]), "x", PASSAGE)["fidelidade"] == "nao_suportada"


def test_empty_expected_answer_is_judged_on_admitting_ignorance():
    assert score_extraction(extraction([], [], admits=True), "", "")["acerto"] == "correta"
    assert score_extraction(extraction([], [claim("cobre limpezas", "")], admits=False), "", "")["acerto"] == "incorreta"


def test_no_passages_means_faithfulness_not_applicable():
    assert score_extraction(extraction([fact()], [claim("x", "")]), "x", "")["fidelidade"] == "nao_aplicavel"


def test_unusable_extraction_returns_none():
    assert score_extraction({"fatos_gabarito": "?", "afirmacoes_resposta": [], "admite_desconhecimento": False}, "x", PASSAGE) is None
    assert score_extraction(extraction([], [], False), "tem gabarito mas nenhum fato listado", PASSAGE) is None


def test_prompt_is_filled_and_versioned_rubric_is_used():
    p = build_prompt({"pergunta": "Q?", "resposta_esperada": "", "resposta": "R", "trechos_citados": ""})
    assert "Q?" in p and "(vazia: a documentação não responde)" in p and "(nenhum)" in p
    assert "{{" not in p and "afirmacoes_resposta" in p
    assert RUBRIC_VERSION == "v2"


class SequenceLLM(FakeLLM):
    def __init__(self, replies):
        super().__init__()
        self.replies = list(replies)

    def stream(self, messages):
        self.calls.append(messages)
        yield self.replies.pop(0)


def test_judge_retries_once_on_bad_json_then_gives_up():
    row = {"pergunta": "q", "resposta": "r", "resposta_esperada": "45 dias", "trechos_citados": PASSAGE}
    llm = SequenceLLM(["lixo", json.dumps(GOOD)])
    assert judge_one(llm, row)["fidelidade"] == "suportada" and len(llm.calls) == 2
    llm = SequenceLLM(["lixo", "mais lixo"])
    assert judge_one(llm, row) is None


def rag_row(id_, tipo, expected, refused, acerto=None, fid=None, answer="resp"):
    return {"id": id_, "tipo": tipo, "pergunta": "q", "resposta_esperada": expected, "resposta": answer,
            "recusou": str(refused), "trechos_citados": "[1] Doc: texto", "_acerto": acerto, "_fid": fid}


def test_refusals_are_scored_by_rule_without_calling_the_judge():
    llm = SequenceLLM([])
    rows = judge_rows([rag_row("a", "sem_resposta", "", True), rag_row("b", "com_resposta", "45 dias", True)], "rag", llm, progress=lambda *_: None)
    assert llm.calls == []
    assert (rows[0]["juiz_acerto"], rows[1]["juiz_acerto"]) == ("correta", "incorreta")


def test_rag_summary_hallucination_and_accuracy():
    rows = [
        {**rag_row("1", "com_resposta", "x", False), "juiz_acerto": "correta", "juiz_fidelidade": "suportada"},
        {**rag_row("2", "com_resposta", "x", False), "juiz_acerto": "parcial", "juiz_fidelidade": "parcial"},
        {**rag_row("3", "com_resposta", "x", False), "juiz_acerto": "incorreta", "juiz_fidelidade": "nao_suportada"},
        {**rag_row("4", "com_resposta", "x", True), "juiz_acerto": "incorreta", "juiz_fidelidade": "nao_aplicavel"},
        {**rag_row("5", "sem_resposta", "", True), "juiz_acerto": "correta", "juiz_fidelidade": "nao_aplicavel"},
    ]
    s = summarize_judged(rows, "rag")
    assert s["acerto_perguntas_com_resposta"] == pytest.approx((1 + 0.5 + 0 + 0) / 4)
    assert s["comportamento_correto_sem_resposta"] == 1.0
    assert s["n_respondidas_julgadas"] == 3
    assert s["taxa_alucinacao"] == pytest.approx(2 / 3) and s["taxa_nao_suportada"] == pytest.approx(1 / 3)
    assert s["fidelidade_suportada"] == pytest.approx(1 / 3)


def test_sem_recuperacao_summary_measures_contamination_and_fabrication():
    def row(id_, expected, acerto):
        return {"id": id_, "tipo": "x", "pergunta": "q", "resposta_esperada": expected, "resposta": "r", "juiz_acerto": acerto, "juiz_fidelidade": "nao_aplicavel"}

    rows = [row("1", "fato", "incorreta"), row("2", "fato", "correta"), row("3", "fato", "parcial"), row("4", "", "incorreta"), row("5", "", "correta")]
    s = summarize_judged(rows, "sem_recuperacao")
    assert s["contaminacao_acerto_total"] == pytest.approx(1 / 3)
    assert s["contaminacao_acerto_medio"] == pytest.approx(0.5)
    assert s["fabricacao_sem_resposta"] == 0.5


def test_unparseable_judgments_are_counted_not_scored():
    rows = [{**rag_row("1", "com_resposta", "x", False), "juiz_acerto": "", "juiz_fidelidade": ""}]
    assert summarize_judged(rows, "rag")["juiz_falhas"] == 1


# --- threshold sweep ----------------------------------------------------------------------------

ROWS = [
    {"tipo": "com_resposta", "top_score": "0.99"}, {"tipo": "com_resposta", "top_score": "0.72"},
    {"tipo": "desatualizado", "top_score": "0.60"},
    {"tipo": "sem_resposta", "top_score": "0.10"}, {"tipo": "vazamento", "top_score": "0.01"},
]


def test_sweep_tradeoff_values():
    pts = {p.threshold: p for p in sweep(ROWS, [0.0, 0.05, 0.3, 0.65, 1.0])}
    assert (pts[0.0].correct_refusal, pts[0.0].wrong_refusal) == (0.0, 0.0)  # nothing refused
    assert (pts[0.05].correct_refusal, pts[0.05].wrong_refusal) == (0.5, 0.0)
    assert (pts[0.3].correct_refusal, pts[0.3].wrong_refusal) == (1.0, 0.0)
    assert pts[0.65].wrong_refusal == pytest.approx(1 / 3)  # 0.60 refused
    assert (pts[1.0].correct_refusal, pts[1.0].wrong_refusal) == (1.0, 1.0)  # everything refused


def test_recommendation_is_the_plateau_of_best_score():
    points = sweep(ROWS, [round(i * 0.05, 2) for i in range(21)])
    lo, hi = recommend(points)
    assert (lo, hi) == (0.15, 0.60) and 0.10 < (lo + hi) / 2 < 0.60


def test_point_score_handles_missing_groups():
    assert Point(0.5, None, 0.2).score == pytest.approx(-0.2)
