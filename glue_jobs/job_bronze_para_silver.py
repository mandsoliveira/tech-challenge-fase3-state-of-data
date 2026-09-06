"""
Glue Job: Bronze -> Silver.

Harmoniza as três edições do State of Data em duas tabelas Silver:

    silver/respondentes            41 dimensões canônicas, uma linha por respondente
    silver/respostas_multiescolha  formato longo, uma linha por opção marcada
    silver/respondeu_multiescolha  denominador das perguntas multi-escolha

Este arquivo roda sem alteração em dois ambientes. Localmente:

    export JAVA_HOME=/opt/homebrew/opt/openjdk@17
    .venv-spark/bin/python -m glue_jobs.job_bronze_para_silver

No Glue, como script de um job `glueetl`. A detecção de ambiente é feita pelo
`ContextoExecucao`, e a lógica de transformação é idêntica nos dois casos.
"""

from __future__ import annotations

import sys
from typing import Dict, List, Optional


def _parametros_glue() -> Dict[str, str]:
    """Lê os parâmetros do Glue Job, se estiver rodando no Glue.

    Returns:
        Dicionário com os parâmetros reconhecidos. Vazio em execução local.
    """
    try:
        from awsglue.utils import getResolvedOptions  # noqa: PLC0415
    except ImportError:
        return {}

    opcionais = ["raiz_lake", "edicoes"]
    presentes = [nome for nome in opcionais if f"--{nome}" in sys.argv]
    reconhecidos = getResolvedOptions(sys.argv, ["JOB_NAME", *presentes])
    return reconhecidos


def _parametros_locais() -> Dict[str, str]:
    """Lê os parâmetros da linha de comando em execução local.

    Returns:
        Dicionário com os parâmetros informados.
    """
    import argparse  # noqa: PLC0415

    analisador = argparse.ArgumentParser(description="Bronze -> Silver")
    analisador.add_argument("--raiz_lake", default=None, help="Raiz do Data Lake.")
    analisador.add_argument(
        "--edicoes", default=None, help="Edições a processar, separadas por vírgula."
    )
    argumentos, _ = analisador.parse_known_args()
    return {
        chave: valor
        for chave, valor in vars(argumentos).items()
        if valor is not None
    }


def _resolver_edicoes(valor: Optional[str]) -> Optional[List[int]]:
    """Converte a lista de edições informada por parâmetro em inteiros.

    Args:
        valor: edições separadas por vírgula, ou None.

    Returns:
        Lista de anos, ou None para processar todas.
    """
    if not valor:
        return None
    return [int(parte.strip()) for parte in valor.split(",") if parte.strip()]


def main() -> None:
    """Executa a transformação Bronze -> Silver."""
    from src import config  # noqa: PLC0415
    from src.contexto_execucao import ContextoExecucao  # noqa: PLC0415
    from src.ingestao import ler_todas_edicoes  # noqa: PLC0415
    from src.transformacoes import bronze_para_silver, multiescolha  # noqa: PLC0415

    parametros = _parametros_glue() or _parametros_locais()
    edicoes = _resolver_edicoes(parametros.get("edicoes"))

    contexto = ContextoExecucao(
        nome_aplicacao="sod-bronze-para-silver",
        raiz_lake=parametros.get("raiz_lake"),
    )

    try:
        metadados = contexto.registrar_ambiente()

        # Os brutos são lidos uma única vez e reaproveitados pelas duas
        # transformações, evitando reprocessar a leitura de CSV.
        brutos = ler_todas_edicoes(contexto, edicoes)

        silver = bronze_para_silver.harmonizar(contexto, brutos)
        silver = silver.cache()
        contexto.escrever_parquet(
            silver, config.CAMADA_SILVER, config.TABELA_SILVER, particoes=["edicao"]
        )

        marcacoes, respondeu = multiescolha.executar(contexto, brutos)

        contexto.registrar(
            f"concluído: {silver.count()} respondentes, "
            f"{marcacoes.count()} marcações multi-escolha, "
            f"Spark {metadados['versao_spark']}"
        )
    finally:
        contexto.encerrar()


if __name__ == "__main__":
    main()
