"""
Sanitização de nomes de coluna para compatibilidade com Glue Data Catalog e Athena.

POR QUE É NECESSÁRIO
--------------------
Nenhuma das 388 a 403 colunas das edições é utilizável no Athena como está.
Os nomes contêm pontos, barras, vírgulas, interrogações, parênteses, espaços,
acentos e maiúsculas:

    2023: "('P1_c ', 'Cor/raca/etnia')"
    2024: "3.e_ai_generativa_e_llm_é_uma_prioridade?"
    2025: "4.j.4 A empresa que trabalho paga pelas soluções de AI Generativa..."

O Athena aceita apenas `[a-z0-9_]` em nomes de coluna. Sem esta etapa, o Glue
Crawler cataloga as tabelas e as consultas falham no momento da leitura.

DECISÃO DE PROJETO
------------------
O código da pergunta é preservado no início do nome sanitizado. Isso mantém a
rastreabilidade até a origem, que é indispensável num dataset onde o mesmo
código significa perguntas diferentes em anos diferentes. Ao ver
`p2_q_empresa_que_trabaha_passou_por_layoff_em_2023` fica claro de qual
pergunta bruta o dado veio.
"""

from __future__ import annotations

import ast
import re
import unicodedata
from typing import Dict, List, Sequence, Tuple

# Limite de comprimento do nome sanitizado. O Glue Data Catalog aceita nomes
# longos, mas nomes muito extensos tornam as consultas SQL ilegíveis. O corte
# preserva o código da pergunta, que fica no início.
COMPRIMENTO_MAXIMO = 120


class ErroDeSanitizacao(RuntimeError):
    """Erro na sanitização de nomes de coluna."""


def _remover_acentuacao(texto: str) -> str:
    """Remove acentuação preservando as letras base.

    Usa decomposição canônica compatível (NFKD), que separa a letra do sinal
    diacrítico, e então descarta os sinais. Assim `ç` torna-se `c` e `é`
    torna-se `e`, em vez de serem removidos.

    Args:
        texto: texto de entrada.

    Returns:
        Texto sem sinais diacríticos.
    """
    decomposto = unicodedata.normalize("NFKD", texto)
    return "".join(caractere for caractere in decomposto if not unicodedata.combining(caractere))


def _desmontar_tupla_2023(nome: str) -> str:
    """Converte o nome em formato de tupla da edição 2023 em texto plano.

    A edição 2023 nomeia as colunas como a repr de uma tupla Python:
    `"('P1_a ', 'Idade')"`. Aqui a tupla é interpretada e seus dois elementos
    são unidos, produzindo `P1_a Idade`.

    Args:
        nome: nome bruto da coluna.

    Returns:
        Texto plano com código e rótulo unidos, ou o nome original se não for
        uma tupla interpretável.
    """
    bruto = nome.strip()
    if not bruto.startswith("("):
        return bruto

    # Tentativa preferencial: interpretar como tupla Python.
    try:
        elementos = ast.literal_eval(bruto)
        if isinstance(elementos, tuple):
            return " ".join(str(elemento).strip() for elemento in elementos)
    except (ValueError, SyntaxError):
        pass

    # 11 dos 399 cabeçalhos de 2023 não são literais Python válidos porque o
    # rótulo contém apóstrofo ("ETL's", "API's") ou parêntese desbalanceado.
    # Nesses casos, remove-se apenas a pontuação estrutural da tupla; a
    # sanitização subsequente cuida do resto.
    return bruto.strip("()").replace("'", " ").replace(",", " ")


def sanitizar_nome(nome: str) -> str:
    """Converte um nome de coluna bruto em nome compatível com o Athena.

    Etapas: desmonta o formato de tupla de 2023, remove acentuação, converte
    para minúsculas, substitui tudo que não seja alfanumérico por `_`, colapsa
    sequências de `_` e remove `_` das extremidades.

    Args:
        nome: nome bruto da coluna.

    Returns:
        Nome contendo apenas `[a-z0-9_]`.

    Raises:
        ErroDeSanitizacao: se o resultado ficar vazio, o que indicaria um nome
            de origem composto apenas de caracteres especiais.
    """
    texto = _desmontar_tupla_2023(nome)
    texto = _remover_acentuacao(texto).lower()
    texto = re.sub(r"[^a-z0-9]+", "_", texto)
    texto = re.sub(r"_+", "_", texto).strip("_")

    if len(texto) > COMPRIMENTO_MAXIMO:
        texto = texto[:COMPRIMENTO_MAXIMO].rstrip("_")

    if not texto:
        raise ErroDeSanitizacao(
            f"Sanitização de {nome!r} resultou em nome vazio. "
            f"O nome de origem não contém caracteres alfanuméricos."
        )
    return texto


def sanitizar_nomes(nomes: Sequence[str]) -> Tuple[Dict[str, str], List[Tuple[str, str]]]:
    """Sanitiza uma lista de nomes de coluna resolvendo colisões.

    Duas colunas distintas na origem podem produzir o mesmo nome sanitizado —
    por exemplo se diferirem apenas por acentuação ou pontuação. Nesse caso, a
    segunda em diante recebe sufixo numérico incremental, preservando a
    unicidade exigida pelo catálogo.

    Args:
        nomes: nomes brutos das colunas, na ordem original.

    Returns:
        Tupla com:
            - dicionário `{nome bruto -> nome sanitizado}`, preservando a ordem;
            - lista de colisões resolvidas, como `(nome bruto, nome final)`.

    Raises:
        ErroDeSanitizacao: se algum nome resultante não atender a `[a-z0-9_]+`.
    """
    mapa: Dict[str, str] = {}
    usados: Dict[str, int] = {}
    colisoes: List[Tuple[str, str]] = []

    for nome_bruto in nomes:
        base = sanitizar_nome(nome_bruto)

        if base in usados:
            usados[base] += 1
            final = f"{base}_{usados[base]}"
            colisoes.append((nome_bruto, final))
        else:
            usados[base] = 0
            final = base

        mapa[nome_bruto] = final

    invalidos = [valor for valor in mapa.values() if not re.fullmatch(r"[a-z0-9_]+", valor)]
    if invalidos:
        raise ErroDeSanitizacao(
            f"{len(invalidos)} nomes sanitizados não atendem ao padrão [a-z0-9_]+: "
            f"{invalidos[:5]}"
        )

    return mapa, colisoes


def validar_nomes_sanitizados(nomes: Sequence[str]) -> None:
    """Valida que todos os nomes atendem ao padrão exigido pelo Athena.

    Args:
        nomes: nomes a validar.

    Raises:
        ErroDeSanitizacao: se algum nome estiver fora do padrão `[a-z0-9_]+`
            ou se houver duplicatas.
    """
    fora_do_padrao = [nome for nome in nomes if not re.fullmatch(r"[a-z0-9_]+", nome)]
    if fora_do_padrao:
        raise ErroDeSanitizacao(
            f"{len(fora_do_padrao)} nomes fora do padrão [a-z0-9_]+: {fora_do_padrao[:5]}"
        )

    duplicados = {nome for nome in nomes if list(nomes).count(nome) > 1}
    if duplicados:
        raise ErroDeSanitizacao(f"Nomes duplicados após sanitização: {sorted(duplicados)[:5]}")
