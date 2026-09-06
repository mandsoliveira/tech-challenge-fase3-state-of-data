"""
Provisionamento idempotente da infraestrutura AWS do projeto.

RECURSOS CRIADOS
----------------
    S3 bucket        sod-fase3-datalake-<conta>   (privado, criptografado)
    IAM role         sod-fase3-glue-role          (escopada ao bucket)
    Glue Database    sod_fase3

POSTURA DE SEGURANÇA
--------------------
O requisito é explícito: nada exposto publicamente. As medidas aplicadas:

    - As quatro flags de Block Public Access habilitadas no bucket
    - Criptografia em repouso com SSE-S3
    - Versionamento desabilitado (não é requisito e reduz custo)
    - Nenhuma policy de bucket. Sem policy, o acesso é apenas via IAM da conta
    - IAM role restrita ao ARN do bucket do projeto, sem `s3:*` sobre `*`
    - Nenhum recurso com endpoint público: sem website hosting, sem CloudFront,
      sem API Gateway, sem Load Balancer

A conta já tem Block Public Access habilitado no nível da conta, o que funciona
como segunda barreira: mesmo uma tentativa de tornar o bucket público seria
bloqueada antes de surtir efeito.

IDEMPOTÊNCIA
------------
Toda operação verifica a existência antes de criar e trata o erro de "já
existe" como sucesso. O script pode ser rodado quantas vezes for necessário,
por qualquer integrante do grupo, sem efeito colateral.
"""

from __future__ import annotations

import json
from typing import Dict, List

import boto3
from botocore.exceptions import ClientError

from src import config

# Política de confiança: apenas o serviço Glue pode assumir a role.
POLITICA_CONFIANCA_GLUE = {
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Principal": {"Service": "glue.amazonaws.com"},
            "Action": "sts:AssumeRole",
        }
    ],
}

NOME_POLITICA_INLINE = "sod-fase3-acesso-lake"


def _cliente(servico: str):
    """Cria um cliente boto3 na região do projeto.

    Args:
        servico: nome do serviço AWS.

    Returns:
        Cliente boto3 configurado.
    """
    return boto3.client(servico, region_name=config.REGIAO)


# ---------------------------------------------------------------------------
# S3
# ---------------------------------------------------------------------------


def criar_bucket(s3, nome: str) -> bool:
    """Cria o bucket do Data Lake, se ainda não existir.

    Args:
        s3: cliente boto3 do S3.
        nome: nome do bucket.

    Returns:
        `True` se o bucket foi criado agora, `False` se já existia.

    Raises:
        ClientError: para erros diferentes de "já existe".
    """
    try:
        s3.head_bucket(Bucket=nome)
        print(f"  bucket {nome} já existe")
        return False
    except ClientError as erro:
        codigo = erro.response["Error"]["Code"]
        if codigo not in ("404", "NoSuchBucket", "403"):
            raise
        if codigo == "403":
            # Bucket existe e pertence a outra conta, ou sem permissão de head.
            print(f"  bucket {nome} inacessível (403). Verifique se o nome já está em uso.")
            raise

    # us-east-1 é a única região que não aceita CreateBucketConfiguration.
    if config.REGIAO == "us-east-1":
        s3.create_bucket(Bucket=nome)
    else:
        s3.create_bucket(
            Bucket=nome,
            CreateBucketConfiguration={"LocationConstraint": config.REGIAO},
        )
    print(f"  bucket {nome} criado")
    return True


def aplicar_block_public_access(s3, nome: str) -> None:
    """Habilita as quatro flags de Block Public Access no bucket.

    Args:
        s3: cliente boto3 do S3.
        nome: nome do bucket.
    """
    s3.put_public_access_block(
        Bucket=nome,
        PublicAccessBlockConfiguration={
            "BlockPublicAcls": True,
            "IgnorePublicAcls": True,
            "BlockPublicPolicy": True,
            "RestrictPublicBuckets": True,
        },
    )
    print("  block public access: 4 flags habilitadas")


