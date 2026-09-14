"""Prepara o notebook executado para publicação sem dados do ambiente local.

O processo é idempotente: atualiza as explicações, acrescenta uma seção que
exibe o código-fonte canônico das transformações e higieniza somente saídas e
metadados de execução. A lógica analítica e seus resultados são preservados.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import nbformat

from src import config

CAMINHO_NOTEBOOK = config.RAIZ_PROJETO / "notebooks" / "pipeline_state_of_data.ipynb"
TAG_AUDITORIA = "codigo-fonte-auditavel"

# Detecta caminhos pessoais comuns que tenham escapado da substituição da raiz
# dinâmica. A construção em partes evita que o próprio validador seja marcado.
PADRAO_CAMINHO_PESSOAL = re.compile(
    r"(?:file://)?/" + r"(?:Users|home)/" + r"[^\s\"']+",
    flags=re.IGNORECASE,
)
PADRAO_CAMINHO_TEMPORARIO = re.compile(
    r"/(?:private/var|var/folders|tmp)/[^\s\"']+",
    flags=re.IGNORECASE,
)


def sanitizar_texto(texto: str) -> str:
    """Substitui caminhos reais por referências portáveis e não identificáveis."""
    sanitizado = texto.replace(str(config.RAIZ_PROJETO), ".")
    sanitizado = sanitizado.replace(config.NOME_BUCKET, "<BUCKET>")
    sanitizado = PADRAO_CAMINHO_PESSOAL.sub("<CAMINHO_LOCAL>", sanitizado)
    sanitizado = PADRAO_CAMINHO_TEMPORARIO.sub("<CAMINHO_TEMPORARIO>", sanitizado)
    return sanitizado


def _sanitizar_estrutura(valor: Any) -> Any:
    if isinstance(valor, str):
        return sanitizar_texto(valor)
    if isinstance(valor, list):
        for indice, item in enumerate(valor):
            valor[indice] = _sanitizar_estrutura(item)
        return valor
    if isinstance(valor, dict):
        # NotebookNode herda de dict; alterar no próprio objeto preserva os
        # atributos esperados internamente pelo nbformat.
        for chave in list(valor):
            valor[chave] = _sanitizar_estrutura(valor[chave])
        return valor
    return valor


def _atualizar_apresentacao(notebook) -> None:
    primeira = notebook.cells[0]
    primeira.source = primeira.source.replace(
        "O venv principal do workspace usa Python 3.14, incompatível com PySpark 3.5.x.",
        "Use Python 3.10 ou 3.11; o PySpark 3.5.x não é compatível com Python 3.12 ou superior.",
    )

    configuracao = next(celula for celula in notebook.cells if celula.get("id") == "44f9db11")
    configuracao.source = configuracao.source.replace(
        'print(f"raiz do projeto: {RAIZ}")',
        'print("raiz do projeto: diretório do repositório (caminho omitido)")',
    ).replace(
        'print(f"conta AWS: {config.ID_CONTA} · região: {config.REGIAO}")',
        'print(f"conta AWS: identificador omitido · região: {config.REGIAO}")',
    )

    gold = next(celula for celula in notebook.cells if celula.get("id") == "5089fc35")
    gold.source = gold.source.replace(
        "Oito tabelas, uma por pergunta de negócio do enunciado.",
        "Sete tabelas respondem às perguntas de negócio e `salario_medio` é uma tabela auxiliar.",
    )


def _adicionar_codigo_auditavel(notebook) -> None:
    if any(TAG_AUDITORIA in celula.get("metadata", {}).get("tags", []) for celula in notebook.cells):
        return

    indice_gold = next(
        indice for indice, celula in enumerate(notebook.cells)
        if celula.get("id") == "a18f5732"
    )

    explicacao = nbformat.v4.new_markdown_cell(
        """### 5.1 Código-fonte auditável das transformações

As células anteriores executam diretamente as funções canônicas de `src/`; os Glue Jobs usam as mesmas funções. Para tornar a implementação visível ao avaliador sem manter uma segunda cópia, a célula abaixo projeta automaticamente o código-fonte efetivamente importado.

Na execução local, a etapa Bronze lê e valida `data/raw`. Na AWS, `infra/ingerir_bronze.py` realiza o upload fiel para o S3, e o Glue Job lê o prefixo Bronze. Nenhum caminho absoluto do ambiente local é publicado."""
    )
    explicacao.metadata["tags"] = [TAG_AUDITORIA]

    codigo = nbformat.v4.new_code_cell(
        """import inspect

funcoes_auditadas = [
    bronze_para_silver.preparar_edicao,
    bronze_para_silver.harmonizar,
    multiescolha.extrair_multiescolha,
    silver_para_gold.agregar_multiescolha,
    silver_para_gold.construir_tabelas,
]

for funcao in funcoes_auditadas:
    print(f"\\n# {funcao.__module__}.{funcao.__name__}")
    print(inspect.getsource(funcao))"""
    )
    codigo.metadata["tags"] = [TAG_AUDITORIA]

    notebook.cells[indice_gold + 1:indice_gold + 1] = [explicacao, codigo]


def preparar(caminho: Path = CAMINHO_NOTEBOOK) -> Path:
    """Atualiza e higieniza o notebook de entrega no próprio arquivo."""
    notebook = nbformat.read(caminho, as_version=4)
    _atualizar_apresentacao(notebook)
    _adicionar_codigo_auditavel(notebook)

    for celula in notebook.cells:
        celula.metadata.pop("execution", None)
        if celula.cell_type == "code":
            celula.outputs = _sanitizar_estrutura(celula.get("outputs", []))

    notebook.metadata = _sanitizar_estrutura(notebook.metadata)
    nbformat.write(notebook, caminho)

    conteudo = caminho.read_text(encoding="utf-8")
    if (
        str(config.RAIZ_PROJETO) in conteudo
        or PADRAO_CAMINHO_PESSOAL.search(conteudo)
        or PADRAO_CAMINHO_TEMPORARIO.search(conteudo)
    ):
        raise RuntimeError("O notebook ainda contém referência a caminho local.")
    return caminho


def main() -> None:
    caminho = preparar()
    print(f"Notebook preparado para entrega: {caminho.name}")


if __name__ == "__main__":
    main()
