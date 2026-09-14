# Prompt-file — Arquitetura SoD Fase 3 (ícones oficiais AWS)

Arquivo gerado: `arquitetura_aws_icones.drawio` (+ PNG e PDF).

Versão com ícones oficiais AWS da arquitetura do projeto 3. Complementa
`arquitetura_sod_fase3.drawio`, que é a versão executiva anotada com números,
custos e seções de segurança.

## Arquitetura confirmada na AWS

Conferido em `us-east-1`, conta resolvida em tempo de execução, via chamadas
somente de leitura (`glue get-crawler`, `get-database`, `get-tables`,
`get-partitions`):

| Item | Estado real |
|---|---|
| Bronze | CSV fiel à origem, **fora do catálogo** |
| Silver | 3 tabelas Parquet, `PartitionKey = edicao` |
| Gold | 8 tabelas Parquet, **sem** partição |
| Crawler `sod-fase3-crawler` | 11 alvos S3 explícitos (3 Silver + 8 Gold), último crawl `SUCCEEDED` |
| Data Catalog | database `sod_fase3`, 11 tabelas |
| Athena | resolve schema e location no catálogo, lê os Parquet direto do S3 |
| Resultados SQL | prefixo `athena-results` |

## Prompt de origem

> Diagrama de arquitetura AWS do pipeline State of Data Brasil, separando o
> plano de dados do plano de metadados.
>
> Plano de dados: Kaggle → Amazon S3 Bronze → AWS Glue Job 1 → Amazon S3 Silver
> → AWS Glue Job 2 → Amazon S3 Gold → Amazon Athena → Amazon S3 athena-results.
>
> Plano de metadados: Amazon S3 Silver e Amazon S3 Gold → AWS Glue Crawler → AWS
> Glue Data Catalog → Amazon Athena. A Bronze não é catalogada.
>
> Linhas sólidas para dados, tracejadas para metadados. Serviços transversais
> sem conexão: Amazon CloudWatch e AWS IAM. Região us-east-1, sem VPC.

## Padrões identificados

- Cadeia linear no plano de dados.
- Fan-in: Silver e Gold convergem no Crawler.
- Dupla dependência do Athena: dados vêm da Gold, schema vem do Data Catalog.
- Sem VPC: todos os componentes são serviços gerenciados e regionais.

## Grupos

| group_id | label | group_type | x | y | width | height |
|---|---|---|---|---:|---:|---:|---:|
| `aws-cloud` | AWS Cloud - us-east-1 | `aws-cloud` | 200 | 20 | 1420 | 700 |

Único grupo. Uma tentativa anterior usou um grupo `generic` extra para cercar
Crawler e Data Catalog, e foi abandonada — ver "Layout" abaixo.

## Nós

Três faixas, colunas a cada 200px começando em `x=50`. Coordenadas dos serviços
AWS relativas ao `aws-cloud`; o Kaggle usa coordenada absoluta de página.

- `LINHA_DADOS = 100`
- `LINHA_METADADOS = 340`
- `LINHA_APOIO = 540`

| node_id | label | sublabel | aws_service | parent | x | y |
|---|---|---|---|---|---:|---:|
| `kaggle` | Kaggle | State of Data - 3 edicoes CSV | `external-provider` | raiz | 40 | 120 |
| `s3-bronze` | Amazon S3 | Bronze - CSV bruto, fora do catalogo | `s3` | `aws-cloud` | 50 | 100 |
| `glue-job-silver` | AWS Glue | Job 1 - Bronze para Silver | `glue` | `aws-cloud` | 250 | 100 |
| `s3-silver` | Amazon S3 | Silver - 3 tabelas, particao edicao | `s3` | `aws-cloud` | 450 | 100 |
| `glue-job-gold` | AWS Glue | Job 2 - Silver para Gold | `glue` | `aws-cloud` | 650 | 100 |
| `s3-gold` | Amazon S3 | Gold - 8 tabelas, sem particao | `s3` | `aws-cloud` | 850 | 100 |
| `athena` | Amazon Athena | 16 consultas - le Parquet do S3 | `athena` | `aws-cloud` | 1050 | 100 |
| `s3-results` | Amazon S3 | athena-results | `s3` | `aws-cloud` | 1250 | 100 |
| `glue-crawler` | AWS Glue | Crawler - 11 alvos S3 | `glue` | `aws-cloud` | 850 | 340 |
| `glue-catalog` | AWS Glue | Data Catalog - sod_fase3, 11 tabelas | `glue` | `aws-cloud` | 1050 | 340 |
| `cloudwatch` | Amazon CloudWatch | Logs e metricas dos jobs | `cloudwatch` | `aws-cloud` | 50 | 540 |
| `iam` | AWS IAM | sod-fase3-glue-role | `iam` | `aws-cloud` | 250 | 540 |

O `kaggle` fica em `y=120` para alinhar com `LINHA_DADOS + y do aws-cloud` e
deixar a seta 1 reta.

## Conexões

### Plano de dados — sólido

