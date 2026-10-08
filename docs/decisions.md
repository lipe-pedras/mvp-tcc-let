# Decisões de projeto

Registro das decisões não cobertas (ou interpretadas) a partir do enunciado do MVP.

## Fase 1

- **Python 3.12 em venv gerenciado pelo `uv`.** O Python do sistema (3.14) é novo demais para Docling/PyTorch.
- **Ollama roda nativo, fora do Docker.** Só o PostgreSQL (pgvector) está no Compose. Evita configurar GPU em container e mantém a mesma configuração em Linux e Mac (onde o nativo é obrigatório).
- **Embeddings via Ollama (`bge-m3`)**, reranker via sentence-transformers na CPU. O Ollama carrega/descarrega o modelo de embedding sob demanda, poupando memória (4 GB VRAM, ~10 GiB RAM livres).
- **Streaming com buffer (opção B).** O backend gera a resposta inteira, valida citações e só então a envia. Nenhuma afirmação sem fonte chega ao usuário. O frontend mostra etapas (`retrieving`, `generating`, `validating`) com frases de carregamento. Reavaliar se a espera ficar incômoda.
- **SQLAlchemy síncrono + psycopg 3.** Mais simples; suficiente para o MVP.
- **Autenticação:** JWT Bearer, expiração de 8h, sem refresh token.
- **Documento sem permissão devolve 404, não 403**, para não revelar que o documento existe.
- **Visibilidade:** admin vê tudo; gestor vê documentos de seus grupos (em qualquer status); colaborador vê só documentos *publicados* de seus grupos.
- **Gestor só concede acesso a grupos dos quais participa**, e só edita documentos de seus grupos. Todo documento precisa de ao menos um grupo (o grupo `todos` é o padrão para conteúdo geral).
- **Documentos são arquivados, nunca apagados** (`DELETE` muda o status para `archived`), preservando o histórico de versões.
- **Nova versão só quando título ou conteúdo mudam.** Editar metadados (responsável, revisão, grupos, status) não cria versão.
- **Responsável pelo tema** é uma referência a um usuário (`responsible_id`), não texto livre.
- **Banco de testes separado (`kb_test`)**, criado pelo script de init do Postgres, para que os testes nunca toquem dados reais.
- **Commits sem co-autoria**; um branch por unidade de trabalho, nada direto na `main`.

## Fase 2

- **Chunking por estrutura** (seções e tabelas), com teto de ~1500 caracteres por chunk. Tabelas até 2500 caracteres ficam inteiras; maiores são divididas por linhas repetindo o cabeçalho. Sem sobreposição entre chunks.
- **Caminho de seções sem o título repetido:** se o primeiro nível do caminho for igual ao título do documento, ele é omitido (o título já vem antes no texto indexado).
- **Texto indexado = título + caminho + conteúdo.** É isso que alimenta tanto o embedding quanto o `tsvector` (coluna gerada, configuração `portuguese`).
- **Sem índice vetorial (HNSW/IVFFlat) no MVP.** A busca densa é exata (varredura filtrada por grupo), o que evita perda de recall quando o filtro de permissão é seletivo. Reavaliar quando o corpus passar de dezenas de milhares de chunks.
- **Busca lexical com OR** entre os termos da pergunta (cada termo entre aspas, para preservar códigos como `HR-204`), ordenada por `ts_rank_cd`. Um AND exigiria que todas as palavras da pergunta aparecessem no trecho. Limitação conhecida: sem `unaccent`, "ferias" não casa com "férias" na busca lexical (a densa cobre).
- **Filtro de permissão dentro das duas consultas SQL** (`group_ids && grupos_do_usuario`), antes do ranking, inclusive para admin: **a busca do chat nunca ignora grupos**, mesmo para admin. A visibilidade de leitura de documentos (API) é uma regra separada.
- **Só documentos `published` têm chunks ativos.** Rascunhos e arquivados não são pesquisáveis; publicar reindexa.
- **Indexação na mesma transação da edição.** Se o Ollama estiver fora, a API responde 503 e nada é salvo (evita documento sem índice).
- **Mudar só os grupos** do documento não reindexa; apenas copia os novos grupos para os chunks ativos.
- **Importação (PDF/DOCX/PPTX) via Docling cria o documento como rascunho**, para o gestor revisar a conversão antes de publicar. Página (`page`) fica vazia por enquanto; ponto de extensão em `ingestion/parsers.py`.
- **PyTorch somente CPU** (`torch`/`torchvision` do índice `pytorch-cpu`): a GPU de 4 GB fica reservada ao LLM. O reranker roda na CPU (~5 s por pergunta com 15 candidatos nesta máquina).
- **Telemetria desativada** explicitamente: `HF_HUB_DISABLE_TELEMETRY`, `DO_NOT_TRACK`, OpenTelemetry do FastAPI desligado. O único acesso à rede é o download único dos modelos (Hugging Face e Docling) na primeira execução.
- **Pacote `eval/` dentro de `backend/`**, para importar `app` sem configuração extra. Perguntas e resultados em `backend/eval/`. Resultados (`eval/results/`) não são versionados.
- **Perfil das perguntas de avaliação = lista de grupos** (`"perfil": {"grupos": [...]}`), não usuário. O vazamento é checado contra os grupos do *chunk* e os grupos atuais do *documento*.
- **Corpus de exemplo:** empresa fictícia "Alvorada Logística". O documento de deploy é restrito ao grupo `engenharia` e as faixas salariais ao `financeiro` (dois cenários de vazamento). A contradição proposital: prazo de reembolso de 15 dias corridos (Reembolso de Despesas) × 10 dias corridos (Guia de Viagens). Revisão vencida: Política de Senhas (30/06/2025).
