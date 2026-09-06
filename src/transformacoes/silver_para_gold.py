"""
Transformação Silver -> Gold: sete tabelas agregadas, uma por pergunta de negócio.

ESTRUTURA
---------
Cada tabela responde a uma das sete perguntas do enunciado e segue o contrato
uniforme definido em `src/agregacoes.py`:

    <dimensões de corte> | quantidade | percentual | respondentes_validos
                         | taxa_resposta | fragil | aviso_metodologico

O campo `respondentes_validos` é o que impede o erro mais provável do projeto:
apresentar um percentual sem saber sobre qual base ele foi calculado. A seção 3
da pesquisa, por exemplo, só é respondida por gestores — em 2025-2026 são 652 de
3.495 respondentes.

AVISOS METODOLÓGICOS VIAJAM COM O DADO
--------------------------------------
Quebras conhecidas de comparabilidade são gravadas como coluna nas tabelas, não
apenas documentadas. Quem consultar a tabela no Athena vê o aviso sem precisar
ler o README. São três:

    - senioridade ganhou "Especialista/Staff+" em 2025-2026
    - múltipla escolha soma acima de 100%
    - "linguagem preferida" mudou de escolha única para múltipla em 2025-2026
"""

from __future__ import annotations

from typing import Dict, List, Optional

from pyspark.sql import DataFrame
from pyspark.sql import functions as F

from src import config
from src.agregacoes import (
    AVISO_LINGUAGEM_PREFERIDA,
    AVISO_MULTIESCOLHA,
    AVISO_SECAO_GESTORES,
    AVISO_SENIORIDADE,
    anexar_aviso_metodologico,
    distribuir,
)
from src.contexto_execucao import ContextoExecucao
from src.dominio import PERGUNTAS_DE_NEGOCIO
from src.transformacoes.multiescolha import TABELA_MULTIESCOLHA, TABELA_RESPONDEU

SEM_AVISO = "-"


# ---------------------------------------------------------------------------
# Agregação de multi-escolha a partir da tabela longa
# ---------------------------------------------------------------------------


def agregar_multiescolha(
    marcacoes: DataFrame,
    respondeu: DataFrame,
    totais: DataFrame,
    dimensoes: Optional[List[str]] = None,
) -> DataFrame:
    """Agrega a adoção de opções multi-escolha a partir das tabelas longas.

    O denominador vem da tabela `respondeu`, que registra quem respondeu à
    pergunta independentemente de ter marcado alguma opção. Usar a contagem de
    marcações como denominador inflaria os percentuais.

    Args:
        marcacoes: tabela longa com uma linha por opção marcada.
        respondeu: tabela longa indicando quem respondeu cada pergunta.
        totais: DataFrame com `edicao` e `total_edicao`.
        dimensoes: dimensões a agregar. Quando omitido, agrega todas.

    Returns:
        DataFrame com `edicao`, `dimensao`, `opcao`, `quantidade`,
        `percentual`, `respondentes_validos`, `taxa_resposta` e `fragil`.
    """
    marcadas = marcacoes
    validos = respondeu.filter(F.col("respondeu"))

    if dimensoes:
        marcadas = marcadas.filter(F.col("dimensao").isin(dimensoes))
        validos = validos.filter(F.col("dimensao").isin(dimensoes))

    contagem = marcadas.groupBy("edicao", "dimensao", "opcao").agg(
        F.count("*").alias("quantidade")
    )
    denominador = validos.groupBy("edicao", "dimensao").agg(
        F.count("*").alias("respondentes_validos")
    )

    return (
        contagem.join(denominador, on=["edicao", "dimensao"], how="inner")
        .join(totais, on="edicao", how="left")
        .withColumn(
            "percentual",
            F.round(F.col("quantidade") / F.col("respondentes_validos") * 100, 2),
        )
        .withColumn(
            "taxa_resposta",
            F.round(F.col("respondentes_validos") / F.col("total_edicao") * 100, 2),
        )
        .withColumn(
            "fragil",
            F.col("respondentes_validos") < F.lit(config.MINIMO_RESPONDENTES_RECORTE),
        )
        .drop("total_edicao")
    )


