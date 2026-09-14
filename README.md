# Tech Challenge Fase 3 — State of Data Brasil

Pipeline de Engenharia de Dados e Analytics em AWS sobre a pesquisa **State of Data Brasil** (Data Hackers + Bain), analisando o mercado brasileiro de Dados, Analytics e IA para apoiar decisões de contratação, capacitação e investimento.

Especificação completa em `docs/spec/`.

## Dados

Três edições, **14.005 respondentes**:

| Edição | Dataset Kaggle | Respondentes | Colunas |
|---|---|---|---|
| 2023-2024 | `datahackers/state-of-data-brazil-2023` | 5.293 | 399 |
| 2024-2025 | `datahackers/state-of-data-brazil-20242025` | 5.217 | 403 |
| 2025-2026 | `datahackers/state-of-data-brazil-2025-2026` | 3.495 | 388 |

Baixe os três datasets do Kaggle, descompacte e renomeie os CSVs para `data/raw/`:

```
data/raw/state_of_data_2023.csv
data/raw/state_of_data_2024.csv
data/raw/state_of_data_2025.csv
```

Os dados não são versionados: são públicos sob Open Database License e somam ~42 MB.

## Ambiente

O Spark local precisa de Python 3.10 ou 3.11 e Java 17, espelhando o runtime do Glue 5.0. **PySpark 3.5.x não funciona em Python 3.12+.**

```bash
brew install openjdk@17

/opt/homebrew/bin/python3.10 -m venv .venv-spark
.venv-spark/bin/pip install -r requirements.txt

export JAVA_HOME=/opt/homebrew/opt/openjdk@17
export PATH=$JAVA_HOME/bin:$PATH
```

Registre o kernel do Jupyter para rodar o notebook de entrega:

```bash
.venv-spark/bin/python -m ipykernel install --user \
    --name sod-fase3-spark --display-name "Python 3.10 (SoD Fase 3 · Spark)"
```

## Execução local

```bash
# 1. Validar o mapeamento semântico entre edições (gate obrigatório)
.venv-spark/bin/python -m src.validar_mapeamento

# 2. Bronze -> Silver (inclui as tabelas de múltipla escolha)
.venv-spark/bin/python -m glue_jobs.job_bronze_para_silver

# 3. Conferência cruzada da Silver contra cálculo independente em pandas
.venv-spark/bin/python -m src.conferencia_cruzada

# 4. Silver -> Gold
.venv-spark/bin/python -m glue_jobs.job_silver_para_gold

# 5. Gráficos a partir da camada Gold
.venv-spark/bin/python -m src.gerador_graficos

# 6. Material executivo (usa python-pptx)
../.venv/bin/python -m src.gerador_material_executivo

# 7. Relatório técnico em DOCX e PDF
../.venv/bin/python -m src.gerador_relatorio_tecnico

# 8. Sanitizar as saídas do notebook antes da publicação
.venv-spark/bin/python -m src.preparar_notebook_entrega

# 9. Bloquear caminhos locais, identificadores e credenciais na entrega
../.venv/bin/python -m src.validar_privacidade_entrega
```

O pipeline completo roda em cerca de 50 segundos localmente.

### Privacidade dos artefatos

Antes da publicação, `src.preparar_notebook_entrega` substitui caminhos absolutos por referências portáveis e remove metadados de execução do notebook. Em seguida, `src.validar_privacidade_entrega` examina arquivos textuais, notebooks, documentos Office, PDFs e imagens e falha se encontrar caminho pessoal, usuário local, identificador da conta, e-mail corporativo ou padrão de credencial.

## Execução na AWS

O identificador da conta AWS não é versionado. Ele não é uma credencial, mas publicá-lo num repositório aberto permite phishing direcionado e vincula o código a uma conta específica.

O projeto resolve a conta em tempo de execução, nesta ordem:

1. variável de ambiente `SOD_ID_CONTA`
2. a conta ativa das suas credenciais AWS locais, consultada via STS

Ou seja, se o seu `aws configure` já está apontando para a conta desejada, não há nada a fazer. Para forçar outra conta:

```bash
export SOD_ID_CONTA=123456789012
export AWS_REGION=us-east-1   # opcional, o padrão é us-east-1
```

A execução **local** não precisa de conta AWS nenhuma — o pipeline roda inteiro sobre o sistema de arquivos.

```bash
# Provisiona bucket privado, IAM role escopada e Glue Database
.venv-spark/bin/python -m infra.provisionar

# Ingere os CSVs na camada Bronze
.venv-spark/bin/python -m infra.ingerir_bronze

# Cria e executa os dois Glue Jobs, e coleta a evidência de execução
.venv-spark/bin/python -m infra.executar_jobs

# Cataloga Silver e Gold, e valida cada tabela no Athena
.venv-spark/bin/python -m infra.catalogar

# Executa as 16 consultas analíticas e grava os resultados
.venv-spark/bin/python -m infra.executar_consultas
```

Região `us-east-1`. Todos os recursos são privados: bucket com as quatro flags de Block Public Access, criptografia em repouso com SSE-S3, IAM role restrita ao ARN do bucket do projeto. Nenhum recurso com endpoint público é criado, e o script de provisionamento verifica essa postura ao final.

Custo medido da execução completa: **US$ 0,07** — 537 DPU-segundos de Glue e 0,02 MB escaneados no Athena.

## Entregáveis

