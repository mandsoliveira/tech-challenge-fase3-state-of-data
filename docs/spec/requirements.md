# Documento de Requisitos

## Introdução

Este documento especifica os requisitos do **Tech Challenge Fase 3** (POSTECH DTAT). O projeto constrói uma solução de Engenharia de Dados e Analytics em ambiente AWS sobre a pesquisa **State of Data Brasil** (Data Hackers + Bain), atendendo a uma instituição financeira de grande porte que precisa compreender o mercado brasileiro de dados para definir estratégias de contratação, capacitação e investimento em Dados, Analytics e Inteligência Artificial.

O escopo cobre o ciclo de vida completo dos dados: ingestão no S3, transformação com Spark via Glue Jobs, organização em camadas Bronze/Silver/Gold, catalogação no Glue Data Catalog, consultas analíticas no Athena e geração de gráficos para o material executivo.

### Edições utilizadas

As três pesquisas mais recentes disponíveis no Data Hackers, totalizando **14.005 respondentes**:

| Edição | Arquivo bruto | Respondentes | Colunas |
|---|---|---|---|
| 2023-2024 | `state_of_data_2023.csv` | 5.293 | 399 |
| 2024-2025 | `state_of_data_2024.csv` | 5.217 | 403 |
| 2025-2026 | `state_of_data_2025.csv` | 3.495 | 388 |

### Perguntas de negócio a responder

1. Como está estruturado o mercado brasileiro de Dados?
2. Quais perfis profissionais são mais valorizados pelo mercado?
3. Qual é o cenário de diversidade de gênero nas carreiras de dados?
4. Quais tecnologias apresentam maior adoção entre os profissionais?
5. Qual é o índice de adoção de Inteligência Artificial e seu impacto?
6. Existem diferenças relevantes entre regiões, senioridades ou modelos de trabalho?
7. Quais oportunidades e desafios podem ser identificados para empresas que desejam investir em Dados e IA?

### Restrições assumidas

- **Região AWS:** `us-east-1`.
- **Conta AWS:** conta individual de desenvolvimento do aluno. Nenhum recurso pode ser exposto publicamente.
- **Ambiente de execução:** os scripts devem rodar tanto localmente (iteração rápida) quanto em Glue Jobs (evidência de execução na AWS), sem alteração da lógica de transformação.

## Glossário

- **Edicao**: Uma das três pesquisas anuais utilizadas, identificada pelo ano de início (2023, 2024, 2025).
- **Camada_Bronze**: Zona do Data Lake que armazena os CSVs brutos exatamente como baixados do Kaggle, sem transformação, particionados por Edicao.
- **Camada_Silver**: Zona do Data Lake que armazena os dados limpos, com nomes de coluna sanitizados, dimensões harmonizadas entre edições e valores categóricos normalizados, em formato Parquet.
- **Camada_Gold**: Zona do Data Lake que armazena tabelas agregadas, uma por pergunta de negócio, prontas para consumo analítico e geração de gráficos.
- **Dimensao_Canonica**: Nome único e estável atribuído a uma pergunta da pesquisa, válido nas três edições (ex.: `faixa_salarial`, `cloud_preferida`).
- **Mapeamento_Semantico**: Estrutura curada manualmente que associa cada Dimensao_Canonica ao código da pergunta correspondente em cada Edicao.
- **Deslocamento_De_Codigo**: Fenômeno em que o código de uma pergunta muda entre edições porque perguntas foram inseridas ou removidas, fazendo com que o mesmo código represente perguntas diferentes em anos diferentes.
- **Nulo_Estrutural**: Valor nulo decorrente do fluxo condicional do questionário, não de falha de qualidade. Exemplo: a seção 3 só é respondida por gestores.
- **Coluna_Sanitizada**: Nome de coluna contendo apenas caracteres `[a-z0-9_]`, compatível com Glue Data Catalog e Athena.
- **Executor**: Componente que abstrai o ambiente de execução, permitindo que o mesmo script rode em Spark local ou em Glue Job.
- **Evidencia_De_Execucao**: Artefato que comprova que o pipeline rodou na AWS (identificador de execução do job, contagem de registros processados, listagem de objetos gerados no S3, resultado de consulta no Athena).

## Requisitos

### Requisito 1: Ingestão dos Dados Brutos na Camada Bronze

**User Story:** Como engenheiro de dados, eu quero ingerir os CSVs das três edições no S3 sem transformação, para que exista uma cópia fiel e auditável da origem.

#### Critérios de Aceitação

