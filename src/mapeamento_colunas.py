"""
Mapeamento semântico de colunas entre as edições do State of Data Brasil.

PROBLEMA QUE ESTE MÓDULO RESOLVE
--------------------------------
As três edições usadas no projeto (2023-2024, 2024-2025, 2025-2026) NÃO são
compatíveis por código de pergunta. Duas incompatibilidades coexistem:

1. Convenção de nome mudou entre 2023 e 2024:
       2023  ->  "('P1_b ', 'Genero')"      (string de tupla)
       2024  ->  "1.b_genero"                (slug achatado)
       2025  ->  "1.b_genero"

2. As LETRAS das perguntas deslocam entre edições, porque perguntas foram
   inseridas e removidas. Casar pelo código produz uniões semanticamente
   erradas e silenciosas. Exemplos reais medidos nos arquivos:

       codigo 2_q  ->  2023: layoff em 2023
                       2024: layoff em 2024
                       2025: modelo_de_trabalho_atual      (!!)

       codigo 4_e  ->  2023: linguagem que mais utiliza
                       2024: linguagem_mais_usada
                       2025: cloud_(dia_a_dia)             (!!)

   Em 2025 a seção 4 perdeu três perguntas ("fonte mais usada", "linguagem no
   dia a dia", "linguagem mais usada"), então tudo a partir de 4.c deslocou.
   Na seção 2, o layoff saiu de "q" para "p" e o resto deslocou uma letra.
   Na seção 3, entrou "resultados com LLMs" em 3.g e "motivos para não usar"
   foi para 3.h.

Por isso o mapeamento abaixo é CURADO À MÃO por significado, não derivado do
código. Cada entrada foi conferida contra o rótulo e, nos casos ambíguos,
contra a distribuição de valores (ver `validar_mapeamento.py`).

ARMADILHA ADICIONAL (2023)
--------------------------
Em 2023 o rótulo de P4_h diz "Dentre as opções listadas, qual sua Cloud
preferida?", mas os valores incluem "Servidores On Premise/Não utilizamos
Cloud" e "Cloud Própria" — ou seja, é a cloud USADA no dia a dia, não a
preferida. A cloud preferida de verdade é P4_i. O rótulo está errado na
origem; só a inspeção dos valores revela isso.
"""

from __future__ import annotations

import ast
import re
from typing import Dict, Optional

# Anos (edições) tratados pelo pipeline. A chave é o ano de início da pesquisa.
ANOS = (2023, 2024, 2025)

# Rótulo amigável de cada edição, para exibição em gráficos e relatórios.
ROTULO_EDICAO: Dict[int, str] = {
    2023: "2023-2024",
    2024: "2024-2025",
    2025: "2025-2026",
}

# Nome do arquivo bruto de cada edição dentro de data/raw/.
ARQUIVO_BRUTO: Dict[int, str] = {
    2023: "state_of_data_2023.csv",
    2024: "state_of_data_2024.csv",
    2025: "state_of_data_2025.csv",
}


# ---------------------------------------------------------------------------
# Mapeamento semântico: nome canônico -> código da pergunta em cada edição
# ---------------------------------------------------------------------------
# `None` significa que a pergunta não existe naquela edição. A camada Silver
# materializa a coluna como nula, preservando a união entre os três anos.
#
# Os códigos seguem a notação da própria edição:
#   2023 -> "P1_b", "P1_i_2"      (prefixo P, separador _)
#   2024 -> "1.b",  "1.i.2"       (separador .)
#   2025 -> "1.b",  "1.i.2"
#
# A marcação  # DESLOCADO  sinaliza dimensões em que o código muda entre anos.
# São exatamente os pontos onde um join por código produziria dados errados.

