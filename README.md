# Plataforma de conhecimento interno (MVP)

Tutoriais internos + chat RAG que responde só com base na documentação, sempre citando a fonte e recusando quando não há evidência.

> Status: **Fase 2 concluída** (ingestão, busca híbrida com filtro de permissão, reranker, avaliação `so_busca`). Chat, frontend e juiz LLM vêm nas próximas fases. Ver `docs/decisions.md`.

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

Modelos do Ollama:

```bash
ollama pull bge-m3
ollama pull qwen3.5:4b
ollama pull gemma4:e4b
```

## Dados de exemplo

```bash
cd backend
uv run python -m app.cli.seed --reset   # apaga o banco e carrega usuários + 10 documentos (precisa do Ollama com bge-m3)
```

Usuários de exemplo (senha `senha-12345`, só para desenvolvimento): `admin@`, `gestor.rh@`, `gestor.eng@`, `colab.fin@`, `colab.eng@` e `novato@alvorada.example`. O documento de faixas salariais só é visível ao grupo `financeiro`; o de deploy, a `engenharia`.

Importar arquivos: `POST /api/documents/import` (PDF/DOCX/PPTX, multipart). O documento entra como rascunho. Na primeira conversão de PDF, o Docling baixa seus modelos (uma vez).

## Avaliação

```bash
cd backend
uv run python -m eval.run --questions eval/questions.example.jsonl --mode so_busca
```

Gera, em `backend/eval/results/`, um CSV por pergunta (com coluna `anotacao_humana`) e um resumo em Markdown. A primeira execução baixa o reranker `bge-reranker-v2-m3` (~2 GB). Os modos `rag` e `sem_recuperacao` chegam na Fase 3.

Resultado atual sobre o corpus de exemplo (13 perguntas): Recall@3 = 1,0, MRR = 1,0, vazamentos = 0, recusa correta = 100%, recusa indevida = 0% (limiar 0,3). Conjunto pequeno: serve como teste de fumaça, não como estimativa de qualidade.

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
