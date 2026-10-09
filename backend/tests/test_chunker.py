from app.services.ingestion.chunker import MAX_CHARS, MAX_TABLE_CHARS, chunk_markdown

DOC = """# Férias

Todo colaborador tem direito a 30 dias.

## Como solicitar

1. Abra o chamado no sistema ORBITA.
2. Aguarde a aprovação do gestor.

## Parâmetros

| Tipo | Prazo |
|------|-------|
| Normal | 30 dias |
| Parcelada | 3 períodos |

Observação final.
"""


def test_chunks_follow_sections_with_paths():
    chunks = chunk_markdown(DOC)
    paths = [c.section_path for c in chunks]
    assert paths == [
        "Férias",
        "Férias > Como solicitar",
        "Férias > Parâmetros",  # table
        "Férias > Parâmetros",  # trailing paragraph
    ]
    assert chunks[0].text.startswith("Todo colaborador")
    assert "ORBITA" in chunks[1].text


def test_small_table_stays_whole():
    table_chunks = [c for c in chunk_markdown(DOC) if c.text.startswith("|")]
    assert len(table_chunks) == 1
    assert "Parcelada" in table_chunks[0].text and "Tipo" in table_chunks[0].text


def test_indexed_text_includes_title_and_path():
    chunk = chunk_markdown(DOC)[1]
    indexed = chunk.indexed_text("Política de Férias")
    assert indexed.startswith("Política de Férias > Férias > Como solicitar")
    assert "ORBITA" in indexed


def test_long_section_is_split_at_paragraphs():
    paragraphs = [f"Parágrafo {i}. " + "texto " * 60 for i in range(10)]
    chunks = chunk_markdown("# Doc\n\n" + "\n\n".join(paragraphs))
    assert len(chunks) > 1
    assert all(len(c.text) <= MAX_CHARS for c in chunks)
    assert "Parágrafo 0" in chunks[0].text


def test_long_table_split_by_rows_repeats_header():
    rows = "\n".join(f"| item {i} | {'x' * 60} |" for i in range(80))
    chunks = chunk_markdown(f"# T\n\n| Nome | Valor |\n|---|---|\n{rows}\n")
    assert len(chunks) > 1
    assert all(c.text.startswith("| Nome | Valor |") for c in chunks)
    assert all(len(c.text) <= MAX_TABLE_CHARS + 100 for c in chunks)
    assert sum(c.text.count("| item") for c in chunks) == 80


def test_headings_inside_code_fences_are_ignored():
    chunks = chunk_markdown("# Doc\n\n```\n# not a heading\nls\n```\n")
    assert len(chunks) == 1 and "# not a heading" in chunks[0].text


def test_empty_sections_are_skipped():
    assert chunk_markdown("# Só título\n\n## Vazio\n") == []


def test_leading_h1_equal_to_title_is_not_repeated():
    chunk = chunk_markdown("# Política de Férias\n\n## Como solicitar\n\nAbra o chamado.")[0]
    assert chunk.section_path == "Política de Férias > Como solicitar"
    assert chunk.path_without_title("Política de Férias") == "Como solicitar"
    assert chunk.indexed_text("Política de Férias").startswith("Política de Férias > Como solicitar\n")
    # A different H1 is kept: it carries information.
    assert chunk.path_without_title("Outro título") == "Política de Férias > Como solicitar"