1. THE Camada_Bronze SHALL armazenar os três arquivos CSV brutos no S3 sem qualquer alteração de conteúdo, nomes de coluna ou tipos de dado.
2. THE Camada_Bronze SHALL particionar os objetos por Edicao, usando o padrão de prefixo `bronze/state_of_data/edicao=<ano>/`.
3. WHEN a ingestão é concluída, THE pipeline SHALL registrar, para cada Edicao, a quantidade de linhas e colunas do arquivo ingerido.
4. IF um arquivo CSV bruto não for encontrado no diretório de origem, THEN THE pipeline SHALL falhar com mensagem indicando o nome do arquivo ausente e o caminho esperado.
5. THE pipeline SHALL validar que a contagem de linhas ingeridas corresponde a 5.293 para a edição 2023, 5.217 para 2024 e 3.495 para 2025.

### Requisito 2: Segurança e Isolamento dos Recursos

**User Story:** Como titular da conta AWS, eu quero garantir que nenhum recurso do projeto seja acessível publicamente, para que não haja exposição de dados ou de infraestrutura.

#### Critérios de Aceitação

1. THE pipeline SHALL criar todos os buckets S3 com as quatro configurações de Block Public Access habilitadas (`BlockPublicAcls`, `IgnorePublicAcls`, `BlockPublicPolicy`, `RestrictPublicBuckets`).
2. THE pipeline SHALL habilitar criptografia em repouso em todos os buckets S3 criados.
3. THE pipeline SHALL NOT criar nenhum recurso que exponha endpoint público, incluindo hospedagem de site estático em S3, distribuição CloudFront, API Gateway ou Load Balancer.
4. THE pipeline SHALL NOT anexar política de bucket ou ACL que conceda acesso a `Principal: "*"` ou a `AllUsers`/`AuthenticatedUsers`.
5. THE IAM role usada pelos Glue Jobs SHALL conceder acesso apenas aos buckets do projeto, sem permissões amplas de leitura ou escrita sobre todo o S3 da conta.
6. WHEN o provisionamento é concluído, THE pipeline SHALL verificar e reportar o estado de Block Public Access de cada bucket criado.

### Requisito 3: Sanitização dos Nomes de Coluna

**User Story:** Como engenheiro de dados, eu quero converter os nomes de coluna para um formato compatível com o catálogo, para que as tabelas possam ser consultadas no Athena.

#### Critérios de Aceitação

1. THE transformação Bronze→Silver SHALL converter cada nome de coluna para uma Coluna_Sanitizada, contendo apenas caracteres `[a-z0-9_]`.
2. THE transformação SHALL remover acentuação, converter para minúsculas e substituir por `_` os caracteres `.`, `/`, `,`, `?`, `(`, `)`, espaço e hífen.
3. THE transformação SHALL preservar o código original da pergunta no nome sanitizado, de modo que a origem permaneça rastreável (ex.: `1.c_cor/raca/etnia` torna-se `1_c_cor_raca_etnia`).
4. IF a sanitização produzir nomes duplicados, THEN THE transformação SHALL acrescentar um sufixo numérico incremental para garantir unicidade e registrar cada colisão resolvida.
5. WHEN a sanitização é concluída, THE transformação SHALL validar que 100% dos nomes resultantes atendem ao padrão `[a-z0-9_]+`.

### Requisito 4: Harmonização Semântica entre Edições

**User Story:** Como analista de dados, eu quero que a mesma pergunta seja identificada pelo mesmo nome nas três edições, para que eu possa comparar os anos sem risco de unir perguntas diferentes.

#### Critérios de Aceitação

1. THE Camada_Silver SHALL usar o Mapeamento_Semantico curado manualmente para resolver cada Dimensao_Canonica ao nome real de coluna de cada Edicao.
2. THE Camada_Silver SHALL NOT unir colunas de edições diferentes com base apenas na igualdade do código da pergunta, dado que o Deslocamento_De_Codigo torna esse critério incorreto.
3. THE Mapeamento_Semantico SHALL identificar explicitamente as dimensões afetadas por Deslocamento_De_Codigo, incluindo no mínimo: `layoff` (2023: `P2_q`, 2024: `2.q`, 2025: `2.p`), `modelo_trabalho_atual` (2023: `P2_r`, 2024: `2.r`, 2025: `2.q`), `linguagem_preferida` (2023: `P4_f`, 2024: `4.f`, 2025: `4.c`), `cloud_preferida` (2023: `P4_i`, 2024: `4.i`, 2025: `4.f`), `usa_chatgpt_copilot` (2023: `P4_m`, 2024: `4.m`, 2025: `4.j`) e `motivos_nao_usar_ia` (2023: `P3_g`, 2024: `3.g`, 2025: `3.h`).
4. IF uma Dimensao_Canonica não existir em determinada Edicao, THEN THE Camada_Silver SHALL materializar a coluna com valor nulo para os registros daquela edição, preservando a união entre os três anos.
5. THE Mapeamento_Semantico SHALL mapear a dimensão `cloud_dia_a_dia` da edição 2023 para o código `P4_h`, apesar de seu enunciado declarar "Cloud preferida", dado que a distribuição de valores contém "Servidores On Premise/Não utilizamos Cloud" e "Cloud Própria", comprovando tratar-se da cloud utilizada.
6. WHEN o Mapeamento_Semantico é aplicado, THE pipeline SHALL validar que toda Dimensao_Canonica declarada como presente resolve para uma coluna existente na Edicao correspondente, e falhar caso alguma não resolva.
7. THE Camada_Silver SHALL incluir uma coluna `edicao` identificando a origem de cada registro.

