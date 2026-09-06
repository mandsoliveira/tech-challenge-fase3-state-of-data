"""
Valida o mapeamento semântico de colunas contra os CSVs brutos.

Este script existe porque o mapeamento em `mapeamento_colunas.py` é curado à
mão e, portanto, sujeito a erro humano. Ele não "conserta" nada: apenas expõe
o que o mapeamento resolveu em cada edição, para conferência.

Duas verificações são feitas:

1. COBERTURA — toda dimensão declarada resolve para uma coluna existente na
   edição correspondente? Uma dimensão que resolve para None sem estar
   declarada como ausente indica código errado no mapeamento.

2. COERÊNCIA SEMÂNTICA — os rótulos resolvidos nos três anos falam da mesma
   coisa? Isso exige olho humano, então o script imprime os três lado a lado.
   Um desalinhamento aqui é exatamente o bug que o mapeamento existe para
   evitar (ex.: unir "layoff" de 2024 com "modelo de trabalho" de 2025).

Uso:
    python -m src.validar_mapeamento
    python -m src.validar_mapeamento --valores genero faixa_salarial
"""

from __future__ import annotations

import argparse
import ast
import re
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd

from src.mapeamento_colunas import (
    ANOS,
    ARQUIVO_BRUTO,
    MAPEAMENTO,
    ROTULO_EDICAO,
    resolver_colunas,
)

DIRETORIO_BRUTO = Path(__file__).resolve().parent.parent / "data" / "raw"


def extrair_rotulo(coluna: str) -> str:
    """Extrai o texto legível da pergunta a partir do nome bruto da coluna.

    Args:
        coluna: nome da coluna como aparece no CSV bruto.

    Returns:
        O enunciado ou slug da pergunta, sem o código.
    """
    bruta = coluna.strip()
    if bruta.startswith("("):
        try:
            return str(ast.literal_eval(bruta)[1]).strip()
        except (ValueError, SyntaxError, IndexError):
            return bruta
    correspondencia = re.match(r"^\d+\.[a-z]+(?:\.\d+)?_(.*)$", bruta)
    return correspondencia.group(1) if correspondencia else bruta


def carregar_cabecalhos() -> Dict[int, List[str]]:
    """Lê apenas o cabeçalho de cada CSV bruto.

    Returns:
        Dicionário {ano -> lista de nomes de coluna}.

    Raises:
        FileNotFoundError: se algum CSV bruto estiver ausente.
    """
    cabecalhos: Dict[int, List[str]] = {}
    for ano in ANOS:
        caminho = DIRETORIO_BRUTO / ARQUIVO_BRUTO[ano]
        if not caminho.exists():
            raise FileNotFoundError(
                f"CSV bruto da edição {ROTULO_EDICAO[ano]} não encontrado em {caminho}. "
                f"Descompacte os arquivos do Kaggle em {DIRETORIO_BRUTO}."
            )
        cabecalhos[ano] = list(pd.read_csv(caminho, nrows=0, low_memory=False).columns)
    return cabecalhos


def validar(cabecalhos: Dict[int, List[str]]) -> int:
    """Imprime o relatório de cobertura e coerência do mapeamento.

    Args:
        cabecalhos: dicionário {ano -> lista de colunas} dos CSVs brutos.

    Returns:
        Quantidade de problemas de cobertura encontrados.
    """
    resolvidos = {ano: resolver_colunas(cabecalhos[ano], ano) for ano in ANOS}
    problemas = 0

    print("=" * 100)
    print("VALIDAÇÃO DO MAPEAMENTO SEMÂNTICO — State of Data Brasil")
    print("=" * 100)

    for dimensao in MAPEAMENTO:
        rotulos: Dict[int, str] = {}
        falhas: List[int] = []

        for ano in ANOS:
            coluna = resolvidos[ano][dimensao]
            declarada_ausente = MAPEAMENTO[dimensao][ano] is None
            if coluna is None:
                if not declarada_ausente:
                    falhas.append(ano)
                rotulos[ano] = "— ausente —" if declarada_ausente else "!! NÃO RESOLVEU !!"
            else:
                rotulos[ano] = extrair_rotulo(coluna)

        marcador = "FALHA" if falhas else "ok"
        print(f"\n[{marcador}] {dimensao}")
        for ano in ANOS:
            codigo = MAPEAMENTO[dimensao][ano] or "-"
            print(f"    {ROTULO_EDICAO[ano]:10} {codigo:8} | {rotulos[ano][:72]}")

        if falhas:
            problemas += len(falhas)

    print("\n" + "=" * 100)
    print(f"Dimensões mapeadas: {len(MAPEAMENTO)}")
    print(f"Problemas de cobertura: {problemas}")
    print("=" * 100)
    print(
        "\nRevise visualmente os blocos acima: os três rótulos de cada dimensão\n"
        "devem falar da mesma coisa. Rótulos divergentes significam mapeamento\n"
        "errado, e produziriam uma união silenciosamente incorreta na Silver."
    )
    return problemas


def comparar_valores(dimensoes: List[str]) -> None:
    """Imprime a distribuição de valores de dimensões específicas nos três anos.

    Útil para os casos em que o rótulo é ambíguo ou incorreto na origem — como
    a cloud de 2023, cujo enunciado diz "preferida" mas cujos valores revelam
    ser a cloud usada no dia a dia.

    Args:
        dimensoes: nomes canônicos das dimensões a inspecionar.
    """
    for dimensao in dimensoes:
        if dimensao not in MAPEAMENTO:
            print(f"\n[aviso] dimensão desconhecida: {dimensao}")
            continue

        print("\n" + "=" * 100)
        print(f"DISTRIBUIÇÃO DE VALORES — {dimensao}")
        print("=" * 100)

        for ano in ANOS:
            caminho = DIRETORIO_BRUTO / ARQUIVO_BRUTO[ano]
            cabecalho = list(pd.read_csv(caminho, nrows=0, low_memory=False).columns)
            coluna = resolver_colunas(cabecalho, ano)[dimensao]

            print(f"\n--- {ROTULO_EDICAO[ano]} ---")
            if coluna is None:
                print("    (dimensão ausente nesta edição)")
                continue

            serie = pd.read_csv(caminho, usecols=[coluna], low_memory=False)[coluna]
            print(f"    coluna: {coluna[:88]}")
            print(f"    nulos : {serie.isna().sum()} de {len(serie)}")
            contagem = serie.value_counts(dropna=True).head(6)
            for valor, quantidade in contagem.items():
                print(f"      {quantidade:6}  {str(valor)[:74]}")


def main() -> None:
    """Ponto de entrada da validação."""
    analisador = argparse.ArgumentParser(
        description="Valida o mapeamento semântico de colunas do State of Data."
    )
    analisador.add_argument(
        "--valores",
        nargs="*",
        metavar="DIMENSAO",
        help="Dimensões cujas distribuições de valores devem ser comparadas.",
    )
    argumentos = analisador.parse_args()

    cabecalhos = carregar_cabecalhos()
    problemas = validar(cabecalhos)

    if argumentos.valores:
        comparar_valores(argumentos.valores)

    raise SystemExit(1 if problemas else 0)


if __name__ == "__main__":
    main()
