"""
Transformação das perguntas multi-escolha em tabela Silver de formato longo.

POR QUE UMA SEGUNDA TABELA SILVER
---------------------------------
As perguntas multi-escolha existem na origem como colunas booleanas explodidas:
33 para banco de dados, 23 para ferramenta de BI, 15 para linguagem, e assim por
diante. Somadas, passam de 200 colunas.

Acrescentá-las à tabela `respondentes` a deixaria com mais de 250 colunas,
quase todas booleanas e esparsas, difícil de consultar e de catalogar. Uma
consulta de adoção de banco de dados precisaria referenciar 33 colunas por nome.

A alternativa adotada é uma tabela longa:

    edicao | token | dimensao      | opcao
    -------+-------+---------------+--------------------------
    2025   | a1b2  | banco_dados   | PostgreSQL
    2025   | a1b2  | banco_dados   | Google BigQuery
    2025   | a1b2  | cloud_dia_a_dia | Amazon Web Services (AWS)

Só as opções efetivamente marcadas geram linha. Isso torna a tabela compacta,
faz a agregação por opção virar um `GROUP BY` simples, e permite juntar com
`respondentes` pelo `token` para cruzar tecnologia com senioridade, região ou
faixa salarial.

O CUIDADO COM O DENOMINADOR
---------------------------
Como só as marcações viram linha, esta tabela sozinha não sabe quem respondeu à
pergunta e não marcou nada. Por isso a tabela também registra, para cada
respondente e dimensão, se a pergunta foi respondida — via a tabela auxiliar
`respondeu`, que preserva o denominador correto.
"""

from __future__ import annotations

from typing import Dict, Iterable, List, Optional

from pyspark.sql import DataFrame
from pyspark.sql import functions as F

from src import config
from src.contexto_execucao import ContextoExecucao
from src.mapeamento_colunas import ANOS, ROTULO_EDICAO
from src.mapeamento_multiescolha import (
    MAPEAMENTO_MULTIESCOLHA,
    dimensoes_disponiveis,
    resolver_opcoes,
)
from src.transformacoes.bronze_para_silver import _resolver_identificador

TABELA_MULTIESCOLHA = "respostas_multiescolha"
TABELA_RESPONDEU = "respondeu_multiescolha"


# Valores que representam "não marcado" nas colunas explodidas. A origem é
# heterogênea entre edições: pode ser `0`, `False`, ou o próprio texto da opção
# quando marcada e nulo quando não.
VALORES_NAO_MARCADO = ("0", "false", "nao", "não", "")


def _expressao_marcado(coluna: str):
    """Constrói a expressão que identifica uma opção marcada.

    Args:
        coluna: nome bruto da coluna booleana de opção.

    Returns:
        Expressão booleana do Spark.
    """
    referencia = F.col(f"`{coluna}`")
    texto = F.lower(F.trim(referencia.cast("string")))
    return referencia.isNotNull() & (~texto.isin(*VALORES_NAO_MARCADO))


def _escapar_literal_sql(texto: str) -> str:
    """Escapa um texto para uso como literal de string em SQL do Spark.

    Necessário porque rótulos de opção contêm apóstrofo, como em
    "Realizo construções de ETL's em ferramentas...".

    Args:
        texto: texto a escapar.

    Returns:
        Texto com apóstrofos e barras invertidas escapados.
    """
    return texto.replace("\\", "\\\\").replace("'", "\\'")


def _expressao_stack(opcoes) -> str:
    """Monta a expressão SQL `stack` que transpõe as colunas de opção em linhas.

    Produz algo como:

        stack(3, 'MySQL', `4.d.1_MySQL`, 'Oracle', `4.d.2_Oracle`, ...)
            as (opcao, valor_bruto)

    Args:
        opcoes: sequência de `OpcaoMultiEscolha`.

    Returns:
        Expressão SQL pronta para `selectExpr`.
    """
    pares = []
    for opcao in opcoes:
        rotulo = _escapar_literal_sql(opcao.rotulo)
        coluna = opcao.coluna.replace("`", "``")
        pares.append(f"'{rotulo}', `{coluna}`")
    return f"stack({len(opcoes)}, {', '.join(pares)}) as (opcao, valor_bruto)"


def _marcado_apos_stack():
    """Constrói o filtro de "opção marcada" aplicado após o `stack`.

    Trata os valores textuais de negação e também o caso numérico. Nas edições
    atuais o Spark lê as colunas explodidas como texto `"0"` e `"1"`, mas uma
    exportação futura em ponto flutuante produziria `"0.0"`, que não casaria com
    a comparação textual — e então TODO zero seria contado como marcado, fazendo
    cada opção aparecer com cerca de 100% de adoção. A comparação numérica
    fecha essa falha silenciosa.

    Returns:
        Expressão booleana do Spark sobre a coluna `valor_bruto`.
    """
    referencia = F.col("valor_bruto")
    texto = F.lower(F.trim(referencia.cast("string")))
    # `try_cast` devolve nulo quando o valor não é numérico (caso das colunas
    # que trazem o próprio texto da opção quando marcada).
    numerico = F.expr("try_cast(trim(valor_bruto) as double)")
    return (
        referencia.isNotNull()
        & (~texto.isin(*VALORES_NAO_MARCADO))
        & (numerico.isNull() | (numerico != F.lit(0.0)))
    )


