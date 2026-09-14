"""
Abstração do ambiente de execução: Spark local ou AWS Glue Job.

MOTIVAÇÃO
---------
O requisito é que a lógica de transformação seja idêntica nos dois ambientes.
Sem uma camada como esta, cada função de transformação acabaria com um
`if rodando_no_glue:` no meio, e a versão local deixaria de ser evidência
confiável de que a versão do Glue funciona.

A separação adotada é:

    ContextoExecucao   -> sabe onde está e resolve caminhos e SparkSession
    transformacoes/    -> funções puras de DataFrame, não sabem onde estão
    glue_jobs/         -> entrypoints finos que ligam os dois

Assim, o que roda local é literalmente o mesmo código que roda no Glue. A única
diferença é o valor de `raiz_lake` e a origem da SparkSession.

DETECÇÃO DE AMBIENTE
--------------------
Feita pela disponibilidade do módulo `awsglue`, que existe apenas no runtime do
Glue. Não usamos variável de ambiente porque ela pode ser herdada por acidente
em execução local e levaria o pipeline a tentar escrever no S3 sem intenção.
"""

from __future__ import annotations

import importlib.util
import os
import sys
from datetime import datetime, timezone
from typing import Dict, Optional

from pyspark.sql import DataFrame, SparkSession

from src import config


def _glue_disponivel() -> bool:
    """Indica se o runtime do AWS Glue está presente.

    Returns:
        `True` quando o módulo `awsglue` pode ser importado, o que ocorre
        apenas dentro de um Glue Job.
    """
    return importlib.util.find_spec("awsglue") is not None


