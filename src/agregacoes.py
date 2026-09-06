"""
Utilitários de agregação da camada Gold.

O CONTRATO UNIFORME
-------------------
Toda agregação da Gold emite as mesmas colunas de suporte ao lado da métrica:

    <dimensões de corte> | quantidade | percentual | respondentes_validos
                         | taxa_resposta | fragil

`respondentes_validos` é o denominador efetivo: quantos respondentes de fato
responderam à pergunta naquele recorte. `taxa_resposta` é essa quantidade
dividida pelo total de respondentes da edição.

POR QUE ISSO É O CENTRO DA CAMADA GOLD
--------------------------------------
O questionário é condicional. A seção 3 só é respondida por gestores: em
2025-2026, `ia_e_prioridade` tem 652 respostas de 3.495 respondentes. Um
percentual de adoção de IA calculado sobre 3.495 estaria errado por um fator
de cinco.

O erro é silencioso: o gráfico sai bonito, os percentuais somam 100%, e a
conclusão está completamente equivocada. Emitir `respondentes_validos` e
`taxa_resposta` junto de cada número torna o denominador visível e impede que
alguém apresente uma taxa sem saber sobre o que ela foi calculada.

`fragil` marca recortes com menos de 30 respondentes válidos. Cruzamentos
finos — gênero por senioridade por região, por exemplo — esgotam a base
rapidamente, e uma diferença de 2 respondentes em 8 não sustenta conclusão.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Sequence

from pyspark.sql import DataFrame
from pyspark.sql import functions as F

from src import config
from src.dominio import SENIORIDADE_EXCLUSIVA_2025

COLUNA_EDICAO = "edicao"


def totais_por_edicao(df: DataFrame) -> DataFrame:
    """Calcula o total de respondentes de cada edição.

    Serve de denominador para a taxa de resposta: quanto da base sustenta cada
    número apresentado.

    Args:
        df: DataFrame da camada Silver.

    Returns:
        DataFrame com `edicao` e `total_edicao`.
    """
    return df.groupBy(COLUNA_EDICAO).agg(F.count("*").alias("total_edicao"))


def distribuir(
    df: DataFrame,
    dimensao: str,
    cortes: Optional[Sequence[str]] = None,
    incluir_edicao: bool = True,
) -> DataFrame:
    """Calcula a distribuição de uma dimensão de escolha única.

    Registros com valor nulo na dimensão são excluídos da contagem e do
    denominador, porque representam quem não respondeu à pergunta. Isso é o que
    torna o percentual correto: ele é calculado sobre quem respondeu, não sobre
    a base inteira.

    Args:
        df: DataFrame da camada Silver.
        dimensao: coluna cuja distribuição será calculada.
        cortes: colunas adicionais de segmentação (ex.: `regiao_onde_mora`).
        incluir_edicao: quando `True`, segmenta também por edição.

    Returns:
        DataFrame com as colunas de corte, a dimensão, `quantidade`,
        `percentual`, `respondentes_validos`, `taxa_resposta` e `fragil`.
    """
    chaves: List[str] = []
    if incluir_edicao:
        chaves.append(COLUNA_EDICAO)
    chaves.extend(cortes or [])

    # Exclui quem não respondeu à pergunta: nulo aqui é ausência de resposta,
    # não categoria.
    valido = df.filter(F.col(dimensao).isNotNull())

    contagem = valido.groupBy(*chaves, dimensao).agg(F.count("*").alias("quantidade"))

    # O denominador é a quantidade de respostas válidas dentro do mesmo recorte,
    # de modo que os percentuais de cada recorte somem 100%.
    denominador = valido.groupBy(*chaves).agg(
        F.count("*").alias("respondentes_validos")
    )

    resultado = contagem.join(denominador, on=chaves, how="inner").withColumn(
        "percentual",
        F.round(F.col("quantidade") / F.col("respondentes_validos") * 100, 2),
    )

    if incluir_edicao:
        resultado = _anexar_taxa_resposta(resultado, df)

    return _marcar_fragil(resultado).orderBy(*chaves, F.col("quantidade").desc())


def distribuir_multiescolha(
    df: DataFrame,
    colunas_opcoes: Dict[str, str],
    nome_dimensao: str = "opcao",
    cortes: Optional[Sequence[str]] = None,
    incluir_edicao: bool = True,
) -> DataFrame:
    """Calcula a adoção de cada opção de uma pergunta de múltipla escolha.

    Cada opção é contada independentemente, então a soma dos percentuais pode
    exceder 100%. Isso não é erro: um respondente que usa MySQL e PostgreSQL
    conta nas duas opções.

    O denominador é a quantidade de respondentes que responderam à pergunta,
    identificados como aqueles com valor não nulo em ao menos uma das colunas
    de opção. Quem não respondeu fica fora, preservando a lógica de nulo
    estrutural.

    Args:
        df: DataFrame contendo as colunas booleanas de opção.
        colunas_opcoes: mapa `{nome da coluna -> rótulo da opção}`.
        nome_dimensao: nome da coluna de saída que conterá o rótulo da opção.
        cortes: colunas adicionais de segmentação.
        incluir_edicao: quando `True`, segmenta também por edição.

    Returns:
        DataFrame com as colunas de corte, `nome_dimensao`, `quantidade`,
        `percentual`, `respondentes_validos`, `taxa_resposta`, `fragil` e
        `soma_pode_exceder_100`.

    Raises:
        ValueError: se `colunas_opcoes` estiver vazio.
    """
    if not colunas_opcoes:
        raise ValueError("colunas_opcoes não pode estar vazio.")

    chaves: List[str] = []
    if incluir_edicao:
        chaves.append(COLUNA_EDICAO)
    chaves.extend(cortes or [])

    nomes = list(colunas_opcoes)

    # Respondeu à pergunta quem tem valor não nulo em ao menos uma opção.
    condicao_respondeu = F.lit(False)
    for nome in nomes:
        condicao_respondeu = condicao_respondeu | F.col(nome).isNotNull()
    respondentes = df.filter(condicao_respondeu)

    denominador = respondentes.groupBy(*chaves).agg(
        F.count("*").alias("respondentes_validos")
    )

    # Uma linha por opção, com a contagem de quem marcou aquela opção.
    parciais: List[DataFrame] = []
    for nome, rotulo in colunas_opcoes.items():
        marcado = _expressao_marcado(nome)
        parcial = (
            respondentes.groupBy(*chaves)
            .agg(F.sum(F.when(marcado, 1).otherwise(0)).alias("quantidade"))
            .withColumn(nome_dimensao, F.lit(rotulo))
        )
        parciais.append(parcial)

    empilhado = parciais[0]
    for parcial in parciais[1:]:
        empilhado = empilhado.unionByName(parcial)

    resultado = (
        empilhado.join(denominador, on=chaves, how="inner")
        .withColumn(
            "percentual",
            F.round(F.col("quantidade") / F.col("respondentes_validos") * 100, 2),
        )
        # Marcador explícito para que quem consome a tabela não interprete a
        # soma acima de 100% como inconsistência.
        .withColumn("soma_pode_exceder_100", F.lit(True))
        .filter(F.col("quantidade") > 0)
    )

    if incluir_edicao:
        resultado = _anexar_taxa_resposta(resultado, df)

    return _marcar_fragil(resultado).orderBy(*chaves, F.col("quantidade").desc())


def _expressao_marcado(coluna: str):
    """Constrói a expressão que identifica uma opção marcada.

    As colunas explodidas da origem trazem valores heterogêneos entre edições:
    `1`/`0`, `True`/`False`, ou o próprio texto da opção quando marcada e nulo
    quando não. Esta expressão trata os três casos.

    Args:
        coluna: nome da coluna booleana de opção.

    Returns:
        Expressão booleana do Spark.
    """
    referencia = F.col(coluna)
    texto = F.lower(F.trim(referencia.cast("string")))
    return referencia.isNotNull() & (~texto.isin("0", "false", "nao", "não", ""))


def _anexar_taxa_resposta(resultado: DataFrame, base: DataFrame) -> DataFrame:
    """Anexa a taxa de resposta da pergunta em relação ao total da edição.

    Args:
        resultado: DataFrame agregado, contendo `edicao` e
            `respondentes_validos`.
        base: DataFrame da Silver, usado para obter o total por edição.

    Returns:
        DataFrame com a coluna `taxa_resposta` (percentual com 2 decimais).
    """
    return resultado.join(totais_por_edicao(base), on=COLUNA_EDICAO, how="left").withColumn(
        "taxa_resposta",
        F.round(F.col("respondentes_validos") / F.col("total_edicao") * 100, 2),
    )


def _marcar_fragil(resultado: DataFrame) -> DataFrame:
    """Marca recortes estatisticamente frágeis.

    Args:
        resultado: DataFrame agregado contendo `respondentes_validos`.

    Returns:
        DataFrame com a coluna booleana `fragil`.
    """
    return resultado.withColumn(
        "fragil", F.col("respondentes_validos") < F.lit(config.MINIMO_RESPONDENTES_RECORTE)
    )


def calcular_variacao_entre_edicoes(
    agregado: DataFrame,
    dimensao: str,
    cortes: Optional[Sequence[str]] = None,
    primeira: int = 2023,
    ultima: int = 2025,
) -> DataFrame:
    """Calcula a variação do percentual entre a primeira e a última edição.

    Sustenta a leitura de tendência: quanto cada categoria cresceu ou caiu ao
    longo das três edições.

    Args:
        agregado: DataFrame produzido por `distribuir` ou
            `distribuir_multiescolha`.
        dimensao: coluna que contém a categoria.
        cortes: colunas adicionais de segmentação presentes no agregado.
        primeira: edição inicial da comparação.
        ultima: edição final da comparação.

    Returns:
        DataFrame com a dimensão, os cortes, `percentual_inicial`,
        `percentual_final`, `variacao_pp` (diferença em pontos percentuais) e
        `presente_nas_duas`.
    """
    chaves = [dimensao, *(cortes or [])]

    inicial = (
        agregado.filter(F.col(COLUNA_EDICAO) == primeira)
        .select(*chaves, F.col("percentual").alias("percentual_inicial"))
    )
    final = (
        agregado.filter(F.col(COLUNA_EDICAO) == ultima)
        .select(*chaves, F.col("percentual").alias("percentual_final"))
    )

    return (
        inicial.join(final, on=chaves, how="full_outer")
        .withColumn(
            "variacao_pp",
            F.round(F.col("percentual_final") - F.col("percentual_inicial"), 2),
        )
        .withColumn(
            "presente_nas_duas",
            F.col("percentual_inicial").isNotNull() & F.col("percentual_final").isNotNull(),
        )
        .orderBy(F.col("variacao_pp").desc_nulls_last())
    )


def anexar_aviso_metodologico(df: DataFrame, aviso: str) -> DataFrame:
    """Anexa um aviso metodológico a todas as linhas de um agregado.

    Existe para que quebras conhecidas de comparabilidade viajem junto com o
    dado, em vez de ficarem só na documentação. Quem ler a tabela no Athena vê
    o aviso sem precisar consultar o README.

    Args:
        df: DataFrame agregado.
        aviso: texto do aviso.

    Returns:
        DataFrame com a coluna `aviso_metodologico`.
    """
    return df.withColumn("aviso_metodologico", F.lit(aviso))


AVISO_SENIORIDADE = (
    f"A edicao 2025-2026 introduziu o nivel '{SENIORIDADE_EXCLUSIVA_2025}', "
    f"ausente nas anteriores. A queda do share de Senior entre edicoes reflete "
    f"essa mudanca de categorias, nao necessariamente mudanca de mercado."
)

AVISO_MULTIESCOLHA = (
    "Pergunta de multipla escolha: a soma dos percentuais excede 100% porque "
    "um respondente pode marcar varias opcoes."
)

AVISO_LINGUAGEM_PREFERIDA = (
    "Linguagem preferida era escolha unica em 2023-2024 e passou a multipla "
    "escolha em 2025-2026. Os percentuais nao sao comparaveis entre esses "
    "periodos."
)

AVISO_SECAO_GESTORES = (
    "Pergunta respondida apenas por quem atua como gestor. Verifique "
    "taxa_resposta antes de generalizar o resultado para o mercado."
)