| Entregável | Caminho |
|---|---|
| Material executivo | `output/Material_Executivo_State_of_Data_Fase3.pptx` (13 slides) |
| Relatório técnico | `output/Relatorio_Tecnico_State_of_Data_Fase3.docx` e `.pdf` (9 páginas) |
| Fonte editável do relatório | `docs/RELATORIO_TECNICO.md` |
| Diagrama de arquitetura (anotado) | `arquitetura/arquitetura_sod_fase3.drawio` + PNG e PDF |
| Diagrama de arquitetura (ícones AWS) | `arquitetura/arquitetura_aws_icones.drawio` + PNG e PDF |
| Notebook de entrega | `notebooks/pipeline_state_of_data.ipynb` (executado, com saídas) |
| Consultas SQL | `athena/00_perguntas_de_negocio.sql` (16 consultas) |
| Gráficos | `output/img/` (9 figuras) |
| Evidência de execução | `output/evidencias/` (Glue e Athena) e `output/prints/` (console AWS) |

## Arquitetura

```
CSV (Kaggle)
     v
S3 Bronze  ---- CSV bruto, particionado por edicao, cópia fiel da origem
     v          Glue Job 1 (PySpark)
S3 Silver  ---- Parquet, 41 dimensões harmonizadas entre as 3 edições
     v          Glue Job 2 (PySpark)
S3 Gold    ---- Parquet, 8 tabelas analíticas (7 domínios + salário auxiliar)
     |\
     | +-------> Glue Crawler <------- S3 Silver
     |                v
     |         Glue Data Catalog
     |                v (schema e localização)
     +----------> Athena (lê Parquet do S3) ---> S3 athena-results

Notebooks e gráficos leem a Gold local diretamente; não consomem os resultados do Athena.
```

## Estrutura

```
projeto3/
├── src/
│   ├── config.py                 # recursos AWS, caminhos, contagens esperadas
│   ├── dominio.py                # constantes de domínio, sem dependência de Spark
│   ├── mapeamento_colunas.py     # mapeamento semântico curado entre edições
│   ├── validar_mapeamento.py     # gate de validação do mapeamento
│   ├── contexto_execucao.py      # abstração local versus Glue
│   ├── ingestao.py               # leitura dos brutos com validação de integridade
│   ├── conferencia_cruzada.py    # verificação da Silver contra pandas
│   └── transformacoes/
│       ├── sanitizacao.py        # nomes de coluna compatíveis com Athena
│       ├── normalizacao.py       # valores categóricos e colunas derivadas
│       ├── bronze_para_silver.py # harmonização das 3 edições
│       └── silver_para_gold.py   # as 8 tabelas (7 domínios + salário auxiliar)
├── glue_jobs/                    # entrypoints dos Glue Jobs
├── infra/                        # provisionamento e execução na AWS
├── notebooks/                    # notebooks de entrega
├── athena/                       # consultas SQL versionadas
├── arquitetura/                  # diagrama Draw.io
├── output/img/                   # gráficos gerados
└── tests/
```

## O problema central deste projeto

As três edições **não são compatíveis por código de pergunta**. A convenção de nome mudou entre 2023 e 2024, e as letras das perguntas deslocam entre edições porque perguntas foram inseridas e removidas:

```
código 2.q  ->  2023: layoff em 2023
                2024: layoff em 2024
                2025: modelo_de_trabalho_atual     <- outra pergunta

código 4.e  ->  2023: linguagem que mais utiliza
                2024: linguagem_mais_usada
                2025: cloud_(dia_a_dia)            <- outra pergunta
```

Um union automático pelos 306 códigos comuns às três edições produziria dados errados **sem nenhum erro visível**. Por isso `mapeamento_colunas.py` é curado à mão por significado, com 41 dimensões canônicas e 12 marcadas como deslocadas.

Três camadas de defesa garantem a correção:

1. `validar_mapeamento.py` — confirma que toda dimensão resolve e exibe os rótulos dos três anos lado a lado para conferência humana.
2. Validações no pipeline — contagem por edição, 13 faixas salariais, nomes válidos para Athena, consistência de dimensões.
3. `conferencia_cruzada.py` — recalcula as distribuições direto dos CSVs com pandas, por caminho de código independente, e compara com a Silver.

## Cuidados conhecidos nos dados

**Nulos são estruturais, não sujeira.** O questionário é condicional: a seção 3 só é respondida por gestores, senioridade é nula para desempregados e estudantes. O pipeline nunca executa `dropna()`, e toda agregação da Gold reporta `respondentes_validos` e `taxa_resposta` ao lado da métrica.

**Dois erros de digitação na origem**, um respondente cada: `R$ 101` em 2023 (era `R$ 1.001`) e `R$ 3000` em 2025 (era `R$ 30.000`). Corrigidos na Silver, resultando em 13 faixas idênticas nos três anos.

**Sentinelas de nulo em texto.** Os brutos contêm `NA`, `NULL` e `N/A` como strings literais em algumas células. O pandas nulifica por padrão, o Spark não. Sem tratamento, `NA` apareceria como categoria legítima nos gráficos.

**Senioridade ganhou um nível em 2025.** `Especialista/Staff+` existe apenas na última edição. É preservado em vez de agrupado em `Sênior`, e a quebra metodológica é sinalizada — a variação do share de Sênior entre anos não deve ser lida como movimento de mercado.

**Múltipla escolha soma acima de 100%.** Perguntas de tecnologia e IA aceitam várias respostas. As métricas de adoção explicitam isso.
