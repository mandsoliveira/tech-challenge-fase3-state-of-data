# Plano de Implementação: Tech Challenge Fase 3 — State of Data Brasil

## Visão Geral

Este plano converte o design em tarefas incrementais. A ordem é deliberada: o pipeline é construído e validado inteiramente **em Spark local** antes de tocar a AWS, porque iterar local leva segundos e iterar no Glue leva minutos. A subida para a AWS acontece com o código já correto.

As tarefas marcadas com `*` são testes automatizados, opcionais para a entrega mas recomendadas nas transformações críticas.

## Divisão sugerida entre o grupo

O plano é organizado em quatro frentes que podem correr em paralelo após a Fase 1:

| Frente | Tarefas | Pré-requisito |
|---|---|---|
| A — Pipeline de dados | 2 a 5 | Fase 1 concluída |
| B — Infraestrutura AWS | 6 a 8 | Fase 1 concluída |
| C — Análise e gráficos | 9 a 10 | Tarefa 5 (Gold local pronta) |
| D — Diagrama e material executivo | 11 a 12 | Tarefa 10 (gráficos prontos) |

## Tarefas

### Fase 1 — Fundação

- [x] 1. Estabelecer o mapeamento semântico e validá-lo
  - [x] 1.1 Implementar `src/mapeamento_colunas.py`
    - Mapeamento curado de 41 dimensões canônicas com o código de cada edição
    - Documentar o problema de deslocamento de código e as justificativas das decisões ambíguas
    - Implementar `extrair_codigo`, `normalizar_codigo`, `construir_indice`, `resolver_colunas`
    - Manter o módulo livre de dependência de Spark
    - _Requisitos: R4.1, R4.2, R4.3, R4.4, R4.5_

  - [x] 1.2 Implementar `src/validar_mapeamento.py`
    - Resolver o mapeamento contra os três CSVs e imprimir os rótulos lado a lado
    - Retornar código de saída diferente de zero se alguma dimensão declarada não resolver
    - Suportar `--valores DIMENSAO` para comparar distribuições
    - _Requisitos: R4.6_

- [ ] 2. Configurar estrutura do projeto e ambiente
  - Criar diretórios: `src/transformacoes/`, `glue_jobs/`, `infra/`, `notebooks/`, `athena/`, `arquitetura/`, `output/img/`, `tests/`, `data/lake/`
  - Criar `src/__init__.py`, `src/transformacoes/__init__.py`, `tests/__init__.py`
  - Criar `requirements.txt` com versões fixas alinhadas ao Glue 5.0: `pyspark==3.5.4`, `pandas==2.2.3`, `matplotlib==3.9.2`, `seaborn==0.13.2`, `boto3`, `pytest`
  - Criar `.gitignore` excluindo `data/raw/`, `data/lake/`, `archive*.zip`, `*.csv`, `.venv-spark/`, `__pycache__/`, `.ipynb_checkpoints/`
  - Criar `src/config.py` com: `ID_CONTA`, `REGIAO = "us-east-1"`, `NOME_BUCKET`, `NOME_DATABASE_GLUE`, `RAIZ_LAKE_LOCAL`, contagens esperadas por edição
  - Criar `README.md` documentando obtenção dos dados, setup do `.venv-spark` com Python 3.10 e `JAVA_HOME`, e execução local e na AWS
  - _Requisitos: R17.1, R17.2, R17.3, R17.4_

### Fase 2 — Pipeline em Spark local (frente A)

- [ ] 3. Implementar o contexto de execução dual
  - [ ] 3.1 Implementar `src/contexto_execucao.py`
    - Classe `ContextoExecucao` com propriedades `spark`, `no_glue` e métodos `caminho`, `registrar`
    - Detectar ambiente Glue pela disponibilidade do módulo `awsglue`
    - No ambiente local: `SparkSession` com `master("local[*]")`, `spark.sql.shuffle.partitions=4`, Spark UI desabilitada
    - No ambiente Glue: usar `GlueContext` e `SparkSession` derivada
    - `caminho(camada, tabela)` resolve para `data/lake/<camada>/<tabela>` local e `s3://<bucket>/<camada>/<tabela>` no Glue
    - Aceitar raiz do lake por parâmetro, com default por ambiente
    - _Requisitos: R10.1, R10.2, R10.3, R10.5_

  - [ ] 3.2 Implementar leitura padronizada dos CSVs brutos
    - Função que aplica as opções verificadas: `header`, `multiLine`, `quote='"'`, `escape='"'`
    - Validar contagem de linhas contra o esperado por edição (5.293 / 5.217 / 3.495) e falhar em caso de divergência
    - Falhar com mensagem descritiva se o arquivo não existir
    - _Requisitos: R1.3, R1.4, R1.5_