def _empilhar(partes: List[DataFrame]) -> DataFrame:
    """Empilha DataFrames pelo nome das colunas.

    Args:
        partes: DataFrames a empilhar. Não pode estar vazio.

    Returns:
        DataFrame resultante da união.

    Raises:
        ValueError: se a lista estiver vazia.
    """
    if not partes:
        raise ValueError("Nenhuma parte para empilhar.")
    resultado = partes[0]
    for parte in partes[1:]:
        resultado = resultado.unionByName(parte, allowMissingColumns=True)
    return resultado


def _distribuicao_rotulada(
    silver: DataFrame,
    dimensao: str,
    rotulo: str,
    cortes: Optional[List[str]] = None,
    aviso: str = SEM_AVISO,
) -> DataFrame:
    """Calcula uma distribuição e a rotula com o nome da métrica.

    Padroniza a saída para que várias distribuições possam ser empilhadas numa
    tabela única, com a coluna `metrica` identificando qual é qual.

    Args:
        silver: DataFrame da camada Silver.
        dimensao: coluna cuja distribuição será calculada.
        rotulo: nome da métrica na saída.
        cortes: colunas adicionais de segmentação.
        aviso: aviso metodológico a anexar.

    Returns:
        DataFrame padronizado com `metrica` e `categoria`.
    """
    agregado = distribuir(silver, dimensao, cortes=cortes)
    resultado = agregado.withColumn("metrica", F.lit(rotulo)).withColumnRenamed(
        dimensao, "categoria"
    )
    return anexar_aviso_metodologico(resultado, aviso)


# ---------------------------------------------------------------------------
# As sete tabelas
# ---------------------------------------------------------------------------


def perfil_mercado(silver: DataFrame) -> DataFrame:
    """Como está estruturado o mercado brasileiro de Dados?

    Distribuição de cargo, senioridade, setor, porte de empresa, situação de
    trabalho e tempo de experiência, por edição.

    Args:
        silver: DataFrame da camada Silver.

    Returns:
        Tabela Gold `perfil_mercado`.
    """
    return _empilhar(
        [
            _distribuicao_rotulada(silver, "cargo_atual", "cargo"),
            _distribuicao_rotulada(
                silver, "nivel_senioridade", "senioridade", aviso=AVISO_SENIORIDADE
            ),
            _distribuicao_rotulada(silver, "setor", "setor"),
            _distribuicao_rotulada(silver, "porte_empresa", "porte_empresa"),
            _distribuicao_rotulada(silver, "situacao_trabalho", "situacao_trabalho"),
            _distribuicao_rotulada(silver, "tempo_exp_dados", "tempo_experiencia_dados"),
            _distribuicao_rotulada(silver, "nivel_ensino", "nivel_ensino"),
            _distribuicao_rotulada(silver, "area_formacao", "area_formacao"),
            _distribuicao_rotulada(silver, "funcao_atuacao", "funcao_atuacao"),
        ]
    )


def remuneracao(silver: DataFrame) -> DataFrame:
    """Quais perfis profissionais são mais valorizados pelo mercado?

    Faixa salarial cruzada com senioridade, região, modelo de trabalho, gênero e
    setor. Inclui o salário médio estimado por recorte, calculado a partir do
    ponto médio das faixas.

    Args:
        silver: DataFrame da camada Silver.

    Returns:
        Tabela Gold `remuneracao`.
    """
    distribuicoes = _empilhar(
        [
            _distribuicao_rotulada(silver, "faixa_salarial", "faixa_salarial_geral"),
            _distribuicao_rotulada(
                silver,
                "faixa_salarial",
                "faixa_salarial_por_senioridade",
                cortes=["nivel_senioridade"],
                aviso=AVISO_SENIORIDADE,
            ),
            _distribuicao_rotulada(
                silver,
                "faixa_salarial",
                "faixa_salarial_por_regiao",
                cortes=["regiao_onde_mora"],
            ),
            _distribuicao_rotulada(
                silver,
                "faixa_salarial",
                "faixa_salarial_por_modelo_trabalho",
                cortes=["modelo_trabalho_atual"],
            ),
            _distribuicao_rotulada(
                silver, "faixa_salarial", "faixa_salarial_por_genero", cortes=["genero"]
            ),
        ]
    )

    # Anexa a ordem da faixa para que gráficos e consultas ordenem por valor e
    # não alfabeticamente.
    ordens = (
        silver.select(
            F.col("faixa_salarial").alias("categoria"),
            F.col("faixa_salarial_ordem").alias("categoria_ordem"),
            "salario_medio_estimado",
        )
        .filter(F.col("faixa_salarial").isNotNull())
        .distinct()
    )

    return distribuicoes.join(ordens, on="categoria", how="left")


