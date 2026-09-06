"""
Configuração central do projeto Tech Challenge Fase 3.

Concentra identificadores de recursos AWS, caminhos e valores esperados de
validação. Nenhum módulo deve repetir esses valores por conta própria.

As contagens em `LINHAS_ESPERADAS` e `COLUNAS_ESPERADAS` não são estimativas:
foram medidas nos arquivos brutos com pandas e reconferidas com Spark. Elas
funcionam como asserção de integridade da ingestão — se o número mudar, algo
aconteceu com o arquivo de origem e o pipeline deve falhar em vez de seguir.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, Final

# ---------------------------------------------------------------------------
# AWS
# ---------------------------------------------------------------------------

ID_CONTA: Final[str] = "242201276836"
REGIAO: Final[str] = "us-east-1"

# Bucket único do Data Lake, com separação lógica por prefixo de camada.
NOME_BUCKET: Final[str] = f"sod-fase3-datalake-{ID_CONTA}"

NOME_DATABASE_GLUE: Final[str] = "sod_fase3"
NOME_ROLE_GLUE: Final[str] = "sod-fase3-glue-role"
NOME_CRAWLER: Final[str] = "sod-fase3-crawler"

NOME_JOB_SILVER: Final[str] = "sod-fase3-bronze-para-silver"
NOME_JOB_GOLD: Final[str] = "sod-fase3-silver-para-gold"

# Glue 5.0 = Spark 3.5.4, Python 3.11, Java 17. Escolhido por já estar
# validado nesta conta e por haver PySpark local correspondente instalado.
VERSAO_GLUE: Final[str] = "5.0"
TIPO_WORKER: Final[str] = "G.1X"
# 2 é o mínimo permitido para jobs glueetl. São ~42 MB de dados: mais workers
# só aumentariam custo e tempo de startup sem ganho.
NUMERO_WORKERS: Final[int] = 2

PREFIXO_RESULTADOS_ATHENA: Final[str] = "athena-results"

# ---------------------------------------------------------------------------
# Caminhos locais
# ---------------------------------------------------------------------------

RAIZ_PROJETO: Final[Path] = Path(__file__).resolve().parent.parent
DIRETORIO_BRUTO: Final[Path] = RAIZ_PROJETO / "data" / "raw"
RAIZ_LAKE_LOCAL: Final[Path] = RAIZ_PROJETO / "data" / "lake"
DIRETORIO_IMAGENS: Final[Path] = RAIZ_PROJETO / "output" / "img"
DIRETORIO_EVIDENCIAS: Final[Path] = RAIZ_PROJETO / "output" / "evidencias"

# ---------------------------------------------------------------------------
# Camadas e tabelas
# ---------------------------------------------------------------------------

CAMADA_BRONZE: Final[str] = "bronze"
CAMADA_SILVER: Final[str] = "silver"
CAMADA_GOLD: Final[str] = "gold"

TABELA_BRONZE: Final[str] = "state_of_data"
TABELA_SILVER: Final[str] = "respondentes"

# Tabelas da Gold. As sete primeiras correspondem às sete perguntas de negócio
# do enunciado; `salario_medio` é auxiliar, derivada do ponto médio das faixas.
TABELAS_GOLD: Final[tuple[str, ...]] = (
    "perfil_mercado",
    "remuneracao",
    "salario_medio",
    "diversidade",
    "tecnologias",
    "adocao_ia",
    "recortes_comparativos",
    "oportunidades_desafios",
)

# Tabelas da Silver.
TABELAS_SILVER: Final[tuple[str, ...]] = (
    "respondentes",
    "respostas_multiescolha",
    "respondeu_multiescolha",
)

# ---------------------------------------------------------------------------
# Validação da ingestão
# ---------------------------------------------------------------------------

LINHAS_ESPERADAS: Final[Dict[int, int]] = {2023: 5293, 2024: 5217, 2025: 3495}
COLUNAS_ESPERADAS: Final[Dict[int, int]] = {2023: 399, 2024: 403, 2025: 388}

TOTAL_RESPONDENTES_ESPERADO: Final[int] = sum(LINHAS_ESPERADAS.values())  # 14005

# Abaixo deste número de respondentes válidos, um recorte é estatisticamente
# frágil e deve ser sinalizado em vez de apresentado como conclusão.
MINIMO_RESPONDENTES_RECORTE: Final[int] = 30

# ---------------------------------------------------------------------------
# Spark local
# ---------------------------------------------------------------------------

# O default de 200 partições de shuffle produz centenas de arquivos minúsculos
# sobre um volume de dezenas de MB, tornando a execução local mais lenta.
PARTICOES_SHUFFLE_LOCAL: Final[int] = 4

# Opções de leitura de CSV verificadas contra as três edições: com elas o
# Spark produz exatamente a mesma contagem de linhas e colunas que o pandas.
#
# Sobre `multiLine`: foi medido que estas três edições NÃO contêm quebras de
# linha dentro de campos — a contagem é idêntica com e sem a opção. Ela é
# mantida como defesa para edições futuras, onde uma resposta aberta com
# quebra de linha dividiria um respondente em vários registros sem nenhum erro
# visível. O custo é que o Spark não paraleliza a leitura dentro de um mesmo
# arquivo, irrelevante para arquivos de ~15 MB.
OPCOES_LEITURA_CSV: Final[Dict[str, object]] = {
    "header": True,
    "multiLine": True,
    "quote": '"',
    "escape": '"',
}


def caminho_s3(camada: str, tabela: str = "") -> str:
    """Monta o URI S3 de uma camada ou tabela do Data Lake.

    Args:
        camada: nome da camada (`bronze`, `silver` ou `gold`).
        tabela: nome da tabela dentro da camada. Se vazio, retorna a raiz da
            camada.

    Returns:
        URI no formato `s3://<bucket>/<camada>/<tabela>`, sem barra final.
    """
    sufixo = f"/{tabela}" if tabela else ""
    return f"s3://{NOME_BUCKET}/{camada}{sufixo}"


def caminho_local(camada: str, tabela: str = "") -> str:
    """Monta o caminho local equivalente a uma camada ou tabela do Data Lake.

    Args:
        camada: nome da camada (`bronze`, `silver` ou `gold`).
        tabela: nome da tabela dentro da camada. Se vazio, retorna a raiz da
            camada.

    Returns:
        Caminho absoluto no sistema de arquivos local.
    """
    destino = RAIZ_LAKE_LOCAL / camada
    if tabela:
        destino = destino / tabela
    return str(destino)


def raiz_lake_padrao(no_glue: bool) -> str:
    """Devolve a raiz do Data Lake apropriada ao ambiente.

    Permite sobrescrita pela variável de ambiente `SOD_RAIZ_LAKE`, útil para
    apontar uma execução local para o S3 ou para um diretório alternativo.

    Args:
        no_glue: `True` quando a execução ocorre em um Glue Job.

    Returns:
        Raiz do Data Lake, como URI S3 ou caminho local.
    """
    sobrescrita = os.environ.get("SOD_RAIZ_LAKE")
    if sobrescrita:
        return sobrescrita.rstrip("/")
    return f"s3://{NOME_BUCKET}" if no_glue else str(RAIZ_LAKE_LOCAL)
