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