def extrair_multiescolha(df_bruto: DataFrame, ano: int) -> tuple[DataFrame, DataFrame]:
    """Extrai as respostas multi-escolha de uma edição em formato longo.

    Args:
        df_bruto: DataFrame bruto da edição.
        ano: ano de início da edição (2023, 2024 ou 2025).

    Returns:
        Tupla `(marcacoes, respondeu)`:
            - `marcacoes`: uma linha por opção marcada, com `edicao`, `token`,
              `dimensao` e `opcao`.
            - `respondeu`: uma linha por respondente e dimensão, indicando se a
              pergunta foi respondida. Preserva o denominador.
    """
    identificador = _resolver_identificador(df_bruto.columns, ano)
    expressao_token = (
        F.col(f"`{identificador}`") if identificador else F.lit(None).cast("string")
    )

    base = df_bruto.withColumn("token", expressao_token).withColumn(
        "edicao", F.lit(ano).cast("int")
    )

    marcacoes: List[DataFrame] = []
    respondeu: List[DataFrame] = []

    for dimensao in dimensoes_disponiveis(ano):
        opcoes = resolver_opcoes(df_bruto.columns, dimensao, ano)
        if not opcoes:
            continue

        # Respondeu à pergunta quem tem valor não nulo em ao menos uma opção.
        condicao_respondeu = F.lit(False)
        for opcao in opcoes:
            condicao_respondeu = condicao_respondeu | F.col(f"`{opcao.coluna}`").isNotNull()

        # A condição referencia as colunas de opção, então precisa ser avaliada
        # no `select` que ainda as contém. Projetar `edicao` e `token` antes
        # descartaria as colunas e a expressão não resolveria.
        respondeu.append(
            base.select(
                "edicao",
                "token",
                F.lit(dimensao).alias("dimensao"),
                condicao_respondeu.alias("respondeu"),
            )
        )

        # Transposição das N colunas de opção em N linhas numa única passada,
        # via `stack`. A alternativa de unir N DataFrames (33 só para banco de
        # dados) construía mais de 130 planos por edição e levava ~50s; com
        # `stack` cai para poucos segundos, o que importa no Glue.
        marcacoes.append(
            base.selectExpr(
                "edicao",
                "token",
                _expressao_stack(opcoes),
            )
            .filter(_marcado_apos_stack())
            .select(
                "edicao",
                "token",
                F.lit(dimensao).alias("dimensao"),
                "opcao",
            )
        )

    vazio_marcacoes = base.select("edicao", "token").limit(0).withColumn(
        "dimensao", F.lit(None).cast("string")
    ).withColumn("opcao", F.lit(None).cast("string"))

    resultado_marcacoes = _empilhar(marcacoes, vazio_marcacoes)
    resultado_respondeu = _empilhar(
        respondeu,
        base.select("edicao", "token")
        .limit(0)
        .withColumn("dimensao", F.lit(None).cast("string"))
        .withColumn("respondeu", F.lit(None).cast("boolean")),
    )

    return resultado_marcacoes, resultado_respondeu


def _empilhar(partes: List[DataFrame], vazio: DataFrame) -> DataFrame:
    """Empilha uma lista de DataFrames, devolvendo o vazio se a lista estiver vazia.

    Args:
        partes: DataFrames a empilhar.
        vazio: DataFrame vazio com o schema esperado.

    Returns:
        DataFrame resultante da união.
    """
    if not partes:
        return vazio
    resultado = partes[0]
    for parte in partes[1:]:
        resultado = resultado.unionByName(parte)
    return resultado


def executar(
    contexto: ContextoExecucao,
    brutos: Dict[int, DataFrame],
    escrever: bool = True,
) -> tuple[DataFrame, DataFrame]:
    """Produz as tabelas Silver de multi-escolha para todas as edições.

    Args:
        contexto: contexto de execução ativo.
        brutos: dicionário `{ano -> DataFrame bruto}`.
        escrever: quando `True`, persiste as tabelas em Parquet.

    Returns:
        Tupla `(marcacoes, respondeu)` unificada entre as edições.
    """
    marcacoes: List[DataFrame] = []
    respondeu: List[DataFrame] = []

    for ano in sorted(brutos):
        contexto.registrar(f"extraindo multi-escolha de {ROTULO_EDICAO[ano]}")
        parte_marcacoes, parte_respondeu = extrair_multiescolha(brutos[ano], ano)
        marcacoes.append(parte_marcacoes)
        respondeu.append(parte_respondeu)

    unificado_marcacoes = marcacoes[0]
    for parte in marcacoes[1:]:
        unificado_marcacoes = unificado_marcacoes.unionByName(parte)

    unificado_respondeu = respondeu[0]
    for parte in respondeu[1:]:
        unificado_respondeu = unificado_respondeu.unionByName(parte)

    if escrever:
        contexto.escrever_parquet(
            unificado_marcacoes,
            config.CAMADA_SILVER,
            TABELA_MULTIESCOLHA,
            particoes=["edicao"],
        )
        contexto.escrever_parquet(
            unificado_respondeu,
            config.CAMADA_SILVER,
            TABELA_RESPONDEU,
            particoes=["edicao"],
        )

    return unificado_marcacoes, unificado_respondeu
