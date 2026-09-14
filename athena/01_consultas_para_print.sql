-- =====================================================================
-- Três consultas selecionadas para evidência em print do console Athena
-- Database: sod_fase3
-- =====================================================================
--
-- O console do Athena executa UMA instrução por vez. Rode cada bloco
-- separadamente (cole, Executar, print, limpe, cole a próxima).
--
-- As 16 consultas completas estão em 00_perguntas_de_negocio.sql e seus
-- resultados em output/evidencias/consultas_athena.json.
--
-- Estas três foram escolhidas porque cada uma prova uma capacidade
-- diferente da solução, e o resultado cabe na tela sem rolagem.


-- =====================================================================
-- PRINT 1 — Evolução da adoção de cloud nas três edições
-- =====================================================================
-- Prova: leitura da camada Gold, comparação entre as três edições e
-- cálculo de variação. É o resultado mais forte visualmente, porque
-- mostra a AWS ultrapassando o Azure no período.

SELECT
    opcao                                                    AS cloud,
    MAX(CASE WHEN edicao = 2023 THEN percentual END)         AS pct_2023_2024,
    MAX(CASE WHEN edicao = 2024 THEN percentual END)         AS pct_2024_2025,
    MAX(CASE WHEN edicao = 2025 THEN percentual END)         AS pct_2025_2026,
    ROUND(
        MAX(CASE WHEN edicao = 2025 THEN percentual END)
        - MAX(CASE WHEN edicao = 2023 THEN percentual END)
    , 2)                                                     AS variacao_pp
FROM tecnologias
WHERE dimensao = 'cloud_dia_a_dia'
GROUP BY opcao
ORDER BY pct_2025_2026 DESC;


-- =====================================================================
-- PRINT 2 — Adoção de IA com a base explícita
-- =====================================================================
-- Prova: o tratamento correto do denominador. A coluna taxa_resposta
-- mostra que a pergunta foi respondida por 60% da base, e a coluna
-- respondentes_validos mostra o denominador real usado no percentual.
-- É a evidência de que os percentuais não foram calculados sobre a
-- base cheia.

SELECT
    edicao,
    SUBSTR(categoria, 1, 60)  AS forma_de_uso,
    quantidade,
    percentual,
    respondentes_validos,
    taxa_resposta
FROM adocao_ia
WHERE dimensao = 'usa_chatgpt_copilot'
  AND edicao = 2025
ORDER BY percentual DESC;


-- =====================================================================
-- PRINT 3 — Leitura da Silver com filtro de partição
-- =====================================================================
-- Prova: a tabela particionada funciona e o total confere com o
-- documentado (5.293 + 5.217 + 3.495 = 14.005 respondentes).
-- O filtro por edicao demonstra que a partição foi registrada pelo
-- Crawler, que é justamente o ponto que falhava antes do ajuste de
-- permissão da IAM role.

SELECT
    edicao,
    COUNT(*)                                                      AS respondentes,
    COUNT(nivel_senioridade)                                      AS informaram_senioridade,
    COUNT(faixa_salarial)                                         AS informaram_salario,
    ROUND(100.0 * COUNT(faixa_salarial) / COUNT(*), 1)            AS pct_com_salario
FROM respondentes
GROUP BY edicao
ORDER BY edicao;
