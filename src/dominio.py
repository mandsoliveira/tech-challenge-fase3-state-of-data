"""
Constantes de domínio da pesquisa State of Data, livres de dependência de Spark.

POR QUE SEPARADO DE `normalizacao.py`
-------------------------------------
Estes valores descrevem o domínio: quais são as faixas salariais, quais erros
de digitação existem na origem, qual a ordem dos níveis de senioridade. São
fatos sobre os dados, não sobre o processamento.

Mantê-los aqui, sem importar Spark, permite que sejam usados por:

    - `transformacoes/normalizacao.py`  (pipeline PySpark)
    - `conferencia_cruzada.py`          (verificação independente em pandas)
    - testes                            (sem precisar de JVM)

A conferência cruzada precisa aplicar as mesmas correções de typo que o
pipeline aplica, mas deve chegar ao resultado por caminho de código
independente. Se ela importasse o módulo PySpark, perderia parte do valor como
verificação: um erro no módulo de transformação poderia contaminar as duas
pontas da comparação.
"""

from __future__ import annotations

from typing import Dict, Tuple

# ---------------------------------------------------------------------------
# Correções de erro de digitação na origem
# ---------------------------------------------------------------------------
# Cada correção afeta exatamente 1 respondente, confirmado por contagem nos
# arquivos brutos. Sem elas, viram categorias fantasma e quebram o parsing
# numérico da faixa (o intervalo "25.001 a 3.000" é inválido).

CORRECOES_FAIXA_SALARIAL: Dict[str, str] = {
    # Edição 2023-2024
    "de R$ 101/mês a R$ 2.000/mês": "de R$ 1.001/mês a R$ 2.000/mês",
    # Edição 2025-2026
    "de R$ 25.001/mês a R$ 3000/mês": "de R$ 25.001/mês a R$ 30.000/mês",
}

# ---------------------------------------------------------------------------
# Faixas salariais canônicas, em ordem crescente
# ---------------------------------------------------------------------------
# Tupla de (rótulo, ordem, ponto médio estimado em reais).
#
# O ponto médio das faixas fechadas é a média dos extremos. As duas faixas
# abertas recebem estimativa conservadora: "Menos de R$ 1.000" usa 500, e
# "Acima de R$ 40.001" usa 50.000 — valor deliberadamente moderado, porque a
# cauda superior é desconhecida e uma estimativa alta inflaria as médias.

FAIXAS_SALARIAIS: Tuple[Tuple[str, int, float], ...] = (
    ("Menos de R$ 1.000/mês", 1, 500.0),
    ("de R$ 1.001/mês a R$ 2.000/mês", 2, 1500.5),
    ("de R$ 2.001/mês a R$ 3.000/mês", 3, 2500.5),
    ("de R$ 3.001/mês a R$ 4.000/mês", 4, 3500.5),
    ("de R$ 4.001/mês a R$ 6.000/mês", 5, 5000.5),
    ("de R$ 6.001/mês a R$ 8.000/mês", 6, 7000.5),
    ("de R$ 8.001/mês a R$ 12.000/mês", 7, 10000.5),
    ("de R$ 12.001/mês a R$ 16.000/mês", 8, 14000.5),
    ("de R$ 16.001/mês a R$ 20.000/mês", 9, 18000.5),
    ("de R$ 20.001/mês a R$ 25.000/mês", 10, 22500.5),
    ("de R$ 25.001/mês a R$ 30.000/mês", 11, 27500.5),
    ("de R$ 30.001/mês a R$ 40.000/mês", 12, 35000.5),
    ("Acima de R$ 40.001/mês", 13, 50000.0),
)

QUANTIDADE_FAIXAS_ESPERADA: int = len(FAIXAS_SALARIAIS)  # 13

# ---------------------------------------------------------------------------
# Senioridade
# ---------------------------------------------------------------------------
# Ordem crescente. "Especialista/Staff+" aparece apenas na edição 2025-2026 e
# é posicionado acima de Sênior por representar trilha técnica superior.
#
# Ele é PRESERVADO, não agrupado em "Sênior". Agrupar tornaria a série
# comparável entre os três anos, mas esconderia uma mudança real do mercado: a
# criação de uma trilha de especialista. A quebra metodológica é sinalizada na
# camada Gold em vez de ser apagada na Silver.

NIVEIS_SENIORIDADE: Tuple[Tuple[str, int], ...] = (
    ("Júnior", 1),
    ("Pleno", 2),
    ("Sênior", 3),
    ("Especialista/Staff+", 4),
)

SENIORIDADE_EXCLUSIVA_2025: str = "Especialista/Staff+"

# ---------------------------------------------------------------------------
# Dimensões verificadas como consistentes entre edições
# ---------------------------------------------------------------------------
# Medidas como idênticas nas três edições. A verificação no pipeline existe
# para detectar se uma edição futura alterar as opções de resposta.

DIMENSOES_CONSISTENTES: Tuple[str, ...] = (
    "regiao_onde_mora",
    "genero",
    "modelo_trabalho_atual",
)

# ---------------------------------------------------------------------------
# Sentinelas de valor ausente presentes na origem
# ---------------------------------------------------------------------------
# Os CSVs brutos contêm strings literais representando "sem resposta" em
# algumas células, resultado da exportação da ferramenta de pesquisa:
#
#     2023: 8 colunas com "NA", "NULL" ou "N/A"
#     2024: 1 coluna com "n/a"
#     2025: 1 coluna com "N/A"
#
# O pandas nulifica esses valores por padrão; o Spark os lê como texto. Sem
# tratamento explícito, "NA" apareceria como categoria legítima — um gráfico de
# "ferramenta de BI preferida" listaria "NA" entre as ferramentas.
#
# A lista replica o conjunto default de valores nulos do pandas. Igualar os dois
# comportamentos é o que mantém a conferência cruzada válida como verificação:
# divergência passa a indicar erro de mapeamento, não diferença de engine.

SENTINELAS_NULO: Tuple[str, ...] = (
    "#N/A",
    "#N/A N/A",
    "#NA",
    "-1.#IND",
    "-1.#QNAN",
    "-NaN",
    "-nan",
    "1.#IND",
    "1.#QNAN",
    "<NA>",
    "N/A",
    "NA",
    "NULL",
    "NaN",
    "None",
    "n/a",
    "nan",
    "null",
)

# ---------------------------------------------------------------------------
# Perguntas de negócio do enunciado
# ---------------------------------------------------------------------------
# Usadas para rotular as tabelas da Gold e organizar o material executivo.

PERGUNTAS_DE_NEGOCIO: Dict[str, str] = {
    "perfil_mercado": "Como está estruturado o mercado brasileiro de Dados?",
    "remuneracao": "Quais perfis profissionais são mais valorizados pelo mercado?",
    "diversidade": "Qual é o cenário de diversidade de gênero nas carreiras de dados?",
    "tecnologias": "Quais tecnologias apresentam maior adoção entre os profissionais?",
    "adocao_ia": "Qual é o índice de adoção de Inteligência Artificial e seu impacto?",
    "recortes_comparativos": (
        "Existem diferenças relevantes entre regiões, senioridades ou modelos de trabalho?"
    ),
    "oportunidades_desafios": (
        "Quais oportunidades e desafios podem ser identificados para empresas "
        "que desejam investir em Dados e IA?"
    ),
}