def aplicar_criptografia(s3, nome: str) -> None:
    """Habilita criptografia em repouso com SSE-S3 no bucket.

    Args:
        s3: cliente boto3 do S3.
        nome: nome do bucket.
    """
    s3.put_bucket_encryption(
        Bucket=nome,
        ServerSideEncryptionConfiguration={
            "Rules": [
                {
                    "ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"},
                    "BucketKeyEnabled": True,
                }
            ]
        },
    )
    print("  criptografia em repouso: SSE-S3 (AES256)")


# ---------------------------------------------------------------------------
# IAM
# ---------------------------------------------------------------------------


def _politica_acesso_lake(nome_bucket: str) -> Dict:
    """Monta a política de acesso da role do Glue.

    O acesso ao S3 é restrito ao bucket do projeto. As permissões de Glue
    Catalog e CloudWatch Logs são as mínimas para um job `glueetl` funcionar e
    registrar log.

    Args:
        nome_bucket: nome do bucket do Data Lake.

    Returns:
        Documento de política IAM.
    """
    arn_bucket = f"arn:aws:s3:::{nome_bucket}"
    return {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "ListarBucketDoProjeto",
                "Effect": "Allow",
                "Action": ["s3:ListBucket", "s3:GetBucketLocation"],
                "Resource": arn_bucket,
            },
            {
                "Sid": "LerEscreverObjetosDoProjeto",
                "Effect": "Allow",
                "Action": ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"],
                "Resource": f"{arn_bucket}/*",
            },
            {
                "Sid": "CatalogoGlue",
                "Effect": "Allow",
                # As operações em lote de partição são usadas pelo Crawler ao
                # registrar as partições `edicao=`. Sem `BatchGetPartition` o
                # crawl falha com AccessDenied DEPOIS de criar as tabelas,
                # deixando o catálogo com tabelas de zero partição — que o
                # Athena consulta sem erro e devolve zero registros.
                "Action": [
                    "glue:GetDatabase",
                    "glue:GetDatabases",
                    "glue:CreateDatabase",
                    "glue:UpdateDatabase",
                    "glue:GetTable",
                    "glue:GetTables",
                    "glue:CreateTable",
                    "glue:UpdateTable",
                    "glue:DeleteTable",
                    "glue:BatchDeleteTable",
                    "glue:GetPartition",
                    "glue:GetPartitions",
                    "glue:CreatePartition",
                    "glue:UpdatePartition",
                    "glue:DeletePartition",
                    "glue:BatchGetPartition",
                    "glue:BatchCreatePartition",
                    "glue:BatchUpdatePartition",
                    "glue:BatchDeletePartition",
                ],
                "Resource": [
                    f"arn:aws:glue:{config.REGIAO}:{config.ID_CONTA}:catalog",
                    f"arn:aws:glue:{config.REGIAO}:{config.ID_CONTA}:database/{config.NOME_DATABASE_GLUE}",
                    f"arn:aws:glue:{config.REGIAO}:{config.ID_CONTA}:table/{config.NOME_DATABASE_GLUE}/*",
                ],
            },
            {
                "Sid": "LogsDoJob",
                "Effect": "Allow",
                "Action": [
                    "logs:CreateLogGroup",
                    "logs:CreateLogStream",
                    "logs:PutLogEvents",
                ],
                "Resource": f"arn:aws:logs:{config.REGIAO}:{config.ID_CONTA}:log-group:/aws-glue/*",
            },
        ],
    }


