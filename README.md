# Plataforma de conhecimento interno (MVP)

Tutoriais internos + chat RAG que responde só com base na documentação, sempre citando a fonte e recusando quando não há evidência.

> Status: **Fase 1 concluída** (base: Docker/Postgres, FastAPI, JWT, papéis e grupos, CRUD de documentos com versões). Ver `docs/decisions.md`.

## Requisitos

- Linux/Mac, Docker + Compose, [uv](https://docs.astral.sh/uv/), Node 24 (frontend, Fase 4), Ollama.
- Hardware de desenvolvimento: notebook com RTX 3050 (4 GB VRAM), 16 GB de RAM. Modelos de ~4B rodam na GPU/CPU; modelos maiores ficam lentos.
- No Mac (Apple Silicon), rode o Ollama nativamente para usar a GPU.

## Instalação (desenvolvimento)

```bash
cp .env.example .env            # ajuste JWT_SECRET
docker compose up -d db         # PostgreSQL 17 + pgvector (cria também o banco kb_test)

cd backend
uv venv --python 3.12 .venv
uv sync
uv run alembic upgrade head
uv run uvicorn app.main:app --reload
```

API em http://localhost:8000 (docs interativas em `/docs`).

Modelos do Ollama (usados a partir da Fase 2/3):

```bash
ollama pull bge-m3
ollama pull qwen3.5:4b
ollama pull gemma4:e4b
```

## Testes

```bash
cd backend && uv run pytest
```

Os testes usam o banco `kb_test` (recriado a cada execução).

## Permissões (resumo)

| Papel | Lê | Escreve |
|---|---|---|
| colaborador | documentos publicados dos seus grupos | – |
| gestor | documentos dos seus grupos (qualquer status), histórico de versões | documentos dos seus grupos |
| admin | tudo | tudo + usuários e grupos |
