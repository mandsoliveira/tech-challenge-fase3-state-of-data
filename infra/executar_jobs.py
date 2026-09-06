"""
Criação, execução e coleta de evidências dos Glue Jobs.

FLUXO
-----
    1. Empacota `src/` num zip e sobe para o S3 (dependência dos jobs)
    2. Sobe os scripts de entrypoint
    3. Cria ou atualiza os dois Glue Jobs
    4. Executa em sequência: Bronze -> Silver, depois Silver -> Gold
    5. Coleta a evidência de execução

POR QUE O ZIP
-------------
O Glue executa apenas o script de entrypoint. Os módulos de `src/` precisam ser
enviados via `--extra-py-files`, que aceita um zip contendo o pacote. É isso que
permite que o mesmo código validado localmente rode no job, sem duplicação.

EVIDÊNCIA DE EXECUÇÃO
---------------------
O enunciado pede demonstração do uso efetivo dos serviços AWS. A evidência
coletada inclui identificador da execução, horários, duração, DPU consumida,
contagem de objetos gerados por camada e o estado final de cada job. É gravada
em JSON versionado.
"""

from __future__ import annotations

import io
import json
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

import boto3
from botocore.exceptions import ClientError

from src import config

PREFIXO_SCRIPTS = "scripts"
NOME_ZIP_DEPENDENCIAS = "src.zip"

# Estados terminais de uma execução de Glue Job.
ESTADOS_FINAIS = ("SUCCEEDED", "FAILED", "TIMEOUT", "STOPPED", "ERROR")

JOBS = (
    (config.NOME_JOB_SILVER, "glue_jobs/job_bronze_para_silver.py"),
    (config.NOME_JOB_GOLD, "glue_jobs/job_silver_para_gold.py"),
)


def _cliente(servico: str):
    """Cria um cliente boto3 na região do projeto."""
    return boto3.client(servico, region_name=config.REGIAO)


# ---------------------------------------------------------------------------
# Empacotamento e upload
# ---------------------------------------------------------------------------


def empacotar_src() -> bytes:
    """Empacota o pacote `src` num zip em memória.

    Preserva a estrutura de diretórios a partir da raiz do projeto, para que
    `from src import config` funcione dentro do job. Arquivos de cache são
    excluídos.

    Returns:
        Conteúdo do zip.
    """
    buffer = io.BytesIO()
    raiz = config.RAIZ_PROJETO

    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as arquivo:
        for caminho in sorted((raiz / "src").rglob("*.py")):
            if "__pycache__" in caminho.parts:
                continue
            arquivo.write(caminho, caminho.relative_to(raiz))

    buffer.seek(0)
    return buffer.read()


def subir_artefatos(s3) -> Dict[str, str]:
    """Sobe o zip de dependências e os scripts dos jobs para o S3.

    Args:
        s3: cliente boto3 do S3.

    Returns:
        Dicionário com as URIs dos artefatos enviados.
    """
    uris: Dict[str, str] = {}

    conteudo_zip = empacotar_src()
    chave_zip = f"{PREFIXO_SCRIPTS}/{NOME_ZIP_DEPENDENCIAS}"
    s3.put_object(
        Bucket=config.NOME_BUCKET,
        Key=chave_zip,
        Body=conteudo_zip,
        ServerSideEncryption="AES256",
    )
    uris["dependencias"] = f"s3://{config.NOME_BUCKET}/{chave_zip}"
    print(f"  {len(conteudo_zip) / 1024:.1f} KB -> {chave_zip}")

    for _, caminho_relativo in JOBS:
        origem = config.RAIZ_PROJETO / caminho_relativo
        chave = f"{PREFIXO_SCRIPTS}/{origem.name}"
        s3.put_object(
            Bucket=config.NOME_BUCKET,
            Key=chave,
            Body=origem.read_bytes(),
            ServerSideEncryption="AES256",
        )
        uris[origem.name] = f"s3://{config.NOME_BUCKET}/{chave}"
        print(f"  {origem.stat().st_size / 1024:.1f} KB -> {chave}")

    return uris


# ---------------------------------------------------------------------------
# Criação dos jobs
# ---------------------------------------------------------------------------


