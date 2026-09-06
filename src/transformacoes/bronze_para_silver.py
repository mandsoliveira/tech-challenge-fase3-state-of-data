"""
Transformação Bronze -> Silver: harmonização das três edições em tabela única.

FLUXO
-----
Para cada edição, na ordem:

    1. Resolver as 41 dimensões canônicas via mapeamento semântico curado
    2. Materializar como nulo as dimensões ausentes naquela edição
    3. Sanitizar o nome do identificador de origem
    4. Adicionar `edicao` e `ingerido_em`
    5. Unir as edições com unionByName

Depois da união:

    6. Normalizar valores categóricos e derivar colunas de ordenação
    7. Validar faixas salariais e consistência de dimensões
    8. Validar que a contagem total é 14.005

POR QUE O MAPEAMENTO E NÃO TODAS AS COLUNAS
-------------------------------------------
A Silver seleciona apenas as dimensões mapeadas. As demais ~350 colunas não
têm garantia de comparabilidade entre edições, porque o código da pergunta
desloca entre anos. Mantê-las na Silver convidaria alguém a usá-las achando
que são comparáveis. A Bronze permanece como cópia fiel e completa, então
nada é perdido de forma irreversível.

O QUE ESTA TRANSFORMAÇÃO NÃO FAZ
--------------------------------
Não executa `dropna()` em nenhum momento. Os nulos aqui são estruturais: a
seção 3 só é respondida por gestores, senioridade é nula para desempregados e
estudantes. Remover essas linhas descartaria respondentes válidos e distorceria
todo denominador subsequente.
"""

from __future__ import annotations

from typing import Dict, Iterable, List, Optional

from pyspark.sql import DataFrame
from pyspark.sql import functions as F

from src import config
from src.contexto_execucao import ContextoExecucao
from src.mapeamento_colunas import (
    ANOS,
    MAPEAMENTO,
    ROTULO_EDICAO,
    resolver_colunas,
)
from src.transformacoes.normalizacao import (
    normalizar,
    validar_dimensoes_consistentes,
    validar_faixas_salariais,
)
from src.transformacoes.sanitizacao import validar_nomes_sanitizados

# Dimensões que devem ser convertidas para inteiro. As demais permanecem como
# string, porque são respostas categóricas de questionário.
DIMENSOES_INTEIRAS = ("idade",)

# Coluna de identificador anônimo do respondente. O nome bruto difere entre
# edições, então é resolvido pelo código da pergunta, não pelo nome.
CODIGO_IDENTIFICADOR = {2023: "0", 2024: "0.a", 2025: "0.a"}


class ErroDeHarmonizacao(RuntimeError):
    """Erro na harmonização das edições."""


def _resolver_identificador(colunas: Iterable[str], ano: int) -> Optional[str]:
    """Localiza a coluna de identificador anônimo do respondente.

    Args:
        colunas: nomes das colunas da edição.
        ano: ano de início da edição.

    Returns:
        Nome da coluna de identificador, ou None se não for encontrada.
    """
    lista = list(colunas)
    if ano == 2023:
        # Edição 2023: "('P0', 'id')"
        for coluna in lista:
            if "'P0'" in coluna:
                return coluna
        return None
    # Edições 2024 e 2025: "0.a_token"
    for coluna in lista:
        if coluna.strip().startswith("0.a"):
            return coluna
    return None


def preparar_edicao(df_bruto: DataFrame, ano: int) -> DataFrame:
    """Extrai e renomeia as dimensões canônicas de uma edição.

    Dimensões ausentes na edição são materializadas como nulo tipado, de modo
    que o `unionByName` posterior encontre schema idêntico nas três edições.

    Args:
        df_bruto: DataFrame bruto da edição, com nomes de coluna da origem.
        ano: ano de início da edição (2023, 2024 ou 2025).

    Returns:
        DataFrame com as dimensões canônicas, `token`, `edicao` e `ingerido_em`.

    Raises:
        ErroDeHarmonizacao: se alguma dimensão declarada como presente no
            mapeamento não resolver para uma coluna existente.
    """
    resolvido = resolver_colunas(df_bruto.columns, ano)

    nao_resolvidas = [
        dimensao
        for dimensao, coluna in resolvido.items()
        if coluna is None and MAPEAMENTO[dimensao][ano] is not None
    ]
    if nao_resolvidas:
        raise ErroDeHarmonizacao(
            f"Edição {ROTULO_EDICAO[ano]}: {len(nao_resolvidas)} dimensões declaradas "
            f"no mapeamento não resolveram para colunas existentes: {nao_resolvidas}.\n"
            f"Rode `python -m src.validar_mapeamento` para diagnosticar."
        )

    expressoes = []

    identificador = _resolver_identificador(df_bruto.columns, ano)
    if identificador is not None:
        expressoes.append(F.col(f"`{identificador}`").alias("token"))
    else:
        expressoes.append(F.lit(None).cast("string").alias("token"))

    for dimensao, coluna in resolvido.items():
        if coluna is None:
            tipo = "int" if dimensao in DIMENSOES_INTEIRAS else "string"
            expressoes.append(F.lit(None).cast(tipo).alias(dimensao))
            continue

        referencia = F.col(f"`{coluna}`")
        if dimensao in DIMENSOES_INTEIRAS:
            # `try_cast` evita que valores não numéricos derrubem o job; eles
            # viram nulo, que é o comportamento correto para idade inválida.
            expressoes.append(referencia.cast("int").alias(dimensao))
        else:
            expressoes.append(referencia.alias(dimensao))

    return (
        df_bruto.select(*expressoes)
        .withColumn("edicao", F.lit(ano).cast("int"))
        .withColumn("ingerido_em", F.current_timestamp())
    )