def criar_role_glue(iam, nome_role: str, nome_bucket: str) -> str:
    """Cria ou atualiza a IAM role usada pelos Glue Jobs.

    Args:
        iam: cliente boto3 do IAM.
        nome_role: nome da role.
        nome_bucket: nome do bucket do Data Lake.

    Returns:
        ARN da role.
    """
    try:
        iam.create_role(
            RoleName=nome_role,
            AssumeRolePolicyDocument=json.dumps(POLITICA_CONFIANCA_GLUE),
            Description="Role dos Glue Jobs do Tech Challenge Fase 3 (State of Data).",
        )
        print(f"  role {nome_role} criada")
    except ClientError as erro:
        if erro.response["Error"]["Code"] != "EntityAlreadyExists":
            raise
        print(f"  role {nome_role} já existe")

    # A política inline é sempre reescrita, para que ajustes no escopo sejam
    # aplicados em reexecuções.
    iam.put_role_policy(
        RoleName=nome_role,
        PolicyName=NOME_POLITICA_INLINE,
        PolicyDocument=json.dumps(_politica_acesso_lake(nome_bucket)),
    )
    print(f"  política {NOME_POLITICA_INLINE} aplicada (escopada ao bucket do projeto)")

    return iam.get_role(RoleName=nome_role)["Role"]["Arn"]


# ---------------------------------------------------------------------------
# Glue Data Catalog
# ---------------------------------------------------------------------------


def criar_database_glue(glue, nome: str) -> None:
    """Cria o Glue Database do projeto, se ainda não existir.

    Args:
        glue: cliente boto3 do Glue.
        nome: nome do database.
    """
    try:
        glue.create_database(
            DatabaseInput={
                "Name": nome,
                "Description": "Camadas Silver e Gold do Tech Challenge Fase 3.",
            }
        )
        print(f"  glue database {nome} criado")
    except ClientError as erro:
        if erro.response["Error"]["Code"] != "AlreadyExistsException":
            raise
        print(f"  glue database {nome} já existe")


# ---------------------------------------------------------------------------
# Verificação de segurança
# ---------------------------------------------------------------------------


def verificar_seguranca(s3, nome_bucket: str) -> List[str]:
    """Verifica os controles de segurança do bucket.

    Args:
        s3: cliente boto3 do S3.
        nome_bucket: nome do bucket a verificar.

    Returns:
        Lista de problemas encontrados. Vazia quando tudo está conforme.
    """
    problemas: List[str] = []

    # Block Public Access: as quatro flags devem estar ativas.
    try:
        configuracao = s3.get_public_access_block(Bucket=nome_bucket)[
            "PublicAccessBlockConfiguration"
        ]
        for flag in (
            "BlockPublicAcls",
            "IgnorePublicAcls",
            "BlockPublicPolicy",
            "RestrictPublicBuckets",
        ):
            estado = configuracao.get(flag, False)
            print(f"    {flag}: {estado}")
            if not estado:
                problemas.append(f"{flag} está desabilitada em {nome_bucket}")
    except ClientError as erro:
        problemas.append(f"não foi possível ler block public access: {erro}")

    # Criptografia em repouso.
    try:
        regras = s3.get_bucket_encryption(Bucket=nome_bucket)[
            "ServerSideEncryptionConfiguration"
        ]["Rules"]
        algoritmo = regras[0]["ApplyServerSideEncryptionByDefault"]["SSEAlgorithm"]
        print(f"    criptografia: {algoritmo}")
    except ClientError:
        problemas.append(f"criptografia em repouso ausente em {nome_bucket}")

    # Não deve existir policy de bucket concedendo acesso público.
    try:
        politica = json.loads(s3.get_bucket_policy(Bucket=nome_bucket)["Policy"])
        for declaracao in politica.get("Statement", []):
            principal = declaracao.get("Principal")
            if principal == "*" or (
                isinstance(principal, dict) and principal.get("AWS") == "*"
            ):
                problemas.append(
                    f"policy de {nome_bucket} concede acesso a Principal '*'"
                )
        print("    policy de bucket: presente, sem Principal '*'")
    except ClientError as erro:
        if erro.response["Error"]["Code"] == "NoSuchBucketPolicy":
            print("    policy de bucket: ausente (acesso apenas via IAM da conta)")
        else:
            problemas.append(f"não foi possível ler a policy: {erro}")

    # Website hosting expõe conteúdo publicamente e não deve existir.
    try:
        s3.get_bucket_website(Bucket=nome_bucket)
        problemas.append(f"{nome_bucket} tem website hosting habilitado")
    except ClientError as erro:
        if erro.response["Error"]["Code"] in (
            "NoSuchWebsiteConfiguration",
            "NoSuchBucket",
        ):
            print("    website hosting: desabilitado")
        else:
            problemas.append(f"não foi possível verificar website hosting: {erro}")

    return problemas


