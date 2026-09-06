"""
Mapeamento das perguntas de múltipla escolha entre as edições.

O PROBLEMA
----------
As perguntas multi-escolha existem na origem em dois formatos simultâneos:

    1. Coluna raiz com as opções concatenadas por vírgula:
       "4.d_banco_de_dados_(dia_a_dia)" = "MySQL, PostgreSQL, Google BigQuery"

    2. Colunas booleanas explodidas, uma por opção:
       "4.d.1_MySQL", "4.d.2_Oracle", "4.d.3_SQL SERVER", ...

Usar a coluna raiz é inviável: o separador é vírgula, mas os próprios textos
das respostas contêm vírgulas. Uma opção real do questionário é

    "Utilizo soluções pagas de AI Generativa (como por exemplo ChatGPT plus,
     Anthropic Claude, Google Gemini etc) e a empresa em que trabalho paga"

Dividir isso por vírgula produziria "Anthropic Claude" e "Google Gemini etc)"
como respostas separadas. É por isso que a coluna raiz de `banco_dados` tem 175
a 221 valores distintos: são combinações, não opções.

A SOLUÇÃO
---------
Usar as colunas explodidas, cujo nome já contém o rótulo da opção:

    "4.d.1_MySQL"                      -> opção "MySQL"
    "4.e.1_Amazon Web Services (AWS)"  -> opção "Amazon Web Services (AWS)"
    "3.f.1 Colaboradores usando AI..." -> opção "Colaboradores usando AI..."

Note que o separador entre código e rótulo é underscore em algumas colunas e
ESPAÇO em outras. Ambos são tratados.

DESLOCAMENTO TAMBÉM SE APLICA
-----------------------------
Os códigos das multi-escolha deslocam entre edições pelo mesmo motivo das
perguntas raiz. `banco_dados` é P4_g em 2023, 4.g em 2024 e 4.d em 2025. O
mapeamento abaixo é curado à mão, igual ao de `mapeamento_colunas.py`.
"""

from __future__ import annotations

import re
from typing import Dict, List, NamedTuple, Optional, Sequence

from src.mapeamento_colunas import ANOS, extrair_codigo, normalizar_codigo


class OpcaoMultiEscolha(NamedTuple):
    """Uma opção de resposta de pergunta multi-escolha.

    Attributes:
        coluna: nome real da coluna booleana explodida no CSV bruto.
        rotulo: texto da opção, extraído do nome da coluna.
        codigo: código normalizado da coluna (ex.: `4.d.1`).
    """

    coluna: str
    rotulo: str
    codigo: str


# ---------------------------------------------------------------------------
# Mapeamento das perguntas multi-escolha por edição
# ---------------------------------------------------------------------------
# Estrutura: {dimensão canônica -> {ano -> código da pergunta raiz}}
#
# As colunas explodidas são descobertas em tempo de execução como aquelas cujo
# código é o código raiz seguido de mais um nível numérico. Ex.: para a raiz
# `4.d`, as explodidas são `4.d.1`, `4.d.2`, ...
#
# A marcação  # DESLOCADO  indica dimensões cujo código muda entre edições.

MAPEAMENTO_MULTIESCOLHA: Dict[str, Dict[int, Optional[str]]] = {
    # --- Tecnologias -------------------------------------------------------
    # Responde: "Quais tecnologias apresentam maior adoção entre os
    # profissionais?"
    #
    # ARMADILHA DA LINGUAGEM — duas mudanças estruturais em 2025:
    #
    # a) A edição 2025 eliminou "linguagem no dia a dia" e "linguagem mais
    #    usada", mantendo apenas a preferida. Por isso `linguagem_usada` é nula
    #    em 2025.
    #
    # b) "Linguagem preferida" MUDOU DE NATUREZA. Era escolha única em 2023 e
    #    2024 (16 valores distintos, nenhum com vírgula) e virou múltipla
    #    escolha em 2025 (137 combinações, 1.710 respostas com vírgula:
    #    "Python, SQL" com 735, "SQL, Python" com 506).
    #
    #    Consequência: comparar "% que prefere Python" entre as três edições
    #    compara coisas diferentes. Em 2023 o respondente escolhia uma
    #    linguagem; em 2025 pode marcar Python e SQL simultaneamente, o que
    #    infla artificialmente qualquer share.
    #
    #    Por isso `linguagem_preferida` consta aqui APENAS para 2025, com as
    #    colunas explodidas. Em 2023 e 2024 ela é escolha única e vive na Silver
    #    como coluna simples. A camada Gold deve sinalizar a quebra em vez de
    #    apresentar a série como contínua.
    "linguagem_usada":     {2023: "P4_d", 2024: "4.d", 2025: None},
    "linguagem_preferida": {2023: None,   2024: None,  2025: "4.c"},
    "banco_dados":         {2023: "P4_g", 2024: "4.g", 2025: "4.d"},   # DESLOCADO
    "cloud_dia_a_dia":     {2023: "P4_h", 2024: "4.h", 2025: "4.e"},   # DESLOCADO
    "bi_dia_a_dia":        {2023: "P4_j", 2024: "4.j", 2025: "4.g"},   # DESLOCADO

    # --- Inteligência Artificial ------------------------------------------
    # Responde: "Qual é o índice de adoção de Inteligência Artificial e seu
    # impacto?"
    #
    # `tipo_uso_ia_empresa` aparece duas vezes na origem: na seção 3 (respondida
    # por gestores) e na seção 4 (respondida por todos). Aqui usamos a da seção
    # 3 para a visão de empresa e a da seção 4 em `tipo_uso_ia_area`.
    "tipo_uso_ia_empresa": {2023: "P3_f", 2024: "3.f", 2025: "3.f"},
    "motivos_nao_usar_ia": {2023: "P3_g", 2024: "3.g", 2025: "3.h"},   # DESLOCADO
    "tipo_uso_ia_area":    {2023: "P4_l", 2024: "4.l", 2025: "4.i"},   # DESLOCADO
    "usa_chatgpt_copilot": {2023: "P4_m", 2024: "4.m", 2025: "4.j"},   # DESLOCADO

    # --- Oportunidades e desafios -----------------------------------------
    # Responde: "Quais oportunidades e desafios podem ser identificados para
    # empresas que desejam investir em Dados e IA?"
    "desafios_gestor":     {2023: "P3_d", 2024: "3.d", 2025: "3.d"},
    "criterios_escolha":   {2023: "P2_o", 2024: "2.o", 2025: "2.o"},

    # --- Diversidade -------------------------------------------------------
    # Responde: "Qual é o cenário de diversidade de gênero nas carreiras de
    # dados?" — os aspectos prejudicados dão a dimensão qualitativa.
    "aspectos_prejudicados": {2023: "P1_f", 2024: "1.f", 2025: "1.f"},
}


