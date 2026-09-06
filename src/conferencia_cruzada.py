"""
Conferência cruzada da camada Silver contra o cálculo direto em pandas.

POR QUE EXISTE
--------------
Todas as validações internas do pipeline (contagem de linhas, quantidade de
faixas, consistência de dimensões) verificam a INTEGRIDADE do processamento.
Nenhuma delas verifica se o mapeamento semântico apontou para a coluna CERTA.

Se `cloud_preferida` da edição 2023 estivesse mapeada para a coluna errada, o
pipeline rodaria sem erro, a Silver teria 14.005 registros, as 13 faixas
salariais estariam corretas — e o material executivo apresentaria a
distribuição de cloud errada com total confiança.

Este módulo é a defesa contra isso. Ele recalcula distribuições diretamente dos
CSVs brutos com pandas, por caminho independente do pipeline Spark, e compara
com o que a Silver produziu. Divergência aqui significa mapeamento errado.

O valor da verificação vem justamente de usar uma ferramenta e um caminho de
código diferentes: se ambos chegam ao mesmo número, o erro teria que estar
presente nas duas implementações de forma idêntica.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import pandas as pd

from src import config
from src.dominio import CORRECOES_FAIXA_SALARIAL
from src.mapeamento_colunas import ANOS, ARQUIVO_BRUTO, ROTULO_EDICAO, resolver_colunas

# Dimensões conferidas por padrão. Priorizam as afetadas por deslocamento de
# código, que são as de maior risco de mapeamento incorreto.
DIMENSOES_CONFERIDAS: Tuple[str, ...] = (
    "genero",
    "regiao_onde_mora",
    "nivel_senioridade",
    "faixa_salarial",
    "modelo_trabalho_atual",  # deslocada em 2025
    "layoff",                 # deslocada em 2025
    "linguagem_preferida",    # deslocada em 2025
    "cloud_preferida",        # deslocada em 2025, rótulo enganoso em 2023
    "cloud_dia_a_dia",        # deslocada em 2025, rótulo errado na origem 2023
    "usa_chatgpt_copilot",    # deslocada em 2025
    "ia_e_prioridade",
    "motivos_nao_usar_ia",    # deslocada em 2025
)


class DivergenciaDeConferencia(RuntimeError):
    """A Silver divergiu do cálculo independente em pandas."""


def _distribuicao_pandas(ano: int, dimensao: str) -> Optional[Dict[str, int]]:
    """Calcula a distribuição de uma dimensão direto do CSV bruto com pandas.

    Args:
        ano: ano de início da edição.
        dimensao: nome canônico da dimensão.

    Returns:
        Dicionário `{valor -> contagem}`, ou None se a dimensão não existir na
        edição.
    """
    caminho = config.DIRETORIO_BRUTO / ARQUIVO_BRUTO[ano]
    cabecalho = list(pd.read_csv(caminho, nrows=0, low_memory=False).columns)
    coluna = resolver_colunas(cabecalho, ano)[dimensao]
    if coluna is None:
        return None

    serie = pd.read_csv(caminho, usecols=[coluna], low_memory=False)[coluna]

    # Aplica as mesmas correções de typo que o pipeline aplica, senão a
    # comparação acusaria divergência causada pela própria correção.
    if dimensao == "faixa_salarial":
        serie = serie.replace(CORRECOES_FAIXA_SALARIAL)

    return serie.value_counts(dropna=True).to_dict()


def _distribuicao_silver(
    silver: pd.DataFrame, ano: int, dimensao: str
) -> Optional[Dict[str, int]]:
    """Calcula a distribuição de uma dimensão a partir da Silver.

    Args:
        silver: Silver materializada como DataFrame pandas.
        ano: ano de início da edição.
        dimensao: nome canônico da dimensão.

    Returns:
        Dicionário `{valor -> contagem}`, ou None se a coluna não existir.
    """
    if dimensao not in silver.columns:
        return None
    recorte = silver.loc[silver["edicao"] == ano, dimensao]
    return recorte.value_counts(dropna=True).to_dict()


def conferir(
    silver: pd.DataFrame,
    dimensoes: Optional[Sequence[str]] = None,
    anos: Optional[Sequence[int]] = None,
    verboso: bool = True,
) -> List[str]:
    """Compara as distribuições da Silver com o cálculo direto em pandas.

    Args:
        silver: Silver materializada como DataFrame pandas.
        dimensoes: dimensões a conferir. Quando omitido, usa
            `DIMENSOES_CONFERIDAS`.
        anos: edições a conferir. Quando omitido, confere as três.
        verboso: quando `True`, imprime o resultado de cada conferência.

    Returns:
        Lista de descrições das divergências encontradas. Vazia quando tudo
        confere.
    """
    alvo_dimensoes = tuple(dimensoes) if dimensoes else DIMENSOES_CONFERIDAS
    alvo_anos = tuple(anos) if anos else ANOS
    divergencias: List[str] = []

    if verboso:
        print("=" * 92)
        print("CONFERÊNCIA CRUZADA — Silver (Spark) versus cálculo direto (pandas)")
        print("=" * 92)

    for dimensao in alvo_dimensoes:
        if verboso:
            print(f"\n[{dimensao}]")

        for ano in alvo_anos:
            esperado = _distribuicao_pandas(ano, dimensao)
            obtido = _distribuicao_silver(silver, ano, dimensao)

            if esperado is None:
                if verboso:
                    print(f"    {ROTULO_EDICAO[ano]:10} — ausente nesta edição")
                # Se a dimensão não existe na origem, a Silver deve estar vazia.
                if obtido:
                    divergencias.append(
                        f"{dimensao}/{ROTULO_EDICAO[ano]}: ausente na origem, "
                        f"mas a Silver tem {sum(obtido.values())} valores"
                    )
                continue

            if obtido is None:
                divergencias.append(f"{dimensao}: coluna ausente na Silver")
                continue

            if esperado == obtido:
                total = sum(obtido.values())
                distintos = len(obtido)
                if verboso:
                    print(
                        f"    {ROTULO_EDICAO[ano]:10} OK   "
                        f"{total} respostas, {distintos} valores distintos"
                    )
                continue

            somente_pandas = {
                chave: valor for chave, valor in esperado.items() if obtido.get(chave) != valor
            }
            somente_silver = {
                chave: valor for chave, valor in obtido.items() if esperado.get(chave) != valor
            }
            descricao = (
                f"{dimensao}/{ROTULO_EDICAO[ano]}: divergência. "
                f"pandas={list(somente_pandas.items())[:3]} "
                f"silver={list(somente_silver.items())[:3]}"
            )
            divergencias.append(descricao)
            if verboso:
                print(f"    {ROTULO_EDICAO[ano]:10} DIVERGE")
                print(f"        só em pandas: {list(somente_pandas.items())[:3]}")
                print(f"        só em silver: {list(somente_silver.items())[:3]}")

    if verboso:
        print("\n" + "=" * 92)
        if divergencias:
            print(f"DIVERGÊNCIAS: {len(divergencias)}")
            for item in divergencias:
                print(f"  - {item}")
        else:
            print("Nenhuma divergência. O mapeamento semântico está correto para as")
            print("dimensões conferidas, incluindo todas as afetadas por deslocamento.")
        print("=" * 92)

    return divergencias


def carregar_silver_local() -> pd.DataFrame:
    """Carrega a Silver local em pandas a partir do Parquet.

    Returns:
        Silver como DataFrame pandas.

    Raises:
        FileNotFoundError: se a Silver não tiver sido materializada.
    """
    caminho = Path(config.caminho_local(config.CAMADA_SILVER, config.TABELA_SILVER))
    if not caminho.exists():
        raise FileNotFoundError(
            f"Silver não encontrada em {caminho}. "
            f"Execute a transformação Bronze -> Silver antes da conferência."
        )
    return pd.read_parquet(caminho)


def main() -> None:
    """Executa a conferência cruzada sobre a Silver local."""
    silver = carregar_silver_local()
    print(f"Silver carregada: {len(silver)} registros, {len(silver.columns)} colunas\n")
    divergencias = conferir(silver)
    raise SystemExit(1 if divergencias else 0)


if __name__ == "__main__":
    main()