def verificar_block_public_access_da_conta() -> List[str]:
    """Verifica o Block Public Access no nível da conta.

    Funciona como segunda barreira: com ele ativo, nem uma configuração
    equivocada de bucket consegue expor conteúdo.

    Returns:
        Lista de problemas encontrados.
    """
    problemas: List[str] = []
    controle = _cliente("s3control")
    try:
        configuracao = controle.get_public_access_block(AccountId=config.ID_CONTA)[
            "PublicAccessBlockConfiguration"
        ]
        for flag, estado in configuracao.items():
            print(f"    {flag}: {estado}")
            if not estado:
                problemas.append(f"{flag} desabilitada no nível da conta")
    except ClientError as erro:
        if "NoSuchPublicAccessBlockConfiguration" in str(erro):
            problemas.append(
                "conta sem Block Public Access configurado no nível da conta"
            )
        else:
            problemas.append(f"não foi possível verificar a conta: {erro}")
    return problemas


# ---------------------------------------------------------------------------
# Orquestração
# ---------------------------------------------------------------------------


def provisionar() -> Dict[str, str]:
    """Provisiona toda a infraestrutura e verifica a postura de segurança.

    Returns:
        Dicionário com os identificadores dos recursos criados.

    Raises:
        RuntimeError: se a verificação de segurança encontrar problemas.
    """
    s3 = _cliente("s3")
    iam = _cliente("iam")
    glue = _cliente("glue")

    print("=" * 78)
    print(f"PROVISIONAMENTO — conta {config.ID_CONTA}, região {config.REGIAO}")
    print("=" * 78)

    print("\n[S3]")
    criar_bucket(s3, config.NOME_BUCKET)
    aplicar_block_public_access(s3, config.NOME_BUCKET)
    aplicar_criptografia(s3, config.NOME_BUCKET)

    print("\n[IAM]")
    arn_role = criar_role_glue(iam, config.NOME_ROLE_GLUE, config.NOME_BUCKET)
    print(f"  arn: {arn_role}")

    print("\n[Glue Data Catalog]")
    criar_database_glue(glue, config.NOME_DATABASE_GLUE)

    print("\n[Verificação de segurança — bucket]")
    problemas = verificar_seguranca(s3, config.NOME_BUCKET)

    print("\n[Verificação de segurança — conta]")
    problemas.extend(verificar_block_public_access_da_conta())

    print("\n" + "=" * 78)
    if problemas:
        print("PROBLEMAS DE SEGURANÇA ENCONTRADOS:")
        for problema in problemas:
            print(f"  - {problema}")
        print("=" * 78)
        raise RuntimeError(
            f"{len(problemas)} problema(s) de segurança. "
            f"Nenhum dado deve ser ingerido até que sejam resolvidos."
        )

    print("Infraestrutura provisionada. Nenhum recurso exposto publicamente.")
    print("=" * 78)

    return {
        "bucket": config.NOME_BUCKET,
        "role_arn": arn_role,
        "database": config.NOME_DATABASE_GLUE,
        "regiao": config.REGIAO,
    }


def main() -> None:
    """Ponto de entrada do provisionamento."""
    provisionar()


if __name__ == "__main__":
    main()