MAPEAMENTO: Dict[str, Dict[int, Optional[str]]] = {
    # ----------------------------- Demografia -----------------------------
    # Responde: "Qual o cenário de diversidade de gênero nas carreiras de dados?"
    # e sustenta os cortes por região.
    "idade":               {2023: "P1_a",   2024: "1.a",   2025: "1.a"},
    "faixa_idade":         {2023: "P1_a_1", 2024: "1.a.1", 2025: "1.a.1"},
    "genero":              {2023: "P1_b",   2024: "1.b",   2025: "1.b"},
    "cor_raca_etnia":      {2023: "P1_c",   2024: "1.c",   2025: "1.c"},
    "pcd":                 {2023: "P1_d",   2024: "1.d",   2025: "1.d"},
    "vive_no_brasil":      {2023: "P1_g",   2024: "1.g",   2025: "1.g"},
    "uf_onde_mora":        {2023: "P1_i_1", 2024: "1.i.1", 2025: "1.i.1"},
    "regiao_onde_mora":    {2023: "P1_i_2", 2024: "1.i.2", 2025: "1.i.2"},
    "nivel_ensino":        {2023: "P1_l",   2024: "1.l",   2025: "1.l"},
    "area_formacao":       {2023: "P1_m",   2024: "1.m",   2025: "1.m"},

    # ------------------------ Situação profissional -----------------------
    # Responde: "Como está estruturado o mercado brasileiro de Dados?" e
    # "Quais perfis profissionais são mais valorizados pelo mercado?"
    "situacao_trabalho":   {2023: "P2_a",   2024: "2.a",   2025: "2.a"},
    "setor":               {2023: "P2_b",   2024: "2.b",   2025: "2.b"},
    "porte_empresa":       {2023: "P2_c",   2024: "2.c",   2025: "2.c"},
    "atua_como_gestor":    {2023: "P2_d",   2024: "2.d",   2025: "2.d"},
    "cargo_atual":         {2023: "P2_f",   2024: "2.f",   2025: "2.f"},
    "nivel_senioridade":   {2023: "P2_g",   2024: "2.g",   2025: "2.g"},
    "faixa_salarial":      {2023: "P2_h",   2024: "2.h",   2025: "2.h"},
    "tempo_exp_dados":     {2023: "P2_i",   2024: "2.i",   2025: "2.i"},
    "tempo_exp_ti":        {2023: "P2_j",   2024: "2.j",   2025: "2.j"},
    "satisfeito_empresa":  {2023: "P2_k",   2024: "2.k",   2025: "2.k"},
    "motivo_insatisfacao": {2023: "P2_l",   2024: "2.l",   2025: "2.l"},
    "planos_mudar_6m":     {2023: "P2_n",   2024: "2.n",   2025: "2.n"},

    # Responde: "Existem diferenças relevantes entre regiões, senioridades ou
    # modelos de trabalho?" — e o layoff alimenta a leitura de risco/mercado.
    "layoff":              {2023: "P2_q",   2024: "2.q",   2025: "2.p"},  # DESLOCADO
    "modelo_trabalho_atual": {2023: "P2_r", 2024: "2.r",   2025: "2.q"},  # DESLOCADO
    "modelo_trabalho_ideal": {2023: "P2_s", 2024: "2.s",   2025: "2.r"},  # DESLOCADO

    # --------------------- Empresa e IA (só gestores) ---------------------
    # Responde: "Qual é o índice de adoção de Inteligência Artificial e seu
    # impacto?" e "Quais oportunidades e desafios...?"
    # Atenção: seção 3 é condicional — só quem é gestor responde. Nulo aqui
    # é estrutural, não falta de qualidade.
    "num_pessoas_dados":   {2023: "P3_a",   2024: "3.a",   2025: "3.a"},
    "desafios_gestor":     {2023: "P3_d",   2024: "3.d",   2025: "3.d"},
    "ia_e_prioridade":     {2023: "P3_e",   2024: "3.e",   2025: "3.e"},
    "tipo_uso_ia_empresa": {2023: "P3_f",   2024: "3.f",   2025: "3.f"},
    # Pergunta nova em 2025: não existe nas edições anteriores.
    "resultados_com_llm":  {2023: None,     2024: None,    2025: "3.g"},
    "motivos_nao_usar_ia": {2023: "P3_g",   2024: "3.g",   2025: "3.h"},  # DESLOCADO

    # ----------------------------- Tecnologia -----------------------------
    # Responde: "Quais tecnologias apresentam maior adoção entre os
    # profissionais?"
    "funcao_atuacao":      {2023: "P4_a",   2024: "4.a",   2025: "4.a"},
    "fontes_dados":        {2023: "P4_b",   2024: "4.b",   2025: "4.b"},
    "linguagem_preferida": {2023: "P4_f",   2024: "4.f",   2025: "4.c"},  # DESLOCADO
    "banco_dados":         {2023: "P4_g",   2024: "4.g",   2025: "4.d"},  # DESLOCADO
    # 2023: rótulo de P4_h diz "preferida", mas os valores provam que é a
    # cloud usada no dia a dia (contém "On Premise" e "Cloud Própria").
    "cloud_dia_a_dia":     {2023: "P4_h",   2024: "4.h",   2025: "4.e"},  # DESLOCADO
    "cloud_preferida":     {2023: "P4_i",   2024: "4.i",   2025: "4.f"},  # DESLOCADO
    "bi_dia_a_dia":        {2023: "P4_j",   2024: "4.j",   2025: "4.g"},  # DESLOCADO
    "bi_preferida":        {2023: "P4_k",   2024: "4.k",   2025: "4.h"},  # DESLOCADO
    "tipo_uso_ia_area":    {2023: "P4_l",   2024: "4.l",   2025: "4.i"},  # DESLOCADO
    "usa_chatgpt_copilot": {2023: "P4_m",   2024: "4.m",   2025: "4.j"},  # DESLOCADO
}


