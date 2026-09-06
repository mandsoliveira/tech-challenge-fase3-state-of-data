"""
Catalogação das camadas Silver e Gold no Glue Data Catalog via Crawler.

POR QUE UM CRAWLER
------------------
O Crawler infere o schema dos Parquet e registra as partições automaticamente.
A alternativa seria declarar cada tabela à mão com `create_table`, informando
todas as colunas e tipos — trabalhoso e frágil, já que a Gold tem oito tabelas
com schemas diferentes.

O Crawler também reconhece o padrão Hive dos caminhos (`edicao=2023/`) e registra
`edicao` como coluna de partição, o que permite ao Athena filtrar por edição sem
varrer os arquivos das outras.

O QUE É VERIFICADO
------------------
Catalogar sem erro não significa que as tabelas funcionam. O script executa uma
consulta real no Athena contra cada tabela catalogada, porque é comum a
catalogação passar e a consulta falhar — tipicamente por nome de coluna
incompatível, que é exatamente o problema que a etapa de sanitização resolve.
"""

from __future__ import annotations

import time
from typing import Dict, List, Optional

import boto3
from botocore.exceptions import ClientError

from src import config

ESTADOS_FINAIS_CRAWLER = ("READY",)
ESTADOS_FINAIS_CONSULTA = ("SUCCEEDED", "FAILED", "CANCELLED")


def _cliente(servico: str):
    """Cria um cliente boto3 na região do projeto."""
    return boto3.client(servico, region_name=config.REGIAO)


def criar_ou_atualizar_crawler(glue, arn_role: str) -> None:
    """Cria ou atualiza o Crawler que cataloga as camadas Silver e Gold.

    A Bronze não é catalogada: são CSVs com nomes de coluna inválidos para o
    Athena, e o propósito dela é ser cópia fiel da origem, não superfície de
    consulta.

    Args:
        glue: cliente boto3 do Glue.
        arn_role: ARN da IAM role usada pelo Crawler.
    """
    # Cada tabela é declarada como alvo próprio, em vez de apontar para a raiz
    # da camada.
    #
    # Apontar para `gold/` fez o Crawler interpretar os oito subdiretórios como
    # PARTIÇÕES de uma única tabela chamada `gold`, com `partition_0` guardando
    # o nome do diretório. As oito tabelas viraram uma só com 3.449 linhas
    # empilhadas — consultável, e completamente errada.
    #
    # A Silver não sofreu disso porque cada subdiretório contém partições
    # `edicao=`, o que torna a estrutura inequívoca. Ainda assim, declarar
    # explicitamente evita depender dessa sorte.
    caminhos = [
        f"s3://{config.NOME_BUCKET}/{config.CAMADA_SILVER}/{tabela}/"
        for tabela in config.TABELAS_SILVER
    ] + [
        f"s3://{config.NOME_BUCKET}/{config.CAMADA_GOLD}/{tabela}/"
        for tabela in config.TABELAS_GOLD
    ]
    alvos = {"S3Targets": [{"Path": caminho} for caminho in caminhos]}

    definicao = {
        "Role": arn_role,
        "DatabaseName": config.NOME_DATABASE_GLUE,
        "Targets": alvos,
        "Description": "Cataloga Silver e Gold do Tech Challenge Fase 3.",
        # Atualiza schema e remove tabelas órfãs em reexecuções, mantendo o
        # catálogo fiel ao que existe no S3.
        "SchemaChangePolicy": {
            "UpdateBehavior": "UPDATE_IN_DATABASE",
            "DeleteBehavior": "DELETE_FROM_DATABASE",
        },
    }

    try:
        glue.create_crawler(Name=config.NOME_CRAWLER, **definicao)
        print(f"  crawler {config.NOME_CRAWLER} criado")
    except ClientError as erro:
        if erro.response["Error"]["Code"] != "AlreadyExistsException":
            raise
        glue.update_crawler(Name=config.NOME_CRAWLER, **definicao)
        print(f"  crawler {config.NOME_CRAWLER} atualizado")


def _inicio_ultimo_crawl(glue) -> Optional[str]:
    """Devolve o horário de início do último crawl, se houver.

    Args:
        glue: cliente boto3 do Glue.

    Returns:
        Horário em ISO 8601, ou None se o crawler nunca rodou.
    """
    crawler = glue.get_crawler(Name=config.NOME_CRAWLER)["Crawler"]
    inicio = crawler.get("LastCrawl", {}).get("StartTime")
    return inicio.isoformat() if inicio else None


