"""Valida que a entrega pública não exponha informações do ambiente local.

A verificação cobre arquivos textuais, notebooks, conteúdo XML interno de
DOCX/PPTX, texto e metadados de PDFs e metadados de imagens. Dados brutos,
ambientes virtuais, Git e a nota privada de continuidade não fazem parte da
entrega e são ignorados.
"""

from __future__ import annotations

import argparse
import getpass
import json
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator

from PIL import Image
from pypdf import PdfReader

from src import config

EXTENSOES_PACOTE_OFFICE = {".docx", ".pptx"}
EXTENSOES_IMAGEM = {".png", ".jpg", ".jpeg"}
DIRETORIOS_IGNORADOS = {
    ".git",
    ".venv",
    ".venv-spark",
    "__pycache__",
    ".ipynb_checkpoints",
    ".pytest_cache",
    "data",
}
ARQUIVOS_IGNORADOS = {
    Path("docs/CONTEXTO_PARA_NOVO_CHAT.md"),
    Path(".DS_Store"),
}


@dataclass(frozen=True)
class Violacao:
    """Ocorrência confidencial sem reproduzir o valor encontrado."""

    arquivo: str
    origem: str
    regra: str


@dataclass(frozen=True)
class Regra:
    nome: str
    padrao: re.Pattern[str]


def _regras() -> list[Regra]:
    regras = [
        Regra(
            "caminho pessoal Unix/macOS",
            re.compile(r"(?:file://)?/" + r"(?:Users|home)/" + r"[^\s\"'<>]+", re.I),
        ),
        Regra(
            "caminho pessoal Windows",
            re.compile(r"[A-Za-z]:\\" + r"Users\\" + r"[^\s\"'<>]+", re.I),
        ),
        Regra(
            "diretório temporário local",
            re.compile(r"/(?:private/var|var/folders|tmp)/[^\s\"'<>]+", re.I),
        ),
        Regra(
            "chave de acesso AWS",
            re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
        ),
        Regra(
            "e-mail corporativo",
            re.compile(r"\b[A-Z0-9._%+-]+@(?:[A-Z0-9.-]+\.)?amazon\.com\b", re.I),
        ),
    ]

    usuario = getpass.getuser().strip()
    if usuario and usuario.lower() not in {"root", "runner", "user"}:
        regras.append(Regra("nome do usuário local", re.compile(rf"\b{re.escape(usuario)}\b", re.I)))

    nome_workspace = config.RAIZ_PROJETO.parent.name.strip()
    if nome_workspace:
        regras.append(Regra("nome da pasta local", re.compile(re.escape(nome_workspace), re.I)))

    if config.ID_CONTA.isdigit() and len(config.ID_CONTA) == 12:
        regras.append(Regra("identificador da conta AWS", re.compile(re.escape(config.ID_CONTA))))

    return regras


def _arquivos_publicos(raiz: Path) -> Iterator[Path]:
    for caminho in raiz.rglob("*"):
        if not caminho.is_file():
            continue
        relativo = caminho.relative_to(raiz)
        if relativo in ARQUIVOS_IGNORADOS:
            continue
        if any(parte in DIRETORIOS_IGNORADOS for parte in relativo.parts):
            continue
        yield caminho


def _conteudos_office(caminho: Path) -> Iterator[tuple[str, str]]:
    with zipfile.ZipFile(caminho) as pacote:
        for membro in pacote.namelist():
            if membro.endswith("/"):
                continue
            conteudo = pacote.read(membro).decode("utf-8", errors="ignore")
            yield membro, conteudo


def _conteudos_pdf(caminho: Path) -> Iterator[tuple[str, str]]:
    leitor = PdfReader(caminho)
    yield "metadados PDF", json.dumps(dict(leitor.metadata or {}), ensure_ascii=False)
    for indice, pagina in enumerate(leitor.pages, start=1):
        yield f"página {indice}", pagina.extract_text() or ""


def _conteudos_imagem(caminho: Path) -> Iterator[tuple[str, str]]:
    with Image.open(caminho) as imagem:
        yield "metadados da imagem", f"{imagem.info!r} {dict(imagem.getexif())!r}"


def _conteudos(caminho: Path) -> Iterator[tuple[str, str]]:
    extensao = caminho.suffix.lower()
    if extensao in EXTENSOES_PACOTE_OFFICE:
        yield from _conteudos_office(caminho)
    elif extensao == ".pdf":
        yield from _conteudos_pdf(caminho)
    elif extensao in EXTENSOES_IMAGEM:
        yield from _conteudos_imagem(caminho)
    else:
        yield "conteúdo", caminho.read_bytes().decode("utf-8", errors="ignore")


def validar(raiz: Path = config.RAIZ_PROJETO) -> tuple[list[Violacao], int]:
    """Retorna violações e total de arquivos examinados."""
    raiz = raiz.resolve()
    regras = _regras()
    violacoes: list[Violacao] = []
    total = 0

    for caminho in _arquivos_publicos(raiz):
        total += 1
        relativo = caminho.relative_to(raiz).as_posix()
        for origem, conteudo in _conteudos(caminho):
            for regra in regras:
                if regra.padrao.search(conteudo):
                    violacoes.append(Violacao(relativo, origem, regra.nome))

    return violacoes, total


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--raiz",
        type=Path,
        default=config.RAIZ_PROJETO,
        help="Raiz da entrega a validar (padrão: repositório atual).",
    )
    argumentos = parser.parse_args()
    violacoes, total = validar(argumentos.raiz)

    if violacoes:
        print(f"FALHA: {len(violacoes)} ocorrência(s) confidencial(is) em {total} arquivo(s):")
        for violacao in violacoes:
            print(f"  - {violacao.arquivo} [{violacao.origem}]: {violacao.regra}")
        raise SystemExit(1)

    print(f"Privacidade validada: {total} arquivos, nenhuma informação local ou credencial encontrada.")


if __name__ == "__main__":
    main()
