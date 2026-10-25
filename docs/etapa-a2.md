# Etapa A2 — utilização, acessos e documentos

Branch `fix/etapa-a2-utilizacao`, baseada em `fix/entradas-saidas-diretas`
(Etapa A / PR #8, revisão `7263c53`). PR em rascunho destinado à Etapa A;
não inclui nem integra as etapas Android 6/7. Django 5.2, Python 3.12,
PostgreSQL 17 e os originais Copo com Vida mantêm-se.

## Utilização

- Entradas e Saídas abrem com **Pesquisar referência**, sem resultados até
  pesquisar pelo nome. Clicar no nome adiciona diretamente uma referência,
  sem duplicados; Caixas e Garrafas soltas começam vazias. **Confirmar quantidade**
  guarda a linha e minimiza-a; clicar no resumo permite editar/remover.
  Este passo não confirma o movimento nem altera stock. Só a conferência e a
  confirmação final têm efeito quantitativo. Campos inválidos ficam visíveis.
- **Stock** mantém a listagem inicial e a paginação. A pesquisa pelo nome é
  automática, sem filtros de localização/setor. O nome abre a ficha; as ações
  administrativas e a consulta de inativas estão aqui. O menu Referências foi
  retirado, conservando as rotas e dados. Desativar continua a exigir stock zero.
- **Histórico** começa minimizado; expandir/minimizar é uma operação nativa do
  navegador, sem pedidos de escrita. Conserva filtros, ordem, paginação,
  proveniência Excel, correções e transferências. O PDF continua acessível.
- O painel tem apenas as três métricas de stock e os atalhos autorizados.
  Operações por concluir continuam disponíveis no respetivo formulário.
- Inventários conservam a seleção e filtros existentes; a nova seleção direta
  aplica-se apenas a Entradas e Saídas. A aplicação Stock separada não é alterada.

## Perfis e contas individuais

Em **Definições → Perfis de Acesso**, o Administrador cria/edita/desativa perfis,
com password atual, confirmação e motivo auditado. Em **Gerir utilizadores**,
escolhe perfil Personalizado e o perfil concreto. Não existem contas partilhadas
ou passwords predefinidas; a migração cria apenas o exemplo **Substituto**.

| Ação | Administrador | Consulta | Substituto inicial |
|---|---|---|---|
| Consultar stock ativo | Sim | Sim | Sim |
| Criar/editar/conferir/confirmar entradas e saídas próprias | Sim | Não | Sim |
| Histórico e relatórios | Todos | Todos | Só entradas/saídas próprias autorizadas |
| Obter PDF; regenerar uma cópia eliminada | Sim | Obter apenas | Só das próprias operações autorizadas |
| Eliminar ficheiro PDF | Sim | Não | Não |
| Inventários e correções relacionadas | Sim | Não | Não |
| Catálogo, alertas, reativação e localizações | Sim | Não | Não |
| Excel/exportação | Sim | Sim (comportamento anterior) | Não |
| Utilizadores, perfis, definições e importação | Sim | Não | Não |

As capacidades podem ser escolhidas individualmente. `reports_manage` exige
também `reports_view` para aceder a um documento; não alarga o âmbito do histórico.
Sem `history_all`, o âmbito são operações próprias dos tipos concedidos.
Administração de acessos e importação são exclusivas do perfil fixo Administrador,
sem opção de concedê-las a perfis personalizados. O Substituto não pode criar
referências durante uma entrada; pede essa criação a um Administrador.

O servidor e os serviços consultam novamente a conta/perfil persistidos em cada
ação. A desativação/revogação afeta sessões existentes e objetos de utilizador
antigos. Escritas de domínio e mudanças de acesso partilham um bloqueio de
transação, impedindo a passagem de uma revogação entre validação e gravação.
Não se pode retirar o próprio acesso de Administrador nem o último Administrador
ativo. Contas e perfis desativados preservam identidades e rastreabilidade.

## Datas, números e compatibilidade histórica

A data inicial é o dia local, no fuso `Europe/Lisbon`. A confirmação exige que
**a data oficial e o dia local da criação sejam hoje**, inclusive em pedidos
forjados. Uma operação de outro dia pode ser consultada/cancelada, ou pode
iniciar-se outra; nunca se apaga automaticamente nem se muda a data em silêncio.

Novos PDFs recebem `Mov-N/AA`, com ano completo no modelo e na evidência.
O contador anual é bloqueado em PostgreSQL dentro da confirmação. Unicidade,
imutabilidade e transições do contador têm constraints/triggers. Entradas sem PDF
não consomem número. Falhas revertem stock, documentos, auditoria e contador;
um número efetivamente emitido nunca é reutilizado. Regenerar não emite outro.

**Não se numeram retroativamente** movimentos Excel, documentos anteriores ou
movimentos sem relatório. Os anteriores conservam `MOV-id`, ficheiros, datas,
hashes e metadados originais. Filtros e histórico aceitam a nova numeração.
O identificador técnico do movimento continua distinto do número anual do PDF.

## PDFs e evidência

Os novos PDFs de entrada/saída têm o logótipo completo original à esquerda,
Vertente Aveludada à direita, apenas data oficial, Cliente e três colunas:
Referência / Quantidade movimentada / Stock final. Conservam a decomposição
efetivamente introduzida; o saldo usa caixas completas e soltas, ou só garrafas
se a capacidade é desconhecida. Não recalculam documentos ao abrir.
Inventários mantêm a tabela detalhada de contagem/ajuste/transferências.

“Validação com assinatura.” é só apresentação: permanece uma assinatura desenhada
PNG, sem estatuto de assinatura digital qualificada. A evidência original não muda.

`Document` continua imutável. Para PDFs A2, a evidência contém o snapshot completo,
hash/tamanho, número, data e hash da assinatura; `ReportFile` contém os bytes
reproduzíveis. `ReportTemplate` preserva fontes e logótipo públicos, nomes,
layout, versão do motor e hash do renderizador. Os bytes de assinaturas e PDFs
anteriores continuam em `Document.payload`.

Eliminar em **Relatórios** exige confirmação explícita e autorização. Antes de
remover os bytes, o serviço demonstra uma reprodução **idêntica byte a byte**.
Mantêm-se a identidade, número, receita, movimento, saldo, assinatura e auditoria.
No **Histórico**, regenerar repõe apenas bytes com hash/tamanho iguais aos de
emissão, auditados como reprodução. Não usa catálogo, pessoa ou stock atuais.
Repetir a regeneração não produz outro número/ficheiro ou auditoria fictícia.

**O único exemplar histórico sem receita fiel não pode ser eliminado.** Se mudar
o motor/layout e já não se obtiverem os mesmos bytes, o sistema recusa eliminar
ou regenerar: conservar código/imagem e dependências da versão de emissão e
pedir recuperação compatível. Preservar `pdf_v3.py` e os auxiliares de apresentação
para futuras versões; um novo layout deve ter outro renderizador. Os backups
incluem receitas, números, perfis, assinaturas e estado de ficheiros eliminados.

## Migrações e riscos

- `accounts.0003`: perfis, associação de conta e terceiro tipo de perfil;
  `0004`: exemplo Substituto sem conta.
- `inventory.0011`: confirmação individual de quantidade, contador, identidade,
  receita e bytes reproduzíveis; `0012`: proteções PostgreSQL; `0013`: bloqueio
  de reversão destrutiva quando já existem evidências/quantidades A2.
- Não se reescrevem saldos, histórico, PDFs, números ou contas anteriores.
  As tabelas são adicionais, mas **o código anterior não compreende perfis
  personalizados nem PDFs A2**. Não iniciar código antigo sobre uma base A2.
- Atualizar os grants da conta restrita depois das migrações. As novas transições
  permitem somente substituir bytes por NULL ou repor os bytes originais;
  não concedem DELETE sobre o livro ou a identidade dos documentos.
- O dump contém dados privados; guardar fora de Git, com proteção autorizada.
  Backup inclui segredos/configuração em cópia protegida separada conforme o guia.
- A reprodução e fontes aumentam o tamanho da base; as receitas são partilhadas
  por versão. O bloqueio comum privilegia consistência para o volume deste piloto.

## Atualização segura do piloto Windows

**Procedimento manual posterior à revisão; não foi executado no computador do
utilizador.** Não aplicar o procedimento sem migrações da Etapa A à A2.

1. Conferir a versão do piloto atual e fazer **Backup.cmd** com a versão instalada,
   para uma pasta/suporte autorizado. Conservar código/imagem anteriores, pasta
   privada e segredos protegidos. Anotar contas, saldos, movimentos, PDFs e números.
2. **Parar.cmd** no piloto anterior. Não apagar contentores, volumes, backups,
   atalhos, manifestos ou segredos. Não executar `down -v`, reset ou limpeza Docker.
3. Obter o código A2 revisto numa **nova pasta de código**. Não mudar a branch
   dentro da pasta `Source` do piloto anterior. Confirmar espaço para imagem,
   segunda base, dump e backups. A recuperação exige Docker/WSL2 já autorizados;
   não altera políticas do Windows nem requer portas de rede novas.
4. Na raiz da nova cópia A2, em PowerShell aprovado, recuperar para uma pasta
   privada inexistente e porta loopback livre (ajustar os três caminhos):

   ```powershell
   $ErrorActionPreference = 'Stop'
   Import-Module .\scripts\windows\Common.psm1 -Force
   $a2 = Recover-GGPilot -Archive 'C:\BackupsAutorizados\piloto.tar.gz' `
       -NewHomePath "$env:LOCALAPPDATA\GestaoGarrafasA2" `
       -SourceRoot (Get-Location).Path -Port 8766
   Start-GGPilot -HomePath $a2.Home
   ```

   Usar a função **da nova cópia A2**, não Recuperar.cmd da versão antiga.
   O arquivo é verificado, o destino tem de estar vazio, os documentos são
   verificados e só a cópia recebe migrações/grants e uma nova identidade de
   instalação. A origem não é adotada nem substituída. Repetir sobre um destino
   já ocupado é recusado. Se falhar, preservar a tentativa para diagnóstico;
   nunca forçar flags, hashes ou manifestos para ultrapassar proteções.
5. Conferir na cópia contas, referências, saldos, movimentos, PDFs históricos e
   novas permissões. Testar uma operação fictícia, numeração, backup e recuperação
   para outro destino vazio. Confirmar que PostgreSQL não publica portas e que
   a aplicação só responde em `127.0.0.1`. Não usar simultaneamente os dois pilotos.
6. Só após aceitação, criar explicitamente os atalhos da cópia validada:
   `New-GGShortcuts -HomePath $a2.Home`. A recuperação não troca atalhos sozinha.
   Conservar a origem parada e os backups. A nova cópia passa a ser o único piloto
   usado, com os mesmos dados recuperados; não é uma nova seed de substituição.

**Regressar à versão anterior:** antes de usar a A2, parar a cópia e arrancar a
origem intocada com os scripts originais; repor o atalho original explicitamente.
Depois de novas operações/contas/perfis A2, a origem já não inclui esse trabalho:
não a apresentar como atual, nem forçar reversão de migrações. Preservar a A2,
fazer backup e recuperar a última cópia com código compatível. A reversão destrutiva
é bloqueada quando há evidência; qualquer migração inversa exige revisão específica.

Instalar A2 sobre um manifesto anterior e executar migrações pendentes numa base
semeada são recusados. O arranque diário nunca migra. Nenhum procedimento desta
entrega importa/publica Excel, altera a pré-visualização ou ativa uso oficial.

## Validação

Os testes usam apenas bases novas sintéticas: fluxos web, permissões/revogação,
CSRF e pedidos forjados; mudança de ano/concorrência real; PDFs/assinaturas,
eliminação e reprodução exata; migração de esquema anterior com evidência
preservada; backup/restauro e reprodução num processo separado; Chromium em
computador/móvel; imagem com conta restrita e stack Windows em projetos isolados.
`tests/windows/smoke_stack.py --image IMAGEM_A2 --previous-image IMAGEM_A`
permite ensaiar a recuperação de um piloto anterior inteiramente fictício.

A CI verifica PowerShell 5.1, NTFS, atalhos e recusa de atualização direta num
runner Windows. Falta aceitação física no Windows 11/Docker Desktop/WSL2 do
utilizador: permissões empresariais, espaço, backup em suporte autorizado,
atalhos/ícone/PWA e impressão dos PDFs. Chromium móvel não substitui Android físico.
Não se executou qualquer instalação/atualização nos dispositivos reais.