def executar_crawler(glue, timeout_segundos: int = 900) -> None:
    """Dispara o Crawler e aguarda que um NOVO crawl termine com sucesso.

    Duas armadilhas tratadas aqui:

    1. `READY` é também o estado INICIAL do crawler, não só o final. Esperar
       simplesmente por `READY` sai do laço antes do crawl começar. Por isso o
       laço só considera terminado quando o horário de início do último crawl
       mudou em relação ao registrado antes do disparo.

    2. O crawler chega a `READY` tanto ao ter sucesso quanto ao falhar. É
       preciso inspecionar `LastCrawl.Status` — sem isso, uma falha de permissão
       passa como sucesso e deixa o catálogo com tabelas de zero partição, que o
       Athena consulta sem erro e devolve zero registros.

    Args:
        glue: cliente boto3 do Glue.
        timeout_segundos: tempo máximo de espera.

    Raises:
        TimeoutError: se o crawl não terminar dentro do tempo limite.
        RuntimeError: se o crawl terminar em estado diferente de SUCCEEDED.
    """
    inicio_anterior = _inicio_ultimo_crawl(glue)

    try:
        glue.start_crawler(Name=config.NOME_CRAWLER)
        print("  crawler iniciado")
    except ClientError as erro:
        if erro.response["Error"]["Code"] != "CrawlerRunningException":
            raise
        print("  crawler já estava rodando, aguardando")

    limite = time.time() + timeout_segundos
    while time.time() < limite:
        crawler = glue.get_crawler(Name=config.NOME_CRAWLER)["Crawler"]
        estado = crawler["State"]
        ultimo_crawl = crawler.get("LastCrawl", {})
        inicio_atual = (
            ultimo_crawl["StartTime"].isoformat()
            if ultimo_crawl.get("StartTime")
            else None
        )

        # Terminou quando voltou a READY E registrou um crawl mais recente.
        if estado == "READY" and inicio_atual != inicio_anterior:
            situacao = ultimo_crawl.get("Status", "DESCONHECIDO")
            if situacao != "SUCCEEDED":
                mensagem = ultimo_crawl.get("ErrorMessage", "sem mensagem")
                raise RuntimeError(
                    f"Crawl terminou como {situacao}: {mensagem}\n"
                    f"  Log: /aws-glue/crawlers, stream {config.NOME_CRAWLER}"
                )
            break

        time.sleep(10)
    else:
        raise TimeoutError(f"Crawl não terminou em {timeout_segundos}s.")

    metricas = glue.get_crawler_metrics(CrawlerNameList=[config.NOME_CRAWLER])[
        "CrawlerMetricsList"
    ][0]
    print(
        f"  crawl SUCCEEDED: {metricas.get('TablesCreated', 0)} tabelas criadas, "
        f"{metricas.get('TablesUpdated', 0)} atualizadas, "
        f"{metricas.get('TablesDeleted', 0)} removidas"
    )


def listar_tabelas(glue) -> List[Dict]:
    """Lista as tabelas catalogadas no database do projeto.

    Args:
        glue: cliente boto3 do Glue.

    Returns:
        Lista de dicionários com nome, quantidade de colunas e partições.
    """
    paginador = glue.get_paginator("get_tables")
    tabelas: List[Dict] = []
    for pagina in paginador.paginate(DatabaseName=config.NOME_DATABASE_GLUE):
        for tabela in pagina["TableList"]:
            tabelas.append(
                {
                    "nome": tabela["Name"],
                    "colunas": len(tabela["StorageDescriptor"].get("Columns", [])),
                    "particoes": [c["Name"] for c in tabela.get("PartitionKeys", [])],
                    "formato": tabela["StorageDescriptor"]
                    .get("SerdeInfo", {})
                    .get("SerializationLibrary", "")
                    .split(".")[-1],
                }
            )
    return sorted(tabelas, key=lambda t: t["nome"])


