"""Structure-aware Markdown chunking.

Chunks follow the document's sections instead of a fixed character count.
Small tables stay whole in one chunk; long sections are split at paragraph
boundaries; very long tables are split by rows, repeating the header.
Every chunk carries its section path, which is also prepended to the indexed text.
"""

import re
from dataclasses import dataclass

MAX_CHARS = 1500
MAX_TABLE_CHARS = 2500

_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_FENCE = re.compile(r"^\s*(```|~~~)")
_TABLE_ROW = re.compile(r"^\s*\|.*\|\s*$")


@dataclass(frozen=True)
class Chunk:
    section_path: str  # e.g. "Férias > Como solicitar"
    text: str
    page: int | None = None

    def path_without_title(self, doc_title: str) -> str:
        """Drop a leading section equal to the document title (the H1 usually repeats it)."""
        prefix = doc_title.strip().casefold()
        parts = self.section_path.split(" > ") if self.section_path else []
        if parts and parts[0].strip().casefold() == prefix:
            parts = parts[1:]
        return " > ".join(parts)

    def indexed_text(self, doc_title: str) -> str:
        """Text used for embeddings and lexical search: context + content."""
        path = self.path_without_title(doc_title)
        head = doc_title if not path else f"{doc_title} > {path}"
        return f"{head}\n\n{self.text}"


def _blocks(lines: list[str]) -> list[str]:
    """Split a section body into blocks: paragraphs, lists, tables, code fences."""
    blocks: list[str] = []
    current: list[str] = []
    in_fence = False
    in_table = False

    def flush():
        nonlocal current
        if current and any(l.strip() for l in current):
            blocks.append("\n".join(current).strip("\n"))
        current = []

    for line in lines:
        if _FENCE.match(line):
            if not in_fence:
                flush()
            in_fence = not in_fence
            current.append(line)
            if not in_fence:
                flush()
            continue
        if in_fence:
            current.append(line)
            continue
        is_row = bool(_TABLE_ROW.match(line))
        if is_row != in_table:
            flush()
            in_table = is_row
        if not line.strip():
            flush()
            continue
        current.append(line)
    flush()
    return blocks


def _split_table(table: str) -> list[str]:
    if len(table) <= MAX_TABLE_CHARS:
        return [table]
    rows = table.split("\n")
    header, body = rows[:2], rows[2:]
    parts, current = [], list(header)
    for row in body:
        if len("\n".join(current + [row])) > MAX_TABLE_CHARS and len(current) > len(header):
            parts.append("\n".join(current))
            current = list(header)
        current.append(row)
    parts.append("\n".join(current))
    return parts


def _is_table(block: str) -> bool:
    return all(_TABLE_ROW.match(l) for l in block.split("\n"))


def _pack(blocks: list[str]) -> list[str]:
    """Group blocks into pieces of at most MAX_CHARS, keeping tables intact."""
    pieces: list[str] = []
    current = ""
    for block in blocks:
        if _is_table(block):
            if current:
                pieces.append(current)
                current = ""
            pieces.extend(_split_table(block))
            continue
        if current and len(current) + len(block) + 2 > MAX_CHARS:
            pieces.append(current)
            current = ""
        current = f"{current}\n\n{block}" if current else block
    if current:
        pieces.append(current)
    return pieces


def chunk_markdown(content: str) -> list[Chunk]:
    sections: list[tuple[list[str], list[str]]] = []  # (heading stack, body lines)
    stack: list[tuple[int, str]] = []
    body: list[str] = []
    in_fence = False

    def close():
        nonlocal body
        if any(l.strip() for l in body):
            sections.append(([t for _, t in stack], body))
        body = []

    for line in content.splitlines():
        if _FENCE.match(line):
            in_fence = not in_fence
        m = None if in_fence else _HEADING.match(line)
        if m:
            close()
            level, title = len(m.group(1)), m.group(2).strip()
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, title))
        else:
            body.append(line)
    close()

    chunks: list[Chunk] = []
    for path_parts, lines in sections:
        # The first heading is usually the document title, which indexed_text adds anyway.
        path = " > ".join(path_parts)
        for piece in _pack(_blocks(lines)):
            chunks.append(Chunk(section_path=path, text=piece))
    return chunks
