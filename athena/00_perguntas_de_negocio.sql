-- =====================================================================
-- Tech Challenge Fase 3 — Consultas analíticas no Athena
-- Database: sod_fase3
-- =====================================================================
--
-- Uma consulta por pergunta de negócio do enunciado. Todas leem a camada
-- Gold, que já traz o denominador correto em `respondentes_validos`.
--
-- REGRA QUE ATRAVESSA TODAS AS CONSULTAS
-- --------------------------------------
-- O questionário é condicional. A seção 3, por exemplo, só é respondida por
-- gestores: em 2025-2026 são 652 de 3.495 respondentes. Por isso toda consulta
-- expõe `taxa_resposta`, e nenhuma calcula percentual sobre a base cheia.
-- Ignorar isso erra a adoção de IA por um fator de cinco.
--
-- A coluna `fragil` marca recortes com menos de 30 respondentes válidos, e
-- `aviso_metodologico` carrega quebras de comparabilidade conhecidas.


-- =====================================================================
-- 1. Como está estruturado o mercado brasileiro de Dados?
-- =====================================================================
-- Os dez cargos mais frequentes em cada edição, com a base que sustenta
-- cada percentual.

SELECT
    edicao,
    categoria                AS cargo,
    quantidade,
    percentual,
    respondentes_validos,
    taxa_resposta
FROM perfil_mercado
WHERE metrica = 'cargo'
  AND NOT fragil
ORDER BY edicao DESC, percentual DESC
LIMIT 30;


-- =====================================================================
-- 2. Quais perfis profissionais são mais valorizados pelo mercado?
-- =====================================================================
-- Salário médio e mediano estimados por senioridade, a partir do ponto
-- médio das faixas. A faixa superior é aberta, então o valor é
-- aproximação — serve para comparar recortes, não como salário absoluto.

SELECT
    edicao,
    categoria                AS senioridade,
    salario_medio,
    salario_mediano,
    respondentes_validos
FROM salario_medio
WHERE recorte = 'senioridade'
  AND NOT fragil
ORDER BY edicao DESC, salario_medio DESC;


-- Os cargos com maior salário médio na edição mais recente.
SELECT
    categoria                AS cargo,
    salario_medio,
    respondentes_validos
FROM salario_medio
WHERE recorte = 'cargo'
  AND edicao = 2025
  AND NOT fragil
ORDER BY salario_medio DESC
LIMIT 15;


-- =====================================================================
-- 3. Qual é o cenário de diversidade de gênero nas carreiras de dados?
-- =====================================================================
-- Participação feminina por nível de senioridade. A leitura relevante é a
-- variação entre níveis: se o percentual cai conforme a senioridade sobe,
-- há afunilamento na progressão de carreira.
--
-- Atenção ao aviso: a edição 2025-2026 introduziu 'Especialista/Staff+'.

SELECT
    edicao,
    nivel_senioridade,
    percentual               AS percentual_feminino,
    quantidade               AS mulheres,
    respondentes_validos     AS total_no_nivel,
    aviso_metodologico
FROM diversidade
WHERE metrica = 'genero_por_senioridade'
  AND categoria = 'Feminino'
  AND NOT fragil
ORDER BY edicao DESC, nivel_senioridade;


-- Participação feminina por faixa salarial na edição mais recente,
-- ordenada da menor para a maior faixa.
SELECT
    d.faixa_salarial,
    d.percentual             AS percentual_feminino,
    d.respondentes_validos   AS total_na_faixa
FROM diversidade d
WHERE d.metrica = 'genero_por_faixa_salarial'
  AND d.categoria = 'Feminino'
  AND d.edicao = 2025
  AND NOT d.fragil
ORDER BY d.percentual DESC;


-- =====================================================================
-- 4. Quais tecnologias apresentam maior adoção entre os profissionais?
-- =====================================================================
-- Múltipla escolha: a soma dos percentuais excede 100% porque um
-- respondente pode marcar várias opções.

SELECT
    dimensao                 AS categoria_tecnologia,
    opcao                    AS tecnologia,
    edicao,
    percentual,
    quantidade,
    respondentes_validos
FROM tecnologias
WHERE dimensao IN ('cloud_dia_a_dia', 'banco_dados', 'bi_dia_a_dia')
  AND edicao = 2025
  AND NOT fragil
ORDER BY dimensao, percentual DESC;


