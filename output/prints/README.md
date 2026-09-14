# Evidências visuais da execução na AWS

As imagens desta pasta foram preparadas para publicação: identificadores da conta, nomes reais de bucket e IDs de execução foram ocultados, sem remover os resultados técnicos relevantes.

## Evidências principais — incluídas no relatório

1. `01_s3_camadas_medallion.png` — bucket com os prefixos Bronze, Silver, Gold e resultados do Athena.
2. `02_glue_jobs_sucesso.png` — dois AWS Glue Jobs concluídos, com 100% de sucesso.
3. `03_glue_crawler.png` — duas execuções finais concluídas; a tentativa inicial com configuração incorreta foi corrigida.
4. `04_glue_data_catalog.png` — banco `sod_fase3` com 11 tabelas: 3 Silver e 8 Gold.
5. `05_athena_resultado_perfil.png` — consulta analítica concluída com resultado e denominador válido.

## Evidências complementares

A subpasta `complementares/` contém resultados de remuneração, diversidade e o histórico sanitizado das consultas do Athena.

## Regeneração segura

Os PNGs públicos são gerados a partir das capturas originais pelo comando:

```bash
python -m src.preparar_prints_aws --origem <PASTA_DOS_PRINTS_ORIGINAIS>
```

Antes de publicar novas capturas, confirme que não aparecem usuário, e-mail, ARN pessoal, identificador da conta, nome real do bucket, caminho local ou credencial.
