# Validação Etapa C

Só se usam dados fictícios novos. A base reservada ao Excel, bases existentes,
instalações Windows, volumes e backups do utilizador não são acedidos/alterados.

## Resultados locais

**480 testes aprovados** na regressão completa inicial em PostgreSQL17 isolado
(227,976s). Foram acrescentados dois testes de empacotamento seguro: agora são24
nativos, todos aprovados isoladamente; a execução final passa a482 testes. Incluem51 testes Chromium das aplicações de gestão e Stock, operações,
concorrência, perfis, PDFs, exportações assinadas, backups e recuperação existentes.

Os24 nativos cobrem assinatura/inventário/versionamento, chave errada, ficheiros
alterados/em falta/extra, versões repetidas/antigas/incompatíveis, reposição após
desinstalação reconhecida, reparse points, cifragem autenticada e frase errada,
truncamento/corrupção, arquivo/extração segura, evidências e sequências PostgreSQL,
falhas em cada fase do atualizador, bloqueio exclusivo, perfil loopback e política
HTTPS/mTLS/CRL reutilizada. O SQL de evidências SHA-256 foi também executado em
PostgreSQL17 sintético.

A primeira regressão teve7 erros de backup causados pela porta do adaptador Docker
do ambiente de ensaio; corrigido esse adaptador privado, todos passaram. Não houve
alteração à lógica de backup existente para acomodar o ensaio.

## CI e instaladores reais

Os workflows executam:

- Django/PG17/Chromium, build Docker limpo, backup/restauro do piloto anterior,
  exportações com conta restrita e Stock offline com HTTPS confiável.
- 37 verificações PowerShell das etapas anteriores em Windows.
- NTFS real e SID de contas virtuais num fixture novo, antes do empacotamento.
- Compilação NSIS1.0.0/1.1.0, com hashes e autoridade temporária de teste.
- Instalação real de `.exe`, criação/arranque/paragem de serviços, utilizador
  Windows não administrador, isolamento dos ficheiros privados e persistência.
- Migração irreversível **apenas sintética** entre1.0 e1.1, sem mudar as migrações
  funcionais do repositório; o código antigo deve recusar o esquema mais recente.
- Ensaio efetivo de pg_restore, dados/documentos/evidências, falha após migração,
  serviços desativados, recuperação nova com a versão exata e original conservado.
- Ficheiros Stock assinados antes/depois, origem/contador/chaves preservados,
  certificados/CRL, HTTPS nativo, ausência/revogação de certificado, POST negado,
  ficheiros privados inacessíveis e PostgreSQL recusado no IP da rede.
- Recusa de downgrade, desinstalação sem destruição e reposição da mesma versão
  sem reseed/migração.

Resultados finais e links da CI serão completados após a revisão final. A
instalação inicial real e o probe NTFS já passaram; uma falha no teste de conta
sem privilégios está a ser corrigida antes de declarar o ciclo integral validado.
Os instaladores compilados são **SYNTHETIC / UNSIGNED / NOT FOR PRODUCTION**.
Usar o par de versões do **mesmo artefacto/run**: a autoridade temporária muda
entre execuções e instalações diferentes não aceitam pacotes de outra autoridade.

A execução hospedada é **WindowsServer2025**, não Windows11 físico. As chaves
privadas de teste, certificados e backups nunca são incluídos nos artefactos.

## Homologação ainda obrigatória

- VM Windows11Pro limpa: requisitos, runtimes, antivírus e políticas empresariais.
- Reinício real e interrupção/reboot/energia a meio de uma atualização.
- Sessão Windows não administradora com desktop, atalhos e navegador real.
- Certificado empresarial Authenticode, timestamp, cadeia/revogação, SmartScreen.
- Versões históricas representativas, avaria/espaço insuficiente e recuperação.
- Destino empresarial de backup, retenção, monitorização e recuperação de chaves.
- Android físico com certificados individuais, CRL/DNS e Wi-Fi autorizados.

`tests/native_windows/reboot_probe.py before|after` prepara verificações automáticas
para um reinício real efetuado pelo orquestrador de uma VM de homologação. Exige
aprovação explícita, Hyper-V convidado Windows11 (recusa computador físico/Server)
e base sintética com movimentos confirmados. Compara dados, documentos, sequências,
identidade, chave e serviços após o reboot. **Não foi executado neste ambiente** e
não reinicia qualquer máquina por iniciativa própria.

Não confundir código ou simulação com homologação. Não instalar em produção antes
de aprovação da informática. Não foram instalados componentes em dispositivos reais.
