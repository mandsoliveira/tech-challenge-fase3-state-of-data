"""
Glue Job: Silver -> Gold.

Produz as tabelas agregadas da camada Gold, uma por pergunta de negócio do
enunciado, mais a tabela auxiliar de salário médio por recorte.

Roda sem alteração local e no Glue. Localmente:

    export JAVA_HOME=/opt/homebrew/opt/openjdk@17
    .venv-spark/bin/python -m glue_jobs.job_silver_para_gold
"""

from __future__ import annotations

import sys
from typing import Dict


def _parametros_glue() -> Dict[str, str]:
    """Lê os parâmetros do Glue Job, se estiver rodando no Glue.

    Returns:
        Dicionário com os parâmetros reconhecidos. Vazio em execução local.
    """
    try:
        from awsglue.utils import getResolvedOptions  # noqa: PLC0415
    except ImportError:
        return {}

    presentes = [nome for nome in ["raiz_lake"] if f"--{nome}" in sys.argv]
    return getResolvedOptions(sys.argv, ["JOB_NAME", *presentes])


def _parametros_locais() -> Dict[str, str]:
    """Lê os parâmetros da linha de comando em execução local.

    Returns:
        Dicionário com os parâmetros informados.
    """
    import argparse  # noqa: PLC0415

    analisador = argparse.ArgumentParser(description="Silver -> Gold")
    analisador.add_argument("--raiz_lake", default=None, help="Raiz do Data Lake.")
    argumentos, _ = analisador.parse_known_args()
    return {c: v for c, v in vars(argumentos).items() if v is not None}


def main() -> None:
    """Executa a transformação Silver -> Gold."""
    from src.contexto_execucao import ContextoExecucao  # noqa: PLC0415
    from src.transformacoes import silver_para_gold  # noqa: PLC0415

    parametros = _parametros_glue() or _parametros_locais()

    contexto = ContextoExecucao(
        nome_aplicacao="sod-silver-para-gold",
        raiz_lake=parametros.get("raiz_lake"),
    )

    try:
        metadados = contexto.registrar_ambiente()
        tabelas = silver_para_gold.executar(contexto)
        contexto.registrar(
            f"concluído: {len(tabelas)} tabelas Gold, Spark {metadados['versao_spark']}"
        )
    finally:
        contexto.encerrar()


if __name__ == "__main__":
    main()
