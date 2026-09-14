"""
Geração dos gráficos do material executivo a partir da camada Gold.

REGRAS QUE OS GRÁFICOS SEGUEM
-----------------------------
1. Leem exclusivamente a camada Gold. Nunca os CSVs brutos. Se um número do
   material executivo estiver errado, o erro está na Gold e é rastreável até a
   consulta que o produziu.

2. Faixa salarial é ordenada por `faixa_salarial_ordem`, nunca alfabeticamente.
   Sem isso, "de R$ 1.001" aparece ao lado de "de R$ 12.001".

3. Toda figura exibe a base (`n = ...`) no título ou no rótulo. Um percentual
   sem denominador é uma afirmação sem evidência, e a base varia muito entre
   perguntas: 3.228 respondentes para faixa salarial, 652 para prioridade de IA.

4. Quebras metodológicas conhecidas aparecem como nota no rodapé da figura,
   não apenas na documentação.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional

import matplotlib

# Backend sem interface gráfica: o script roda em terminal e em CI.
matplotlib.use("Agg")

import matplotlib.pyplot as plt
import pandas as pd

from src import config
from src.dominio import SENIORIDADE_EXCLUSIVA_2025

# Paleta com contraste suficiente para impressão em tons de cinza e para
# leitores com deficiência de visão de cores.
COR_PRIMARIA = "#1f4e79"
COR_SECUNDARIA = "#c55a11"
COR_TERCIARIA = "#7f7f7f"
CORES_EDICAO = {2023: "#a6c8e0", 2024: "#4a90c2", 2025: COR_PRIMARIA}

ROTULO_EDICAO = {2023: "2023-2024", 2024: "2024-2025", 2025: "2025-2026"}

plt.rcParams.update(
    {
        "figure.dpi": 130,
        "savefig.dpi": 130,
        "savefig.bbox": "tight",
        "font.size": 9,
        "axes.titlesize": 11,
        "axes.titleweight": "bold",
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.grid": True,
        "grid.alpha": 0.25,
        "grid.linestyle": "-",
    }
)


def carregar_gold(nome: str, raiz: Optional[Path] = None) -> pd.DataFrame:
    """Carrega uma tabela da camada Gold local.

    Args:
        nome: nome da tabela Gold.
        raiz: raiz do Data Lake. Quando omitido, usa a raiz local configurada.

    Returns:
        Tabela como DataFrame pandas.

    Raises:
        FileNotFoundError: se a tabela não tiver sido materializada.
    """
    base = raiz or config.RAIZ_LAKE_LOCAL
    caminho = base / config.CAMADA_GOLD / nome
    if not caminho.exists():
        raise FileNotFoundError(
            f"Tabela Gold '{nome}' não encontrada em {caminho}. "
            f"Execute o job Silver -> Gold antes de gerar os gráficos."
        )
    return pd.read_parquet(caminho)


def _anotar_rodape(figura, texto: str) -> None:
    """Escreve uma nota de rodapé na figura.

    Args:
        figura: figura do matplotlib.
        texto: texto da nota.
    """
    figura.text(
        0.01,
        -0.02,
        texto,
        fontsize=7,
        color=COR_TERCIARIA,
        ha="left",
        va="top",
        wrap=True,
    )


def _rotular_barras_horizontais(eixo, valores, sufixo: str = "%") -> None:
    """Escreve o valor ao final de cada barra horizontal.

    Args:
        eixo: eixo do matplotlib.
        valores: valores das barras.
        sufixo: sufixo a acrescentar ao número.
    """
    limite = max(valores) if len(valores) else 0
    for indice, valor in enumerate(valores):
        eixo.text(
            valor + limite * 0.015,
            indice,
            f"{valor:.1f}{sufixo}",
            va="center",
            fontsize=8,
        )


def _salvar(figura, nome_arquivo: str) -> Path:
    """Salva a figura no diretório de imagens e a fecha.

    Args:
        figura: figura do matplotlib.
        nome_arquivo: nome do arquivo, sem diretório.

    Returns:
        Caminho do arquivo salvo.
    """
    config.DIRETORIO_IMAGENS.mkdir(parents=True, exist_ok=True)
    destino = config.DIRETORIO_IMAGENS / nome_arquivo
    figura.savefig(destino)
    plt.close(figura)
    return destino


# ---------------------------------------------------------------------------
# Um gráfico por pergunta de negócio
# ---------------------------------------------------------------------------


def grafico_perfil_mercado() -> Path:
    """Pergunta 1: como está estruturado o mercado brasileiro de Dados?

    Returns:
        Caminho da imagem gerada.
    """
    dados = carregar_gold("perfil_mercado")
    recorte = dados[(dados.metrica == "cargo") & (dados.edicao == 2025)]
    recorte = recorte.nlargest(10, "percentual").sort_values("percentual")

    base = int(recorte.respondentes_validos.iloc[0])
    figura, eixo = plt.subplots(figsize=(8.5, 4.6))

    eixo.barh(recorte.categoria.str.slice(0, 44), recorte.percentual, color=COR_PRIMARIA)
    _rotular_barras_horizontais(eixo, recorte.percentual.values)
    eixo.set_xlabel("% dos profissionais que responderam")
    eixo.set_title(
        f"Cargos mais frequentes no mercado de dados — 2025-2026 (n = {base:,})".replace(
            ",", "."
        )
    )
    eixo.set_xlim(0, recorte.percentual.max() * 1.18)
    _anotar_rodape(
        figura,
        "Fonte: State of Data Brasil 2025-2026, camada Gold (perfil_mercado). "
        "Base: quem informou cargo atual.",
    )
    return _salvar(figura, "01_perfil_mercado.png")


def grafico_remuneracao() -> Path:
    """Pergunta 2: quais perfis são mais valorizados pelo mercado?

    Returns:
        Caminho da imagem gerada.
    """
    dados = carregar_gold("salario_medio")
    recorte = dados[
        (dados.recorte == "senioridade") & (~dados.fragil)
    ].sort_values(["edicao", "salario_medio"])

    ordem = ["Júnior", "Pleno", "Sênior", SENIORIDADE_EXCLUSIVA_2025]
    presentes = [nivel for nivel in ordem if nivel in set(recorte.categoria)]

    figura, eixo = plt.subplots(figsize=(8.5, 4.4))
    largura = 0.26

    for deslocamento, edicao in enumerate(sorted(recorte.edicao.unique())):
        por_edicao = recorte[recorte.edicao == edicao].set_index("categoria")
        valores = [
            por_edicao.salario_medio.get(nivel, float("nan")) for nivel in presentes
        ]
        posicoes = [indice + deslocamento * largura for indice in range(len(presentes))]
        eixo.bar(
            posicoes,
            valores,
            width=largura,
            label=ROTULO_EDICAO[edicao],
            color=CORES_EDICAO[edicao],
        )
        for posicao, valor in zip(posicoes, valores):
            if pd.notna(valor):
                eixo.text(
                    posicao,
                    valor + 300,
                    f"{valor / 1000:.1f}k",
                    ha="center",
                    fontsize=7.5,
                )

    eixo.set_xticks([indice + largura for indice in range(len(presentes))])
    eixo.set_xticklabels(presentes)
    eixo.set_ylabel("Salário médio estimado (R$/mês)")
    eixo.set_title("Salário médio estimado por senioridade, nas três edições")
    eixo.legend(frameon=False, fontsize=8)
    _anotar_rodape(
        figura,
        "Valores nominais, não corrigidos pela inflação. Estimativa pelo ponto médio "
        "das faixas salariais; a faixa superior é aberta, então os valores servem para "
        "comparar recortes, não como remuneração absoluta. "
        f"'{SENIORIDADE_EXCLUSIVA_2025}' existe apenas na edição 2025-2026. "
        "Recortes com menos de 30 respondentes foram omitidos.",
    )
    return _salvar(figura, "02_remuneracao_senioridade.png")


def grafico_diversidade() -> Path:
    """Pergunta 3: qual é o cenário de diversidade de gênero?

    Returns:
        Caminho da imagem gerada.
    """
    dados = carregar_gold("diversidade")
    recorte = dados[
        (dados.metrica == "genero_por_senioridade")
        & (dados.categoria == "Feminino")
        & (~dados.fragil)
    ]

    ordem = ["Júnior", "Pleno", "Sênior", SENIORIDADE_EXCLUSIVA_2025]
    figura, eixo = plt.subplots(figsize=(8.5, 4.4))

    for edicao in sorted(recorte.edicao.unique()):
        por_edicao = recorte[recorte.edicao == edicao].set_index("nivel_senioridade")
        presentes = [nivel for nivel in ordem if nivel in por_edicao.index]
        eixo.plot(
            presentes,
            [por_edicao.percentual[nivel] for nivel in presentes],
            marker="o",
            linewidth=2,
            label=ROTULO_EDICAO[edicao],
            color=CORES_EDICAO[edicao],
        )

    # Anota a base de cada nível na edição mais recente.
    recente = recorte[recorte.edicao == recorte.edicao.max()].set_index(
        "nivel_senioridade"
    )
    for nivel in ordem:
        if nivel in recente.index:
            eixo.annotate(
                f"n = {int(recente.respondentes_validos[nivel])}",
                (nivel, recente.percentual[nivel]),
                textcoords="offset points",
                xytext=(0, -16),
                ha="center",
                fontsize=7,
                color=COR_TERCIARIA,
            )

    eixo.set_ylabel("% de mulheres no nível")
    eixo.set_ylim(0, 35)
    eixo.set_title("Participação feminina cai conforme a senioridade aumenta")
    eixo.legend(frameon=False, fontsize=8)
    _anotar_rodape(
        figura,
        "Base: quem informou gênero e nível de senioridade. "
        f"O nível '{SENIORIDADE_EXCLUSIVA_2025}' existe apenas na edição 2025-2026, "
        "portanto a série de Sênior não é diretamente comparável entre edições.",
    )
    return _salvar(figura, "03_diversidade_senioridade.png")


def grafico_tecnologias() -> Path:
    """Pergunta 4: quais tecnologias apresentam maior adoção?

    Returns:
        Caminho da imagem gerada.
    """
    dados = carregar_gold("tecnologias")
    nuvem = dados[dados.dimensao == "cloud_dia_a_dia"]

    pivotado = nuvem.pivot_table(
        index="opcao", columns="edicao", values="percentual"
    ).sort_values(2025, ascending=True)
    # Mantém apenas os provedores relevantes, para não poluir com cauda longa.
    pivotado = pivotado[pivotado[2025] >= 3]

    figura, eixo = plt.subplots(figsize=(8.5, 4.4))
    altura = 0.26

    for deslocamento, edicao in enumerate(sorted(nuvem.edicao.unique())):
        posicoes = [indice + deslocamento * altura for indice in range(len(pivotado))]
        eixo.barh(
            posicoes,
            pivotado[edicao],
            height=altura,
            label=ROTULO_EDICAO[edicao],
            color=CORES_EDICAO[edicao],
        )

    eixo.set_yticks([indice + altura for indice in range(len(pivotado))])
    eixo.set_yticklabels([nome[:34] for nome in pivotado.index])
    eixo.set_xlabel("% de quem respondeu a pergunta")
    eixo.set_title("Adoção de cloud no dia a dia: AWS ultrapassa Azure entre 2023 e 2024")
    eixo.legend(frameon=False, fontsize=8, loc="lower right")

    base = int(nuvem[nuvem.edicao == 2025].respondentes_validos.iloc[0])
    _anotar_rodape(
        figura,
        f"Pergunta de múltipla escolha: a soma excede 100% porque um respondente pode "
        f"marcar vários provedores. Base 2025-2026: n = {base:,}.".replace(",", "."),
    )
    return _salvar(figura, "04_tecnologias_cloud.png")


def grafico_adocao_ia() -> Path:
    """Pergunta 5: qual é o índice de adoção de IA e seu impacto?

    Returns:
        Caminho da imagem gerada.
    """
    dados = carregar_gold("adocao_ia")
    uso = dados[(dados.dimensao == "usa_chatgpt_copilot") & (dados.edicao == 2025)]
    uso = uso.sort_values("percentual")

    base = int(uso.respondentes_validos.iloc[0])
    taxa = float(uso.taxa_resposta.iloc[0])

    figura, eixo = plt.subplots(figsize=(8.5, 4.2))
    rotulos = [
        texto.replace("soluções", "sol.").replace("produtividade", "produt.")[:52]
        for texto in uso.categoria
    ]
    cores = [
        COR_SECUNDARIA if "Não uso" in texto else COR_PRIMARIA for texto in uso.categoria
    ]
    eixo.barh(rotulos, uso.percentual, color=cores)
    _rotular_barras_horizontais(eixo, uso.percentual.values)

    eixo.set_xlabel("% de quem respondeu a pergunta")
    eixo.set_xlim(0, uso.percentual.max() * 1.2)
    eixo.set_title(
        f"Uso de IA generativa no trabalho — 2025-2026 (n = {base:,})".replace(",", ".")
    )
    _anotar_rodape(
        figura,
        f"Múltipla escolha: a soma excede 100%. A pergunta foi respondida por "
        f"{taxa:.1f}% da base total ({base:,} de 3.495), então o resultado descreve "
        f"quem atua tecnicamente, não o mercado inteiro.".replace(",", "."),
    )
    return _salvar(figura, "05_adocao_ia.png")


def grafico_recortes_regionais() -> Path:
    """Pergunta 6: existem diferenças entre regiões e modelos de trabalho?

    Returns:
        Caminho da imagem gerada.
    """
    concentracao = carregar_gold("recortes_comparativos")
    concentracao = concentracao[
        (concentracao.metrica == "regiao_geral") & (concentracao.edicao == 2025)
    ].sort_values("percentual", ascending=False)

    salarios = carregar_gold("salario_medio")
    salarios = salarios[
        (salarios.recorte == "regiao") & (salarios.edicao == 2025) & (~salarios.fragil)
    ].set_index("categoria")

    figura, (esquerda, direita) = plt.subplots(1, 2, figsize=(10.5, 4.2))

    esquerda.bar(concentracao.categoria, concentracao.percentual, color=COR_PRIMARIA)
    for indice, (_, linha) in enumerate(concentracao.iterrows()):
        esquerda.text(
            indice, linha.percentual + 1.2, f"{linha.percentual:.1f}%", ha="center", fontsize=8
        )
    esquerda.set_ylabel("% dos profissionais")
    esquerda.set_title("Onde estão os profissionais")
    esquerda.tick_params(axis="x", rotation=20)
    esquerda.set_ylim(0, concentracao.percentual.max() * 1.2)

    ordenados = [
        regiao for regiao in concentracao.categoria if regiao in salarios.index
    ]
    valores = [salarios.salario_medio[regiao] for regiao in ordenados]
    direita.bar(ordenados, valores, color=COR_SECUNDARIA)
    for indice, valor in enumerate(valores):
        direita.text(indice, valor + 250, f"{valor / 1000:.1f}k", ha="center", fontsize=8)
    direita.set_ylabel("Salário médio estimado (R$/mês)")
    direita.set_title("Quanto ganham")
    direita.tick_params(axis="x", rotation=20)
    direita.set_ylim(0, max(valores) * 1.2)

    base = int(concentracao.respondentes_validos.iloc[0])
    figura.suptitle(
        f"Concentração e remuneração por região — 2025-2026 (n = {base:,})".replace(
            ",", "."
        ),
        fontweight="bold",
    )
    _anotar_rodape(
        figura,
        "Regiões com menos de 30 respondentes foram omitidas do painel de salário. "
        "Salário estimado pelo ponto médio das faixas.",
    )
    return _salvar(figura, "06_recortes_regionais.png")


def grafico_modelo_trabalho() -> Path:
    """Pergunta 6 (complemento): distância entre modelo atual e ideal.

    Returns:
        Caminho da imagem gerada.
    """
    dados = carregar_gold("recortes_comparativos")
    recorte = dados[
        dados.metrica.isin(["modelo_trabalho_geral", "modelo_trabalho_ideal"])
        & (dados.edicao == 2025)
    ]

    pivotado = recorte.pivot_table(
        index="categoria", columns="metrica", values="percentual"
    ).fillna(0)
    pivotado = pivotado.assign(
        diferenca=(
            pivotado["modelo_trabalho_ideal"]
            - pivotado["modelo_trabalho_geral"]
        )
    )
    pivotado = pivotado.sort_values("modelo_trabalho_ideal")

    figura, eixo = plt.subplots(figsize=(8.5, 4.2))
    altura = 0.36
    posicoes = range(len(pivotado))
    rotulos = [
        nome.replace("Modelo ", "").replace(
            " (o funcionário tem liberdade para escolher quando estar no escritório presencialmente)",
            " (flexível)",
        )[:40]
        for nome in pivotado.index
    ]

    eixo.barh(
        [indice - altura / 2 for indice in posicoes],
        pivotado["modelo_trabalho_geral"],
        height=altura,
        label="Modelo atual",
        color=COR_TERCIARIA,
    )
    eixo.barh(
        [indice + altura / 2 for indice in posicoes],
        pivotado["modelo_trabalho_ideal"],
        height=altura,
        label="Modelo ideal",
        color=COR_PRIMARIA,
    )

    eixo.set_yticks(list(posicoes))
    eixo.set_yticklabels(rotulos)
    eixo.set_xlabel("% dos profissionais")
    eixo.set_title("Modelo de trabalho: o que existe contra o que se deseja")
    eixo.legend(frameon=False, fontsize=8, loc="lower right")

    base = int(recorte.respondentes_validos.iloc[0])
    _anotar_rodape(
        figura,
        f"Base: n = {base:,}. A distância entre as barras indica pressão de retenção — "
        f"20,8% trabalham 100% presencial, mas apenas 1,9% consideram esse o modelo "
        f"ideal.".replace(",", "."),
    )
    return _salvar(figura, "07_modelo_trabalho.png")


def grafico_oportunidades_desafios() -> Path:
    """Pergunta 7: quais oportunidades e desafios para quem investe em Dados e IA?

    Returns:
        Caminho da imagem gerada.
    """
    dados = carregar_gold("oportunidades_desafios")
    criterios = dados[
        (dados.dimensao == "criterios_escolha") & (dados.edicao == 2025) & (~dados.fragil)
    ].nlargest(8, "percentual").sort_values("percentual")

    base = int(criterios.respondentes_validos.iloc[0])
    figura, eixo = plt.subplots(figsize=(8.5, 4.4))

    eixo.barh(
        [texto[:46] for texto in criterios.categoria],
        criterios.percentual,
        color=COR_PRIMARIA,
    )
    _rotular_barras_horizontais(eixo, criterios.percentual.values)
    eixo.set_xlabel("% dos profissionais que responderam")
    eixo.set_xlim(0, criterios.percentual.max() * 1.16)
    eixo.set_title(
        f"O que pesa na escolha de um emprego — 2025-2026 (n = {base:,})".replace(
            ",", "."
        )
    )
    _anotar_rodape(
        figura,
        "Pergunta de múltipla escolha: a soma excede 100%. "
        "Base: quem respondeu aos critérios de escolha de emprego.",
    )
    return _salvar(figura, "08_criterios_escolha.png")


def grafico_barreiras_ia() -> Path:
    """Pergunta 7 (complemento): barreiras declaradas à adoção de IA.

    Returns:
        Caminho da imagem gerada.
    """
    dados = carregar_gold("adocao_ia")
    barreiras = dados[
        (dados.dimensao == "motivos_nao_usar_ia") & (dados.edicao == 2025) & (~dados.fragil)
    ].nlargest(8, "percentual").sort_values("percentual")

    base = int(barreiras.respondentes_validos.iloc[0])
    taxa = float(barreiras.taxa_resposta.iloc[0])

    figura, eixo = plt.subplots(figsize=(8.5, 4.4))
    eixo.barh(
        [texto[:48] for texto in barreiras.categoria],
        barreiras.percentual,
        color=COR_SECUNDARIA,
    )
    _rotular_barras_horizontais(eixo, barreiras.percentual.values)
    eixo.set_xlabel("% de quem respondeu a pergunta")
    eixo.set_xlim(0, barreiras.percentual.max() * 1.18)
    eixo.set_title(f"Barreiras à adoção de IA nas empresas — 2025-2026 (n = {base})")
    _anotar_rodape(
        figura,
        f"Pergunta da seção de gestão, respondida por {taxa:.1f}% da base total "
        f"(n = {base}). Múltipla escolha: a soma excede 100%. "
        f"O resultado descreve empresas com gestor respondente, não o mercado inteiro.",
    )
    return _salvar(figura, "09_barreiras_ia.png")


# ---------------------------------------------------------------------------
# Orquestração
# ---------------------------------------------------------------------------

GRAFICOS = (
    ("1. Estrutura do mercado", grafico_perfil_mercado),
    ("2. Perfis mais valorizados", grafico_remuneracao),
    ("3. Diversidade de gênero", grafico_diversidade),
    ("4. Adoção de tecnologias", grafico_tecnologias),
    ("5. Adoção de IA", grafico_adocao_ia),
    ("6. Recortes regionais", grafico_recortes_regionais),
    ("6. Modelo de trabalho", grafico_modelo_trabalho),
    ("7. Critérios de escolha", grafico_oportunidades_desafios),
    ("7. Barreiras à IA", grafico_barreiras_ia),
)


def gerar_todos() -> Dict[str, Path]:
    """Gera todos os gráficos do material executivo.

    Returns:
        Dicionário `{pergunta de negócio -> caminho da imagem}`.
    """
    print("=" * 78)
    print("GERAÇÃO DE GRÁFICOS — a partir da camada Gold")
    print("=" * 78)

    gerados: Dict[str, Path] = {}
    for rotulo, funcao in GRAFICOS:
        destino = funcao()
        gerados[rotulo] = destino
        tamanho = destino.stat().st_size / 1024
        print(f"  {rotulo:30} {destino.name:34} {tamanho:6.1f} KB")

    print("\n" + "=" * 78)
    print(f"{len(gerados)} gráficos em {config.DIRETORIO_IMAGENS.relative_to(config.RAIZ_PROJETO)}")
    print("=" * 78)
    return gerados


def main() -> None:
    """Ponto de entrada da geração de gráficos."""
    gerar_todos()


if __name__ == "__main__":
    main()