### Requisito 5: Preservação dos Nulos Estruturais

**User Story:** Como analista de dados, eu quero que os nulos decorrentes do fluxo condicional do questionário sejam preservados, para que as taxas calculadas não sejam distorcidas.

#### Critérios de Aceitação

1. THE Camada_Silver SHALL NOT remover registros em função da presença de valores nulos em qualquer Dimensao_Canonica.
2. THE Camada_Gold SHALL calcular percentuais e taxas usando como denominador a quantidade de respondentes que efetivamente responderam à pergunta, excluindo Nulo_Estrutural do denominador.
3. THE Camada_Gold SHALL registrar, para cada agregação, a quantidade de respondentes válidos (denominador) ao lado do resultado.
4. WHEN uma agregação é gerada, THE Camada_Gold SHALL reportar a taxa de resposta da pergunta, calculada como respondentes válidos dividido pelo total de respondentes da Edicao.
5. IF a quantidade de respondentes válidos de um recorte for inferior a 30, THEN THE Camada_Gold SHALL sinalizar o recorte como estatisticamente frágil.

### Requisito 6: Normalização dos Valores Categóricos

**User Story:** Como analista de dados, eu quero que os valores das categorias sejam consistentes entre edições, para que a comparação temporal seja válida.

#### Critérios de Aceitação

1. THE Camada_Silver SHALL corrigir o valor `de R$ 101/mês a R$ 2.000/mês` da edição 2023 para `de R$ 1.001/mês a R$ 2.000/mês`, tratando-se de erro de digitação na origem que afeta 1 respondente.
2. THE Camada_Silver SHALL corrigir o valor `de R$ 25.001/mês a R$ 3000/mês` da edição 2025 para `de R$ 25.001/mês a R$ 30.000/mês`, tratando-se de erro de digitação na origem que afeta 1 respondente.
3. WHEN as correções de faixa salarial são aplicadas, THE Camada_Silver SHALL resultar em exatamente 13 faixas salariais distintas, idênticas nas três edições.
4. THE Camada_Silver SHALL derivar uma coluna `faixa_salarial_ordem` com a posição ordinal de cada faixa, para que gráficos e consultas ordenem as faixas por valor e não alfabeticamente.
5. THE Camada_Silver SHALL derivar uma coluna `salario_medio_estimado` com o ponto médio de cada faixa, para permitir cálculo de médias e medianas aproximadas.
6. THE Camada_Silver SHALL preservar o nível `Especialista/Staff+`, presente apenas na edição 2025, sem reclassificá-lo em `Sênior`.
7. WHEN a senioridade é comparada entre edições, THE Camada_Gold SHALL sinalizar que a edição 2025 introduziu o nível `Especialista/Staff+`, de modo que a variação do share de `Sênior` não seja interpretada como mudança de mercado.
8. THE Camada_Silver SHALL validar que os valores de `regiao_onde_mora`, `genero` e `modelo_trabalho_atual` são consistentes nas três edições, sem necessidade de normalização.

### Requisito 7: Tratamento das Perguntas Multi-Escolha

**User Story:** Como analista de dados, eu quero contabilizar corretamente perguntas de múltipla escolha, para que a adoção de tecnologias não seja subestimada.

#### Critérios de Aceitação

