# Etapa D — Plano de homologação Windows 11 Home e Pro

Estado: plano para revisão. Não autoriza instalações, alterações de políticas,
execução destrutiva, publicação de releases ou utilização de dados reais.
Base analisada: `f88861ce057b98be3636f9a23ae3b36aff08c8bb` (merge do PR #13).
A aplicação final mantém Django 5.2/Python 3.12/PostgreSQL 17 nativos, sem Docker/WSL2.

## 1. Evidências e limites atuais

Na revisão anterior ao merge (`2b76519`), o PR #13 registou:

- 500 testes da suite Django/PostgreSQL, incluindo Chromium e unidades nativas;
- 14 testes de segurança, análise dos workflows e auditoria das dependências;
- 36 testes unitários nativos também executados separadamente no Windows;
- PowerShell, NTFS/ACL, compilação dos EXEs 1.0.0/1.1.0 e instalação, atualização,
  backup/restauro, recusa de downgrade, reparação e desinstalação conservadora;
- preservação de dados/movimentos, PDFs e identidade de assinatura da Etapa B.

Esses ensaios nativos foram em Windows Server 2025 hospedado. Não comprovam
Windows 11 Home/Pro, reboot do sistema, hardware físico, políticas empresariais
ou assinatura Authenticode de produção. A CI do commit main escolhido para cada
build deve ser confirmada novamente; não reutilizar apenas a conclusão do PR.

Análise dos mecanismos existentes:

- Programa e dados separados; serviços com contas virtuais; PostgreSQL apenas em
  loopback; assinatura ECDSA do pacote e confiança instalada nas atualizações.
- Atualização exige backup cifrado efetivamente restaurado e comparado antes das
  migrações. Interrupções bloqueiam arranque; não existe downgrade/rollback cego.
- Recuperação exige instalador/payload exato e destino novo sem serviços GVA.
  Preserva a origem e mantém a cópia recuperada bloqueada até conferência explícita.
- Canais synthetic/release usam dados separados mas os mesmos nomes de serviço:
  não instalar os dois simultaneamente no mesmo Windows convidado.

## 2. Decisões anteriores à execução

O proprietário deve confirmar:

1. Hipervisor autorizado para o computador Home (proposta: VirtualBox suportado,
   com TPM 2.0/Secure Boot para o Windows convidado), ou outro ambiente descartável.
   Confirmar CPU x64, RAM, espaço livre e virtualização disponível. Instalar ou
   configurar o hipervisor exige autorização separada; não contornar políticas.
2. Disponibilidade de ISO oficial e licença/direitos de utilização adequados para
   cada Windows convidado Home e Pro. Home no anfitrião não significa que o
   convidado seja Home; registar efetivamente a edição testada.
3. Responsável de informática pela assinatura do editor, políticas de execução,
   custódia das chaves e destino externo de backup; janela aceitável de perda de
   trabalho e tempo máximo de recuperação.

Windows Home não disponibiliza oficialmente a função Hyper-V nem Windows Sandbox.
Não instalar componentes de edição Pro por métodos não suportados. Sandbox não é
adequado ao ciclo persistente de serviços, reinícios e atualizações. Uma conta
Windows separada ou o sufixo synthetic não isolam serviços e alterações de sistema.

## 3. Preparar o laboratório persistente

No Home, usar uma VM persistente autorizada. No Pro, pode usar Hyper-V autorizado
ou repetir o hipervisor escolhido, documentando a diferença. A VM é apenas o
laboratório; a instalação final na empresa será nativa, sem hipervisor obrigatório.

Configuração inicial orientativa para testes sintéticos: 2–4 vCPU, 8 GB de RAM e
80–100 GB de disco virtual, mais espaço para checkpoints e cópias. O anfitrião deve
continuar com recursos livres; confirmar hardware antes de executar.

**A distribuição release exige pelo menos 16 GB de RAM no computador convidado.**
Uma VM sintética com 8 GB não homologa esse requisito. Para testar o pacote final,
reservar 16 GB ao convidado e memória adicional ao anfitrião (tipicamente um host
com 32 GB ou mais), ou escolher outro laboratório. Não reduzir a verificação de
RAM do instalador para fazer passar o ensaio.

Preparar uma imagem Windows limpa por edição e clones distintos para instalação,
recuperação e falhas. Utilizar rede NAT sem encaminhamento de portas; sem bridge,
pastas pessoais partilhadas, clipboard partilhado ou ligação automática de USB.
Transferir apenas instaladores e dados fictícios por meio controlado. Não disponibilizar
um runner de testes privilegiado no computador principal.

Criar checkpoint com a VM desligada antes de cada cenário. Checkpoints são meios
de reposição do laboratório, não são prova de recuperação de um backup da aplicação.
Guardar as evidências fora da VM antes de a repor, em área privada; não enviar
chaves, certificados privados, backups, passwords ou logs sensíveis para GitHub.

## 4. Preparar o par exato de instaladores

O workflow manual existente continua fixado a `5e34c6c`, conforme o PR #19.
Não o apresentar como build do merge `f88861c`.

Antes de homologar a Etapa D, preparar num PR separado um workflow manual próprio
com o SHA completo aprovado da main (inicialmente `f88861c...`), versões sintéticas
1.0.0/1.1.0 na mesma execução/autoridade temporária, testes Windows Server completos,
SHA256SUMS e proveniência de execução/tentativa. Disponibilizar os EXEs só após
sucesso, sem segredos, mantendo intacto o workflow histórico do PR #19.

Arquivar os dois EXEs e hashes da mesma execução. Uma recompilação com o mesmo
número de versão não substitui o payload exato exigido pelos backups. Identificar
os pacotes como sintéticos, não aprovados para produção.

Os EXEs sintéticos atuais não possuem Authenticode empresarial. Se o Windows ou
antivírus os bloquear/avisar, registar e parar, sem desativar proteção nem ignorar
avisos. Nesse caso é necessário preparar uma assinatura confiável de homologação
antes de continuar. Não instalar certificados de teste no anfitrião para contornar
bloqueios. O pacote assinado final terá de ser homologado novamente.

## 5. Sequência de testes por edição Windows convidada

| Ordem | Cenário | Aprovação mínima |
| --- | --- | --- |
| 1 | Diagnóstico prévio | Registar edição/build, recursos, disco, navegador, antivírus, ausência de serviços GVA e portas 8765/55432 livres. Nenhum serviço alheio é parado/adotado. |
| 2 | Instalação 1.0.0 pela interface | UAC compreensível, conta fictícia e recuperação configuradas; atalhos e aplicação funcionam; PostgreSQL isolado. Sem Python/PostgreSQL global. |
| 3 | Utilização sem privilégios | Login e perfis, entradas/saídas, inventários, histórico, PDFs e assinaturas; stock alterado uma única vez; operações não confirmadas sem efeitos. |
| 4 | Reboot normal do convidado | Reiniciar só a VM; serviços retomam, dados, PDFs, identidades e numeração permanecem; confirmar com evidências anteriores/posteriores. |
| 5 | Backup | Criar backup manual cifrado e verificar execução automática; cópia autorizada fora da VM; guardar chave e frase separadamente. |
| 6 | Atualização 1.0.0 para 1.1.0 | Executar segundo EXE pelo assistente; backup/restauro de ensaio antes de migrar; dados, contas, PDFs e identidade preservados; repetir reboot normal. |
| 7 | Restauro numa VM nova | Desligar/isolar origem; recuperar com instalador exato, backup/chave/frase; comparar evidências e só depois aprovar arranque. Nunca manter duas origens iguais ativas. |
| 8 | Desinstalação e reparação | Serviços/programa removidos, dados e backups conservados; reposição da mesma versão exata sem recriar dados, seguida de atualização válida. |
| 9 | Falhas e recusas | Apenas clones descartáveis: porta ocupada, pacote alterado, assinatura/canal/versão errados, frase errada e falta de espaço; falhar sem adotar dados ou apagar cópias. |
| 10 | Interrupção de atualização | Apenas clone descartável: fase controlada, interrupção do convidado, arranque bloqueado e recuperação comprovada; nunca cortar energia ao anfitrião. |

Não começar pelos cenários destrutivos. Para validar resistência a falhas, voltar
sempre ao checkpoint próprio do cenário, preservando antes a evidência e os backups.
A inicialização sintética e a migração de ensaio não pertencem à distribuição real.

Cada cenário precisa de registo PASS/FAIL/BLOQUEADO/NÃO EXECUTADO, edição/build,
commit, EXE/hash, execução/tentativa, fase e data, resultado esperado/observado,
verificações de dados/serviços e evidências privadas. Um bloqueio não conta como PASS.
A matriz Home e Pro tem resultados independentes; sucesso num não homologa o outro.

## 6. Automação adicional — proposta, ainda não implementada

`windows_smoke.py` é limitado a CI descartável e usa operações de manutenção/falha.
Não o executar no PC nem simular GITHUB_ACTIONS=true para contornar a proteção.
`reboot_probe.py` possui fases before/after úteis, mas aceita apenas convidados
Hyper-V Windows 11 e nunca reinicia a máquina por si.

Após escolha do hipervisor, preparar num PR separado:

- Um orquestrador de VM autorizada: identificar o convidado por ID, edição/build,
  manifesto de descarte e origem limpa; confirmar canal/base sintéticos, ausência
  de importações e isolamento antes de permitir qualquer ação de falha.
- Adaptar a validação de VM de forma restrita para o hipervisor escolhido; não
  remover a rejeição de máquinas físicas nem confiar apenas numa variável booleana
  ou no nome/modelo da VM. Esses testes não são uma fronteira contra administrador
  malicioso; protegem contra erros operacionais.
- Reutilizar before/after e testes de evidência, recolhendo a prova antes do reboot
  e retomando após o arranque. O reboot deve ser comandado pelo orquestrador no
  convidado autorizado, não por uma rotina livre no anfitrião.
- Automatizar checkpoints, serviços/portas, comparação de dados, atualização,
  restauro e relatórios. Testar o assistente WinForms e o uso de conta comum pela
  interface: a atual CI silenciosa não prova a experiência gráfica.
- Acrescentar testes negativos que recusem host físico, base importada, canal
  release para falhas, VM não aprovada, destino com dados e máquina errada.
- Usar laboratório privado para orquestração. Não ligar uma VM pessoal ou de
  empresa a jobs públicos de PR externos nem acrescentar runner self-hosted aos
  workflows atuais, cuja política só aprova runners hospedados.

Continuam manuais a conferência visual/UAC, confiança do editor e timestamp,
comportamento do antivírus, aceitação pela informática e ensaio final no hardware
empresarial. Automação do convidado não comprova comportamento físico do PC.

## 7. Produção e decisão de entrada em serviço

Antes da aprovação de produção:

1. Rever fornecedores, versões, hashes independentes, licenças e dependências.
2. Obter certificado Authenticode de editor confiável, com timestamp e verificação
   de cadeia/revogação; assinar os executáveis exigidos pelo build, instalador e
   desinstalador. Manter a chave ECDSA dos pacotes separada das de backup/Android.
   Custódia privada aprovada, sem chaves no Git, Android ou pacote. Assinatura não
   garante por si só ausência de avisos SmartScreen; validar sem contornar avisos.
3. Compilar canal release, sem dados ou migração de ensaio sintéticos. Não converter
   a instalação synthetic em produção nem reutilizar a sua autoridade temporária.
4. Homologar o EXE final assinado no laboratório Pro, incluindo os requisitos de
   16 GB, runtimes VC++ se necessários, antivírus/políticas, atualização e recuperação.
5. Definir destino externo de backup, retenção, monitorização e responsável; testar
   restauro. O mecanismo atual copia ao arrancar e a cada 24 h enquanto ligado,
   não a cada movimento; acordar a perda de trabalho e indisponibilidade aceitáveis.
6. Aprovar separadamente a publicação/distribuição, instalação empresarial e eventual
   carga inicial de dados reais. Não publicar release automaticamente.

A Etapa D termina com matriz de resultados, relatório de falhas/correções,
evidência privada de restauro/reboot e aprovação explícita da informática. Só então
é possível propor utilização operacional no computador Pro da empresa.