def _definicao_job(nome: str, nome_script: str, arn_role: str) -> Dict:
    """Monta a definição de um Glue Job.

    Args:
        nome: nome do job.
        nome_script: nome do arquivo de script no prefixo de scripts.
        arn_role: ARN da IAM role do job.

    Returns:
        Dicionário com os campos aceitos por `create_job` e `update_job`.
    """
    return {
        "Role": arn_role,
        "Command": {
            "Name": "glueetl",
            "ScriptLocation": f"s3://{config.NOME_BUCKET}/{PREFIXO_SCRIPTS}/{nome_script}",
            "PythonVersion": "3",
        },
        "DefaultArguments": {
            "--extra-py-files": (
                f"s3://{config.NOME_BUCKET}/{PREFIXO_SCRIPTS}/{NOME_ZIP_DEPENDENCIAS}"
            ),
            "--raiz_lake": f"s3://{config.NOME_BUCKET}",
            "--job-language": "python",
            "--enable-metrics": "true",
            "--enable-continuous-cloudwatch-log": "true",
            # Desabilita o bookmark: o pipeline é idempotente e reprocessa tudo,
            # então rastrear estado entre execuções só criaria confusão.
            "--job-bookmark-option": "job-bookmark-disable",
            "--TempDir": f"s3://{config.NOME_BUCKET}/temp/",
        },
        "GlueVersion": config.VERSAO_GLUE,
        "WorkerType": config.TIPO_WORKER,
        "NumberOfWorkers": config.NUMERO_WORKERS,
        # 42 MB de dados. O timeout curto evita que um job travado acumule custo.
        "Timeout": 30,
        "MaxRetries": 0,
        "Description": f"Tech Challenge Fase 3 — {nome}",
    }


def criar_ou_atualizar_job(glue, nome: str, nome_script: str, arn_role: str) -> None:
    """Cria o Glue Job, ou atualiza sua definição se já existir.

    Args:
        glue: cliente boto3 do Glue.
        nome: nome do job.
        nome_script: nome do arquivo de script.
        arn_role: ARN da IAM role.
    """
    definicao = _definicao_job(nome, nome_script, arn_role)
    try:
        glue.create_job(Name=nome, **definicao)
        print(f"  job {nome} criado ({config.TIPO_WORKER} x{config.NUMERO_WORKERS})")
    except ClientError as erro:
        if erro.response["Error"]["Code"] != "AlreadyExistsException":
            raise
        glue.update_job(JobName=nome, JobUpdate=definicao)
        print(f"  job {nome} atualizado ({config.TIPO_WORKER} x{config.NUMERO_WORKERS})")


# ---------------------------------------------------------------------------
# Execução
# ---------------------------------------------------------------------------


def executar_job(glue, nome: str, timeout_segundos: int = 1800) -> Dict:
    """Dispara um Glue Job e aguarda sua conclusão.

    Args:
        glue: cliente boto3 do Glue.
        nome: nome do job.
        timeout_segundos: tempo máximo de espera.

    Returns:
        Dicionário com os dados da execução, incluindo estado final, duração e
        DPU consumida.

    Raises:
        TimeoutError: se a execução não terminar dentro do tempo limite.
        RuntimeError: se o job terminar em estado diferente de SUCCEEDED.
    """
    inicio = glue.start_job_run(JobName=nome)
    id_execucao = inicio["JobRunId"]
    print(f"  {nome}: execução {id_execucao} iniciada")

    limite = time.time() + timeout_segundos
    estado = "STARTING"
    execucao: Dict = {}

    while time.time() < limite:
        execucao = glue.get_job_run(JobName=nome, RunId=id_execucao)["JobRun"]
        estado = execucao["JobRunState"]
        if estado in ESTADOS_FINAIS:
            break
        time.sleep(15)
    else:
        raise TimeoutError(
            f"{nome}: execução {id_execucao} não terminou em {timeout_segundos}s "
            f"(último estado: {estado})."
        )

    duracao = execucao.get("ExecutionTime", 0)
    dpu = execucao.get("DPUSeconds")
    print(f"  {nome}: {estado} em {duracao}s" + (f", {dpu} DPU-s" if dpu else ""))

    if estado != "SUCCEEDED":
        mensagem = execucao.get("ErrorMessage", "sem mensagem de erro")
        raise RuntimeError(
            f"{nome}: execução {id_execucao} terminou como {estado}.\n"
            f"  {mensagem}\n"
            f"  Log: /aws-glue/jobs/output, stream {id_execucao}"
        )

    return {
        "job": nome,
        "id_execucao": id_execucao,
        "estado": estado,
        "iniciado_em": _formatar_instante(execucao.get("StartedOn")),
        "concluido_em": _formatar_instante(execucao.get("CompletedOn")),
        "duracao_segundos": duracao,
        "dpu_segundos": dpu,
        "versao_glue": execucao.get("GlueVersion"),
        "tipo_worker": execucao.get("WorkerType"),
        "numero_workers": execucao.get("NumberOfWorkers"),
    }