| # | source | target | label | style | exit | entry |
|---|---|---|---|---|---|---|
| 1 | `kaggle` | `s3-bronze` | 1. Upload | async | 1.0, 0.5 | 0.0, 0.5 |
| 2 | `s3-bronze` | `glue-job-silver` | 2. Ler | sync | 1.0, 0.5 | 0.0, 0.5 |
| 3 | `glue-job-silver` | `s3-silver` | 3. Gravar | sync | 1.0, 0.5 | 0.0, 0.5 |
| 4 | `s3-silver` | `glue-job-gold` | 4. Ler | sync | 1.0, 0.5 | 0.0, 0.5 |
| 5 | `glue-job-gold` | `s3-gold` | 5. Gravar | sync | 1.0, 0.5 | 0.0, 0.5 |
| 6 | `s3-gold` | `athena` | 6. Ler Parquet | sync | 1.0, 0.5 | 0.0, 0.5 |
| 7 | `athena` | `s3-results` | 7. Resultados | sync | 1.0, 0.5 | 0.0, 0.5 |

A 1 é tracejada por ser ingestão externa manual; as demais são sólidas.

### Plano de metadados — tracejado

| # | source | target | label | style | exit | entry |
|---|---|---|---|---|---|---|
| M1 | `s3-silver` | `glue-crawler` | M1. Descobrir | async | 0.5, 1.0 | 0.0, 0.5 |
| M2 | `s3-gold` | `glue-crawler` | M2. Descobrir | async | 0.5, 1.0 | 0.5, 0.0 |
| M3 | `glue-crawler` | `glue-catalog` | M3. Registrar | async | 1.0, 0.5 | 0.0, 0.5 |
| M4 | `glue-catalog` | `athena` | M4. Schema | async | 0.5, 0.0 | 0.5, 1.0 |

A Bronze não tem aresta para o Crawler: não foi catalogada na implementação.
O sublabel dela declara isso.

CloudWatch e IAM não têm conexão — com 12 nós, a regra de serviços transversais
manda representá-los isolados na faixa de baixo.

## Layout

A chave é o alinhamento por coluna: **Crawler na mesma coluna do Gold** (`x=850`)
e **Data Catalog na mesma coluna do Athena** (`x=1050`). Isso torna M2 e M4
verticais retas e M3 uma horizontal curta. Só M1 tem dobra, e seu trecho
horizontal termina em `x=1050` absoluto, antes da vertical do M2 em `x=1110`,
então não há cruzamento de arestas.

### Duas tentativas descartadas

**Crawler e Catalog em linha no fluxo de dados.** Produzia a sequência
`Gold → Crawler → Catalog → Athena`, que sugere que o dado atravessa o catálogo.
Não atravessa: o catálogo guarda só metadados e o Athena lê os Parquet no S3.

**Grupo `generic` cercando Crawler e Catalog.** Visualmente pior. As setas M2 e
M4 furavam a borda superior e caíam sobre o texto do título do grupo, a M1
atravessava a borda esquerda depois de 700px de percurso, e o `validate_diagram`
acusava `icons 'plano-metadados' and 'glue-crawler' have overlapping bounding
boxes`. A separação por faixa e por estilo de linha comunica o mesmo sem a caixa.

## Decisões conscientes

- **Sem AWS KMS.** O validador sugere; o projeto usa SSE-S3 (AES256) por decisão
  documentada em `.kiro/specs/state-of-data-fase3/design.md`.
- **Sem aresta Athena → gráficos.** O `src/gerador_graficos.py` lê a Gold local
  com `pd.read_parquet`. As consultas Athena produzem evidência SQL e arquivos em
  `athena-results`, mas não alimentam as 9 figuras.
- **Notebooks e material executivo fora do diagrama.** Rodam na máquina local.
- **Ícones S3 e Glue repetidos.** Quatro buckets e quatro componentes Glue
  distintos, diferenciados pelo sublabel. O ícone é o mesmo porque o serviço é.

## Avisos esperados do validate_diagram

Nenhum indica defeito:

- `duplicate aws_service 's3' / 'glue'` — intencional, ver acima.
- `cell '<nó>' missing fontColor` e `edge ... non-black strokeColor #232F3E` —
  é o cinza-escuro padrão AWS aplicado pelo próprio engine.
- `group '<nó>' is a direct child of aws-cloud but is not a VPC/AZ/subnet/region`
  — falso positivo: o engine monta cada nó como grupo de ícone + rótulo.
- `S3 buckets should use KMS encryption` — ver acima.

## Como regerar

Sequência: `create_diagram` → `add_group` → `add_node` (12) →
`add_connection` (11) → `fix_diagram` → `drawio_validate_diagram`.

Exportação:

```bash
D="/Applications/draw.io.app/Contents/MacOS/draw.io"
"$D" --export --format png --scale 2 --border 20 \
     --output arquitetura_aws_icones.png arquitetura_aws_icones.drawio
"$D" --export --format pdf --crop --border 20 \
     --output arquitetura_aws_icones.pdf arquitetura_aws_icones.drawio
```

O servidor MCP valida caminhos contra `DRAWIO_FILES_ROOT`. Sem essa variável usa
o `cwd` do processo, e quando o cliente o define como `/` a checagem
`resolved.startsWith(root + separador)` rejeita todo caminho absoluto. Por isso
`.kiro/settings/mcp.json` define `DRAWIO_FILES_ROOT` e `DRAWIO_RENDER_ROOT`
apontando para a raiz do workspace.
