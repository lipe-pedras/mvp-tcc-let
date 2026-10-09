"""Citation handling: the answer must cite numbered passages that were actually sent."""

import re

NO_EVIDENCE = "SEM_EVIDENCIA"

# Matches [1], [1, 2], [1,2], [1][2] groups; each bracket is parsed separately.
_BRACKET = re.compile(r"\[(\s*\d+(?:\s*[,;]\s*\d+)*\s*)\]")


def is_no_evidence(answer: str) -> bool:
    return NO_EVIDENCE in answer.upper().replace(" ", "_") or not answer.strip()


def validate_citations(answer: str, n_passages: int) -> tuple[str, list[int]]:
    """Return (cleaned answer, sorted valid citation numbers).

    Citations pointing to passages that were never sent (e.g. [9] with 5 passages)
    are removed from the text; they must not appear as if they were sources.
    """
    valid: set[int] = set()

    def fix(m: re.Match) -> str:
        nums = [int(x) for x in re.split(r"[,;]", m.group(1))]
        good = [n for n in nums if 1 <= n <= n_passages]
        valid.update(good)
        return f"[{', '.join(map(str, good))}]" if good else ""

    cleaned = _BRACKET.sub(fix, answer)
    cleaned = re.sub(r"[ \t]+([.,;:])", r"\1", cleaned)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned).strip()
    return cleaned, sorted(valid)