- [ ] 4. Implementar a transformação Bronze→Silver
  - [ ] 4.1 Implementar sanitização de nomes de coluna em `src/transformacoes/sanitizacao.py`
    - Remover acentuação via decomposição Unicode (NFKD)
    - Converter para minúsculas, substituir caracteres fora de `[a-z0-9]` por `_`, colapsar `_` repetidos, remover `_` das extremidades
    - Preservar o código da pergunta no início do nome resultante
    - Resolver colisões com sufixo numérico incremental e registrar cada colisão
    - Validar que 100% dos nomes resultantes atendem a `[a-z0-9_]+` e falhar caso contrário
    - _Requisitos: R3.1, R3.2, R3.3, R3.4, R3.5_

  - [ ]* 4.2 Escrever teste da sanitização
    - **Propriedade: sanitização produz apenas caracteres válidos**
    - Verificar contra os nomes reais das três edições que a saída sempre casa com `[a-z0-9_]+`
    - Verificar que nomes colidentes recebem sufixos distintos
    - Verificar que `1.c_cor/raca/etnia` resulta em nome contendo `1_c` e `cor_raca_etnia`
    - Arquivo: `tests/test_sanitizacao.py`
    - **Valida: R3.1, R3.2, R3.3, R3.4**

  - [ ] 4.3 Implementar normalização de valores categóricos em `src/transformacoes/normalizacao.py`
    - Corrigir `de R$ 101/mês a R$ 2.000/mês` para `de R$ 1.001/mês a R$ 2.000/mês` (edição 2023)
    - Corrigir `de R$ 25.001/mês a R$ 3000/mês` para `de R$ 25.001/mês a R$ 30.000/mês` (edição 2025)
    - Validar que restam exatamente 13 faixas salariais distintas e falhar caso contrário
    - Derivar `faixa_salarial_ordem` com a posição ordinal de cada faixa
    - Derivar `salario_medio_estimado` com o ponto médio de cada faixa
    - Preservar `Especialista/Staff+` sem reclassificar em `Sênior`
    - Validar consistência de `regiao_onde_mora`, `genero` e `modelo_trabalho_atual` entre edições
    - _Requisitos: R6.1, R6.2, R6.3, R6.4, R6.5, R6.6, R6.8_

  - [ ]* 4.4 Escrever teste da normalização
    - **Propriedade: correção de typos produz exatamente 13 faixas**
    - Verificar que as 13 faixas são idênticas nas três edições após correção
    - **Propriedade: ordem é monotônica em relação ao ponto médio**
    - Verificar que `faixa_salarial_ordem` cresce junto com `salario_medio_estimado`
    - Arquivo: `tests/test_normalizacao.py`
    - **Valida: R6.3, R6.4, R6.5**

  - [ ] 4.5 Implementar `src/transformacoes/bronze_para_silver.py`
    - Aplicar o mapeamento semântico para selecionar e renomear as 41 dimensões canônicas
    - Materializar dimensões ausentes como `lit(None)` com tipo explícito, garantindo schema idêntico entre edições
    - Aplicar a normalização de valores categóricos
    - Adicionar colunas `edicao` e `ingerido_em`
    - Unir as três edições com `unionByName`
    - **Não executar `dropna()` em nenhum ponto**
    - _Requisitos: R4.1, R4.4, R4.7, R5.1_

  - [ ]* 4.6 Escrever teste de preservação de registros
    - **Propriedade: nenhum registro é perdido na Bronze→Silver**
    - Verificar que a contagem da Silver é exatamente 14.005 (5.293 + 5.217 + 3.495)
    - Verificar a contagem por edição individualmente
    - Verificar que registros com nulos estruturais permanecem presentes
    - Arquivo: `tests/test_bronze_para_silver.py`
    - **Valida: R5.1, R1.5**