1. WHERE uma pergunta multi-escolha possui colunas booleanas explodidas na origem, THE Camada_Silver SHALL utilizar essas colunas em vez de interpretar a string concatenada.
2. WHERE uma pergunta multi-escolha possui apenas a string concatenada, THE Camada_Silver SHALL separá-la em múltiplas linhas ou em vetor de valores, preservando todas as opções selecionadas.
3. THE Camada_Gold SHALL calcular a adoção de cada opção de resposta multi-escolha como a proporção de respondentes que a selecionaram, permitindo que a soma dos percentuais exceda 100%.
4. WHEN uma métrica de adoção multi-escolha é apresentada, THE Camada_Gold SHALL explicitar que a soma pode exceder 100% por se tratar de múltipla escolha.

### Requisito 8: Camada Gold Orientada às Perguntas de Negócio

**User Story:** Como consultor, eu quero tabelas agregadas alinhadas a cada pergunta de negócio, para que a análise e os gráficos sejam construídos diretamente sobre elas.

#### Critérios de Aceitação

1. THE Camada_Gold SHALL produzir uma tabela agregada para cada uma das sete perguntas de negócio definidas na introdução.
2. THE Camada_Gold SHALL produzir agregação de perfil de mercado por Edicao, contendo distribuição de cargo, senioridade, setor, porte de empresa e tempo de experiência.
3. THE Camada_Gold SHALL produzir agregação de remuneração cruzando faixa salarial com senioridade, região, modelo de trabalho e gênero.
4. THE Camada_Gold SHALL produzir agregação de diversidade contendo distribuição de gênero, cor/raça/etnia e PCD, segmentada por senioridade e faixa salarial.
5. THE Camada_Gold SHALL produzir agregação de adoção de tecnologias contendo linguagem, banco de dados, cloud e ferramenta de BI, por Edicao.
6. THE Camada_Gold SHALL produzir agregação de adoção de IA contendo prioridade declarada, tipo de uso na empresa, uso de ChatGPT/Copilot e motivos para não adotar, por Edicao.
7. THE Camada_Gold SHALL produzir agregação comparativa por região, senioridade e modelo de trabalho.
8. THE Camada_Gold SHALL persistir todas as tabelas em formato Parquet.
9. WHERE uma métrica existe nas três edições, THE Camada_Gold SHALL calcular a variação entre a primeira e a última edição, para sustentar a leitura de tendência.

### Requisito 9: Processamento com Spark

**User Story:** Como engenheiro de dados, eu quero que as transformações usem Spark, para que a solução atenda ao requisito de processamento distribuído do desafio.

#### Critérios de Aceitação

1. THE transformações Bronze→Silver e Silver→Gold SHALL ser implementadas com PySpark, utilizando DataFrames do Spark.
2. THE pipeline SHALL executar as transformações através de Glue Jobs na AWS.
3. THE pipeline SHALL registrar a versão do Spark e do Glue utilizada em cada execução.

### Requisito 10: Execução Dual Local e Glue

**User Story:** Como desenvolvedor, eu quero rodar o mesmo script localmente e no Glue, para que eu possa iterar rapidamente sem depender de execução na nuvem.

#### Critérios de Aceitação

1. THE Executor SHALL detectar automaticamente se está rodando em ambiente Glue ou local.
2. WHERE o ambiente é local, THE Executor SHALL usar uma SparkSession local e ler e escrever no sistema de arquivos local.
3. WHERE o ambiente é Glue, THE Executor SHALL usar o GlueContext e ler e escrever no S3.
4. THE lógica de transformação SHALL ser idêntica nos dois ambientes, sem ramificação condicional dentro das funções de transformação.
5. THE pipeline SHALL permitir configurar os caminhos de origem e destino por parâmetro, sem alteração de código.

### Requisito 11: Catalogação no Glue Data Catalog

**User Story:** Como analista, eu quero que as tabelas estejam catalogadas, para que eu possa consultá-las no Athena sem declarar schema manualmente.

#### Critérios de Aceitação

1. THE pipeline SHALL criar um Glue Database dedicado ao projeto.
2. THE pipeline SHALL catalogar as tabelas das camadas Silver e Gold no Glue Data Catalog.
3. THE pipeline SHALL registrar a partição `edicao` como coluna de partição das tabelas que a possuem.
4. WHEN a catalogação é concluída, THE pipeline SHALL validar que cada tabela catalogada é consultável no Athena.

### Requisito 12: Consultas Analíticas no Athena

**User Story:** Como consultor, eu quero consultar as camadas via SQL, para que eu possa explorar os dados e extrair os números do material executivo.

#### Critérios de Aceitação

1. THE projeto SHALL entregar consultas SQL versionadas que respondam a cada uma das sete perguntas de negócio.
2. THE consultas SHALL ser executáveis no Athena sobre as tabelas catalogadas.
3. THE resultados das consultas Athena SHALL ser gravados em bucket privado do projeto.
4. WHERE uma consulta calcula percentual, THE consulta SHALL excluir Nulo_Estrutural do denominador, conforme o Requisito 5.

