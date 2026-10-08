# Procedimento de Deploy no Ambiente Tucano

Procedimento para publicar serviços em produção no ambiente **Tucano** (cluster de produção da Alvorada).

## Janela de deploy

Deploys em produção só podem acontecer às **terças e quintas, das 22h às 23h30**. Fora da janela, só com aprovação do plantão SRE (ramal 4477).

## Parâmetros padrão

| Parâmetro | Valor | Observação |
|-----------|-------|------------|
| Réplicas mínimas | 3 | Nunca reduzir em produção |
| Timeout de readiness | 45 s | Acima disso o pod é reiniciado |
| Flag de canário | `--canario=12` | 12% do tráfego por 20 minutos |
| Limite de CPU por pod | 800m | Aumentos exigem revisão da arquitetura |
| Limite de memória por pod | 1536 Mi | |
| Rollback automático | taxa de erro > 2,5% | Medida em janela de 5 minutos |

## Passo a passo

1. Abra a solicitação de mudança no ORBITA (categoria **Mudança > Produção, código MUD-09**).
2. Rode o pipeline `tucano-release` com a flag de canário.
3. Acompanhe o painel "Saúde Tucano" por 20 minutos.
4. Se a taxa de erro ficar abaixo de 2,5%, promova para 100% com `tucano promote`.
5. Registre o resultado no chamado MUD-09 e feche-o.

## Em caso de falha

O rollback é automático acima do limite de erro. Para forçar manualmente, use `tucano rollback --servico <nome>` e avise o canal #sre-plantao.