def harmonizar(
    contexto: ContextoExecucao,
    brutos: Dict[int, DataFrame],
    validar: bool = True,
) -> DataFrame:
    """Harmoniza as edições brutas em uma tabela Silver única.

    Args:
        contexto: contexto de execução ativo.
        brutos: dicionário `{ano -> DataFrame bruto}`.
        validar: quando `True`, executa as validações de integridade.

    Returns:
        DataFrame Silver unificado, com as dimensões canônicas normalizadas.

    Raises:
        ErroDeHarmonizacao: se a contagem total divergir do esperado ou se
            alguma validação falhar.
    """
    if not brutos:
        raise ErroDeHarmonizacao("Nenhuma edição fornecida para harmonização.")

    preparados: List[DataFrame] = []
    for ano in sorted(brutos):
        contexto.registrar(f"preparando {ROTULO_EDICAO[ano]}")
        preparado = preparar_edicao(brutos[ano], ano)
        preparados.append(preparado)

    unificado = preparados[0]
    for adicional in preparados[1:]:
        unificado = unificado.unionByName(adicional)

    contexto.registrar("normalizando valores categóricos")
    unificado = normalizar(unificado)

    if validar:
        _validar_silver(contexto, unificado, anos=sorted(brutos))

    return unificado


def _validar_silver(
    contexto: ContextoExecucao,
    df: DataFrame,
    anos: List[int],
) -> None:
    """Executa as validações de integridade da camada Silver.

    Args:
        contexto: contexto de execução ativo.
        df: DataFrame Silver unificado.
        anos: edições presentes no DataFrame.

    Raises:
        ErroDeHarmonizacao: se qualquer validação falhar.
    """
    validar_nomes_sanitizados(df.columns)
    contexto.registrar(f"nomes de coluna válidos para Athena: {len(df.columns)} colunas")

    contagem_por_edicao = {
        linha["edicao"]: linha["quantidade"]
        for linha in df.groupBy("edicao").agg(F.count("*").alias("quantidade")).collect()
    }

    divergentes = []
    for ano in anos:
        obtido = contagem_por_edicao.get(ano, 0)
        esperado = config.LINHAS_ESPERADAS[ano]
        contexto.registrar(f"  {ROTULO_EDICAO[ano]}: {obtido} registros (esperado {esperado})")
        if obtido != esperado:
            divergentes.append((ROTULO_EDICAO[ano], esperado, obtido))

    if divergentes:
        detalhe = "; ".join(f"{rotulo}: esperado {e}, obtido {o}" for rotulo, e, o in divergentes)
        raise ErroDeHarmonizacao(
            f"Contagem por edição divergente na Silver ({detalhe}). "
            f"Registros foram perdidos ou duplicados na harmonização."
        )

    total = sum(contagem_por_edicao.values())
    esperado_total = sum(config.LINHAS_ESPERADAS[ano] for ano in anos)
    if total != esperado_total:
        raise ErroDeHarmonizacao(
            f"Total da Silver é {total}, esperado {esperado_total}."
        )
    contexto.registrar(f"total da Silver: {total} registros")

    faixas = validar_faixas_salariais(df)
    contexto.registrar(f"faixas salariais válidas: {len(faixas)} distintas")

    divergencias = validar_dimensoes_consistentes(df)
    if divergencias:
        for dimensao, valores in divergencias.items():
            contexto.registrar(
                f"  ATENÇÃO: {dimensao} tem valores exclusivos de alguma edição: {valores}"
            )
    else:
        contexto.registrar("dimensões consistentes verificadas: sem divergência entre edições")


def executar(
    contexto: ContextoExecucao,
    anos: Optional[Iterable[int]] = None,
    escrever: bool = True,
) -> DataFrame:
    """Executa a transformação Bronze -> Silver de ponta a ponta.

    Args:
        contexto: contexto de execução ativo.
        anos: edições a processar. Quando omitido, processa as três.
        escrever: quando `True`, persiste o resultado em Parquet particionado
            por `edicao`.

    Returns:
        DataFrame Silver resultante.
    """
    from src.ingestao import ler_todas_edicoes  # noqa: PLC0415

    selecionados = tuple(anos) if anos else ANOS
    brutos = ler_todas_edicoes(contexto, selecionados)
    silver = harmonizar(contexto, brutos)

    if escrever:
        # `cache` evita reprocessar toda a leitura de CSV na escrita e na
        # contagem de log subsequente.
        silver = silver.cache()
        contexto.escrever_parquet(
            silver, config.CAMADA_SILVER, config.TABELA_SILVER, particoes=["edicao"]
        )

    return silver
