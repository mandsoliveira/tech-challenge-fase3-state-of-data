"""
Ingestão dos CSVs brutos na camada Bronze do S3.

A Bronze é cópia fiel da origem: os arquivos sobem sem qualquer transformação de
conteúdo, nomes de coluna ou tipos. É o que permite reprocessar tudo a partir do
zero e auditar qualquer número do material executivo até o dado original.

O particionamento segue o padrão Hive (`edicao=2023/`), reconhecido
automaticamente pelo Glue Crawler e pelo Athena como coluna de partição.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List

import boto3
import pandas as pd

from src import config
from src.mapeamento_colunas import ANOS, ARQUIVO_BRUTO, ROTULO_EDICAO


class ErroDeIngestaoS3(RuntimeError):
    """Erro na ingestão dos dados brutos no S3."""


def chave_bronze(ano: int) -> str:
    """Monta a chave S3 do arquivo bruto de uma edição.

    Args:
        ano: ano de início da edição.

    Returns:
        Chave do objeto no S3, sem o prefixo `s3://bucket/`.
    """
    return (
        f"{config.CAMADA_BRONZE}/{config.TABELA_BRONZE}/"
        f"edicao={ano}/{ARQUIVO_BRUTO[ano]}"
    )


def validar_arquivos_locais() -> Dict[int, Path]:
    """Confirma que os três CSVs brutos existem e têm as dimensões esperadas.

    A validação acontece antes do upload para evitar subir arquivo truncado ou
    trocado, o que contaminaria toda a análise a jusante.

    Returns:
        Dicionário `{ano -> caminho do arquivo}`.

    Raises:
        ErroDeIngestaoS3: se algum arquivo faltar ou tiver dimensões diferentes
            das documentadas.
    """
    caminhos: Dict[int, Path] = {}
    problemas: List[str] = []

    for ano in ANOS:
        caminho = config.DIRETORIO_BRUTO / ARQUIVO_BRUTO[ano]
        if not caminho.exists():
            problemas.append(f"{ROTULO_EDICAO[ano]}: arquivo ausente em {caminho}")
            continue

        cabecalho = pd.read_csv(caminho, nrows=0, low_memory=False)
        colunas = len(cabecalho.columns)
        # Conta as linhas sem carregar o arquivo inteiro na memória.
        linhas = sum(1 for _ in open(caminho, encoding="utf-8")) - 1

        esperado_colunas = config.COLUNAS_ESPERADAS[ano]
        if colunas != esperado_colunas:
            problemas.append(
                f"{ROTULO_EDICAO[ano]}: {colunas} colunas, esperado {esperado_colunas}"
            )

        print(f"  {ROTULO_EDICAO[ano]}: {colunas} colunas, ~{linhas} linhas físicas")
        caminhos[ano] = caminho

    if problemas:
        raise ErroDeIngestaoS3(
            "Arquivos brutos inválidos:\n  " + "\n  ".join(problemas) + "\n"
            f"Baixe os datasets do Kaggle e descompacte em {config.DIRETORIO_BRUTO}."
        )

    return caminhos


def ingerir() -> Dict[int, str]:
    """Sobe os CSVs brutos para a camada Bronze.

    Returns:
        Dicionário `{ano -> URI S3 do objeto}`.
    """
    s3 = boto3.client("s3", region_name=config.REGIAO)

    print("=" * 78)
    print(f"INGESTÃO BRONZE — s3://{config.NOME_BUCKET}/{config.CAMADA_BRONZE}/")
    print("=" * 78)

    print("\n[validação dos arquivos locais]")
    caminhos = validar_arquivos_locais()

    print("\n[upload]")
    destinos: Dict[int, str] = {}
    for ano, caminho in caminhos.items():
        chave = chave_bronze(ano)
        s3.upload_file(
            str(caminho),
            config.NOME_BUCKET,
            chave,
            # Reforça a criptografia no objeto, além do default do bucket.
            ExtraArgs={"ServerSideEncryption": "AES256"},
        )
        tamanho = caminho.stat().st_size
        destinos[ano] = f"s3://{config.NOME_BUCKET}/{chave}"
        print(f"  {ROTULO_EDICAO[ano]}: {tamanho / 1_048_576:.1f} MB -> {chave}")

    print("\n[conferência no S3]")
    resposta = s3.list_objects_v2(
        Bucket=config.NOME_BUCKET,
        Prefix=f"{config.CAMADA_BRONZE}/{config.TABELA_BRONZE}/",
    )
    for objeto in resposta.get("Contents", []):
        print(f"  {objeto['Size'] / 1_048_576:6.1f} MB  {objeto['Key']}")

    print("\n" + "=" * 78)
    print(f"Bronze ingerida: {len(destinos)} edições.")
    print("=" * 78)

    return destinos


def main() -> None:
    """Ponto de entrada da ingestão."""
    ingerir()


if __name__ == "__main__":
    main()
