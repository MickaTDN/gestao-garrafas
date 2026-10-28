# Validação Etapa C

Só se usam dados fictícios novos. A base reservada ao Excel, bases existentes,
instalações Windows, volumes e backups do utilizador não são acedidos/alterados.

## Correção dos diagnósticos Windows — 28 de outubro de 2026

A [tentativa 2 da execução 40581409569](https://github.com/MickaTDN/gestao-garrafas/actions/runs/40581409569/attempts/2),
na revisão `1396083044f76ac2e96d5891a6854d8fcc301ae1`, publicou uma anotação
`UnicodeEncodeError` para o carácter `\u2192` da mensagem final de sucesso
(`windows_smoke.py`, antiga linha 350). A consola redirecionada usava cp1252.
A API de logs permanece bloqueada neste ambiente; a anotação pública e o código
da revisão exata foram consultados. Não se afirma ter descarregado o log integral.

A mensagem de versão incompatível anexada à exceção não identifica uma falha
anterior de recuperação: o teste executa deliberadamente o instalador 1.0.0
contra a instalação 1.1.0 e exige que seja recusado. O anfitrião sintético escreve
essa recusa em `host-error.txt`, mas não apaga o ficheiro após comandos posteriores
bem-sucedidos. O antigo tratamento de exceções anexava esse último erro a qualquer
falha posterior, incluindo uma falha ao imprimir o resultado final.

O journal `{"phase":"recovery-started"}` também não basta para concluir que o
restauro falhou. `recover()` conserva-o intencionalmente mesmo após escrever
`recovery-verified.json`, para impedir ativação/publicação automática antes da
conferência explícita da informática. Antes de imprimir a mensagem que falhou,
o teste já tinha exigido o marcador de verificação, a chave original, 33 garrafas
fictícias, dois movimentos confirmados e a origem/sequência de exportação intactas.
Uma falha nessas verificações teria interrompido o teste antes daquela linha.

A correção limita-se ao teste, diagnósticos e CI; não altera o mecanismo de
atualização/recuperação nem as regras de stock:

- Mensagem final ASCII (`1.0->1.1`); mensagens com caracteres não suportados pela
  consola usam escapes reversíveis, sem mascarar a exceção original.
- O erro do anfitrião é limpo antes de cada invocação e só é anexado à falha
  desse comando. Uma recusa esperada tem de devolver código diferente de zero.
- Marcos distintos para atualização, recusa de downgrade, reposição, interrupção
  simulada e recuperação verificada, ainda bloqueada até aprovação da informática.
- Verificação adicional do conteúdo do marcador de recuperação, da ausência de
  autorização de ativação e da recusa de arranque dos serviços web/backup/publicador.
- Dez testes de regressão novos, incluindo subprocesso real com
  `PYTHONIOENCODING=cp1252:strict`, diagnóstico Unicode, erro antigo, erro atual,
  timeout e recusa inesperadamente aceite. Os **34 testes unitários nativos**
  passaram localmente em Linux. O workflow executa-os também em Windows antes
  de compilar/instalar os executáveis sintéticos.

A aprovação do ciclo Windows completo depende da nova execução de CI, não deste
resultado unitário nem da inferência sobre a execução anterior. Continuam válidos
os requisitos de homologação Windows11 e empresarial indicados abaixo.

## Resultados locais

**482 testes aprovados** em PostgreSQL17 isolado (241,140s):458 existentes e24
nativos. Incluem51 testes Chromium das aplicações de gestão e Stock, operações,
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

Os resultados de cada revisão, eventuais falhas e artefactos estão no
[PR13](https://github.com/MickaTDN/gestao-garrafas/pull/13) e nos workflows
[Checks](https://github.com/MickaTDN/gestao-garrafas/actions/workflows/ci.yml) e
[Native Windows installer](https://github.com/MickaTDN/gestao-garrafas/actions/workflows/windows-native.yml).
O ciclo integral Windows deve terminar com sucesso na revisão a homologar;
a simples compilação ou um resultado de revisão anterior não o substituem.
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