# Dimensões em que o código difere entre pelo menos duas edições. Serve de
# checklist de revisão: são os pontos de risco do mapeamento.
DIMENSOES_DESLOCADAS = tuple(
    nome
    for nome, codigos in MAPEAMENTO.items()
    if len({c for c in codigos.values() if c is not None}.union(
        {c.replace("P", "").replace("_", ".") for c in codigos.values() if c}
    )) > 2
)


# ---------------------------------------------------------------------------
# Resolução de código -> nome real da coluna no CSV
# ---------------------------------------------------------------------------

def extrair_codigo(coluna: str) -> Optional[str]:
    """Extrai o código canônico de uma coluna bruta, em forma normalizada.

    Normaliza as duas convenções para um formato único com pontos e sem o
    prefixo 'P', de modo que 'P1_i_2' e '1.i.2' resultem ambos em '1.i.2'.

    Args:
        coluna: nome da coluna como aparece no CSV bruto.

    Returns:
        O código normalizado (ex.: '1.i.2', '4.f'), ou None se a coluna não
        seguir nenhuma das convenções conhecidas.
    """
    bruta = coluna.strip()

    # Convenção 2023: string de tupla "('P1_i_2 ', 'Regiao onde mora')"
    #
    # A extração é feita por regex, não por ast.literal_eval, porque 11 dos 399
    # cabeçalhos de 2023 não são literais Python válidos: o rótulo contém
    # apóstrofo, como em "Realizo construções de ETL's em ferramentas...".
    # O parser falharia nessas colunas e devolveria None silenciosamente.
    # Só o primeiro elemento da tupla interessa aqui, e ele é sempre bem
    # formado, então o regex é mais robusto e suficiente.
    if bruta.startswith("("):
        correspondencia = re.match(r"^\(\s*'P([A-Za-z0-9_]+)\s*'", bruta)
        if not correspondencia:
            return None
        return correspondencia.group(1).strip().replace("_", ".")

    # Convenção 2024/2025: "1.i.2_regiao_onde_mora"
    #
    # O separador entre código e rótulo é underscore nas perguntas raiz, mas
    # ESPAÇO nas colunas multi-escolha explodidas ("3.f.1 Colaboradores usando
    # AI generativa..."). São 30 colunas por edição nesse formato; aceitar
    # apenas underscore as deixaria sem código.
    correspondencia = re.match(r"^(\d+\.[a-z]+(?:\.\d+)?)[_ ]", bruta)
    return correspondencia.group(1) if correspondencia else None


def normalizar_codigo(codigo: str) -> str:
    """Converte um código do mapeamento para a forma normalizada com pontos."""
    return codigo.replace("P", "", 1).replace("_", ".") if codigo.startswith("P") else codigo


def construir_indice(colunas) -> Dict[str, str]:
    """Constrói um índice {código normalizado -> nome real da coluna}.

    Quando mais de uma coluna compartilha o mesmo código (caso das perguntas
    multi-escolha explodidas), a primeira ocorrência é mantida, que por
    convenção do dataset é a coluna raiz.

    Args:
        colunas: iterável com os nomes das colunas do CSV bruto.

    Returns:
        Dicionário de código normalizado para nome de coluna.
    """
    indice: Dict[str, str] = {}
    for coluna in colunas:
        codigo = extrair_codigo(coluna)
        if codigo is not None and codigo not in indice:
            indice[codigo] = coluna
    return indice


def resolver_colunas(colunas, ano: int) -> Dict[str, Optional[str]]:
    """Resolve o mapeamento canônico para os nomes reais de coluna de uma edição.

    Args:
        colunas: iterável com os nomes das colunas do CSV bruto da edição.
        ano: ano de início da edição (2023, 2024 ou 2025).

    Returns:
        Dicionário {nome canônico -> nome real da coluna, ou None se a
        dimensão não existir naquela edição}.

    Raises:
        ValueError: se o ano não estiver entre as edições suportadas.
    """
    if ano not in ANOS:
        raise ValueError(f"Edição não suportada: {ano}. Esperado um de {ANOS}.")

    indice = construir_indice(colunas)
    resolvido: Dict[str, Optional[str]] = {}
    for nome_canonico, codigos_por_ano in MAPEAMENTO.items():
        codigo = codigos_por_ano[ano]
        if codigo is None:
            resolvido[nome_canonico] = None
            continue
        resolvido[nome_canonico] = indice.get(normalizar_codigo(codigo))
    return resolvido
