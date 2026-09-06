"""
Execução das consultas analíticas no Athena e coleta dos resultados.

Lê o arquivo SQL versionado, separa as consultas, executa cada uma no Athena e
grava os resultados como evidência. Serve a dois propósitos:

    1. Provar que as tabelas catalogadas são realmente consultáveis, e não
       apenas registradas no catálogo
    2. Extrair os números que sustentam o material executivo

As consultas são separadas por `;` no final da instrução. Comentários de linha
são preservados no texto enviado ao Athena, que os aceita.
"""

from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

import boto3

from src import config

ARQUIVO_CONSULTAS = config.RAIZ_PROJETO / "athena" / "00_perguntas_de_negocio.sql"
ESTADOS_FINAIS = ("SUCCEEDED", "FAILED", "CANCELLED")

# Limite de linhas retornadas por consulta na coleta de evidência. As consultas
# já usam LIMIT; este é um teto adicional para manter o JSON legível.
MAXIMO_LINHAS = 40


# Reconhece o comentário que enuncia uma das perguntas de negócio, no formato
# "1. Como está estruturado...". Serve para agrupar as consultas por pergunta.
PADRAO_PERGUNTA = re.compile(r"^(\d+)\.\s+(.+)$")


def separar_consultas(sql: str) -> List[Dict[str, str]]:
    """Separa o arquivo SQL em consultas individuais, com título e pergunta.

    O título vem do primeiro comentário do bloco imediatamente anterior à
    instrução. Linhas decorativas (`----`, `====`) delimitam seções e zeram o
    bloco acumulado — sem isso, o cabeçalho do arquivo seria usado como título
    da primeira consulta.

    A pergunta de negócio é rastreada separadamente: o último comentário no
    formato "N. texto" vale para todas as consultas seguintes, até que outro
    apareça.

    Args:
        sql: conteúdo completo do arquivo SQL.

    Returns:
        Lista de dicionários com `titulo`, `pergunta` e `sql`.
    """
    consultas: List[Dict[str, str]] = []
    acumulado: List[str] = []
    comentarios: List[str] = []
    pergunta_atual = ""

    for linha in sql.splitlines():
        despida = linha.strip()

        if despida.startswith("--"):
            texto = despida.lstrip("-").strip()
            if not texto or set(texto) <= {"=", "-"}:
                # Linha decorativa: fecha o bloco de comentários corrente.
                comentarios = []
                continue

            correspondencia = PADRAO_PERGUNTA.match(texto)
            if correspondencia:
                pergunta_atual = texto
                comentarios = []
                continue

            comentarios.append(texto)
            continue

        if not despida:
            continue

        acumulado.append(linha)

        if despida.endswith(";"):
            corpo = "\n".join(acumulado).strip().rstrip(";")
            titulo = comentarios[0] if comentarios else pergunta_atual
            consultas.append(
                {
                    "titulo": titulo or f"consulta {len(consultas) + 1}",
                    "pergunta": pergunta_atual,
                    "sql": corpo,
                }
            )
            acumulado = []
            comentarios = []

    return consultas


