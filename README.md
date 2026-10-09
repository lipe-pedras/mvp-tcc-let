# Plataforma de conhecimento interno (MVP)

Tutoriais internos + chat RAG que responde só com base na documentação, sempre citando a fonte e recusando quando não há evidência.

> Status: **MVP completo (fases 1–5).** Decisões de projeto e suas razões em [`docs/decisions.md`](docs/decisions.md).

## Requisitos

**Software:** Linux ou macOS, Docker + Compose, [uv](https://docs.astral.sh/uv/) (instala o Python 3.12), Node 24 + npm, [Ollama](https://ollama.com).

**Hardware** (testado em notebook com RTX 3050 de 4 GB de VRAM, 16 GB de RAM, CachyOS):

| Item | Mínimo | Observação |
|---|---|---|
| RAM | 16 GB | Postgres, API, reranker (~2 GB) e Ollama convivem. |
| VRAM | 4 GB (ou nenhuma) | O `qwen3.5:4b` cabe em 4 GB. Sem GPU roda na CPU, mais lento. |
| Disco | ~15 GB | Modelos do Ollama (~11 GB), reranker (~2 GB), PyTorch CPU e Docling. |

- **Mac com Apple Silicon (32 GB+):** rode o Ollama **nativamente**, fora do Docker, para usar a GPU. Aqui o Ollama já roda fora do Docker em qualquer sistema; só o PostgreSQL está no Compose.
- **GPU NVIDIA de 16–24 GB:** instale `ollama-cuda` (ou o instalador oficial) e use modelos maiores (`LLM_MODEL=qwen3.5:9b`, por exemplo). O PyTorch do projeto é só CPU de propósito (a GPU fica com o LLM); o reranker roda na CPU em qualquer cenário.
- **Latência esperada nesta máquina:** ~5 s por pergunta (a maior parte é o reranker na CPU) e a resposta só aparece depois de validada.
- **Rede:** o único acesso externo é o download único dos modelos (Ollama e Hugging Face/Docling). Depois disso o sistema funciona offline e, com o provedor `ollama`, nenhum dado sai da máquina.

## Instalação do zero

```bash
git clone <este repositório> && cd <pasta>

# 1. Ollama e modelos (o serviço do Ollama precisa estar rodando)
ollama pull bge-m3          # embeddings
ollama pull qwen3.5:4b      # LLM padrão (e juiz)

# 2. Configuração e banco
cp .env.example .env        # troque JWT_SECRET por uma string longa e aleatória
docker compose up -d db     # PostgreSQL 17 + pgvector (cria também o banco kb_test)

# 3. Backend (Python 3.12 via uv)
cd backend
uv sync
uv run alembic upgrade head
uv run python -m app.cli.seed --reset      # usuários + 10 documentos de exemplo, já indexados
uv run uvicorn app.main:app                # http://localhost:8000  (docs interativas em /docs)

# 4. Frontend (outro terminal)
cd frontend
npm install
npm run dev                                # http://localhost:5173 (o Vite encaminha /api para :8000)
```

Entre com um dos usuários de exemplo (ver abaixo). Na primeira pergunta ao assistente, o reranker (`BAAI/bge-reranker-v2-m3`, ~2 GB) é baixado do Hugging Face e carregado; as perguntas seguintes são mais rápidas.

`npm run build` gera o frontend de produção em `frontend/dist`. Para produção, sirva-o por um proxy reverso que também encaminhe `/api` para a API, e prefira cookies `HttpOnly` ao token em `localStorage` (ver decisões).

## Dados de exemplo

```bash
cd backend
uv run python -m app.cli.seed --reset   # apaga o banco e carrega usuários + 10 documentos (precisa do Ollama com bge-m3)
```

Usuários de exemplo (senha `senha-12345`, só para desenvolvimento): `admin@`, `gestor.rh@`, `gestor.eng@`, `colab.fin@`, `colab.eng@` e `novato@alvorada.example`. O documento de faixas salariais só é visível ao grupo `financeiro`; o de deploy, a `engenharia`.

Importar arquivos: `POST /api/documents/import` (PDF/DOCX/PPTX, multipart). O documento entra como rascunho. Na primeira conversão de PDF, o Docling baixa seus modelos (uma vez).

## Avaliação

O harness de avaliação tem a mesma prioridade do chat. Tudo roda a partir de `backend/`:

```bash
cd backend
Q=eval/questions.example.jsonl        # a equipe escreve o conjunto real (30–50 perguntas) neste formato

uv run python -m eval.run --questions $Q --mode so_busca                 # só a recuperação
uv run python -m eval.run --questions $Q --mode rag --judge              # sistema completo + juiz LLM
uv run python -m eval.run --questions $Q --mode sem_recuperacao --judge  # o LLM sem trechos (contaminação)

uv run python -m eval.sweep_threshold --results eval/results/<run>-so_busca.csv   # calibrar o limiar
uv run python -m eval.judge --selftest                                            # o juiz distingue respostas boas de ruins?
uv run python -m eval.judge --results eval/results/<run>-rag.csv --mode rag       # re-julgar um CSV (ex.: outro juiz)
```

**Formato das perguntas** (JSONL, uma por linha): `id`, `pergunta`, `tipo` (`com_resposta` | `sem_resposta` | `desatualizado` | `vazamento`), `resposta_esperada` (vazia em `sem_resposta` e `vazamento`), `evidencias` (lista de `{documento, secao}`; `secao` é um trecho do caminho de seções) e `perfil` (`{"grupos": [...]}`, quem pergunta). Campo opcional `contradicao: true` para perguntas cuja documentação diverge.

**Modos**

| Modo | O que faz |
|---|---|
| `so_busca` | Só recuperação: Recall@k, MRR, vazamento e a recusa estimada pela nota do reranker. |
| `rag` | Sistema completo. Acrescenta recusa real, citação da evidência esperada, aviso de revisão vencida, latências (primeiro token e total) e, com `--judge`, acerto, fidelidade e alucinação. |
| `sem_recuperacao` | O LLM responde sem nenhum trecho: mede o que o modelo já "sabe" do corpus (contaminação) e o quanto inventa. |

**Métricas principais:** Recall@1/3/5 e MRR; recusa correta (`sem_resposta`, `vazamento`) e recusa indevida (`com_resposta`, `desatualizado`); **taxa de vazamento (deve ser 0; o comando termina com erro se não for)**; citação da evidência esperada; acerto e fidelidade (juiz); taxa de alucinação (resposta com afirmação não sustentada pelos trechos que cita); contaminação e fabricação (`sem_recuperacao`); latências.

**Saídas** em `backend/eval/results/` (não versionadas): um CSV por pergunta, com a coluna `anotacao_humana` para a anotação posterior, e um resumo em Markdown com as métricas e a configuração usada (modelos, limiar, top-k, juiz, rubrica e data). A varredura de limiar gera uma tabela recusa correta × recusa indevida e indica a faixa recomendada.

**Sobre o juiz LLM.** Modelos locais pequenos julgam mal de forma holística. Por isso o juiz só *extrai* (fatos presentes, afirmações com a citação literal que as sustenta) e o código calcula as notas; o `--selftest` confere o juiz com casos conhecidos e deve ser rodado ao trocar `JUDGE_MODEL`. Limitações (viés de autoavaliação, ajuste da rubrica aos casos do autoteste) em [`docs/decisions.md`](docs/decisions.md). A rubrica fica em `backend/eval/prompts/judge_rubric_v2.md`.

**Resultado de referência** (13 perguntas de exemplo, `qwen3.5:4b`, limiar 0,30; é um teste de fumaça, não uma estimativa de qualidade): Recall@3 = 1,0 · MRR = 1,0 · vazamentos = 0 · recusa correta = 100% · recusa indevida = 0% · acerto = 100% · alucinação = 0% · contaminação = 0% · fabricação sem recuperação = 75% · tempo total mediano ≈ 5 s.

## Fluxo manual completo (com prints)

Com a API, o Vite e o Ollama rodando e o banco populado (`app.cli.seed --reset`). As capturas abaixo foram geradas em navegador real por `docs/walkthrough.mjs` (Playwright; instale `playwright` em um diretório à parte e rode `node walkthrough.mjs <pasta-de-saída>`).

1. **Login** como `novato@alvorada.example` (senha `senha-12345`).
   ![login](docs/screenshots/01-login.png)
2. **Ler tutoriais**: só aparecem os documentos dos grupos do usuário (o de faixas salariais e o de deploy não aparecem para o `novato`).
   ![tutoriais](docs/screenshots/02-tutoriais.png) ![leitura](docs/screenshots/03-leitura-tutorial.png)
3. **Perguntar** ao assistente. Enquanto a resposta é gerada e validada, aparecem mensagens de progresso (“Coletando informações no banco de dados…”, “Gerando resposta…”, “Validando conteúdo…”, “Verificando a veracidade…”).
   ![carregando](docs/screenshots/04-carregando.png)
4. **Resposta citada**, com fontes (documento, seção, versão) e botões de feedback.
   ![resposta](docs/screenshots/05-resposta-com-fontes.png)
5. **Clicar na citação** abre, em nova aba, o trecho exato citado e o documento, com a seção destacada (se a versão citada não for mais a atual, a tela avisa).
   ![citação](docs/screenshots/06-citacao-aberta.png)
6. **Recusa**: sem evidência suficiente, o assistente não inventa; indica o responsável pelo tema e registra a lacuna de forma anônima. Perguntas sobre documentos sem permissão (ex.: faixas salariais) também são recusadas.
   ![recusa](docs/screenshots/07-recusa-com-responsavel.png) ![restrito](docs/screenshots/09-restrito-recusa.png)
7. **“Isso não respondeu”**: registra feedback anônimo (e uma lacuna).
   ![feedback](docs/screenshots/08-feedback-enviado.png)
8. **Gestor** (`gestor.rh@alvorada.example`): o **Painel** mostra estatísticas agregadas, a lacuna agrupada (aparece só com ≥ K ocorrências; as perguntas isoladas ficam ocultas e apenas contadas) e os documentos com revisão vencida.
   ![painel](docs/screenshots/10-painel-gestor.png)
9. **Gerenciar documentos**: criar, editar, importar (PDF/DOCX/PPTX), definir responsável, data de revisão e grupos; histórico de versões.
   ![gerenciar](docs/screenshots/11-gerenciar-documentos.png) ![editor](docs/screenshots/12-editor-documento.png)
10. **Admin** (`admin@alvorada.example`): usuários, papéis e grupos.
    ![admin](docs/screenshots/13-administracao.png)

## Chat (API)

- `POST /api/chat` `{"question": "..."}` → Server-Sent Events: eventos `stage` (`retrieving`, `generating`, `validating`) e um `result` final com `status` (`answered`/`refused`), `answer`, `sources` (documento, seção, versão), `warnings` (revisão vencida) e `responsible` (na recusa). A resposta só é enviada depois de gerada e validada.
- `POST /api/chat/feedback` `{question, answer, helpful, comment?}` → 204. Sem vínculo com o usuário; avaliação negativa também registra uma lacuna.
- A busca do chat sempre respeita os grupos do usuário, inclusive para admin.

## Trocar modelos e provedor

Tudo se configura no `.env` (modelo de cada variável em `.env.example`); nenhuma troca exige mudar código.

| Quero trocar | Como |
|---|---|
| **LLM local** | `ollama pull <modelo>` e `LLM_MODEL=<modelo>`. Modelos de 4B (`qwen3.5:4b`, `gemma4:e4b`) rodam em 4 GB de VRAM/16 GB de RAM; 8–14B pedem mais memória ou ficam lentos na CPU. Rode `eval.run --mode rag --judge` antes de adotar. |
| **Provedor do LLM** | `LLM_PROVIDER=ollama` (padrão, local) ou `openai`, que aceita qualquer endpoint compatível com a API da OpenAI (`OPENAI_BASE_URL`, `OPENAI_API_KEY`, `LLM_MODEL`). **Com `openai`, perguntas e trechos de documentos saem da máquina.** |
| **Modelo de embeddings** | `EMBEDDING_MODEL` e `EMBEDDING_DIM`. Se a dimensão mudar, crie uma migração Alembic para a coluna `chunks.embedding`; depois rode `uv run python -m app.cli.reindex`. |
| **Limiar de recusa** | `REFUSAL_THRESHOLD`. Calibre com `eval.sweep_threshold` (ver Avaliação). |
| **Trechos por resposta / candidatos** | `TOP_K`, `RETRIEVAL_CANDIDATES`, `RERANK_TOP_N`. |
| **Mínimo de ocorrências do painel (K)** | `GAP_MIN_OCCURRENCES` (padrão 3) e `GAP_SIMILARITY`. |
| **Modelo do juiz** | `JUDGE_PROVIDER`, `JUDGE_MODEL` (vazio = o mesmo `LLM_MODEL`). |

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