def extrair_rotulo_opcao(coluna: str) -> str:
    """Extrai o rótulo da opção a partir do nome da coluna explodida.

    Trata as duas convenções de separador entre código e rótulo, underscore e
    espaço, e o formato de tupla da edição 2023.

    Args:
        coluna: nome bruto da coluna booleana explodida.

    Returns:
        Texto da opção de resposta.
    """
    bruta = coluna.strip()

    # Edição 2023: "('P4_g_1 ', 'MySQL')"
    if bruta.startswith("("):
        correspondencia = re.match(r"^\(\s*'[^']*'\s*,\s*'(.*)'\s*\)$", bruta, re.DOTALL)
        if correspondencia:
            return correspondencia.group(1).strip()
        # Cabeçalho malformado (apóstrofo no rótulo): recorta após a vírgula.
        partes = bruta.strip("()").split(",", 1)
        return partes[1].strip().strip("'").strip() if len(partes) > 1 else bruta

    # Edições 2024 e 2025: "4.d.1_MySQL" ou "3.f.1 Colaboradores usando..."
    correspondencia = re.match(r"^\d+\.[a-z]+(?:\.\d+)?[_ ](.*)$", bruta)
    return correspondencia.group(1).strip() if correspondencia else bruta


def resolver_opcoes(
    colunas: Sequence[str], dimensao: str, ano: int
) -> List[OpcaoMultiEscolha]:
    """Resolve as colunas explodidas de uma pergunta multi-escolha.

    Localiza as colunas cujo código é o código da pergunta raiz seguido de um
    nível numérico adicional. Para a raiz `4.d`, encontra `4.d.1`, `4.d.2` e
    assim por diante.

    Args:
        colunas: nomes das colunas do CSV bruto da edição.
        dimensao: nome canônico da dimensão multi-escolha.
        ano: ano de início da edição (2023, 2024 ou 2025).

    Returns:
        Lista de opções encontradas, ordenada pelo índice numérico da coluna.
        Vazia se a dimensão não existir na edição.

    Raises:
        KeyError: se a dimensão não estiver no mapeamento multi-escolha.
        ValueError: se o ano não for uma edição conhecida.
    """
    if dimensao not in MAPEAMENTO_MULTIESCOLHA:
        raise KeyError(
            f"Dimensão {dimensao!r} não está em MAPEAMENTO_MULTIESCOLHA. "
            f"Disponíveis: {sorted(MAPEAMENTO_MULTIESCOLHA)}"
        )
    if ano not in ANOS:
        raise ValueError(f"Edição desconhecida: {ano}. Esperado um de {ANOS}.")

    codigo_raiz = MAPEAMENTO_MULTIESCOLHA[dimensao][ano]
    if codigo_raiz is None:
        return []

    raiz_normalizada = normalizar_codigo(codigo_raiz)
    # Uma coluna explodida tem exatamente um nível numérico além da raiz.
    padrao = re.compile(rf"^{re.escape(raiz_normalizada)}\.(\d+)$")

    encontradas: List[tuple[int, OpcaoMultiEscolha]] = []
    for coluna in colunas:
        codigo = extrair_codigo(coluna)
        if codigo is None:
            continue
        correspondencia = padrao.match(codigo)
        if not correspondencia:
            continue
        encontradas.append(
            (
                int(correspondencia.group(1)),
                OpcaoMultiEscolha(
                    coluna=coluna,
                    rotulo=extrair_rotulo_opcao(coluna),
                    codigo=codigo,
                ),
            )
        )

    return [opcao for _, opcao in sorted(encontradas, key=lambda item: item[0])]


def dimensoes_disponiveis(ano: int) -> List[str]:
    """Lista as dimensões multi-escolha presentes em uma edição.

    Args:
        ano: ano de início da edição.

    Returns:
        Nomes canônicos das dimensões que existem na edição.
    """
    return [
        dimensao
        for dimensao, codigos in MAPEAMENTO_MULTIESCOLHA.items()
        if codigos.get(ano) is not None
    ]
