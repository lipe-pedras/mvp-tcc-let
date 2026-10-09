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

## Fase 3

- **Nenhuma conversa é armazenada.** O servidor guarda apenas: lacunas (texto da pergunta, embedding, dia, origem), feedback (sem usuário) e contadores diários (respondidas/recusadas). As tabelas `gaps`, `feedback` e `usage_daily` não têm referência a usuário (há teste automatizado para isso). O cliente reenvia pergunta e resposta ao dar feedback.
- **"Grupo" no painel do gestor = agrupamento de perguntas parecidas** (clusters por embedding), não grupo de acesso. Assim a lacuna não precisa registrar quem perguntou. Interpretação do enunciado.
- **Comentários de feedback são gravados mas não aparecem no painel** (texto livre pode identificar a pessoa). Só contagens agregadas.
- **Trechos enviados ao LLM:** os `top_k` melhores com nota do reranker ≥ limiar. Trechos abaixo do limiar não vão para o prompt, mesmo que sobrem vagas.
- **Recusa:** (a) nota do melhor trecho < limiar → LLM nunca é chamado; (b) LLM responde `SEM_EVIDENCIA`; (c) resposta sem nenhuma citação válida. Em todos os casos o texto devolvido é o da recusa, nunca o texto não citado do modelo. Os três casos registram uma lacuna.
- **Citações inválidas** (`[9]` com 5 trechos) são removidas do texto; se sobrar alguma válida, a resposta vale.
- **Responsável sugerido na recusa** = responsável do documento do melhor trecho recuperado (sempre um documento que o usuário pode ver), exibido junto ao nome do documento para que a pessoa julgue a relevância. Observação: com nota baixa o documento pode ser irrelevante (nas perguntas de teste, a sugestão apontou para documentos sem relação). Avaliar se vale exigir uma nota mínima.
- **Avisos de revisão vencida** só aparecem para documentos efetivamente citados na resposta.
- **Streaming com buffer + eventos de etapa** (`retrieving`, `generating`, `validating`, depois `result`) via SSE em `POST /api/chat`. Indisponibilidade do Ollama gera um evento `error`.
- **Ollama com `think: false`.** Modelos com modo de raciocínio (Qwen 3.5) ficam mais lentos e podem vazar o raciocínio na resposta.
- **Provedor OpenAI-compatível implementado com `httpx`** (sem o SDK `openai`), para manter as dependências e a superfície de rede mínimas. Desligado por padrão; só `LLM_PROVIDER=openai` o ativa. Nesse modo, trechos e perguntas saem da máquina.
- **O harness usa `record=False`**: perguntas de avaliação não poluem lacunas nem estatísticas.
- **Modelo padrão: `qwen3.5:4b`.** Comparado com `gemma4:e4b` no conjunto de exemplo (13 perguntas) houve empate em tudo (recusas corretas, citações, zero vazamento); o Gemma foi um pouco mais rápido (4,9 s vs 6,1 s no total mediano), mas ocupa 6,6 GB e não cabe nos 4 GB de VRAM. Reavaliar com o conjunto real de 30–50 perguntas e o juiz LLM.
- **Contaminação (`sem_recuperacao`):** no exemplo, nenhuma resposta do modelo sem trechos acertou um fato do corpus; ele inventou valores com confiança (ex.: "200 milicores" de CPU). Isso confirma que os fatos fictícios não estão no conhecimento prévio, e que sem recuperação o modelo alucina.

## Fase 4