- [ ] 5. Implementar a transformação Silver→Gold
  - [ ] 5.1 Implementar utilitários de agregação em `src/agregacoes.py`
    - `contar_com_denominador_valido`: contagem excluindo nulos estruturais do denominador
    - `calcular_share`: proporção sobre o denominador válido
    - `explodir_multi_escolha`: separação de perguntas de múltipla escolha
    - `calcular_variacao_entre_edicoes`: variação entre a primeira e a última edição
    - `marcar_fragil`: sinaliza recortes com menos de 30 respondentes válidos
    - Todas as funções devem emitir `respondentes_validos` e `taxa_resposta` junto da métrica
    - _Requisitos: R5.2, R5.3, R5.4, R5.5, R7.2, R7.3, R8.9_

  - [ ]* 5.2 Escrever teste do contrato de agregação
    - **Propriedade: nulos estruturais são excluídos do denominador**
    - Construir DataFrame com nulos conhecidos e verificar que o denominador ignora apenas os nulos
    - **Propriedade: percentuais de escolha única somam 100%**
    - Verificar dentro da tolerância de arredondamento
    - **Propriedade: recorte com menos de 30 respondentes é marcado como frágil**
    - Arquivo: `tests/test_agregacoes.py`
    - **Valida: R5.2, R5.5**

  - [ ] 5.3 Implementar as sete agregações em `src/transformacoes/silver_para_gold.py`
    - `perfil_mercado`: distribuição de cargo, senioridade, setor, porte e tempo de experiência por edição
    - `remuneracao`: faixa salarial cruzada com senioridade, região, modelo de trabalho e gênero
    - `diversidade`: gênero, cor/raça/etnia e PCD segmentados por senioridade e faixa salarial
    - `tecnologias`: adoção de linguagem, banco de dados, cloud e ferramenta de BI por edição
    - `adocao_ia`: prioridade declarada, tipo de uso, uso de ChatGPT/Copilot e motivos para não adotar
    - `recortes_comparativos`: comparação por região, senioridade e modelo de trabalho
    - `oportunidades_desafios`: desafios de gestor, motivos de insatisfação e critérios de escolha
    - Todas seguindo o contrato uniforme com `respondentes_validos`, `taxa_resposta` e `fragil`
    - Sinalizar em `perfil_mercado` e `recortes_comparativos` a introdução de `Especialista/Staff+` em 2025
    - Explicitar em `tecnologias` e `adocao_ia` que a soma pode exceder 100% por múltipla escolha
    - _Requisitos: R8.1 a R8.9, R6.7, R7.4_

  - [ ] 5.4 Implementar os entrypoints dos Glue Jobs
    - `glue_jobs/job_bronze_para_silver.py`: lê `--raiz_lake` e `--edicoes`, chama a transformação, escreve Parquet particionado por `edicao`
    - `glue_jobs/job_silver_para_gold.py`: lê a Silver, gera as sete tabelas Gold, escreve Parquet
    - Ambos registram contagem de entrada e saída, versão do Spark e do Glue
    - Ambos funcionam sem alteração local e no Glue
    - _Requisitos: R9.1, R9.3, R10.4, R16.1_

  - [ ] 5.5 Executar o pipeline completo localmente e validar por conferência cruzada
    - Rodar Bronze→Silver e Silver→Gold sobre `data/lake/` local
    - Conferir que a Silver tem 14.005 registros e o schema esperado
    - Conferir números selecionados da Gold contra o que o pandas produz direto do CSV bruto
    - Documentar qualquer divergência encontrada e resolvê-la antes de subir para a AWS
    - _Requisitos: R1.5, R5.1_

### Fase 3 — Infraestrutura AWS (frente B)

- [ ] 6. Provisionar os recursos AWS de forma idempotente
  - [ ] 6.1 Implementar `infra/provisionar.py`
    - Criar bucket `sod-fase3-datalake-242201276836` em `us-east-1`
    - Habilitar as quatro flags de Block Public Access no bucket
    - Habilitar criptografia em repouso (SSE-S3)
    - Criar Glue Database dedicado ao projeto
    - Criar IAM role para os Glue Jobs, com política escopada ao ARN do bucket do projeto, sem `s3:*` sobre `*`
    - Tornar todas as operações idempotentes, para permitir reexecução
    - _Requisitos: R2.1, R2.2, R2.4, R2.5, R11.1_

  - [ ] 6.2 Implementar verificação de segurança pós-provisionamento
    - Verificar e reportar o estado das quatro flags de Block Public Access de cada bucket criado
    - Verificar que nenhuma política de bucket concede acesso a `Principal: "*"`, `AllUsers` ou `AuthenticatedUsers`
    - Verificar que nenhum recurso com endpoint público foi criado
    - Falhar caso qualquer verificação não passe
    - _Requisitos: R2.3, R2.4, R2.6_

- [ ] 7. Ingerir os dados na camada Bronze
  - Fazer upload dos três CSVs para `bronze/state_of_data/edicao=<ano>/`, sem transformação
  - Registrar linhas e colunas de cada arquivo ingerido
  - Validar as contagens contra os valores esperados por edição
  - _Requisitos: R1.1, R1.2, R1.3, R1.5_

