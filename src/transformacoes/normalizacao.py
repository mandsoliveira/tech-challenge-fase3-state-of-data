"""
Normalização de valores categóricos entre as edições da pesquisa.

O QUE ESTE MÓDULO CORRIGE
-------------------------
Depois de resolver os nomes das colunas, resta o segundo nível de
incompatibilidade: os VALORES. A inspeção das três edições mostrou que:

1. Há dois erros de digitação na origem, cada um afetando 1 respondente:
       2023: "de R$ 101/mês a R$ 2.000/mês"      -> era "R$ 1.001"
       2025: "de R$ 25.001/mês a R$ 3000/mês"    -> era "R$ 30.000"
   Sem correção, viram duas categorias fantasma e, pior, quebram qualquer
   parsing numérico da faixa (o intervalo 25.001–3.000 é inválido).

2. Fora esses dois, as 13 faixas salariais são IDÊNTICAS nos três anos, o que
   viabiliza a comparação temporal de remuneração.

3. `regiao_onde_mora`, `genero` e `modelo_trabalho_atual` são 100% consistentes
   entre edições — nenhuma normalização necessária, apenas verificação.

4. `nivel_senioridade` ganhou o valor "Especialista/Staff+" apenas em 2025.
   Ele é PRESERVADO, não agrupado em "Sênior". Agrupar tornaria a série
   comparável, mas esconderia uma mudança real do mercado: a criação de uma
   trilha de especialista acima de sênior. A quebra metodológica é sinalizada
   na Gold em vez de ser apagada aqui.

ORDENAÇÃO E PONTO MÉDIO
-----------------------
Faixa salarial é uma string, então qualquer gráfico ordena alfabeticamente por
padrão, colocando "de R$ 1.001" ao lado de "de R$ 12.001". As colunas
derivadas `faixa_salarial_ordem` e `salario_medio_estimado` resolvem isso e
permitem calcular médias aproximadas.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Sequence

from pyspark.sql import DataFrame
from pyspark.sql import functions as F

# As constantes de domínio vivem em `src.dominio`, sem dependência de Spark,
# para que a conferência cruzada em pandas e os testes possam usá-las sem JVM.
from src.dominio import (
    CORRECOES_FAIXA_SALARIAL,
    DIMENSOES_CONSISTENTES,
    FAIXAS_SALARIAIS,
    NIVEIS_SENIORIDADE,
    QUANTIDADE_FAIXAS_ESPERADA,
    SENIORIDADE_EXCLUSIVA_2025,
    SENTINELAS_NULO,
)

__all__ = [
    "CORRECOES_FAIXA_SALARIAL",
    "DIMENSOES_CONSISTENTES",
    "FAIXAS_SALARIAIS",
    "NIVEIS_SENIORIDADE",
    "QUANTIDADE_FAIXAS_ESPERADA",
    "SENIORIDADE_EXCLUSIVA_2025",
    "SENTINELAS_NULO",
    "corrigir_faixa_salarial",
    "derivar_colunas_salariais",
    "derivar_ordem_senioridade",
    "normalizar",
    "nulificar_sentinelas",
    "validar_dimensoes_consistentes",
    "validar_faixas_salariais",
]


def nulificar_sentinelas(df: DataFrame) -> DataFrame:
    """Converte strings sentinela de valor ausente em nulo real.

    Aplica-se somente a colunas de tipo string e apenas a correspondências
    exatas após remoção de espaços nas extremidades. Substrings não são
    afetadas: uma resposta contendo a palavra "nan" no meio de um texto
    permanece intacta.

    Args:
        df: DataFrame a limpar.

    Returns:
        DataFrame com as sentinelas convertidas em nulo.
    """
    colunas_texto = [nome for nome, tipo in df.dtypes if tipo == "string"]
    resultado = df
    for nome in colunas_texto:
        referencia = F.col(nome)
        resultado = resultado.withColumn(
            nome,
            F.when(F.trim(referencia).isin(list(SENTINELAS_NULO)), F.lit(None)).otherwise(
                referencia
            ),
        )
    return resultado


class ErroDeNormalizacao(RuntimeError):
    """Erro na normalização de valores categóricos."""


def corrigir_faixa_salarial(df: DataFrame, coluna: str = "faixa_salarial") -> DataFrame:
    """Corrige os erros de digitação de faixa salarial presentes na origem.

    Args:
        df: DataFrame contendo a coluna de faixa salarial.
        coluna: nome da coluna a corrigir.

    Returns:
        DataFrame com os valores corrigidos.
    """
    expressao = F.col(coluna)
    for incorreto, correto in CORRECOES_FAIXA_SALARIAL.items():
        expressao = F.when(F.col(coluna) == incorreto, F.lit(correto)).otherwise(expressao)
    return df.withColumn(coluna, expressao)


def derivar_colunas_salariais(df: DataFrame, coluna: str = "faixa_salarial") -> DataFrame:
    """Deriva a ordem ordinal e o ponto médio estimado da faixa salarial.

    Args:
        df: DataFrame contendo a coluna de faixa salarial já corrigida.
        coluna: nome da coluna de faixa salarial.

    Returns:
        DataFrame com as colunas `faixa_salarial_ordem` (int) e
        `salario_medio_estimado` (double). Ambas ficam nulas quando a faixa é
        nula, preservando o nulo estrutural.
    """
    expressao_ordem = F.lit(None).cast("int")
    expressao_media = F.lit(None).cast("double")

    for rotulo, ordem, media in FAIXAS_SALARIAIS:
        condicao = F.col(coluna) == rotulo
        expressao_ordem = F.when(condicao, F.lit(ordem)).otherwise(expressao_ordem)
        expressao_media = F.when(condicao, F.lit(media)).otherwise(expressao_media)

    return df.withColumn("faixa_salarial_ordem", expressao_ordem).withColumn(
        "salario_medio_estimado", expressao_media
    )


def derivar_ordem_senioridade(df: DataFrame, coluna: str = "nivel_senioridade") -> DataFrame:
    """Deriva a ordem ordinal do nível de senioridade.

    Args:
        df: DataFrame contendo a coluna de senioridade.
        coluna: nome da coluna de senioridade.

    Returns:
        DataFrame com a coluna `nivel_senioridade_ordem` (int), nula quando a
        senioridade é nula.
    """
    expressao = F.lit(None).cast("int")
    for rotulo, ordem in NIVEIS_SENIORIDADE:
        expressao = F.when(F.col(coluna) == rotulo, F.lit(ordem)).otherwise(expressao)
    return df.withColumn("nivel_senioridade_ordem", expressao)


def validar_faixas_salariais(df: DataFrame, coluna: str = "faixa_salarial") -> List[str]:
    """Valida que restam exatamente as 13 faixas salariais canônicas.

    Args:
        df: DataFrame já corrigido.
        coluna: nome da coluna de faixa salarial.

    Returns:
        Lista ordenada das faixas distintas encontradas.

    Raises:
        ErroDeNormalizacao: se a quantidade de faixas divergir de 13 ou se
            houver faixa fora do conjunto canônico.
    """
    encontradas = sorted(
        linha[coluna]
        for linha in df.select(coluna).distinct().collect()
        if linha[coluna] is not None
    )
    canonicas = {rotulo for rotulo, _, _ in FAIXAS_SALARIAIS}
    inesperadas = [faixa for faixa in encontradas if faixa not in canonicas]

    if inesperadas:
        raise ErroDeNormalizacao(
            f"Faixas salariais fora do conjunto canônico após correção: {inesperadas}.\n"
            f"Provável novo erro de digitação na origem ou nova faixa em edição futura. "
            f"Avalie incluir em CORRECOES_FAIXA_SALARIAL ou em FAIXAS_SALARIAIS."
        )

    if len(encontradas) != QUANTIDADE_FAIXAS_ESPERADA:
        raise ErroDeNormalizacao(
            f"Esperadas {QUANTIDADE_FAIXAS_ESPERADA} faixas salariais distintas, "
            f"encontradas {len(encontradas)}: {encontradas}"
        )

    return encontradas


def validar_dimensoes_consistentes(
    df: DataFrame,
    coluna_edicao: str = "edicao",
    dimensoes: Optional[Sequence[str]] = None,
) -> Dict[str, List[str]]:
    """Verifica que as dimensões declaradas consistentes têm os mesmos valores.

    Estas dimensões foram medidas como idênticas entre as três edições. A
    verificação existe para detectar se uma edição futura mudar as opções de
    resposta, o que exigiria normalização.

    Args:
        df: DataFrame unificado das edições.
        coluna_edicao: nome da coluna que identifica a edição.
        dimensoes: dimensões a verificar. Quando omitido, usa
            `DIMENSOES_CONSISTENTES`.

    Returns:
        Dicionário `{dimensão -> lista de valores divergentes}`. Vazio quando
        todas as dimensões são consistentes.
    """
    alvo = tuple(dimensoes) if dimensoes else DIMENSOES_CONSISTENTES
    edicoes = [linha[coluna_edicao] for linha in df.select(coluna_edicao).distinct().collect()]
    divergencias: Dict[str, List[str]] = {}

    for dimensao in alvo:
        if dimensao not in df.columns:
            continue

        conjuntos = []
        for edicao in edicoes:
            valores = {
                linha[dimensao]
                for linha in df.filter(F.col(coluna_edicao) == edicao)
                .select(dimensao)
                .distinct()
                .collect()
                if linha[dimensao] is not None
            }
            conjuntos.append(valores)

        if not conjuntos:
            continue

        comuns = set.intersection(*conjuntos)
        todos = set.union(*conjuntos)
        exclusivos = sorted(todos - comuns)
        if exclusivos:
            divergencias[dimensao] = exclusivos

    return divergencias


def normalizar(df: DataFrame) -> DataFrame:
    """Aplica todas as normalizações de valor categórico.

    Não remove registros nem preenche nulos: nulos estruturais são preservados
    integralmente, conforme o requisito de não distorcer denominadores.

    Args:
        df: DataFrame com as dimensões canônicas já resolvidas.

    Returns:
        DataFrame normalizado, com as colunas derivadas de ordenação e ponto
        médio salarial e de ordem de senioridade.
    """
    # A nulificação vem primeiro: se "NA" chegasse à correção de faixa salarial
    # ou à validação de consistência, apareceria como categoria legítima.
    resultado = nulificar_sentinelas(df)
    if "faixa_salarial" in resultado.columns:
        resultado = corrigir_faixa_salarial(resultado)
        resultado = derivar_colunas_salariais(resultado)
    if "nivel_senioridade" in resultado.columns:
        resultado = derivar_ordem_senioridade(resultado)
    return resultado