- **Endpoints novos para o painel** (`/api/manager/*`): lacunas, estatísticas e revisões vencidas. Nenhuma resposta tem id de usuário, e-mail ou conversa (teste automatizado percorre as respostas procurando esses campos).
- **K-anonimato no painel:** clusters com menos de K ocorrências não são devolvidos nem descritos; só entram em `hidden_gaps` (contagem). K = `GAP_MIN_OCCURRENCES` (padrão 3).
- **Limite de similaridade das lacunas = 0,60** (`GAP_SIMILARITY`), calibrado com embeddings reais do `bge-m3`: perguntas do mesmo tema ficaram entre 0,65 e 0,90 de similaridade e as de temas diferentes abaixo de 0,55 (amostra pequena; recalibrar com dados reais). Agrupamento guloso por centroide.
- **Botão “isso não respondeu” só em respostas dadas.** Em recusas a lacuna já é registrada automaticamente; um segundo registro duplicaria a contagem.
- **Citações abrem em nova aba**, para não perder a conversa (que só existe em memória no navegador e nunca é salva).
- **Passagem citada por id de trecho** (`GET /documents/{id}/passages/{chunk_id}`): a citação continua apontando para o texto que foi de fato lido, mesmo que o documento tenha sido atualizado depois. Segue a mesma regra de visibilidade do documento (404 sem permissão).
- **Token JWT em `localStorage`.** Simples para o MVP; o React escapa o conteúdo e o Markdown não renderiza HTML cru, mas um XSS roubaria o token. Para produção, preferir cookie `HttpOnly`.
- **Editor envia só o que mudou** (diff no cliente), para não gerar versão nem reindexação sem necessidade.
- **Lista de pessoas para “responsável pelo tema”** (`/api/people`) devolve apenas id e nome, para gestores.
- **Sem framework de UI** (CSS próprio, claro/escuro automático) e sem biblioteca de gráficos: o gráfico diário é feito com barras em CSS.

## Fase 5

- **Juiz LLM só extrai; o código dá as notas.** O primeiro desenho pedia ao juiz um veredito direto (correta/parcial/incorreta, suportada/não). Com o `qwen3.5:4b` ele acertou só 4 de 7 casos de teste: aprovou como "suportada" uma resposta com valor errado e como "correta" uma resposta incompleta. A rubrica v2 pede apenas extração (fatos do gabarito presentes/contraditos; afirmações da resposta com a citação literal que as sustenta) e o programa calcula: um fato contraditório torna a resposta incorreta; fato faltando, parcial; uma afirmação só é "sustentada" se a citação existir literalmente nos trechos citados e se todos os números/códigos da afirmação aparecerem nessa citação. Com isso o mesmo modelo passou 7/7 (e o `gemma4:e4b`, 6/7).
- **O autoteste do juiz** (`python -m eval.judge --selftest`) roda esses casos conhecidos e deve ser executado ao trocar o modelo do juiz. **Ressalva:** a rubrica v2 foi ajustada olhando para essas mesmas falhas; 7/7 não prova generalização. Calibrar com anotação humana (coluna `anotacao_humana` do CSV) no conjunto real.
- **Limitações do juiz local:** o `qwen3.5:4b` julga as respostas do próprio `qwen3.5:4b` (viés de autoavaliação) e a checagem de números só vale para fatos numéricos. Para um juiz mais independente, use `JUDGE_MODEL` com outro modelo local ou `JUDGE_PROVIDER=openai` (isso envia dados para fora da máquina; ligar só conscientemente).
- **Recusas são pontuadas por regra, sem chamar o juiz:** recusar é correto exatamente quando a resposta esperada é vazia.
- **Definições das métricas do juiz:** `taxa_alucinacao` = respostas dadas com ao menos uma afirmação não sustentada pelos trechos que citam (fidelidade `parcial` ou `nao_suportada`); `contaminacao_*` (modo `sem_recuperacao`) = quanto do corpus o modelo já "sabia" sem trechos; `fabricacao_sem_resposta` = perguntas sem resposta no corpus em que o modelo inventou detalhes em vez de admitir que não sabe.
- **Rubrica versionada em arquivo** (`eval/prompts/judge_rubric_v2.md`); o resumo registra a versão e o modelo do juiz. A v1 foi removida (permanece no histórico do git).
- **Varredura de limiar** (`eval.sweep_threshold`) usa só o `top_score` do CSV do `so_busca`, então testar muitos limiares não custa nova recuperação. Recomenda a faixa de maior (recusa correta − recusa indevida) e informa se o limiar atual está nela. No exemplo, a faixa é 0,05–0,70 e o limiar 0,30 está dentro; com 13 perguntas isso é só indicativo.
- **Resultado de referência (13 perguntas de exemplo, `qwen3.5:4b`, limiar 0,30):** Recall@3 = 1,0; MRR = 1,0; vazamentos = 0; recusa correta = 100%; recusa indevida = 0%; acerto = 100%; alucinação = 0%; contaminação = 0%; fabricação sem recuperação = 75%; tempo total mediano ≈ 5 s (busca ≈ 4 s, quase tudo no reranker em CPU).