def _formatar_instante(valor) -> Optional[str]:
    """Formata um datetime da API em ISO 8601, tolerando None."""
    return valor.isoformat() if valor else None


# ---------------------------------------------------------------------------
# Evidência
# ---------------------------------------------------------------------------


def inventariar_camada(s3, camada: str) -> Dict:
    """Lista os objetos de uma camada do Data Lake.

    Args:
        s3: cliente boto3 do S3.
        camada: nome da camada.

    Returns:
        Dicionário com quantidade de objetos, tamanho total e amostra de chaves.
    """
    paginador = s3.get_paginator("list_objects_v2")
    chaves: List[str] = []
    tamanho_total = 0

    for pagina in paginador.paginate(Bucket=config.NOME_BUCKET, Prefix=f"{camada}/"):
        for objeto in pagina.get("Contents", []):
            chaves.append(objeto["Key"])
            tamanho_total += objeto["Size"]

    return {
        "camada": camada,
        "objetos": len(chaves),
        "tamanho_mb": round(tamanho_total / 1_048_576, 2),
        "amostra": chaves[:10],
    }


def coletar_evidencia(s3, execucoes: List[Dict]) -> Dict:
    """Consolida a evidência de execução na AWS.

    Args:
        s3: cliente boto3 do S3.
        execucoes: dados das execuções dos jobs.

    Returns:
        Dicionário com a evidência consolidada.
    """
    return {
        "coletado_em": datetime.now(timezone.utc).isoformat(),
        "conta": config.ID_CONTA,
        "regiao": config.REGIAO,
        "bucket": config.NOME_BUCKET,
        "database_glue": config.NOME_DATABASE_GLUE,
        "execucoes": execucoes,
        "camadas": [
            inventariar_camada(s3, camada)
            for camada in (config.CAMADA_BRONZE, config.CAMADA_SILVER, config.CAMADA_GOLD)
        ],
    }


def gravar_evidencia(evidencia: Dict) -> Path:
    """Grava a evidência em JSON no diretório de saídas.

    Args:
        evidencia: evidência consolidada.

    Returns:
        Caminho do arquivo gravado.
    """
    config.DIRETORIO_EVIDENCIAS.mkdir(parents=True, exist_ok=True)
    destino = config.DIRETORIO_EVIDENCIAS / "execucao_glue.json"
    destino.write_text(json.dumps(evidencia, indent=2, ensure_ascii=False), encoding="utf-8")
    return destino


# ---------------------------------------------------------------------------
# Orquestração
# ---------------------------------------------------------------------------


def main() -> None:
    """Cria, executa os jobs e coleta a evidência."""
    s3 = _cliente("s3")
    glue = _cliente("glue")
    iam = _cliente("iam")

    arn_role = iam.get_role(RoleName=config.NOME_ROLE_GLUE)["Role"]["Arn"]

    print("=" * 78)
    print("GLUE JOBS — criação e execução")
    print("=" * 78)

    print("\n[upload dos artefatos]")
    subir_artefatos(s3)

    print("\n[criação dos jobs]")
    for nome, caminho in JOBS:
        criar_ou_atualizar_job(glue, nome, Path(caminho).name, arn_role)

    print("\n[execução]")
    execucoes: List[Dict] = []
    for nome, _ in JOBS:
        execucoes.append(executar_job(glue, nome))

    print("\n[evidência]")
    evidencia = coletar_evidencia(s3, execucoes)
    for camada in evidencia["camadas"]:
        print(
            f"  {camada['camada']:8} {camada['objetos']:4} objetos, "
            f"{camada['tamanho_mb']:8.2f} MB"
        )

    destino = gravar_evidencia(evidencia)
    print(f"\n  evidência gravada em {destino.relative_to(config.RAIZ_PROJETO)}")

    total_dpu = sum(e.get("dpu_segundos") or 0 for e in execucoes)
    if total_dpu:
        # Glue 5.0 a US$ 0,44 por DPU-hora.
        custo = total_dpu / 3600 * 0.44
        print(f"  DPU total: {total_dpu:.0f} DPU-s (~US$ {custo:.3f})")

    print("\n" + "=" * 78)
    print("Jobs executados com sucesso na AWS.")
    print("=" * 78)


if __name__ == "__main__":
    main()
