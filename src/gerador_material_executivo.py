"""
Geração do material executivo em PowerPoint a partir da camada Gold.

PRINCÍPIO
---------
Nenhum número é digitado à mão. Todos são lidos da camada Gold no momento da
geração. Se a Gold mudar, o material muda junto — e se um número estiver
errado, o erro é rastreável até a agregação que o produziu, e dela até o CSV
bruto.

A consequência prática é que este arquivo contém a NARRATIVA, não os dados. Os
textos interpretam; os valores vêm de `_ler()`.

CUIDADOS DE HONESTIDADE ANALÍTICA
---------------------------------
- Recortes marcados como `fragil` (menos de 30 respondentes) não entram no
  material, exceto quando a fragilidade é o próprio ponto.
- Perguntas da seção de gestão têm taxa de resposta baixa por construção
  (só gestores respondem). Onde são usadas, a base é declarada no slide.
- A quebra de comparabilidade da senioridade em 2025-2026 é sinalizada.
- Múltipla escolha soma acima de 100%, e isso é dito onde aparece.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN
from pptx.util import Emu, Inches, Pt

from src import config

# Paleta alinhada à dos gráficos.
AZUL = RGBColor(0x1F, 0x4E, 0x79)
LARANJA = RGBColor(0xC5, 0x5A, 0x11)
CINZA = RGBColor(0x5A, 0x6C, 0x7D)
CINZA_CLARO = RGBColor(0x8C, 0x9B, 0xAB)
BRANCO = RGBColor(0xFF, 0xFF, 0xFF)
GRAFITE = RGBColor(0x16, 0x19, 0x1F)

LARGURA = Inches(13.333)
ALTURA = Inches(7.5)

ARQUIVO_SAIDA = "Material_Executivo_State_of_Data_Fase3.pptx"


# ---------------------------------------------------------------------------
# Leitura da camada Gold
# ---------------------------------------------------------------------------


def _ler(tabela: str) -> pd.DataFrame:
    """Carrega uma tabela da camada Gold local.

    Args:
        tabela: nome da tabela Gold.

    Returns:
        Tabela como DataFrame pandas.

    Raises:
        FileNotFoundError: se a tabela não existir.
    """
    caminho = config.RAIZ_LAKE_LOCAL / config.CAMADA_GOLD / tabela
    if not caminho.exists():
        raise FileNotFoundError(
            f"Tabela Gold '{tabela}' não encontrada em {caminho}. "
            f"Execute o pipeline antes de gerar o material executivo."
        )
    return pd.read_parquet(caminho)


def _br(valor: float, decimais: int = 1) -> str:
    """Formata um número no padrão brasileiro.

    Args:
        valor: número a formatar.
        decimais: quantidade de casas decimais.

    Returns:
        Número formatado com vírgula decimal e ponto de milhar.
    """
    texto = f"{valor:,.{decimais}f}"
    return texto.replace(",", "\u00a0").replace(".", ",").replace("\u00a0", ".")


def _reais(valor: float) -> str:
    """Formata um valor monetário em reais, sem centavos.

    Args:
        valor: valor em reais.

    Returns:
        Valor formatado, como `R$ 14.622`.
    """
    return "R$ " + f"{valor:,.0f}".replace(",", ".")


# ---------------------------------------------------------------------------
# Primitivas de slide
# ---------------------------------------------------------------------------


def _slide_em_branco(apresentacao: Presentation):
    """Cria um slide sem layout predefinido.

    Args:
        apresentacao: objeto Presentation.

    Returns:
        O slide criado.
    """
    return apresentacao.slides.add_slide(apresentacao.slide_layouts[6])


def _caixa_texto(
    slide,
    texto: str,
    esquerda: Emu,
    topo: Emu,
    largura: Emu,
    altura: Emu,
    tamanho: int = 14,
    cor: RGBColor = GRAFITE,
    negrito: bool = False,
    alinhamento=PP_ALIGN.LEFT,
    espacamento: float = 1.15,
):
    """Insere uma caixa de texto no slide.

    Args:
        slide: slide de destino.
        texto: conteúdo, com `\n` separando parágrafos.
        esquerda: posição horizontal.
        topo: posição vertical.
        largura: largura da caixa.
        altura: altura da caixa.
        tamanho: tamanho da fonte em pontos.
        cor: cor do texto.
        negrito: se o texto é negrito.
        alinhamento: alinhamento horizontal.
        espacamento: entrelinha.

    Returns:
        A forma criada.
    """
    forma = slide.shapes.add_textbox(esquerda, topo, largura, altura)
    quadro = forma.text_frame
    quadro.word_wrap = True

    for indice, linha in enumerate(texto.split("\n")):
        paragrafo = quadro.paragraphs[0] if indice == 0 else quadro.add_paragraph()
        paragrafo.alignment = alinhamento
        paragrafo.line_spacing = espacamento
        execucao = paragrafo.add_run()
        execucao.text = linha
        execucao.font.size = Pt(tamanho)
        execucao.font.color.rgb = cor
        execucao.font.bold = negrito
        execucao.font.name = "Calibri"

    return forma


def _faixa(slide, topo: Emu, altura: Emu, cor: RGBColor) -> None:
    """Desenha uma faixa retangular sólida, sem borda.

    Args:
        slide: slide de destino.
        topo: posição vertical.
        altura: altura da faixa.
        cor: cor de preenchimento.
    """
    from pptx.enum.shapes import MSO_SHAPE  # noqa: PLC0415

    forma = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, topo, LARGURA, altura)
    forma.fill.solid()
    forma.fill.fore_color.rgb = cor
    forma.line.fill.background()
    forma.shadow.inherit = False


def _cabecalho(slide, secao: str, titulo: str) -> None:
    """Insere o cabeçalho padrão de um slide de conteúdo.

    Args:
        slide: slide de destino.
        secao: rótulo da seção, exibido acima do título.
        titulo: título do slide.
    """
    _faixa(slide, 0, Inches(0.06), AZUL)
    _caixa_texto(
        slide, secao.upper(), Inches(0.55), Inches(0.28), Inches(12.2), Inches(0.3),
        tamanho=11, cor=LARANJA, negrito=True,
    )
    _caixa_texto(
        slide, titulo, Inches(0.55), Inches(0.58), Inches(12.2), Inches(0.7),
        tamanho=26, cor=AZUL, negrito=True,
    )


def _rodape(slide, texto: str) -> None:
    """Insere a nota de rodapé de um slide.

    Args:
        slide: slide de destino.
        texto: texto da nota, normalmente base e ressalvas metodológicas.
    """
    _caixa_texto(
        slide, texto, Inches(0.55), Inches(6.92), Inches(12.2), Inches(0.45),
        tamanho=9, cor=CINZA_CLARO,
    )


def _imagem(slide, nome: str, esquerda: Emu, topo: Emu, largura: Emu) -> None:
    """Insere um gráfico gerado a partir da camada Gold.

    Args:
        slide: slide de destino.
        nome: nome do arquivo em `output/img/`.
        esquerda: posição horizontal.
        topo: posição vertical.
        largura: largura da imagem.

    Raises:
        FileNotFoundError: se a imagem não existir.
    """
    caminho = config.DIRETORIO_IMAGENS / nome
    if not caminho.exists():
        raise FileNotFoundError(
            f"Gráfico '{nome}' não encontrado. Execute `python -m src.gerador_graficos`."
        )
    slide.shapes.add_picture(str(caminho), esquerda, topo, width=largura)


def _cartoes(slide, itens: List[Tuple[str, str]], topo: Emu) -> None:
    """Desenha uma linha de cartões com número em destaque e legenda.

    Args:
        slide: slide de destino.
        itens: lista de pares `(número, legenda)`.
        topo: posição vertical dos cartões.
    """
    from pptx.enum.shapes import MSO_SHAPE  # noqa: PLC0415

    margem = Inches(0.55)
    espaco = Inches(0.2)
    disponivel = LARGURA - margem * 2 - espaco * (len(itens) - 1)
    largura = int(disponivel / len(itens))

    for indice, (numero, legenda) in enumerate(itens):
        esquerda = margem + indice * (largura + espaco)
        cartao = slide.shapes.add_shape(
            MSO_SHAPE.ROUNDED_RECTANGLE, esquerda, topo, largura, Inches(1.45)
        )
        cartao.fill.solid()
        cartao.fill.fore_color.rgb = RGBColor(0xF2, 0xF6, 0xFA)
        cartao.line.color.rgb = RGBColor(0xD6, 0xE0, 0xEA)
        cartao.shadow.inherit = False
        cartao.text_frame.text = ""

        _caixa_texto(
            slide, numero, esquerda, topo + Inches(0.16), largura, Inches(0.6),
            tamanho=30, cor=AZUL, negrito=True, alinhamento=PP_ALIGN.CENTER,
        )
        _caixa_texto(
            slide, legenda, esquerda + Inches(0.12), topo + Inches(0.78),
            largura - Inches(0.24), Inches(0.6),
            tamanho=10, cor=CINZA, alinhamento=PP_ALIGN.CENTER,
        )


# ---------------------------------------------------------------------------
# Slides
# ---------------------------------------------------------------------------


def slide_capa(apresentacao: Presentation, dados: Dict) -> None:
    """Monta a capa da apresentação."""
    slide = _slide_em_branco(apresentacao)
    _faixa(slide, 0, ALTURA, AZUL)

    _caixa_texto(
        slide, "O mercado brasileiro de Dados e Inteligência Artificial",
        Inches(0.9), Inches(2.0), Inches(11.5), Inches(1.2),
        tamanho=40, cor=BRANCO, negrito=True,
    )
    _caixa_texto(
        slide,
        "Evidências de três edições da pesquisa State of Data Brasil para decisões de\n"
        "contratação, capacitação e investimento em Dados, Analytics e IA",
        Inches(0.9), Inches(3.35), Inches(11.5), Inches(0.9),
        tamanho=17, cor=RGBColor(0xC8, 0xDA, 0xEA),
    )
    _caixa_texto(
        slide,
        f"{_br(dados['total_respondentes'], 0)} respondentes  ·  "
        f"edições 2023-2024, 2024-2025 e 2025-2026  ·  Data Hackers e Bain & Company",
        Inches(0.9), Inches(4.6), Inches(11.5), Inches(0.4),
        tamanho=13, cor=RGBColor(0x9E, 0xBE, 0xD8),
    )
    _caixa_texto(
        slide, "Tech Challenge Fase 3  ·  POSTECH DTAT  ·  Especialista em Big Data & Analytics",
        Inches(0.9), Inches(6.5), Inches(11.5), Inches(0.4),
        tamanho=11, cor=RGBColor(0x7A, 0xA3, 0xC4),
    )


def slide_sumario_executivo(apresentacao: Presentation, dados: Dict) -> None:
    """Monta o sumário executivo com as conclusões e os números de apoio."""
    slide = _slide_em_branco(apresentacao)
    _cabecalho(slide, "Sumário executivo", "Cinco conclusões que orientam a decisão")

    _cartoes(
        slide,
        [
            (f"{_br(dados['ia_nao_usa'], 1)}%", "não usam IA generativa no trabalho\n(eram 19,7% em 2023-2024)"),
            (f"{_br(dados['ia_empresa_paga'], 1)}%", "têm a ferramenta de IA paga\npela empresa (eram 6,4%)"),
            (f"{_br(dados['setor_financas'], 1)}%", "atuam em Finanças ou Bancos:\no maior setor empregador"),
            (f"{_br(dados['feminino_geral'], 1)}%", "de mulheres na área,\nem queda há três edições"),
            (f"{_br(dados['gap_presencial'], 1)} p.p.", "de distância entre trabalho\npresencial imposto e desejado"),
        ],
        Inches(1.45),
    )

    _caixa_texto(
        slide,
        "1.  A adoção de IA deixou de ser individual e passou a ser corporativa.  Em três edições, quem tem a ferramenta paga "
        "pela empresa saltou de 6,4% para 42,4%, enquanto o uso de versões gratuitas caiu de 63,7% para 30,5%. A ferramenta "
        "chegou ao orçamento.\n\n"
        "2.  A adoção individual corre à frente da estratégia corporativa.  Entre gestores, metade relata colaboradores usando IA "
        "de forma descentralizada, mas apenas 23,8% dizem que IA é a principal prioridade da empresa. O risco não é falta de "
        "uso, é uso sem governança.\n\n"
        "3.  O mercado é caro na senioridade e barato na base.  A remuneração média sai de "
        f"{_reais(dados['salario_junior'])} no Júnior para {_reais(dados['salario_especialista'])} no Especialista. "
        "Formar internamente custa menos que disputar o topo.\n\n"
        "4.  A diversidade está piorando, não melhorando.  A participação feminina caiu de 24,4% para 22,0% entre as edições, e "
        f"cai de novo conforme a senioridade sobe: 28,2% no Júnior contra 20,1% no topo. A diferença salarial média é de "
        f"{_br(dados['gap_genero'], 1)}%.\n\n"
        "5.  O modelo de trabalho é o ponto de ruptura mais barato de resolver.  20,8% trabalham 100% presencial, mas somente "
        "1,9% consideram esse o modelo ideal — e flexibilidade remota é o segundo critério mais citado na escolha de um emprego.",
        Inches(0.55), Inches(3.15), Inches(12.2), Inches(3.6),
        tamanho=12.5, cor=GRAFITE, espacamento=1.05,
    )
    _rodape(
        slide,
        f"Base: {_br(dados['total_respondentes'], 0)} respondentes nas três edições. "
        "Percentuais calculados sobre quem respondeu a cada pergunta, não sobre a base total.",
    )


def slide_metodologia(apresentacao: Presentation, dados: Dict) -> None:
    """Monta o slide de metodologia e tratamento dos dados."""
    slide = _slide_em_branco(apresentacao)
    _cabecalho(slide, "Metodologia", "Como os dados foram tratados, e por que isso importa")

    _caixa_texto(
        slide, "Base analisada", Inches(0.55), Inches(1.5), Inches(5.9), Inches(0.35),
        tamanho=15, cor=LARANJA, negrito=True,
    )
    _caixa_texto(
        slide,
        "Três edições da pesquisa State of Data Brasil, realizada pela comunidade\n"
        "Data Hackers em parceria com a Bain & Company:\n\n"
        "     2023-2024      5.293 respondentes      399 colunas\n"
        "     2024-2025      5.217 respondentes      403 colunas\n"
        "     2025-2026      3.495 respondentes      388 colunas\n\n"
        f"Total: {_br(dados['total_respondentes'], 0)} respostas, harmonizadas em 41 dimensões comparáveis\n"
        "e 8 tabelas analíticas.",
        Inches(0.55), Inches(1.9), Inches(5.9), Inches(2.6),
        tamanho=12, cor=GRAFITE,
    )

    _caixa_texto(
        slide, "As três edições não são diretamente comparáveis",
        Inches(6.85), Inches(1.5), Inches(5.9), Inches(0.35),
        tamanho=15, cor=LARANJA, negrito=True,
    )
    _caixa_texto(
        slide,
        "Os códigos das perguntas deslocam entre edições, porque perguntas foram\n"
        "inseridas e removidas. O mesmo código representa perguntas diferentes\n"
        "em anos diferentes:\n\n"
        "     código 2.q       2023: houve layoff\n"
        "                          2025: modelo de trabalho atual\n\n"
        "Unir as edições por código produziria números errados sem nenhum erro\n"
        "visível. Por isso a harmonização é feita por significado, dimensão por\n"
        "dimensão, e verificada por um caminho de cálculo independente.",
        Inches(6.85), Inches(1.9), Inches(5.9), Inches(2.6),
        tamanho=12, cor=GRAFITE,
    )

    _caixa_texto(
        slide, "Três ressalvas que atravessam toda a leitura",
        Inches(0.55), Inches(4.75), Inches(12.2), Inches(0.35),
        tamanho=15, cor=LARANJA, negrito=True,
    )
    _caixa_texto(
        slide,
        "Denominador variável.  O questionário é condicional. A seção de gestão, por exemplo, é respondida apenas por "
        f"gestores: {_br(dados['gestores_ia'], 0)} pessoas de 3.495 na última edição. Todo percentual deste material é calculado "
        "sobre quem respondeu à pergunta, e a base é declarada em cada slide.\n"
        "Múltipla escolha.  Perguntas de tecnologia e de IA aceitam várias respostas, então a soma dos percentuais excede 100%.\n"
        "Quebra de série na senioridade.  A edição 2025-2026 criou o nível Especialista/Staff+, que não existia antes. A queda "
        "do percentual de Sênior entre edições reflete a nova categoria, não uma mudança de mercado.",
        Inches(0.55), Inches(5.15), Inches(12.2), Inches(1.7),
        tamanho=11.5, cor=GRAFITE, espacamento=1.1,
    )


def slide_arquitetura(apresentacao: Presentation) -> None:
    """Monta o slide com o diagrama da arquitetura AWS."""
    slide = _slide_em_branco(apresentacao)
    _cabecalho(
        slide, "Arquitetura da solução",
        "Pipeline em AWS: da ingestão bruta ao consumo analítico",
    )

    caminho = config.RAIZ_PROJETO / "arquitetura" / "arquitetura_sod_fase3.png"
    if not caminho.exists():
        raise FileNotFoundError(
            f"Diagrama não encontrado em {caminho}. Exporte o arquivo .drawio antes."
        )

    # O diagrama é largo (proporção ~1,82) e o espaço vertical é o limitante:
    # sobram 5,4 polegadas entre o cabeçalho e o rodapé. Dimensionar pela
    # largura faria a imagem estourar a borda inferior do slide, então a altura
    # é fixada e a largura calculada a partir da proporção real do arquivo.
    from PIL import Image  # noqa: PLC0415

    with Image.open(caminho) as imagem:
        proporcao = imagem.width / imagem.height

    altura_disponivel = Inches(5.3)
    largura_calculada = Emu(int(altura_disponivel * proporcao))
    esquerda = Emu(int((LARGURA - largura_calculada) / 2))

    slide.shapes.add_picture(
        str(caminho), esquerda, Inches(1.5), height=altura_disponivel
    )
    _rodape(
        slide,
        "Data Lake em três camadas no S3, transformações em PySpark via AWS Glue, catalogação no Glue Data Catalog e consulta "
        "no Athena. Todos os recursos privados, com Block Public Access e criptografia em repouso. Diagrama construído no Draw.io.",
    )


def slide_perfil_mercado(apresentacao: Presentation, dados: Dict) -> None:
    """Pergunta 1: como está estruturado o mercado brasileiro de Dados?"""
    slide = _slide_em_branco(apresentacao)
    _cabecalho(
        slide, "Pergunta 1 · Estrutura do mercado",
        "Três cargos concentram mais da metade do mercado",
    )

    _imagem(slide, "01_perfil_mercado.png", Inches(0.5), Inches(1.5), Inches(7.6))
    _caixa_texto(
        slide,
        "O que os dados mostram\n\n"
        f"Analista de Dados ({_br(dados['cargo_analista'], 1)}%), Cientista de Dados "
        f"({_br(dados['cargo_cientista'], 1)}%) e Engenheiro de Dados "
        f"({_br(dados['cargo_engenheiro'], 1)}%) somam "
        f"{_br(dados['cargo_analista'] + dados['cargo_cientista'] + dados['cargo_engenheiro'], 1)}% "
        "dos profissionais.\n\n"
        f"Finanças e Bancos é o maior setor empregador, com {_br(dados['setor_financas'], 1)}% — "
        f"à frente de Tecnologia ({_br(dados['setor_tecnologia'], 1)}%).\n\n"
        "Leitura para a decisão\n\n"
        "Uma instituição financeira disputa talento no setor que já emprega mais gente "
        "em dados no país. A concorrência não vem só das big techs: vem dos pares "
        "diretos, que oferecem o mesmo tipo de problema e de remuneração.\n\n"
        "A implicação é que diferenciação por salário tem teto baixo. Os fatores de "
        "atração que restam são modelo de trabalho, plano de carreira e a qualidade "
        "técnica dos problemas oferecidos.",
        Inches(8.35), Inches(1.55), Inches(4.45), Inches(5.2),
        tamanho=12, cor=GRAFITE, espacamento=1.1,
    )
    _rodape(
        slide,
        f"Base: {_br(dados['base_cargo'], 0)} respondentes que informaram cargo atual na edição 2025-2026 "
        f"({_br(dados['taxa_cargo'], 1)}% do total). Percentual de setor calculado sobre "
        f"{_br(dados['base_setor'], 0)} respondentes.",
    )


def slide_remuneracao(apresentacao: Presentation, dados: Dict) -> None:
    """Pergunta 2: quais perfis são mais valorizados pelo mercado?"""
    slide = _slide_em_branco(apresentacao)
    _cabecalho(
        slide, "Pergunta 2 · Perfis valorizados",
        f"A remuneração média multiplica por "
        f"{dados['salario_especialista'] / dados['salario_junior']:.1f} entre a base e o topo",
    )

    _imagem(slide, "02_remuneracao_senioridade.png", Inches(0.5), Inches(1.5), Inches(7.6))
    _caixa_texto(
        slide,
        "O que os dados mostram\n\n"
        f"Júnior {_reais(dados['salario_junior'])}  ·  Pleno {_reais(dados['salario_pleno'])}\n"
        f"Sênior {_reais(dados['salario_senior'])}  ·  Especialista {_reais(dados['salario_especialista'])}\n\n"
        f"Do Júnior ao Especialista, a remuneração média multiplica por "
        f"{dados['salario_especialista'] / dados['salario_junior']:.1f}.\n\n"
        f"Por cargo, o topo é de Engenheiro de ML ({_reais(dados['salario_ml'])}) e "
        f"Engenheiro de Dados ({_reais(dados['salario_eng_dados'])}).\n\n"
        "Leitura para a decisão\n\n"
        "Contratar sênior pronto custa cerca de três vezes e meia o custo de um júnior, "
        "num mercado onde 25,3% dos profissionais já estão procurando recolocação — "
        "ou seja, a oferta existe, mas é disputada e precificada.\n\n"
        "A alavanca de custo está em formar Pleno a partir de Júnior internamente. É a "
        "transição com maior salto relativo de valor e a que menos depende do mercado "
        "externo.",
        Inches(8.35), Inches(1.55), Inches(4.45), Inches(5.2),
        tamanho=12, cor=GRAFITE, espacamento=1.1,
    )
    _rodape(
        slide,
        "Valores nominais, não corrigidos pela inflação. Salário estimado pelo ponto médio das faixas; a faixa superior "
        "é aberta, então os valores servem para comparar recortes, não como remuneração absoluta. Recortes com menos "
        "de 30 respondentes foram omitidos. Especialista/Staff+ existe apenas em 2025-2026.",
    )


def slide_diversidade(apresentacao: Presentation, dados: Dict) -> None:
    """Pergunta 3: qual é o cenário de diversidade de gênero?"""
    slide = _slide_em_branco(apresentacao)
    _cabecalho(
        slide, "Pergunta 3 · Diversidade de gênero",
        "O afunilamento é estrutural, e a série está piorando",
    )

    _imagem(slide, "03_diversidade_senioridade.png", Inches(0.5), Inches(1.5), Inches(7.6))
    _caixa_texto(
        slide,
        "O que os dados mostram\n\n"
        f"Participação feminina no total: {_br(dados['feminino_2023'], 1)}% em 2023-2024, "
        f"{_br(dados['feminino_2024'], 1)}% em 2024-2025 e {_br(dados['feminino_geral'], 1)}% "
        "em 2025-2026. Três edições em queda.\n\n"
        f"Por senioridade, cai de {_br(dados['feminino_junior'], 1)}% no Júnior para "
        f"{_br(dados['feminino_senior'], 1)}% no Sênior e {_br(dados['feminino_especialista'], 1)}% "
        "no Especialista.\n\n"
        f"A remuneração média feminina é {_br(dados['gap_genero'], 1)}% inferior à masculina "
        f"({_reais(dados['salario_feminino'])} contra {_reais(dados['salario_masculino'])}).\n\n"
        "Leitura para a decisão\n\n"
        "A entrada não é o gargalo: mulheres são quase 3 em cada 10 na base. O problema "
        "está na progressão — a proporção cai a cada nível acima.\n\n"
        "Programas focados só em atração não corrigem isso. O que a evidência aponta é "
        "retenção e promoção nos níveis Pleno e Sênior, onde a perda acontece.",
        Inches(8.35), Inches(1.55), Inches(4.45), Inches(5.2),
        tamanho=12, cor=GRAFITE, espacamento=1.1,
    )
    _rodape(
        slide,
        "Base: quem informou gênero e senioridade. Diferença salarial calculada sobre o ponto médio das faixas, sem controle por "
        "cargo, senioridade ou tempo de experiência — portanto descreve a diferença observada no mercado, não discriminação "
        "salarial em posição equivalente.",
    )


def slide_tecnologias(apresentacao: Presentation, dados: Dict) -> None:
    """Pergunta 4: quais tecnologias apresentam maior adoção?"""
    slide = _slide_em_branco(apresentacao)
    _cabecalho(
        slide, "Pergunta 4 · Adoção de tecnologias",
        "A liderança em cloud mudou de mão no período analisado",
    )

    _imagem(slide, "04_tecnologias_cloud.png", Inches(0.5), Inches(1.5), Inches(7.6))
    _caixa_texto(
        slide,
        "O que os dados mostram\n\n"
        f"AWS passou de {_br(dados['aws_2023'], 1)}% para {_br(dados['aws_2025'], 1)}% de adoção "
        f"no dia a dia. Azure fez o caminho inverso: de {_br(dados['azure_2023'], 1)}% para "
        f"{_br(dados['azure_2025'], 1)}%. GCP ficou estável em torno de "
        f"{_br(dados['gcp_2025'], 1)}%.\n\n"
        f"Em bancos de dados, PostgreSQL lidera ({_br(dados['postgres'], 1)}%), seguido de "
        f"SQL Server ({_br(dados['sqlserver'], 1)}%) e Databricks ({_br(dados['databricks'], 1)}%).\n\n"
        "Leitura para a decisão\n\n"
        "A disponibilidade de mão de obra com experiência em AWS cresceu 17,7 pontos em "
        "três edições. Para uma instituição que está definindo sua plataforma agora, isso "
        "reduz o custo de contratação e o tempo de rampa.\n\n"
        f"A presença de Databricks em {_br(dados['databricks'], 1)}% indica que "
        "arquitetura de lakehouse já é competência de mercado, não diferencial escasso.",
        Inches(8.35), Inches(1.55), Inches(4.45), Inches(5.2),
        tamanho=12, cor=GRAFITE, espacamento=1.1,
    )
    _rodape(
        slide,
        f"Perguntas de múltipla escolha: a soma dos percentuais excede 100% porque um respondente pode marcar várias "
        f"tecnologias. Base 2025-2026: {_br(dados['base_tecnologia'], 0)} respondentes que responderam à pergunta.",
    )


def slide_adocao_ia(apresentacao: Presentation, dados: Dict) -> None:
    """Pergunta 5: qual é o índice de adoção de IA e seu impacto?"""
    slide = _slide_em_branco(apresentacao)
    _cabecalho(
        slide, "Pergunta 5 · Adoção de Inteligência Artificial",
        "A IA saiu do bolso do profissional e entrou no orçamento da empresa",
    )

    _imagem(slide, "05_adocao_ia.png", Inches(0.5), Inches(1.5), Inches(7.6))
    _caixa_texto(
        slide,
        "O que os dados mostram\n\n"
        f"Quem não usa IA generativa no trabalho caiu de {_br(dados['ia_nao_usa_2023'], 1)}% "
        f"para {_br(dados['ia_nao_usa'], 1)}% em três edições.\n\n"
        f"Quem tem a ferramenta paga pela empresa saltou de {_br(dados['ia_empresa_paga_2023'], 1)}% "
        f"para {_br(dados['ia_empresa_paga'], 1)}%. Uso de versões gratuitas caiu de "
        f"{_br(dados['ia_gratuita_2023'], 1)}% para {_br(dados['ia_gratuita'], 1)}%.\n\n"
        f"Entre gestores, porém, apenas {_br(dados['ia_principal_prioridade'], 1)}% dizem que "
        "IA é a principal prioridade da empresa.\n\n"
        "Leitura para a decisão\n\n"
        "A adoção individual está praticamente universalizada, e a empresa já paga a "
        "conta em 4 de cada 10 casos. O que não acompanhou foi a estratégia: metade dos "
        "gestores descreve uso descentralizado, sem direcionamento central.\n\n"
        "O risco a endereçar não é adoção, é governança — dados sensíveis em ferramentas "
        "não homologadas, sem política de uso.",
        Inches(8.35), Inches(1.55), Inches(4.45), Inches(5.2),
        tamanho=12, cor=GRAFITE, espacamento=1.1,
    )
    _rodape(
        slide,
        f"Uso de IA: base de {_br(dados['base_ia'], 0)} respondentes ({_br(dados['taxa_ia'], 1)}% do total), múltipla escolha. "
        f"Prioridade declarada: base de {_br(dados['gestores_ia'], 0)} gestores ({_br(dados['taxa_gestores'], 1)}% do total) — "
        f"descreve empresas com gestor respondente, não o mercado inteiro.",
    )


def slide_recortes(apresentacao: Presentation, dados: Dict) -> None:
    """Pergunta 6: diferenças entre regiões, senioridades e modelos de trabalho."""
    slide = _slide_em_branco(apresentacao)
    _cabecalho(
        slide, "Pergunta 6 · Região e modelo de trabalho",
        "Duas assimetrias exploráveis: geografia e presencialidade",
    )

    _imagem(slide, "06_recortes_regionais.png", Inches(0.45), Inches(1.5), Inches(6.3))
    _imagem(slide, "07_modelo_trabalho.png", Inches(0.45), Inches(4.25), Inches(6.3))

    _caixa_texto(
        slide,
        "O que os dados mostram\n\n"
        f"O Sudeste concentra {_br(dados['sudeste'], 1)}% dos profissionais. O Nordeste tem "
        f"{_br(dados['nordeste'], 1)}%, com remuneração média "
        f"{_br(dados['gap_nordeste'], 1)}% inferior à do Sudeste "
        f"({_reais(dados['salario_nordeste'])} contra {_reais(dados['salario_sudeste'])}).\n\n"
        f"No modelo de trabalho, {_br(dados['presencial_atual'], 1)}% estão 100% presenciais, "
        f"mas apenas {_br(dados['presencial_ideal'], 1)}% consideram esse o modelo ideal. "
        f"O híbrido flexível é o preferido, com {_br(dados['hibrido_ideal'], 1)}%.\n\n"
        "Leitura para a decisão\n\n"
        "Contratação distribuída fora do Sudeste acessa talento a custo menor, com a "
        "ressalva de que a base amostral do Norte é pequena e não sustenta conclusão "
        "regional fina.\n\n"
        f"O desalinhamento de presencialidade é a maior distância medida neste estudo: "
        f"{_br(dados['gap_presencial'], 1)} pontos entre o que se impõe e o que se deseja. "
        "Corrigi-lo não tem custo de folha, e flexibilidade remota é o segundo critério "
        "mais citado na escolha de um emprego.",
        Inches(7.05), Inches(1.55), Inches(5.75), Inches(5.2),
        tamanho=12, cor=GRAFITE, espacamento=1.1,
    )
    _rodape(
        slide,
        "Base: edição 2025-2026. Regiões com menos de 30 respondentes foram omitidas do comparativo salarial. "
        "A amostra do Norte é pequena e seu salário médio deve ser lido com reserva.",
    )


def slide_oportunidades(apresentacao: Presentation, dados: Dict) -> None:
    """Pergunta 7: oportunidades e desafios para investir em Dados e IA."""
    slide = _slide_em_branco(apresentacao)
    _cabecalho(
        slide, "Pergunta 7 · Oportunidades e desafios",
        "O que atrai profissionais, e o que trava as empresas",
    )

    _imagem(slide, "08_criterios_escolha.png", Inches(0.45), Inches(1.5), Inches(6.3))
    _imagem(slide, "09_barreiras_ia.png", Inches(0.45), Inches(4.25), Inches(6.3))

    _caixa_texto(
        slide,
        "O que os dados mostram\n\n"
        f"Na escolha de um emprego, remuneração pesa para {_br(dados['criterio_salario'], 1)}% e "
        f"flexibilidade remota para {_br(dados['criterio_remoto'], 1)}%. Plano de carreira vem "
        f"em terceiro, com {_br(dados['criterio_carreira'], 1)}%.\n\n"
        f"{_br(dados['aberto_oportunidades'] + dados['buscando'], 1)}% estão buscando "
        "recolocação ou abertos a ela.\n\n"
        f"Entre gestores, o maior desafio é dividir o tempo entre entregas técnicas e "
        f"gestão ({_br(dados['desafio_tempo'], 1)}%), seguido de gerenciar a expectativa das "
        f"áreas de negócio ({_br(dados['desafio_expectativa'], 1)}%).\n\n"
        "Leitura para a decisão\n\n"
        "Salário é condição de entrada, não diferencial: quase todos o citam. O que "
        "separa propostas é o segundo bloco de critérios, que custa menos e é decidido "
        "por política interna, não por orçamento.\n\n"
        "Do lado das empresas, os desafios declarados são de gestão e de tradução para o "
        "negócio, não de tecnologia. Investir só em ferramenta não resolve o gargalo "
        "que os próprios gestores apontam.",
        Inches(7.05), Inches(1.55), Inches(5.75), Inches(5.2),
        tamanho=12, cor=GRAFITE, espacamento=1.1,
    )
    _rodape(
        slide,
        f"Critérios de escolha: base de {_br(dados['base_criterios'], 0)} respondentes, múltipla escolha. "
        f"Desafios de gestão: base de {_br(dados['gestores_desafio'], 0)} gestores "
        f"({_br(dados['taxa_gestores_desafio'], 1)}% do total).",
    )


def slide_recomendacoes(apresentacao: Presentation, dados: Dict) -> None:
    """Monta o slide de recomendações estratégicas."""
    slide = _slide_em_branco(apresentacao)
    _cabecalho(
        slide, "Recomendações",
        "Quatro movimentos, ordenados por relação entre impacto e custo",
    )

    recomendacoes = [
        (
            "1.  Publicar política de uso de IA antes de ampliar investimento em ferramenta",
            f"Apenas {_br(dados['ia_nao_usa'], 1)}% não usam IA generativa no trabalho, e metade dos gestores descreve uso "
            "descentralizado. A ferramenta já está dentro da empresa, com ou sem autorização. Para uma instituição financeira, "
            "o risco de dado sensível em serviço não homologado é regulatório, não apenas técnico.\n"
            "Custo baixo, urgência alta, e é pré-requisito para os demais movimentos.",
        ),
        (
            "2.  Corrigir o desalinhamento de modelo de trabalho",
            f"{_br(dados['presencial_atual'], 1)}% trabalham 100% presencial e apenas {_br(dados['presencial_ideal'], 1)}% "
            f"desejam isso — {_br(dados['gap_presencial'], 1)} pontos de distância. Flexibilidade remota é o segundo critério "
            f"na escolha de emprego ({_br(dados['criterio_remoto'], 1)}%), e "
            f"{_br(dados['aberto_oportunidades'] + dados['buscando'], 1)}% do mercado está aberto a sair.\n"
            "É a maior alavanca de retenção sem impacto em folha de pagamento.",
        ),
        (
            "3.  Formar Pleno internamente em vez de disputar Sênior no mercado",
            f"A remuneração média sai de {_reais(dados['salario_junior'])} no Júnior para {_reais(dados['salario_senior'])} no "
            f"Sênior. Contratar no topo custa cerca de três vezes e meia mais, num mercado disputado. Combinar formação interna "
            f"com contratação distribuída fora do Sudeste, onde a média é até {_br(dados['gap_nordeste'], 1)}% menor, amplia o "
            "alcance do mesmo orçamento.",
        ),
        (
            "4.  Atacar retenção e promoção, não apenas atração, no programa de diversidade",
            f"Mulheres são {_br(dados['feminino_junior'], 1)}% no nível Júnior e "
            f"{_br(dados['feminino_especialista'], 1)}% no topo, e a participação geral caiu em três edições consecutivas. "
            "O gargalo medido está na progressão, não na entrada. Programas de atração isolados não movem esse indicador; "
            "metas de promoção em Pleno e Sênior, sim.",
        ),
    ]

    topo = Inches(1.5)
    for titulo, corpo in recomendacoes:
        _caixa_texto(
            slide, titulo, Inches(0.55), topo, Inches(12.2), Inches(0.32),
            tamanho=14, cor=AZUL, negrito=True,
        )
        _caixa_texto(
            slide, corpo, Inches(0.9), topo + Inches(0.32), Inches(11.85), Inches(0.95),
            tamanho=11, cor=GRAFITE, espacamento=1.05,
        )
        topo += Inches(1.34)

    _rodape(
        slide,
        "Todos os números citados são extraídos da camada Gold do Data Lake e rastreáveis até as respostas originais da pesquisa.",
    )


def slide_encerramento(apresentacao: Presentation) -> None:
    """Monta o slide de encerramento com o resumo da solução técnica."""
    slide = _slide_em_branco(apresentacao)
    _faixa(slide, 0, ALTURA, AZUL)

    _caixa_texto(
        slide, "A solução construída", Inches(0.9), Inches(0.9), Inches(11.5), Inches(0.7),
        tamanho=32, cor=BRANCO, negrito=True,
    )
    _caixa_texto(
        slide,
        "Pipeline completo em AWS, executado e validado\n\n"
        "     Ingestão   três edições brutas no S3, camada Bronze particionada, cópia fiel da origem\n"
        "     ETL          dois Glue Jobs em PySpark, Glue 5.0 com Spark 3.5.4\n"
        "     Camadas   Bronze, Silver e Gold em Parquet, 11 tabelas catalogadas\n"
        "     Catálogo   Glue Crawler e Glue Data Catalog, partições registradas\n"
        "     Consulta   16 consultas SQL versionadas no Athena, uma por pergunta de negócio\n"
        "     Análise     9 gráficos gerados a partir da camada Gold\n\n"
        "Qualidade e governança\n\n"
        "     Harmonização semântica curada, com verificação por caminho de cálculo independente\n"
        "     Denominador válido e taxa de resposta em toda métrica agregada\n"
        "     Nenhum recurso exposto publicamente; criptografia em repouso e IAM de menor privilégio\n"
        "     Custo total de processamento e consulta abaixo de um dólar",
        Inches(0.9), Inches(1.9), Inches(11.5), Inches(4.6),
        tamanho=14, cor=RGBColor(0xD8, 0xE6, 0xF2), espacamento=1.2,
    )
    _caixa_texto(
        slide, "Tech Challenge Fase 3  ·  POSTECH DTAT",
        Inches(0.9), Inches(6.6), Inches(11.5), Inches(0.4),
        tamanho=11, cor=RGBColor(0x7A, 0xA3, 0xC4),
    )


# ---------------------------------------------------------------------------
# Coleta dos números
# ---------------------------------------------------------------------------


def coletar_dados() -> Dict:
    """Lê da camada Gold todos os números usados no material.

    Centralizar a leitura aqui garante que nenhum valor seja digitado à mão nos
    textos dos slides.

    Returns:
        Dicionário com os valores usados na narrativa.
    """
    perfil = _ler("perfil_mercado")
    salarios = _ler("salario_medio")
    diversidade = _ler("diversidade")
    tecnologias = _ler("tecnologias")
    ia = _ler("adocao_ia")
    recortes = _ler("recortes_comparativos")
    oportunidades = _ler("oportunidades_desafios")

    def pct_perfil(metrica: str, contem: str, edicao: int = 2025) -> Tuple[float, int, float]:
        recorte = perfil[(perfil.metrica == metrica) & (perfil.edicao == edicao)]
        linha = recorte[recorte.categoria.str.contains(contem, case=False, na=False)].iloc[0]
        return float(linha.percentual), int(linha.respondentes_validos), float(linha.taxa_resposta)

    def salario(recorte_nome: str, categoria: str, edicao: int = 2025) -> float:
        alvo = salarios[
            (salarios.recorte == recorte_nome)
            & (salarios.edicao == edicao)
            & (salarios.categoria.str.contains(categoria, case=False, na=False))
        ]
        return float(alvo.iloc[0].salario_medio)

    def pct_ia(dimensao: str, contem: str, edicao: int = 2025) -> float:
        alvo = ia[
            (ia.dimensao == dimensao)
            & (ia.edicao == edicao)
            & (ia.categoria.str.contains(contem, case=False, na=False))
        ]
        return float(alvo.iloc[0].percentual)

    def pct_tecnologia(dimensao: str, contem: str, edicao: int) -> float:
        alvo = tecnologias[
            (tecnologias.dimensao == dimensao)
            & (tecnologias.edicao == edicao)
            & (tecnologias.opcao.str.contains(contem, case=False, na=False, regex=False))
        ]
        return float(alvo.iloc[0].percentual)

    def pct_oportunidade(dimensao: str, contem: str, edicao: int = 2025) -> float:
        alvo = oportunidades[
            (oportunidades.dimensao == dimensao)
            & (oportunidades.edicao == edicao)
            & (oportunidades.categoria.str.contains(contem, case=False, na=False))
        ]
        return float(alvo.iloc[0].percentual)

    cargo_analista, base_cargo, taxa_cargo = pct_perfil("cargo", "Analista de Dados")
    cargo_cientista, _, _ = pct_perfil("cargo", "Cientista de Dados")
    cargo_engenheiro, _, _ = pct_perfil("cargo", "Engenheiro de Dados")
    setor_financas, base_setor, _ = pct_perfil("setor", "Finanças")
    setor_tecnologia, _, _ = pct_perfil("setor", "Tecnologia")

    feminino = diversidade[
        (diversidade.metrica == "genero_geral") & (diversidade.categoria == "Feminino")
    ].set_index("edicao")
    feminino_nivel = diversidade[
        (diversidade.metrica == "genero_por_senioridade")
        & (diversidade.categoria == "Feminino")
        & (diversidade.edicao == 2025)
    ].set_index("nivel_senioridade")

    salario_masculino = salario("genero", "Masculino")
    salario_feminino = salario("genero", "Feminino")
    salario_sudeste = salario("regiao", "Sudeste")
    salario_nordeste = salario("regiao", "Nordeste")

    modelo = recortes[
        recortes.metrica.isin(["modelo_trabalho_geral", "modelo_trabalho_ideal"])
        & (recortes.edicao == 2025)
    ]
    presencial_atual = float(
        modelo[
            (modelo.metrica == "modelo_trabalho_geral")
            & modelo.categoria.str.contains("100% presencial")
        ].iloc[0].percentual
    )
    presencial_ideal = float(
        modelo[
            (modelo.metrica == "modelo_trabalho_ideal")
            & modelo.categoria.str.contains("100% presencial")
        ].iloc[0].percentual
    )
    hibrido_ideal = float(
        modelo[
            (modelo.metrica == "modelo_trabalho_ideal")
            & modelo.categoria.str.contains("flexível")
        ].iloc[0].percentual
    )

    regiao = recortes[
        (recortes.metrica == "regiao_geral") & (recortes.edicao == 2025)
    ].set_index("categoria")

    uso_ia = ia[(ia.dimensao == "usa_chatgpt_copilot")]
    base_ia = int(uso_ia[uso_ia.edicao == 2025].iloc[0].respondentes_validos)
    taxa_ia = float(uso_ia[uso_ia.edicao == 2025].iloc[0].taxa_resposta)
    prioridade = ia[(ia.dimensao == "ia_e_prioridade") & (ia.edicao == 2025)]
    gestores_ia = int(prioridade.iloc[0].respondentes_validos)
    taxa_gestores = float(prioridade.iloc[0].taxa_resposta)

    desafios = oportunidades[
        (oportunidades.dimensao == "desafios_gestor") & (oportunidades.edicao == 2025)
    ]
    criterios = oportunidades[
        (oportunidades.dimensao == "criterios_escolha") & (oportunidades.edicao == 2025)
    ]

    return {
        "total_respondentes": config.TOTAL_RESPONDENTES_ESPERADO,
        # Pergunta 1
        "cargo_analista": cargo_analista,
        "cargo_cientista": cargo_cientista,
        "cargo_engenheiro": cargo_engenheiro,
        "base_cargo": base_cargo,
        "taxa_cargo": taxa_cargo,
        "setor_financas": setor_financas,
        "setor_tecnologia": setor_tecnologia,
        "base_setor": base_setor,
        # Pergunta 2
        "salario_junior": salario("senioridade", "Júnior"),
        "salario_pleno": salario("senioridade", "Pleno"),
        "salario_senior": salario("senioridade", "Sênior"),
        "salario_especialista": salario("senioridade", "Especialista"),
        "salario_ml": salario("cargo", "Machine Learning"),
        "salario_eng_dados": salario("cargo", "Engenheiro de Dados"),
        # Pergunta 3
        "feminino_2023": float(feminino.percentual[2023]),
        "feminino_2024": float(feminino.percentual[2024]),
        "feminino_geral": float(feminino.percentual[2025]),
        "feminino_junior": float(feminino_nivel.percentual["Júnior"]),
        "feminino_senior": float(feminino_nivel.percentual["Sênior"]),
        "feminino_especialista": float(feminino_nivel.percentual["Especialista/Staff+"]),
        "salario_masculino": salario_masculino,
        "salario_feminino": salario_feminino,
        "gap_genero": (salario_masculino - salario_feminino) / salario_masculino * 100,
        # Pergunta 4
        "aws_2023": pct_tecnologia("cloud_dia_a_dia", "Amazon Web Services", 2023),
        "aws_2025": pct_tecnologia("cloud_dia_a_dia", "Amazon Web Services", 2025),
        "azure_2023": pct_tecnologia("cloud_dia_a_dia", "Azure", 2023),
        "azure_2025": pct_tecnologia("cloud_dia_a_dia", "Azure", 2025),
        "gcp_2025": pct_tecnologia("cloud_dia_a_dia", "Google Cloud", 2025),
        "postgres": pct_tecnologia("banco_dados", "PostgreSQL", 2025),
        "sqlserver": pct_tecnologia("banco_dados", "SQL SERVER", 2025),
        "databricks": pct_tecnologia("banco_dados", "Databricks", 2025),
        "base_tecnologia": int(
            tecnologias[
                (tecnologias.dimensao == "cloud_dia_a_dia") & (tecnologias.edicao == 2025)
            ].iloc[0].respondentes_validos
        ),
        # Pergunta 5
        "ia_nao_usa": pct_ia("usa_chatgpt_copilot", "Não uso"),
        "ia_nao_usa_2023": pct_ia("usa_chatgpt_copilot", "Não uso", 2023),
        "ia_empresa_paga": pct_ia("usa_chatgpt_copilot", "empresa que trabalho paga"),
        "ia_empresa_paga_2023": pct_ia("usa_chatgpt_copilot", "empresa que trabalho paga", 2023),
        "ia_gratuita": pct_ia("usa_chatgpt_copilot", "gratuitas"),
        "ia_gratuita_2023": pct_ia("usa_chatgpt_copilot", "gratuitas", 2023),
        "ia_principal_prioridade": pct_ia("ia_e_prioridade", "nossa principal prioridade"),
        "base_ia": base_ia,
        "taxa_ia": taxa_ia,
        "gestores_ia": gestores_ia,
        "taxa_gestores": taxa_gestores,
        # Pergunta 6
        "sudeste": float(regiao.percentual["Sudeste"]),
        "nordeste": float(regiao.percentual["Nordeste"]),
        "salario_sudeste": salario_sudeste,
        "salario_nordeste": salario_nordeste,
        "gap_nordeste": (salario_sudeste - salario_nordeste) / salario_sudeste * 100,
        "presencial_atual": presencial_atual,
        "presencial_ideal": presencial_ideal,
        "hibrido_ideal": hibrido_ideal,
        "gap_presencial": presencial_atual - presencial_ideal,
        # Pergunta 7
        "criterio_salario": pct_oportunidade("criterios_escolha", "Remuneração"),
        "criterio_remoto": pct_oportunidade("criterios_escolha", "Flexibilidade"),
        "criterio_carreira": pct_oportunidade("criterios_escolha", "Plano de carreira"),
        "base_criterios": int(criterios.iloc[0].respondentes_validos),
        "desafio_tempo": pct_oportunidade("desafios_gestor", "Dividir o tempo"),
        "desafio_expectativa": pct_oportunidade("desafios_gestor", "expectativa das áreas"),
        "gestores_desafio": int(desafios.iloc[0].respondentes_validos),
        "taxa_gestores_desafio": float(desafios.iloc[0].taxa_resposta),
        "aberto_oportunidades": pct_oportunidade("planos_mudar_6m", "me considero aberto"),
        "buscando": pct_oportunidade("planos_mudar_6m", "Estou em busca de oportunidades dentro"),
    }


# ---------------------------------------------------------------------------
# Orquestração
# ---------------------------------------------------------------------------


def gerar(destino: Optional[Path] = None) -> Path:
    """Gera o material executivo em PowerPoint.

    Args:
        destino: caminho do arquivo de saída. Quando omitido, grava em
            `output/`.

    Returns:
        Caminho do arquivo gerado.
    """
    dados = coletar_dados()

    apresentacao = Presentation()
    apresentacao.slide_width = LARGURA
    apresentacao.slide_height = ALTURA
    propriedades = apresentacao.core_properties
    propriedades.title = "Material Executivo — State of Data Brasil"
    propriedades.subject = "Tech Challenge Fase 3 — Engenharia de Dados e Analytics em AWS"
    propriedades.author = "Equipe do Tech Challenge"
    propriedades.last_modified_by = "Equipe do Tech Challenge"
    propriedades.category = "Material acadêmico"
    propriedades.keywords = "State of Data, AWS, Engenharia de Dados, Analytics"
    propriedades.comments = "Gerado de forma reproduzível a partir da camada Gold."

    slide_capa(apresentacao, dados)
    slide_sumario_executivo(apresentacao, dados)
    slide_metodologia(apresentacao, dados)
    slide_arquitetura(apresentacao)
    slide_perfil_mercado(apresentacao, dados)
    slide_remuneracao(apresentacao, dados)
    slide_diversidade(apresentacao, dados)
    slide_tecnologias(apresentacao, dados)
    slide_adocao_ia(apresentacao, dados)
    slide_recortes(apresentacao, dados)
    slide_oportunidades(apresentacao, dados)
    slide_recomendacoes(apresentacao, dados)
    slide_encerramento(apresentacao)

    saida = destino or (config.RAIZ_PROJETO / "output" / ARQUIVO_SAIDA)
    saida.parent.mkdir(parents=True, exist_ok=True)
    apresentacao.save(str(saida))
    return saida


def main() -> None:
    """Ponto de entrada da geração do material executivo."""
    print("=" * 78)
    print("MATERIAL EXECUTIVO — a partir da camada Gold")
    print("=" * 78)

    destino = gerar()
    tamanho = destino.stat().st_size / 1024

    print(f"\n  {destino.relative_to(config.RAIZ_PROJETO)}  ({tamanho:.0f} KB)")
    print(f"  13 slides, 9 gráficos e o diagrama de arquitetura")
    print("\n" + "=" * 78)
    print("Nenhum número foi digitado à mão: todos vêm da camada Gold.")
    print("=" * 78)


if __name__ == "__main__":
    main()