def executar_consulta_athena(
    athena, consulta: str, timeout_segundos: int = 180
) -> Dict:
    """Executa uma consulta no Athena e aguarda o resultado.

    Args:
        athena: cliente boto3 do Athena.
        consulta: SQL a executar.
        timeout_segundos: tempo máximo de espera.

    Returns:
        Dicionário com `id`, `estado`, `linhas` (as primeiras linhas do
        resultado) e `bytes_escaneados`.

    Raises:
        TimeoutError: se a consulta não terminar dentro do tempo limite.
    """
    inicio = athena.start_query_execution(
        QueryString=consulta,
        QueryExecutionContext={"Database": config.NOME_DATABASE_GLUE},
        ResultConfiguration={
            "OutputLocation": (
                f"s3://{config.NOME_BUCKET}/{config.PREFIXO_RESULTADOS_ATHENA}/"
            ),
            "EncryptionConfiguration": {"EncryptionOption": "SSE_S3"},
        },
    )
    id_consulta = inicio["QueryExecutionId"]

    limite = time.time() + timeout_segundos
    execucao: Dict = {}
    while time.time() < limite:
        execucao = athena.get_query_execution(QueryExecutionId=id_consulta)[
            "QueryExecution"
        ]
        estado = execucao["Status"]["State"]
        if estado in ESTADOS_FINAIS_CONSULTA:
            break
        time.sleep(2)
    else:
        raise TimeoutError(f"Consulta {id_consulta} não terminou em {timeout_segundos}s.")

    resultado = {
        "id": id_consulta,
        "estado": estado,
        "bytes_escaneados": execucao.get("Statistics", {}).get("DataScannedInBytes", 0),
        "linhas": [],
        "erro": execucao["Status"].get("StateChangeReason"),
    }

    if estado == "SUCCEEDED":
        dados = athena.get_query_results(QueryExecutionId=id_consulta, MaxResults=6)
        for linha in dados["ResultSet"]["Rows"]:
            resultado["linhas"].append(
                [celula.get("VarCharValue", "") for celula in linha["Data"]]
            )

    return resultado


def validar_tabelas_no_athena(athena, tabelas: List[Dict]) -> List[str]:
    """Executa uma consulta real contra cada tabela catalogada.

    Catalogar sem erro não garante que a tabela é consultável. Nomes de coluna
    incompatíveis, por exemplo, só falham no momento da consulta.

    Args:
        athena: cliente boto3 do Athena.
        tabelas: tabelas catalogadas.

    Returns:
        Lista de falhas encontradas. Vazia quando todas são consultáveis.
    """
    falhas: List[str] = []
    for tabela in tabelas:
        nome = tabela["nome"]
        resultado = executar_consulta_athena(
            athena, f'SELECT COUNT(*) AS total FROM "{nome}"'
        )
        if resultado["estado"] != "SUCCEEDED":
            falhas.append(f"{nome}: {resultado['erro']}")
            print(f"    {nome:32} FALHA — {resultado['erro']}")
            continue

        total = resultado["linhas"][1][0] if len(resultado["linhas"]) > 1 else "?"
        particoes = ",".join(tabela["particoes"]) or "-"
        print(
            f"    {nome:32} {total:>7} registros | "
            f"{tabela['colunas']:3} colunas | partição: {particoes}"
        )
    return falhas


def main() -> None:
    """Cataloga as camadas e valida cada tabela no Athena."""
    glue = _cliente("glue")
    iam = _cliente("iam")
    athena = _cliente("athena")

    arn_role = iam.get_role(RoleName=config.NOME_ROLE_GLUE)["Role"]["Arn"]

    print("=" * 78)
    print(f"CATALOGAÇÃO — database {config.NOME_DATABASE_GLUE}")
    print("=" * 78)

    print("\n[crawler]")
    criar_ou_atualizar_crawler(glue, arn_role)
    executar_crawler(glue)

    print("\n[tabelas catalogadas]")
    tabelas = listar_tabelas(glue)
    if not tabelas:
        raise RuntimeError(
            f"Nenhuma tabela catalogada em {config.NOME_DATABASE_GLUE}. "
            f"Verifique se as camadas Silver e Gold existem no S3."
        )

    print("\n[validação no Athena]")
    falhas = validar_tabelas_no_athena(athena, tabelas)

    print("\n" + "=" * 78)
    if falhas:
        print(f"TABELAS NÃO CONSULTÁVEIS: {len(falhas)}")
        for falha in falhas:
            print(f"  - {falha}")
        print("=" * 78)
        raise RuntimeError(f"{len(falhas)} tabela(s) catalogada(s) mas não consultável(is).")

    print(f"{len(tabelas)} tabelas catalogadas e consultáveis no Athena.")
    print("=" * 78)


if __name__ == "__main__":
    main()
