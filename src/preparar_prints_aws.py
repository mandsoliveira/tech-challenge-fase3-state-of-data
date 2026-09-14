"""Prepara capturas do console AWS para a entrega pública.

Copia as imagens fornecidas para ``output/prints``, padroniza nomes, remove
metadados e cobre identificadores visíveis. Os cinco prints principais ficam na
raiz para inclusão automática no relatório; três consultas complementares ficam
em subpasta.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Callable

from PIL import Image, ImageDraw, ImageFont

from src import config

DESTINO = config.RAIZ_PROJETO / "output" / "prints"
COR_FUNDO = (22, 27, 34)
COR_TEXTO = (210, 214, 220)

ARQUIVOS = {
    "s3_medallion.png": ("01_s3_camadas_medallion.png", True),
    "glue_jobs.png": ("02_glue_jobs_sucesso.png", True),
    "glue_crawler.png": ("03_glue_crawler.png", True),
    "glue_datacatalog.png": ("04_glue_data_catalog.png", True),
    "athena_consulta1.png": ("05_athena_resultado_perfil.png", True),
    "athena_consulta2.png": ("06_athena_resultado_remuneracao.png", False),
    "athena_consulta3.png": ("07_athena_resultado_diversidade.png", False),
    "athena_consultas.png": ("08_athena_historico.png", False),
}


def _fonte(tamanho: int, negrito: bool = False):
    candidatos = [
        Path("/System/Library/Fonts/Supplemental/Arial Bold.ttf" if negrito else "/System/Library/Fonts/Supplemental/Arial.ttf"),
        Path("/System/Library/Fonts/Helvetica.ttc"),
    ]
    for candidato in candidatos:
        if candidato.exists():
            try:
                return ImageFont.truetype(str(candidato), tamanho)
            except OSError:
                continue
    return ImageFont.load_default()


def _retangulo_relativo(desenho: ImageDraw.ImageDraw, tamanho, caixa, cor=COR_FUNDO) -> None:
    largura, altura = tamanho
    desenho.rectangle(
        tuple(int(valor * (largura if indice % 2 == 0 else altura)) for indice, valor in enumerate(caixa)),
        fill=cor,
    )


def _texto_relativo(desenho: ImageDraw.ImageDraw, tamanho, posicao, texto, tamanho_fonte, negrito=False) -> None:
    largura, altura = tamanho
    desenho.text(
        (int(posicao[0] * largura), int(posicao[1] * altura)),
        texto,
        font=_fonte(tamanho_fonte, negrito),
        fill=COR_TEXTO,
    )


def _sanitizar_s3(imagem: Image.Image) -> None:
    """Substitui o nome do bucket, que contém o identificador da conta."""
    desenho = ImageDraw.Draw(imagem)
    tamanho = imagem.size

    # Breadcrumb superior.
    _retangulo_relativo(desenho, tamanho, (0.115, 0.005, 0.46, 0.062))
    _texto_relativo(desenho, tamanho, (0.120, 0.018), "sod-fase3-datalake-<ID_OCULTO>", 25, True)

    # Título principal do bucket.
    _retangulo_relativo(desenho, tamanho, (0.145, 0.045, 0.58, 0.125))
    _texto_relativo(desenho, tamanho, (0.150, 0.064), "sod-fase3-datalake-<ID_OCULTO>", 45, True)


def _sanitizar_catalogo(imagem: Image.Image) -> None:
    """Cobre o identificador no seletor de catálogo e nos caminhos S3."""
    desenho = ImageDraw.Draw(imagem)
    largura, altura = imagem.size

    # Valor do seletor de catálogo.
    _retangulo_relativo(desenho, imagem.size, (0.158, 0.444, 0.245, 0.493))
    _texto_relativo(desenho, imagem.size, (0.163, 0.456), "<ID_OCULTO>", 24, True)

    # Cada URI é substituída por uma versão pública que preserva a camada e a
    # tabela, mas remove completamente o bucket real.
    caminhos_publicos = [
        "s3://<BUCKET>/gold/adocao_ia/",
        "s3://<BUCKET>/gold/diversidade/",
        "s3://<BUCKET>/gold/oportunidades_desafios/",
        "s3://<BUCKET>/gold/perfil_mercado/",
        "s3://<BUCKET>/gold/recortes_comparativos/",
        "s3://<BUCKET>/gold/remuneracao/",
        "s3://<BUCKET>/silver/respondentes/",
        "s3://<BUCKET>/silver/respondeu_multiescolha/",
        "s3://<BUCKET>/silver/respostas_multiescolha/",
        "s3://<BUCKET>/gold/salario_medio/",
        "s3://<BUCKET>/gold/tecnologias/",
    ]
    for indice, caminho_publico in enumerate(caminhos_publicos):
        centro_y = 0.652 + indice * 0.0323
        desenho.rectangle(
            (
                int(largura * 0.365),
                int(altura * (centro_y - 0.014)),
                int(largura * 0.645),
                int(altura * (centro_y + 0.015)),
            ),
            fill=COR_FUNDO,
        )
        desenho.text(
            (int(largura * 0.382), int(altura * (centro_y - 0.012))),
            caminho_publico,
            font=_fonte(20),
            fill=COR_TEXTO,
        )


def _sanitizar_historico_athena(imagem: Image.Image) -> None:
    """Oculta IDs de execução, desnecessários para a evidência pública."""
    desenho = ImageDraw.Draw(imagem)
    largura, altura = imagem.size
    for indice in range(22):
        centro_y = 0.260 + indice * 0.0374
        if centro_y > 0.985:
            break
        desenho.rectangle(
            (
                int(largura * 0.045),
                int(altura * (centro_y - 0.014)),
                int(largura * 0.220),
                int(altura * (centro_y + 0.014)),
            ),
            fill=COR_FUNDO,
        )
        desenho.text(
            (int(largura * 0.052), int(altura * (centro_y - 0.012))),
            "<ID DE EXECUÇÃO OCULTO>",
            font=_fonte(18),
            fill=COR_TEXTO,
        )


def _processar(origem: Path, destino: Path, sanitizador: Callable[[Image.Image], None] | None = None) -> None:
    with Image.open(origem) as original:
        imagem = original.convert("RGB")
    if sanitizador:
        sanitizador(imagem)
    destino.parent.mkdir(parents=True, exist_ok=True)
    # Um novo PNG é gravado sem copiar EXIF ou metadados do arquivo original.
    imagem.save(destino, format="PNG", optimize=True)


def preparar(pasta_origem: Path) -> list[Path]:
    """Prepara todos os prints esperados e retorna os caminhos gerados."""
    faltantes = [nome for nome in ARQUIVOS if not (pasta_origem / nome).exists()]
    if faltantes:
        raise FileNotFoundError(f"Prints não encontrados em {pasta_origem}: {faltantes}")

    sanitizadores = {
        "s3_medallion.png": _sanitizar_s3,
        "glue_datacatalog.png": _sanitizar_catalogo,
        "athena_consultas.png": _sanitizar_historico_athena,
    }

    gerados: list[Path] = []
    for nome_origem, (nome_destino, principal) in ARQUIVOS.items():
        subpasta = DESTINO if principal else DESTINO / "complementares"
        caminho_destino = subpasta / nome_destino
        _processar(
            pasta_origem / nome_origem,
            caminho_destino,
            sanitizadores.get(nome_origem),
        )
        gerados.append(caminho_destino)
    return gerados


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--origem", type=Path, required=True, help="Pasta com os oito PNGs originais.")
    argumentos = parser.parse_args()
    gerados = preparar(argumentos.origem.resolve())
    print(f"Prints preparados: {len(gerados)}")
    for caminho in gerados:
        print(f"  - {caminho.relative_to(config.RAIZ_PROJETO)}")


if __name__ == "__main__":
    main()