def executar(athena, sql: str, timeout_segundos: int = 180) -> Dict:
    """Executa uma consulta no Athena e devolve o resultado.

    Args:
        athena: cliente boto3 do Athena.
        sql: instrução SQL a executar.
        timeout_segundos: tempo máximo de espera.

    Returns:
        Dicionário com `id`, `estado`, `colunas`, `linhas`, `bytes_escaneados`,
        `milissegundos` e `erro`.

    Raises:
        TimeoutError: se a consulta não terminar dentro do tempo limite.
    """
    inicio = athena.start_query_execution(
        QueryString=sql,
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
        if execucao["Status"]["State"] in ESTADOS_FINAIS:
            break
        time.sleep(2)
    else:
        raise TimeoutError(f"Consulta {id_consulta} não terminou em {timeout_segundos}s.")

    estatisticas = execucao.get("Statistics", {})
    resultado: Dict = {
        "id": id_consulta,
        "estado": execucao["Status"]["State"],
        "bytes_escaneados": estatisticas.get("DataScannedInBytes", 0),
        "milissegundos": estatisticas.get("TotalExecutionTimeInMillis", 0),
        "erro": execucao["Status"].get("StateChangeReason"),
        "colunas": [],
        "linhas": [],
    }

    if resultado["estado"] != "SUCCEEDED":
        return resultado

    resposta = athena.get_query_results(
        QueryExecutionId=id_consulta, MaxResults=MAXIMO_LINHAS + 1
    )
    linhas_brutas = resposta["ResultSet"]["Rows"]
    if linhas_brutas:
        resultado["colunas"] = [
            celula.get("VarCharValue", "") for celula in linhas_brutas[0]["Data"]
        ]
        resultado["linhas"] = [
            [celula.get("VarCharValue") for celula in linha["Data"]]
            for linha in linhas_brutas[1:]
        ]

    return resultado


def _formatar_tabela(colunas: List[str], linhas: List[List[Optional[str]]], limite: int = 8) -> str:
    """Formata um resultado como tabela de texto alinhada.

    Args:
        colunas: nomes das colunas.
        linhas: linhas do resultado.
        limite: máximo de linhas a exibir.

    Returns:
        Tabela formatada.
    """
    if not colunas:
        return "    (sem resultado)"

    amostra = linhas[:limite]
    larguras = [len(nome) for nome in colunas]
    for linha in amostra:
        for indice, valor in enumerate(linha):
            larguras[indice] = min(max(larguras[indice], len(str(valor or ""))), 46)

    def formatar(valores) -> str:
        partes = []
        for indice, valor in enumerate(valores):
            texto = str(valor if valor is not None else "")[: larguras[indice]]
            partes.append(texto.ljust(larguras[indice]))
        return "    " + " | ".join(partes)

    saida = [formatar(colunas), "    " + "-+-".join("-" * largura for largura in larguras)]
    saida.extend(formatar(linha) for linha in amostra)
    if len(linhas) > limite:
        saida.append(f"    ... e mais {len(linhas) - limite} linhas")
    return "\n".join(saida)


def main() -> None:
    """Executa todas as consultas e grava a evidência."""
    athena = boto3.client("athena", region_name=config.REGIAO)

    sql = ARQUIVO_CONSULTAS.read_text(encoding="utf-8")
    consultas = separar_consultas(sql)

    print("=" * 78)
    print(f"CONSULTAS ATHENA — {len(consultas)} consultas, database {config.NOME_DATABASE_GLUE}")
    print("=" * 78)

    resultados: List[Dict] = []
    falhas: List[str] = []
    bytes_totais = 0

    for indice, consulta in enumerate(consultas, start=1):
        print(f"\n[{indice}/{len(consultas)}] {consulta['titulo'][:70]}")
        resultado = executar(athena, consulta["sql"])
        resultado["titulo"] = consulta["titulo"]
        resultado["pergunta"] = consulta["pergunta"]
        resultado["sql"] = consulta["sql"]
        resultados.append(resultado)
        bytes_totais += resultado["bytes_escaneados"]

        if resultado["estado"] != "SUCCEEDED":
            falhas.append(f"{consulta['titulo']}: {resultado['erro']}")
            print(f"    FALHA: {resultado['erro']}")
            continue

        print(
            f"    {len(resultado['linhas'])} linhas, "
            f"{resultado['bytes_escaneados'] / 1024:.1f} KB escaneados, "
            f"{resultado['milissegundos']} ms"
        )
        print(_formatar_tabela(resultado["colunas"], resultado["linhas"]))

    evidencia = {
        "coletado_em": datetime.now(timezone.utc).isoformat(),
        "database": config.NOME_DATABASE_GLUE,
        "regiao": config.REGIAO,
        "consultas": len(consultas),
        "falhas": len(falhas),
        "bytes_escaneados_total": bytes_totais,
        "resultados": resultados,
    }

    config.DIRETORIO_EVIDENCIAS.mkdir(parents=True, exist_ok=True)
    destino = config.DIRETORIO_EVIDENCIAS / "consultas_athena.json"
    destino.write_text(json.dumps(evidencia, indent=2, ensure_ascii=False), encoding="utf-8")

    print("\n" + "=" * 78)
    # Athena cobra US$ 5 por TB escaneado, com mínimo de 10 MB por consulta.
    minimo_faturado = len(consultas) * 10 * 1_048_576
    custo = max(bytes_totais, minimo_faturado) / 1_099_511_627_776 * 5
    print(f"Total escaneado: {bytes_totais / 1_048_576:.2f} MB (~US$ {custo:.5f})")
    print(f"Evidência: {destino.relative_to(config.RAIZ_PROJETO)}")

    if falhas:
        print(f"\nFALHAS: {len(falhas)}")
        for falha in falhas:
            print(f"  - {falha}")
        print("=" * 78)
        raise SystemExit(1)

    print(f"{len(consultas)} consultas executadas com sucesso.")
    print("=" * 78)


if __name__ == "__main__":
    main()