def salario_medio_por_recorte(silver: DataFrame) -> DataFrame:
    """Calcula o salário médio estimado por recorte.

    Usa o ponto médio das faixas salariais. É uma aproximação, já que a faixa
    superior é aberta, mas permite comparar recortes de forma direta.

    Args:
        silver: DataFrame da camada Silver.

    Returns:
        DataFrame com `edicao`, `recorte`, `categoria`, `salario_medio`,
        `respondentes_validos` e `fragil`.
    """
    recortes = {
        "senioridade": "nivel_senioridade",
        "regiao": "regiao_onde_mora",
        "genero": "genero",
        "modelo_trabalho": "modelo_trabalho_atual",
        "setor": "setor",
        "cargo": "cargo_atual",
    }

    partes: List[DataFrame] = []
    base = silver.filter(F.col("salario_medio_estimado").isNotNull())

    for rotulo, coluna in recortes.items():
        partes.append(
            base.filter(F.col(coluna).isNotNull())
            .groupBy("edicao", coluna)
            .agg(
                F.round(F.avg("salario_medio_estimado"), 2).alias("salario_medio"),
                F.round(
                    F.expr("percentile_approx(salario_medio_estimado, 0.5)"), 2
                ).alias("salario_mediano"),
                F.count("*").alias("respondentes_validos"),
            )
            .withColumn("recorte", F.lit(rotulo))
            .withColumnRenamed(coluna, "categoria")
        )

    return (
        _empilhar(partes)
        .withColumn(
            "fragil",
            F.col("respondentes_validos") < F.lit(config.MINIMO_RESPONDENTES_RECORTE),
        )
        .orderBy("edicao", "recorte", F.col("salario_medio").desc())
    )


def diversidade(silver: DataFrame) -> DataFrame:
    """Qual é o cenário de diversidade de gênero nas carreiras de dados?

    Distribuição de gênero, cor/raça/etnia e PCD, tanto geral quanto segmentada
    por senioridade e faixa salarial. O cruzamento com senioridade é o que
    revela se a representatividade se mantém nos níveis mais altos.

    Args:
        silver: DataFrame da camada Silver.

    Returns:
        Tabela Gold `diversidade`.
    """
    return _empilhar(
        [
            _distribuicao_rotulada(silver, "genero", "genero_geral"),
            _distribuicao_rotulada(silver, "cor_raca_etnia", "raca_geral"),
            _distribuicao_rotulada(silver, "pcd", "pcd_geral"),
            _distribuicao_rotulada(
                silver,
                "genero",
                "genero_por_senioridade",
                cortes=["nivel_senioridade"],
                aviso=AVISO_SENIORIDADE,
            ),
            _distribuicao_rotulada(
                silver, "genero", "genero_por_faixa_salarial", cortes=["faixa_salarial"]
            ),
            _distribuicao_rotulada(
                silver, "genero", "genero_por_cargo", cortes=["cargo_atual"]
            ),
            _distribuicao_rotulada(
                silver, "cor_raca_etnia", "raca_por_senioridade", cortes=["nivel_senioridade"]
            ),
            _distribuicao_rotulada(
                silver, "genero", "genero_por_regiao", cortes=["regiao_onde_mora"]
            ),
        ]
    )


def tecnologias(
    marcacoes: DataFrame, respondeu: DataFrame, totais: DataFrame
) -> DataFrame:
    """Quais tecnologias apresentam maior adoção entre os profissionais?

    Adoção de linguagem, banco de dados, cloud e ferramenta de BI. Todas são
    perguntas de múltipla escolha, então a soma dos percentuais excede 100%.

    Args:
        marcacoes: tabela longa de marcações multi-escolha.
        respondeu: tabela longa de quem respondeu cada pergunta.
        totais: DataFrame com `edicao` e `total_edicao`.

    Returns:
        Tabela Gold `tecnologias`.
    """
    dimensoes = [
        "linguagem_usada",
        "linguagem_preferida",
        "banco_dados",
        "cloud_dia_a_dia",
        "bi_dia_a_dia",
    ]
    agregado = agregar_multiescolha(marcacoes, respondeu, totais, dimensoes)

    # "linguagem preferida" mudou de natureza em 2025: era escolha única e
    # passou a múltipla escolha. O aviso impede que a série seja lida como
    # contínua.
    return agregado.withColumn(
        "aviso_metodologico",
        F.when(
            F.col("dimensao") == "linguagem_preferida", F.lit(AVISO_LINGUAGEM_PREFERIDA)
        ).otherwise(F.lit(AVISO_MULTIESCOLHA)),
    )


