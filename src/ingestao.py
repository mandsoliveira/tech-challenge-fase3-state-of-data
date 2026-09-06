"""
Ingestão dos CSVs brutos e validação de integridade.

A validação de contagem existe porque este pipeline depende de números
medidos previamente nos arquivos (5.293 / 5.217 / 3.495 respondentes). Se a
contagem divergir, alguma coisa mudou: arquivo trocado, download incompleto,
ou opção de leitura de CSV incorreta. Nesse caso o pipeline falha em vez de
seguir e produzir agregações sobre base diferente da documentada.

A falha que essa validação protege é silenciosa por natureza. Uma leitura de
CSV mal configurada — separador errado, tratamento de aspas incorreto, ou uma
edição futura com quebra de linha dentro de campo sem `multiLine` — divide ou
funde registros. O pipeline continua rodando, as agregações saem coerentes
entre si, e o número final está errado sem nada acusar.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, Iterable, Optional

from pyspark.sql import DataFrame

from src import config
from src.contexto_execucao import ContextoExecucao
from src.mapeamento_colunas import ANOS, ARQUIVO_BRUTO, ROTULO_EDICAO


class ErroDeIngestao(RuntimeError):
    """Erro de integridade na ingestão dos dados brutos."""


def validar_contagens(ano: int, linhas: int, colunas: int) -> None:
    """Valida a contagem de linhas e colunas de uma edição.

    Args:
        ano: ano de início da edição.
        linhas: quantidade de linhas lidas.
        colunas: quantidade de colunas lidas.

    Raises:
        ErroDeIngestao: se linhas ou colunas divergirem do esperado.
    """
    linhas_esperadas = config.LINHAS_ESPERADAS[ano]
    colunas_esperadas = config.COLUNAS_ESPERADAS[ano]

    if linhas != linhas_esperadas or colunas != colunas_esperadas:
        raise ErroDeIngestao(
            f"Integridade da edição {ROTULO_EDICAO[ano]} não confere.\n"
            f"  esperado: {linhas_esperadas} linhas x {colunas_esperadas} colunas\n"
            f"  obtido  : {linhas} linhas x {colunas} colunas\n"
            f"Causas prováveis: arquivo de origem diferente do documentado, "
            f"download incompleto, ou opção de leitura de CSV incorreta."
        )


def ler_edicao_bruta(
    contexto: ContextoExecucao,
    ano: int,
    caminho: Optional[str] = None,
    validar: bool = True,
) -> DataFrame:
    """Lê o CSV bruto de uma edição e valida sua integridade.

    Args:
        contexto: contexto de execução ativo.
        ano: ano de início da edição (2023, 2024 ou 2025).
        caminho: caminho explícito do arquivo. Quando omitido, resolve a partir
            do diretório de brutos local ou da camada Bronze, conforme o
            ambiente.
        validar: quando `True`, valida linhas e colunas contra o esperado.

    Returns:
        DataFrame com todas as colunas como string, nomes de coluna preservados
        exatamente como na origem.

    Raises:
        ValueError: se o ano não for uma edição conhecida.
        FileNotFoundError: se o arquivo não existir em execução local.
        ErroDeIngestao: se a validação de contagem falhar.
    """
    if ano not in ANOS:
        raise ValueError(f"Edição desconhecida: {ano}. Esperado um de {ANOS}.")

    origem = caminho or _resolver_origem(contexto, ano)

    if not contexto.no_glue and not origem.startswith("s3://"):
        if not Path(origem).exists():
            raise FileNotFoundError(
                f"CSV bruto da edição {ROTULO_EDICAO[ano]} não encontrado.\n"
                f"  esperado em: {origem}\n"
                f"Baixe o dataset do Kaggle e descompacte em "
                f"{config.DIRETORIO_BRUTO}, renomeando para {ARQUIVO_BRUTO[ano]}."
            )

    contexto.registrar(f"lendo {ROTULO_EDICAO[ano]}: {origem}")
    df = contexto.ler_csv(origem)

    linhas, colunas = df.count(), len(df.columns)
    contexto.registrar(f"  {ROTULO_EDICAO[ano]}: {linhas} linhas x {colunas} colunas")

    if validar:
        validar_contagens(ano, linhas, colunas)

    return df


def _resolver_origem(contexto: ContextoExecucao, ano: int) -> str:
    """Resolve o caminho de origem do CSV bruto conforme o ambiente.

    Em execução local, prioriza `data/raw/`, que é onde os arquivos do Kaggle
    são descompactados. No Glue, lê da camada Bronze no S3.

    Args:
        contexto: contexto de execução ativo.
        ano: ano de início da edição.

    Returns:
        Caminho do arquivo CSV bruto.
    """
    if contexto.no_glue:
        return contexto.caminho_bruto(ano)

    candidato_local = config.DIRETORIO_BRUTO / ARQUIVO_BRUTO[ano]
    if candidato_local.exists():
        return str(candidato_local)
    return contexto.caminho_bruto(ano)


def ler_todas_edicoes(
    contexto: ContextoExecucao,
    anos: Optional[Iterable[int]] = None,
    validar: bool = True,
) -> Dict[int, DataFrame]:
    """Lê os CSVs brutos de todas as edições solicitadas.

    Args:
        contexto: contexto de execução ativo.
        anos: edições a ler. Quando omitido, lê as três.
        validar: quando `True`, valida linhas e colunas de cada edição.

    Returns:
        Dicionário `{ano -> DataFrame bruto}`.
    """
    selecionados = tuple(anos) if anos else ANOS
    return {
        ano: ler_edicao_bruta(contexto, ano, validar=validar) for ano in selecionados
    }
