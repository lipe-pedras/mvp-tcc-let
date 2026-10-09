from app.services.chat.citations import is_no_evidence, validate_citations


def test_valid_citations_are_kept_and_collected():
    text, cited = validate_citations("São 30 dias [1]. O pedido é no ORBITA [2].", 3)
    assert text == "São 30 dias [1]. O pedido é no ORBITA [2]." and cited == [1, 2]


def test_citation_to_missing_passage_is_removed():
    text, cited = validate_citations("São 30 dias [1][9]. Outra coisa [7].", 3)
    assert cited == [1]
    assert "[9]" not in text and "[7]" not in text and "[1]" in text


def test_grouped_citations_are_split_and_filtered():
    text, cited = validate_citations("Fato [1, 2, 8].", 2)
    assert cited == [1, 2] and "[1, 2]" in text


def test_zero_and_out_of_range_numbers_are_invalid():
    assert validate_citations("x [0]", 3)[1] == []
    assert validate_citations("x [4]", 3)[1] == []


def test_answer_without_citation_has_no_valid_citation():
    assert validate_citations("São 30 dias.", 3)[1] == []


def test_non_citation_brackets_are_left_alone():
    text, cited = validate_citations("Use o formato [ABC] e o item [1].", 1)
    assert "[ABC]" in text and cited == [1]


def test_no_evidence_marker_detection():
    assert is_no_evidence("SEM_EVIDENCIA")
    assert is_no_evidence("  sem_evidencia.\n")
    assert is_no_evidence("SEM EVIDENCIA")
    assert is_no_evidence("")
    assert not is_no_evidence("São 30 dias [1].")