- [ ] 8. Criar e executar os Glue Jobs, e catalogar as tabelas
  - [ ] 8.1 Criar os dois Glue Jobs
    - Glue version 5.0, worker `G.1X`, 2 workers
    - Fazer upload dos scripts e das dependências de `src/` para o S3
    - Associar a IAM role criada na tarefa 6.1
    - _Requisitos: R9.2_

  - [ ] 8.2 Executar os jobs e coletar a evidência de execução
    - Executar Bronze→Silver e depois Silver→Gold
    - Coletar identificador de execução, horário de início e fim, registros lidos e escritos
    - Coletar a listagem dos objetos gerados em cada camada
    - _Requisitos: R16.1, R16.2_

  - [ ] 8.3 Catalogar as camadas Silver e Gold
    - Criar e executar Glue Crawler sobre os prefixos `silver/` e `gold/`
    - Verificar que `edicao` foi registrada como coluna de partição
    - Verificar que cada tabela catalogada é consultável no Athena
    - _Requisitos: R11.2, R11.3, R11.4_

### Fase 4 — Análise e visualização (frente C)

- [ ] 9. Escrever as consultas analíticas no Athena
  - Criar em `athena/` uma consulta SQL versionada por pergunta de negócio
  - Configurar o local de resultados para `s3://<bucket>/athena-results/`
  - Garantir que toda consulta que calcula percentual exclui nulos estruturais do denominador
  - Executar cada consulta e registrar o resultado de ao menos uma delas como evidência
  - _Requisitos: R12.1, R12.2, R12.3, R12.4, R16.3_

- [ ] 10. Gerar os gráficos a partir da camada Gold
  - Implementar `src/gerador_graficos.py` lendo exclusivamente as tabelas Gold, nunca os CSVs brutos
  - Gerar no mínimo um gráfico por pergunta de negócio
  - Ordenar faixas salariais por `faixa_salarial_ordem`
  - Rotular edições como `2023-2024`, `2024-2025` e `2025-2026`
  - Incluir o denominador ou quantidade de respondentes no rótulo ou legenda
  - Exportar as imagens em `output/img/`
  - _Requisitos: R13.1 a R13.6_

- [ ] 11. Montar os notebooks de entrega
  - `notebooks/01_ingestao_bronze.ipynb`: ingestão e validação das contagens
  - `notebooks/02_bronze_para_silver.ipynb`: sanitização, harmonização e normalização
  - `notebooks/03_silver_para_gold.ipynb`: as sete agregações
  - `notebooks/04_analise_athena.ipynb`: consultas SQL e resultados
  - `notebooks/05_graficos.ipynb`: geração dos gráficos
  - Todos importando os módulos de `src/`, sem duplicar lógica
  - _Requisitos: R17.5_

### Fase 5 — Entregáveis (frente D)

- [ ] 12. Construir o diagrama da arquitetura
  - Desenhar no Draw.io o fluxo da ingestão ao consumo analítico
  - Representar as três camadas do Data Lake, os Glue Jobs, o Glue Data Catalog e o Athena
  - Versionar o arquivo `.drawio` em `arquitetura/`
  - Exportar como imagem para inclusão no material executivo
  - _Requisitos: R14.1 a R14.5_

- [ ] 13. Consolidar a evidência de execução
  - Reunir identificadores de execução dos jobs, contagens, listagem de objetos do S3 e resultado de consulta Athena
  - Versionar o artefato consolidado no repositório
  - _Requisitos: R16.4_

- [ ] 14. Produzir o material executivo
  - Montar apresentação em PDF ou PowerPoint com indicadores, análises, insights e recomendações
  - Construir narrativa sobre perfil profissional, tendências, tecnologias, remuneração, senioridade e modelos de trabalho
  - Propor recomendações estratégicas de contratação, capacitação e investimento em Dados, Analytics e IA
  - Incluir o diagrama da arquitetura
  - Sustentar cada afirmação com número extraído da Gold
  - Sinalizar as mudanças metodológicas conhecidas: introdução de `Especialista/Staff+` em 2025 e múltipla escolha somando acima de 100%
  - _Requisitos: R15.1 a R15.7_

## Pontos de atenção durante a execução

**A tarefa 5.5 é o gate crítico.** Não subir nada para a AWS antes da conferência cruzada local passar. Corrigir lógica no Glue custa minutos por iteração; local custa segundos.

**A validação do mapeamento (tarefa 1.2) deve rodar sempre que alguém alterar `mapeamento_colunas.py`.** É a única defesa contra o erro de harmonização, que não se manifesta como falha, e sim como número errado no material executivo.

**Sempre usar `.venv-spark`.** O venv principal do workspace tem Python 3.14, incompatível com PySpark 3.5.x. E exportar `JAVA_HOME=/opt/homebrew/opt/openjdk@17` antes de rodar Spark local.

**Confirmar duas coisas com o docente na próxima live.** Se o dataset 2025-2026 conta entre "as 3 últimas pesquisas disponíveis", dado que foi publicado três dias após a redação do enunciado. E se é aceitável executar em conta AWS própria em vez do AWS Academy Lab.
