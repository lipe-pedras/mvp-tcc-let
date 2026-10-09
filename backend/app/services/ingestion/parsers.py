"""File parsers. Extension point: add a parser here (e.g. one that describes
images and diagrams) and register it in PARSERS; the rest of the pipeline only
sees Markdown."""

import tempfile
from pathlib import Path
from typing import Protocol

SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".pptx"}


class DocumentParser(Protocol):
    def to_markdown(self, path: Path) -> str: ...


class DoclingParser:
    """PDF, DOCX and PPTX via Docling; tables are exported as Markdown."""

    def __init__(self):
        self._converter = None

    def to_markdown(self, path: Path) -> str:
        if self._converter is None:
            from docling.document_converter import DocumentConverter

            self._converter = DocumentConverter()
        result = self._converter.convert(str(path))
        return result.document.export_to_markdown()


_parser: DocumentParser | None = None


def get_parser() -> DocumentParser:
    global _parser
    if _parser is None:
        _parser = DoclingParser()
    return _parser


def parse_upload(parser: DocumentParser, filename: str, data: bytes) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        raise ValueError(f"Formato não suportado: {suffix or 'sem extensão'}")
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / f"upload{suffix}"
        path.write_bytes(data)
        return parser.to_markdown(path)
