# Backups e recuperação

Não há backups de produção configurados nesta entrega. O mecanismo e os modelos
de agendamento foram implementados e testados apenas com dados sintéticos.
O volume Docker conserva dados, mas não substitui backup nem restauro comprovado.

## O que é guardado

`python manage.py backup_data` cria um pg_dump custom, cópias dos PDFs/assinaturas
efetivamente guardados e um manifesto SHA-256/tamanho por ficheiro. Os documentos
já pertencem ao PostgreSQL e estão também no dump. O bloqueio coordenado pausa
confirmações/publicação enquanto o dump e a cópia dos documentos são criados.
As páginas de consulta continuam disponíveis. O arquivo só aparece no destino
após verificação completa; uma falha não elimina os backups anteriores.

O destino `BACKUP_ROOT` deve estar fora do checkout, com modo 0700, em disco,
servidor ou armazenamento separado da base principal. Ficheiros usam modo 0600.
Em produção, `BACKUP_GPG_RECIPIENT` é obrigatório e o arquivo final é cifrado.
Só a chave pública deve estar no processo de backup; a chave privada de recuperação
é conservada separadamente, com acesso controlado e recuperação da própria chave.
Nunca enviar um backup não cifrado para armazenamento público.

A retenção conserva `BACKUP_RETENTION_COUNT` arquivos completos (14 por defeito).
Só atua depois de publicar um novo backup verificado. Isto não é retenção por
idade nem substitui versões imutáveis/offsite. Ajustar tamanho, frequência,
retenção legal, RPO/RTO e capacidade à infraestrutura real.

## Testar isoladamente

O comando recusa o modo sintético se a base não tiver um nome de testes/sintético.
Nunca usar a base privada reservada. Exemplo com uma base sintética já criada:

```sh
BACKUP_ROOT=/caminho/separado/privado BACKUP_RETENTION_COUNT=3 \
DB_NAME=garrafas_stage4_synthetic uv run python manage.py backup_data --synthetic

BACKUP_ROOT=/caminho/separado/privado DB_NAME=garrafas_stage4_synthetic \
uv run python manage.py restore_synthetic_backup /caminho/separado/privado/ARQUIVO.tar.gz \
  --database garrafas_restore_ensaio --confirm-isolated
```

O destino tem de ser uma base **nova** `garrafas_restore_...`. Se já existir,
recusa e não altera nada. O comando só aceita backups marcados sintéticos, nunca
elimina bases e conserva o destino novo para diagnóstico se o restauro falhar.
Arquivos `.gpg` requerem uma chave privada disponibilizada pelo operador no
ambiente de recuperação; não há password ou chave predefinida. Use PostgreSQL 17
client tools, ou `PG_TOOL_PREFIX` documentado na instalação.

A suíte restaura realmente uma base sintética nova e verifica stock, documentos,
checksums e triggers do histórico. Testa também cifragem/decifragem com chave
GPG temporária, retenção, falha de dump e rejeição de destino existente ou arquivos
alterados/com caminhos indevidos. Não usa dados do Excel nem a base reservada.

## Agendamento futuro

`deploy/garrafas-backup.service` e `.timer` preparam execução diária com atraso
aleatório, permissões restritas e timeout. Não estão instalados nem ativados.
Antes de os ativar num servidor autorizado:

1. Configurar armazenamento separado, propriedade/permissões, capacidade e quota.
2. Importar apenas a chave pública GPG para o processo de backup e guardar a
   privada noutro sistema. Testar a recuperação dessa chave.
3. Ajustar caminhos da unidade ao servidor, configuração Compose privada e timeout.
4. Executar backup e verificar um restauro num servidor de recuperação.
5. Configurar alertas sobre falhas/ausência de backups, capacidade e última
   recuperação. Só depois instalar/ativar o timer como administrador do servidor.

Não há monitorização externa, destino cloud ou conta de armazenamento configurada
pelo código. O timer usa Docker e por isso a unidade e configuração têm de ficar
restritas a root; acesso ao socket Docker é privilegiado.

## Recuperação de produção, quando autorizada

Nunca sobrescrever a base em uso. Desligar escritas e abrir uma janela controlada;
registar a versão da aplicação, o arquivo de origem e responsáveis. Selecionar um
backup próprio confiável; checksums não autenticam arquivos de origem desconhecida.

1. Numa máquina de recuperação privada, decifrar o arquivo com a chave de
   recuperação e criar ficheiros temporários com umask 077.
2. Validar o manifesto com `inventory.backups.verify_archive(caminho)` usando a
   mesma versão revista do código. Não usar `tar --extract` cego em arquivos
   recebidos de terceiros. Só depois extrair os membros verificados para uma
   área privada nova.
3. O operador cria uma base **nova** PostgreSQL 17, com owner de recuperação.
   Executar `pg_restore --no-owner --no-acl --exit-on-error --dbname NOVA_BASE`
   sobre `database.dump`, com autenticação por ficheiro/gestor de segredos e TLS.
4. Comparar tabelas, saldos, movimento final, relações, auditoria e quantidade/
   checksum/tamanho de cada documento restaurado. Abrir PDFs e assinaturas.
   Conferir ausência de movimentos perdidos ou repetidos. Não reaplicar stock.
5. Reaplicar e testar os privilégios da conta restrita; grants não entram no dump.
   Verificar autenticação, HTTPS, persistência e documentação da janela perdida.
6. Apenas após revisão e autorização, mudar a configuração da aplicação para a
   nova base. Conservar a anterior protegida e definir reversão. Nunca anunciar
   recuperação concluída só porque pg_restore terminou sem erro.

Não existe cutover automático de produção nem publicação automática do lote
Excel neste procedimento. A publicação inicial e qualquer restauro real dependem
de autorização explícita e validações de segurança, consistência e persistência.