class ContextoExecucao:
    """Encapsula SparkSession, resolução de caminhos e log do ambiente.

    A instância decide sozinha se está no Glue ou local. O restante do código
    consulta `no_glue` apenas para fins informativos: a resolução de caminhos
    já leva o ambiente em conta.

    Attributes:
        raiz_lake: raiz do Data Lake em uso, como URI S3 ou caminho local.
        nome_aplicacao: nome da aplicação Spark, usado no log e na Spark UI.
    """

    def __init__(
        self,
        nome_aplicacao: str = "sod-fase3",
        raiz_lake: Optional[str] = None,
        forcar_local: bool = False,
    ) -> None:
        """Inicializa o contexto e cria a SparkSession apropriada.

        Args:
            nome_aplicacao: nome da aplicação Spark.
            raiz_lake: raiz do Data Lake. Quando omitido, usa o padrão do
                ambiente detectado.
            forcar_local: quando `True`, ignora a detecção e opera em modo
                local. Útil em testes executados dentro de um ambiente que
                por acaso tenha o `awsglue` instalado.
        """
        self.nome_aplicacao = nome_aplicacao
        self._no_glue = _glue_disponivel() and not forcar_local
        self._contexto_glue = None
        self._job_glue = None
        self._spark = self._criar_sessao()
        self.raiz_lake = (raiz_lake or config.raiz_lake_padrao(self._no_glue)).rstrip("/")

    # -- criação da sessão ---------------------------------------------------

    def _criar_sessao(self) -> SparkSession:
        """Cria a SparkSession adequada ao ambiente detectado.

        Returns:
            A SparkSession ativa.
        """
        if self._no_glue:
            return self._criar_sessao_glue()
        return self._criar_sessao_local()

    def _criar_sessao_glue(self) -> SparkSession:
        """Cria a SparkSession a partir do GlueContext.

        Returns:
            SparkSession derivada do GlueContext.
        """
        from awsglue.context import GlueContext  # noqa: PLC0415
        from pyspark.context import SparkContext  # noqa: PLC0415

        contexto_spark = SparkContext.getOrCreate()
        self._contexto_glue = GlueContext(contexto_spark)
        return self._contexto_glue.spark_session

    def _criar_sessao_local(self) -> SparkSession:
        """Cria uma SparkSession local com configuração adequada ao volume.

        Returns:
            SparkSession local.
        """
        return (
            SparkSession.builder.appName(self.nome_aplicacao)
            .master("local[*]")
            .config("spark.sql.shuffle.partitions", config.PARTICOES_SHUFFLE_LOCAL)
            .config("spark.ui.enabled", "false")
            # Evita que o Spark grave metadados _SUCCESS e CRC desnecessários,
            # que poluem a inspeção manual do lake local.
            .config("spark.hadoop.mapreduce.fileoutputcommitter.marksuccessfuljobs", "false")
            .getOrCreate()
        )

    # -- propriedades --------------------------------------------------------

    @property
    def spark(self) -> SparkSession:
        """A SparkSession ativa."""
        return self._spark

    @property
    def no_glue(self) -> bool:
        """`True` quando a execução ocorre dentro de um Glue Job."""
        return self._no_glue

    @property
    def ambiente(self) -> str:
        """Rótulo legível do ambiente, para log e evidência."""
        return "glue" if self._no_glue else "local"

    # -- caminhos ------------------------------------------------------------

    def caminho(self, camada: str, tabela: str = "") -> str:
        """Resolve o caminho de uma camada ou tabela do Data Lake.

        Args:
            camada: nome da camada (`bronze`, `silver` ou `gold`).
            tabela: nome da tabela dentro da camada. Se vazio, retorna a raiz
                da camada.

        Returns:
            Caminho completo, com o mesmo formato da `raiz_lake` em uso.
        """
        sufixo = f"/{tabela}" if tabela else ""
        return f"{self.raiz_lake}/{camada}{sufixo}"

    def caminho_bruto(self, ano: int) -> str:
        """Resolve o caminho do CSV bruto de uma edição na camada Bronze.

        Na Bronze os arquivos ficam particionados no padrão Hive
        (`edicao=2023/`), reconhecido automaticamente pelo Glue Crawler e pelo
        Athena como coluna de partição.

        Args:
            ano: ano de início da edição (2023, 2024 ou 2025).

        Returns:
            Caminho completo do arquivo CSV bruto.

        Raises:
            ValueError: se o ano não for uma edição conhecida.
        """
        from src.mapeamento_colunas import ARQUIVO_BRUTO, ANOS  # noqa: PLC0415

        if ano not in ANOS:
            raise ValueError(f"Edição desconhecida: {ano}. Esperado um de {ANOS}.")
        base = self.caminho(config.CAMADA_BRONZE, config.TABELA_BRONZE)
        return f"{base}/edicao={ano}/{ARQUIVO_BRUTO[ano]}"

    # -- log -----------------------------------------------------------------

    def registrar(self, mensagem: str) -> None:
        """Emite uma mensagem de log com prefixo de ambiente e horário.

        Escreve em stdout, que é capturado tanto pelo terminal local quanto
        pelo CloudWatch Logs no Glue.

        Args:
            mensagem: texto a registrar.
        """
        instante = datetime.now(timezone.utc).strftime("%H:%M:%S")
        # Logs podem ser preservados no notebook e publicados como evidência.
        # Exiba apenas caminhos relativos e um bucket genérico; os caminhos
        # reais continuam sendo usados normalmente pelas operações de I/O.
        mensagem_publica = str(mensagem).replace(str(config.RAIZ_PROJETO), ".")
        mensagem_publica = mensagem_publica.replace(config.NOME_BUCKET, "<BUCKET>")
        print(f"[{instante}][{self.ambiente}] {mensagem_publica}", flush=True)

    def registrar_ambiente(self) -> Dict[str, str]:
        """Registra e devolve os metadados do ambiente de execução.

        Atende ao requisito de rastrear a versão do Spark e do Glue em cada
        execução, compondo a evidência de execução.

        Returns:
            Dicionário com ambiente, versão do Spark, versão do Python,
            versão do Glue quando aplicável, e a raiz do lake em uso.
        """
        metadados = {
            "ambiente": self.ambiente,
            "versao_spark": self._spark.version,
            "versao_python": sys.version.split()[0],
            "versao_glue": os.environ.get("GLUE_VERSION", config.VERSAO_GLUE if self._no_glue else "-"),
            "raiz_lake": self.raiz_lake,
        }
        for chave, valor in metadados.items():
            self.registrar(f"{chave} = {valor}")
        return metadados

    # -- leitura e escrita ---------------------------------------------------

    def ler_csv(self, caminho: str) -> DataFrame:
        """Lê um CSV bruto com as opções verificadas para estas edições.

        As opções em `config.OPCOES_LEITURA_CSV` foram validadas contra as três
        edições: com elas o Spark produz a mesma contagem de linhas e colunas
        que o pandas.

        Args:
            caminho: caminho do arquivo CSV.

        Returns:
            DataFrame com todas as colunas como string.
        """
        leitor = self._spark.read
        for opcao, valor in config.OPCOES_LEITURA_CSV.items():
            leitor = leitor.option(opcao, valor)
        return leitor.csv(caminho)

    def escrever_parquet(
        self,
        df: DataFrame,
        camada: str,
        tabela: str,
        particoes: Optional[list[str]] = None,
    ) -> str:
        """Escreve um DataFrame em Parquet na camada indicada.

        Usa modo `overwrite` para que reexecuções sejam idempotentes, o que é
        importante porque o pipeline será rodado várias vezes durante o
        desenvolvimento e por diferentes integrantes do grupo.

        Args:
            df: DataFrame a persistir.
            camada: camada de destino (`silver` ou `gold`).
            tabela: nome da tabela de destino.
            particoes: colunas de particionamento. Quando omitido, escreve sem
                particionar.

        Returns:
            O caminho onde os dados foram escritos.
        """
        destino = self.caminho(camada, tabela)
        escritor = df.write.mode("overwrite")
        if particoes:
            escritor = escritor.partitionBy(*particoes)
        escritor.parquet(destino)
        self.registrar(f"escrito: {destino} ({df.count()} registros)")
        return destino

    def ler_parquet(self, camada: str, tabela: str) -> DataFrame:
        """Lê uma tabela Parquet de uma camada do Data Lake.

        Args:
            camada: camada de origem.
            tabela: nome da tabela.

        Returns:
            DataFrame com o conteúdo da tabela.
        """
        return self._spark.read.parquet(self.caminho(camada, tabela))

    # -- ciclo de vida -------------------------------------------------------

    def encerrar(self) -> None:
        """Encerra a SparkSession local.

        No Glue a sessão é gerenciada pelo runtime, então nada é feito.
        """
        if not self._no_glue:
            self._spark.stop()

    def __enter__(self) -> "ContextoExecucao":
        """Permite uso como gerenciador de contexto."""
        return self

    def __exit__(self, *_excecao) -> None:
        """Encerra a sessão ao sair do bloco `with`."""
        self.encerrar()