### Requisito 13: Geração de Gráficos

**User Story:** Como consultor, eu quero gráficos gerados a partir da Camada_Gold, para que o material executivo apresente evidências visuais.

#### Critérios de Aceitação

1. THE projeto SHALL gerar gráficos a partir das tabelas da Camada_Gold, sem processar os CSVs brutos.
2. THE projeto SHALL gerar no mínimo um gráfico por pergunta de negócio.
3. THE gráficos SHALL ser exportados como arquivos de imagem em `output/img/`.
4. WHERE um gráfico apresenta faixa salarial, THE gráfico SHALL ordenar as faixas pela coluna `faixa_salarial_ordem`.
5. WHERE um gráfico compara edições, THE gráfico SHALL rotular as edições como `2023-2024`, `2024-2025` e `2025-2026`.
6. THE gráficos SHALL incluir o denominador ou a quantidade de respondentes na legenda ou no rótulo, para que a leitura considere a base.

### Requisito 14: Diagrama da Arquitetura

**User Story:** Como avaliador, eu quero um diagrama da arquitetura AWS, para que eu compreenda os serviços utilizados e o fluxo dos dados.

#### Critérios de Aceitação

1. THE projeto SHALL entregar um diagrama da arquitetura da solução construído no Draw.io.
2. THE diagrama SHALL evidenciar os serviços AWS utilizados e o fluxo dos dados desde a ingestão até o consumo analítico.
3. THE diagrama SHALL representar as três camadas do Data Lake, os Glue Jobs, o Glue Data Catalog e o Athena.
4. THE diagrama SHALL ser exportado como imagem e incluído no material executivo.
5. THE arquivo fonte `.drawio` SHALL ser versionado no repositório.

### Requisito 15: Material Executivo

**User Story:** Como cliente, eu quero um material executivo com narrativa e recomendações, para que eu possa tomar decisões de contratação, capacitação e investimento.

#### Critérios de Aceitação

1. THE projeto SHALL entregar um material executivo em PDF ou PowerPoint.
2. THE material SHALL apresentar os principais indicadores, análises e insights obtidos das três edições.
3. THE material SHALL construir narrativa sobre perfil dos profissionais, tendências de mercado, uso de tecnologias, remuneração, senioridade e modelos de trabalho.
4. THE material SHALL propor recomendações estratégicas para contratação, capacitação e investimento em Dados, Analytics e IA.
5. THE material SHALL conter o diagrama da arquitetura da solução.
6. WHERE uma afirmação é apresentada, THE material SHALL sustentá-la com número extraído da Camada_Gold.
7. WHERE uma comparação entre edições é apresentada, THE material SHALL sinalizar mudanças metodológicas conhecidas que afetem a leitura, conforme os Requisitos 6.7 e 7.4.

### Requisito 16: Evidência de Execução na AWS

**User Story:** Como aluno, eu quero comprovar que o pipeline executou na AWS, para que a entrega demonstre o uso efetivo dos serviços exigidos.

#### Critérios de Aceitação

1. THE pipeline SHALL registrar, para cada execução de Glue Job, o identificador da execução, o horário de início e fim e a quantidade de registros lidos e escritos.
2. THE projeto SHALL coletar a listagem dos objetos gerados em cada camada do S3.
3. THE projeto SHALL coletar o resultado de ao menos uma consulta Athena executada sobre a Camada_Gold.
4. THE Evidencia_De_Execucao SHALL ser consolidada em artefato versionado no repositório.

### Requisito 17: Organização e Reprodutibilidade

**User Story:** Como membro do grupo, eu quero um repositório organizado e reprodutível, para que qualquer integrante consiga executar o pipeline.

#### Critérios de Aceitação

1. THE projeto SHALL organizar os artefatos em diretórios distintos para notebooks, scripts de Glue Job, código reutilizável, consultas SQL, diagrama e saídas.
2. THE projeto SHALL declarar as dependências Python com versões fixas.
3. THE projeto SHALL excluir do controle de versão os CSVs brutos e os arquivos ZIP baixados do Kaggle.
4. THE projeto SHALL documentar no README os passos para obter os dados, configurar o ambiente e executar o pipeline local e na AWS.
5. THE projeto SHALL entregar os códigos preferencialmente em formato de notebook, com uso de Spark/PySpark e SQL, demonstrando ingestão, tratamento, transformação, catalogação, consultas analíticas e geração dos dados usados nos gráficos.