def adocao_ia(
    silver: DataFrame, marcacoes: DataFrame, respondeu: DataFrame, totais: DataFrame
) -> DataFrame:
    """Qual é o índice de adoção de Inteligência Artificial e seu impacto?

    Combina perguntas de escolha única (prioridade declarada, resultados com
    LLMs) e de múltipla escolha (tipo de uso, motivos para não adotar, uso de
    ChatGPT e Copilot).

    Atenção à taxa de resposta: `ia_e_prioridade` e `tipo_uso_ia_empresa` são da
    seção 3, respondida apenas por gestores.

    Args:
        silver: DataFrame da camada Silver.
        marcacoes: tabela longa de marcações multi-escolha.
        respondeu: tabela longa de quem respondeu cada pergunta.
        totais: DataFrame com `edicao` e `total_edicao`.

    Returns:
        Tabela Gold `adocao_ia`.
    """
    escolha_unica = _empilhar(
        [
            _distribuicao_rotulada(
                silver, "ia_e_prioridade", "ia_e_prioridade", aviso=AVISO_SECAO_GESTORES
            ),
            _distribuicao_rotulada(
                silver,
                "resultados_com_llm",
                "resultados_com_llm",
                aviso=AVISO_SECAO_GESTORES,
            ),
        ]
    ).withColumnRenamed("metrica", "dimensao")

    dimensoes_multi = [
        "tipo_uso_ia_empresa",
        "tipo_uso_ia_area",
        "usa_chatgpt_copilot",
        "motivos_nao_usar_ia",
    ]
    multi = agregar_multiescolha(marcacoes, respondeu, totais, dimensoes_multi)
    multi = multi.withColumnRenamed("opcao", "categoria").withColumn(
        "aviso_metodologico",
        F.when(
            F.col("dimensao").isin("tipo_uso_ia_empresa", "motivos_nao_usar_ia"),
            F.concat_ws(" ", F.lit(AVISO_SECAO_GESTORES), F.lit(AVISO_MULTIESCOLHA)),
        ).otherwise(F.lit(AVISO_MULTIESCOLHA)),
    )

    return _empilhar([escolha_unica, multi])


def recortes_comparativos(silver: DataFrame) -> DataFrame:
    """Existem diferenças relevantes entre regiões, senioridades ou modelos?

    Cruza região, senioridade e modelo de trabalho entre si e com a faixa
    salarial, para expor as assimetrias que sustentam recomendações de
    contratação regional e de política de trabalho remoto.

    Args:
        silver: DataFrame da camada Silver.

    Returns:
        Tabela Gold `recortes_comparativos`.
    """
    return _empilhar(
        [
            _distribuicao_rotulada(silver, "regiao_onde_mora", "regiao_geral"),
            _distribuicao_rotulada(
                silver, "modelo_trabalho_atual", "modelo_trabalho_geral"
            ),
            _distribuicao_rotulada(
                silver, "modelo_trabalho_ideal", "modelo_trabalho_ideal"
            ),
            _distribuicao_rotulada(
                silver,
                "nivel_senioridade",
                "senioridade_por_regiao",
                cortes=["regiao_onde_mora"],
                aviso=AVISO_SENIORIDADE,
            ),
            _distribuicao_rotulada(
                silver,
                "modelo_trabalho_atual",
                "modelo_trabalho_por_regiao",
                cortes=["regiao_onde_mora"],
            ),
            _distribuicao_rotulada(
                silver,
                "modelo_trabalho_atual",
                "modelo_trabalho_por_senioridade",
                cortes=["nivel_senioridade"],
                aviso=AVISO_SENIORIDADE,
            ),
            _distribuicao_rotulada(silver, "layoff", "layoff"),
            _distribuicao_rotulada(
                silver, "layoff", "layoff_por_setor", cortes=["setor"]
            ),
            _distribuicao_rotulada(silver, "uf_onde_mora", "uf"),
        ]
    )


