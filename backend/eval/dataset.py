import json
from dataclasses import dataclass, field
from pathlib import Path

TIPOS = {"com_resposta", "sem_resposta", "desatualizado", "vazamento"}


@dataclass
class Question:
    id: str
    pergunta: str
    tipo: str
    resposta_esperada: str
    evidencias: list[dict[str, str]]
    grupos: list[str]
    extra: dict = field(default_factory=dict)


def load_questions(path: Path) -> list[Question]:
    questions = []
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        d = json.loads(line)
        if d["tipo"] not in TIPOS:
            raise ValueError(f"{path}:{n}: tipo inválido {d['tipo']!r} (esperado: {sorted(TIPOS)})")
        questions.append(
            Question(
                id=d["id"],
                pergunta=d["pergunta"],
                tipo=d["tipo"],
                resposta_esperada=d.get("resposta_esperada", ""),
                evidencias=d.get("evidencias", []),
                grupos=d["perfil"]["grupos"],
                extra={k: v for k, v in d.items() if k not in {"id", "pergunta", "tipo", "resposta_esperada", "evidencias", "perfil"}},
            )
        )
    ids = [q.id for q in questions]
    if len(ids) != len(set(ids)):
        raise ValueError("ids de perguntas duplicados")
    return questions