-- Evolução da adoção de cloud nas três edições, em formato pivotado.
SELECT
    opcao                    AS cloud,
    MAX(CASE WHEN edicao = 2023 THEN percentual END) AS pct_2023_2024,
    MAX(CASE WHEN edicao = 2024 THEN percentual END) AS pct_2024_2025,
    MAX(CASE WHEN edicao = 2025 THEN percentual END) AS pct_2025_2026,
    MAX(CASE WHEN edicao = 2025 THEN percentual END)
        - MAX(CASE WHEN edicao = 2023 THEN percentual END) AS variacao_pp
FROM tecnologias
WHERE dimensao = 'cloud_dia_a_dia'
GROUP BY opcao
ORDER BY pct_2025_2026 DESC;


-- =====================================================================
-- 5. Qual é o índice de adoção de Inteligência Artificial e seu impacto?
-- =====================================================================
-- Uso de IA generativa no trabalho. Note a `taxa_resposta`: a pergunta é
-- respondida por quem atua tecnicamente, não pela base inteira.

SELECT
    edicao,
    categoria                AS forma_de_uso,
    percentual,
    quantidade,
    respondentes_validos,
    taxa_resposta
FROM adocao_ia
WHERE dimensao = 'usa_chatgpt_copilot'
ORDER BY edicao DESC, percentual DESC;


-- IA como prioridade declarada pela empresa. Só gestores respondem, então
-- a taxa_resposta é baixa por construção — e o número NÃO representa o
-- mercado inteiro.
SELECT
    edicao,
    categoria                AS prioridade_declarada,
    percentual,
    respondentes_validos     AS gestores_que_responderam,
    taxa_resposta            AS pct_da_base_total,
    aviso_metodologico
FROM adocao_ia
WHERE dimensao = 'ia_e_prioridade'
  AND edicao = 2025
ORDER BY percentual DESC;


-- Barreiras à adoção de IA, na visão de quem gerencia times de dados.
SELECT
    edicao,
    categoria                AS motivo_para_nao_adotar,
    percentual,
    quantidade,
    respondentes_validos
FROM adocao_ia
WHERE dimensao = 'motivos_nao_usar_ia'
  AND edicao = 2025
  AND NOT fragil
ORDER BY percentual DESC
LIMIT 10;


-- =====================================================================
-- 6. Existem diferenças relevantes entre regiões, senioridades ou
--    modelos de trabalho?
-- =====================================================================
-- Concentração geográfica da força de trabalho em dados.

SELECT
    edicao,
    categoria                AS regiao,
    percentual,
    quantidade,
    respondentes_validos
FROM recortes_comparativos
WHERE metrica = 'regiao_geral'
ORDER BY edicao DESC, percentual DESC;


-- Salário médio por região: expõe a assimetria que sustenta a
-- recomendação de contratação distribuída.
SELECT
    edicao,
    categoria                AS regiao,
    salario_medio,
    respondentes_validos
FROM salario_medio
WHERE recorte = 'regiao'
  AND NOT fragil
ORDER BY edicao DESC, salario_medio DESC;


-- Modelo de trabalho atual contra o modelo considerado ideal. A distância
-- entre os dois é o indicador de risco de retenção.
SELECT
    metrica                  AS momento,
    categoria                AS modelo_de_trabalho,
    percentual,
    respondentes_validos
FROM recortes_comparativos
WHERE metrica IN ('modelo_trabalho_geral', 'modelo_trabalho_ideal')
  AND edicao = 2025
ORDER BY metrica, percentual DESC;


-- =====================================================================
-- 7. Quais oportunidades e desafios para quem investe em Dados e IA?
-- =====================================================================
-- Maiores desafios declarados por gestores de times de dados.

SELECT
    edicao,
    categoria                AS desafio,
    percentual,
    quantidade,
    respondentes_validos,
    taxa_resposta
FROM oportunidades_desafios
WHERE dimensao = 'desafios_gestor'
  AND edicao = 2025
  AND NOT fragil
ORDER BY percentual DESC
LIMIT 10;


-- Critérios que os profissionais consideram ao escolher onde trabalhar.
-- É a contraparte prática das recomendações de atração e retenção.
SELECT
    categoria                AS criterio,
    percentual,
    quantidade,
    respondentes_validos
FROM oportunidades_desafios
WHERE dimensao = 'criterios_escolha'
  AND edicao = 2025
  AND NOT fragil
ORDER BY percentual DESC
LIMIT 10;


-- Intenção de trocar de emprego nos próximos 6 meses, por edição.
-- Indicador direto de pressão sobre o mercado de contratação.
SELECT
    edicao,
    categoria                AS intencao,
    percentual,
    respondentes_validos
FROM oportunidades_desafios
WHERE dimensao = 'planos_mudar_6m'
ORDER BY edicao DESC, percentual DESC;