def oportunidades_desafios(
    silver: DataFrame, marcacoes: DataFrame, respondeu: DataFrame, totais: DataFrame
) -> DataFrame:
    """Quais oportunidades e desafios existem para quem investe em Dados e IA?

    Combina desafios declarados por gestores, motivos de insatisfação, critérios
    de escolha de emprego, intenção de troca e aspectos de carreira
    prejudicados por características pessoais.

    Args:
        silver: DataFrame da camada Silver.
        marcacoes: tabela longa de marcações multi-escolha.
        respondeu: tabela longa de quem respondeu cada pergunta.
        totais: DataFrame com `edicao` e `total_edicao`.

    Returns:
        Tabela Gold `oportunidades_desafios`.
    """
    escolha_unica = _empilhar(
        [
            _distribuicao_rotulada(silver, "satisfeito_empresa", "satisfeito_empresa"),
            _distribuicao_rotulada(silver, "motivo_insatisfacao", "motivo_insatisfacao"),
            _distribuicao_rotulada(silver, "planos_mudar_6m", "planos_mudar_6m"),
            _distribuicao_rotulada(
                silver, "num_pessoas_dados", "tamanho_time_dados", aviso=AVISO_SECAO_GESTORES
            ),
        ]
    ).withColumnRenamed("metrica", "dimensao")

    dimensoes_multi = ["desafios_gestor", "criterios_escolha", "aspectos_prejudicados"]
    multi = (
        agregar_multiescolha(marcacoes, respondeu, totais, dimensoes_multi)
        .withColumnRenamed("opcao", "categoria")
        .withColumn(
            "aviso_metodologico",
            F.when(
                F.col("dimensao") == "desafios_gestor",
                F.concat_ws(" ", F.lit(AVISO_SECAO_GESTORES), F.lit(AVISO_MULTIESCOLHA)),
            ).otherwise(F.lit(AVISO_MULTIESCOLHA)),
        )
    )

    return _empilhar([escolha_unica, multi])


# ---------------------------------------------------------------------------
# Orquestração
# ---------------------------------------------------------------------------


def construir_tabelas(
    contexto: ContextoExecucao,
    silver: DataFrame,
    marcacoes: DataFrame,
    respondeu: DataFrame,
) -> Dict[str, DataFrame]:
    """Constrói as sete tabelas da camada Gold.

    Args:
        contexto: contexto de execução ativo.
        silver: tabela Silver `respondentes`.
        marcacoes: tabela Silver longa de marcações multi-escolha.
        respondeu: tabela Silver longa de quem respondeu cada pergunta.

    Returns:
        Dicionário `{nome da tabela -> DataFrame}`.
    """
    totais = silver.groupBy("edicao").agg(F.count("*").alias("total_edicao"))

    tabelas = {
        "perfil_mercado": perfil_mercado(silver),
        "remuneracao": remuneracao(silver),
        "salario_medio": salario_medio_por_recorte(silver),
        "diversidade": diversidade(silver),
        "tecnologias": tecnologias(marcacoes, respondeu, totais),
        "adocao_ia": adocao_ia(silver, marcacoes, respondeu, totais),
        "recortes_comparativos": recortes_comparativos(silver),
        "oportunidades_desafios": oportunidades_desafios(
            silver, marcacoes, respondeu, totais
        ),
    }

    for nome in tabelas:
        pergunta = PERGUNTAS_DE_NEGOCIO.get(nome)
        if pergunta:
            contexto.registrar(f"gold/{nome}: {pergunta}")

    return tabelas


def executar(contexto: ContextoExecucao, escrever: bool = True) -> Dict[str, DataFrame]:
    """Executa a transformação Silver -> Gold de ponta a ponta.

    Args:
        contexto: contexto de execução ativo.
        escrever: quando `True`, persiste as tabelas em Parquet.

    Returns:
        Dicionário `{nome da tabela -> DataFrame}`.
    """
    silver = contexto.ler_parquet(config.CAMADA_SILVER, config.TABELA_SILVER).cache()
    marcacoes = contexto.ler_parquet(config.CAMADA_SILVER, TABELA_MULTIESCOLHA).cache()
    respondeu = contexto.ler_parquet(config.CAMADA_SILVER, TABELA_RESPONDEU).cache()

    contexto.registrar(
        f"silver: {silver.count()} respondentes, "
        f"{marcacoes.count()} marcações multi-escolha"
    )

    tabelas = construir_tabelas(contexto, silver, marcacoes, respondeu)

    if escrever:
        for nome, df in tabelas.items():
            contexto.escrever_parquet(df, config.CAMADA_GOLD, nome)

    return tabelas
