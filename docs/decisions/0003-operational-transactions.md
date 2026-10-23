# Decisão 3 — rascunhos, conferência e contagens físicas

Data: 2026-10-23. Âmbito: Etapa 3; Django 5.2 LTS / Python 3.12 / PostgreSQL 17.

## Livro e rascunhos

Continuamos com o monólito modular e HTML responsivo V3, com JavaScript local
apenas para antecipar totais. Todas as decisões quantitativas são repetidas no
servidor. `inventory.operations` gere o ciclo dos rascunhos;
`inventory.services.confirm_movement` continua a única confirmação operacional.
A importação reconciliada usa o seu próprio serviço e não é executada nesta etapa.

Os rascunhos têm proprietário, revisão otimista e estado terminal cancelado. As
linhas guardam caixas e garrafas separadamente, incluindo NULL (campo não
preenchido) e zero explícito. A quantidade assinada pode estar NULL num rascunho.
Uma revisão antiga não pode sobrescrever trabalho noutra janela. Criar, guardar,
conferir e cancelar gera eventos de auditoria, sem afetar saldos nem fabricar
movimentos quantitativos. A criação de pessoas normaliza espaços e maiúsculas.

As operações novas criadas pelo serviço usam `workflow_version=1`: exigem
conferência persistida e token antes da confirmação. O valor zero mantém a
compatibilidade dos clientes internos anteriores de entradas/saídas (quantidade
assinada sem decomposição); esse campo não é aceite de pedidos HTTP. Inventários,
incluindo clientes internos, exigem sempre contagem física e base de contagem.
Não se confirma histórico legado por este serviço.

## Concorrência e conferência

A ordem dos bloqueios é: advisory lock do catálogo/importação, movimento, linhas
por referência, referências por PK. Reutilizar o advisory lock impede que edições
de catálogo/remover setores ou publicação inicial se intercalem com operações.
Esta opção serializa também confirmações em referências independentes; é um
compromisso consciente para este volume, com simplicidade e integridade. A futura
redução desse âmbito exige medir contenção e redesenhar a ordem de bloqueios.
Os bloqueios de linha PostgreSQL continuam a proteger os saldos, inclusive perante
outros escritores que bloqueiem diretamente essas linhas.

Conferir guarda um UUID e um snapshot de stock, versão, capacidade, designação,
localização, setor e estado. Editar invalida o token; confirmar repete validações
sob bloqueio. O snapshot não é atualizado silenciosamente por GET. Uma mudança
exige nova conferência. A versão de stock deteta inclusive uma alteração seguida
de reposição do mesmo saldo. Confirmar duas vezes falha, sem repetir efeitos.

## Inventários

A quantidade física contada é separada do impacto: `quantidade = contagem - stock
atual`. Caixas e unidades representam a contagem, nunca o valor absoluto do ajuste.
Conservam-se contagem, capacidade, base observada, motivo, stock anterior, diferença
e stock final. Diferenças não nulas exigem motivo de linha ou motivo geral.
Referências não contadas nunca são convertidas em zero.

O âmbito completo fixa todas as referências ativas abrangidas pelos filtros no
momento da criação. Novas referências posteriores não entram silenciosamente.
Todas as linhas incluídas têm de estar contadas; não é possível removê-las desse
rascunho. O parcial permite seleção e remoção explícitas. Pesquisa e paginação
servem catálogos de centenas de referências sem enviar todos os campos num POST.

Cada contagem conserva a versão observada. O formulário assina o contexto mostrado
(referência, movimento, revisão e estado), para detetar uma alteração durante a
introdução. Reguardar a mesma contagem não aceita automaticamente outro stock.
Depois de consultar a divergência, o administrador pode usar o comando explícito
«Conferi novamente», sobre as linhas da página atual. Uma mudança de quantidade
constitui também nova contagem, com o estado mostrado nessa página.

As localizações/setores de destino ficam apenas planeados no rascunho. Na
confirmação, transferências, auditoria, snapshots e quantidades partilham a mesma
transação. Setores devem pertencer à localização; podem ficar vazios. Transferir
sem diferença gera um registo de transferência e uma linha de contagem com impacto
zero, sem inventar entrada ou saída. Uma falha reverte tudo.

## Imutabilidade e documentos

Os triggers anteriores continuam a proteger movimentos, linhas e proveniência
Excel. Novos triggers protegem transferências confirmadas e tornam a auditoria
apenas de acréscimo. Os caminhos ORM normais também recusam essas alterações.
O dono da base continua a ser privilegiado; isto não substitui a conta restrita
prevista para produção.

Correções criam novos inventários relacionados, limitados às referências do
movimento original, com motivo obrigatório. Não reescrevem o original. Nomes de
referências e pessoas, capacidades, entradas de caixas/unidades e rótulos das
localizações/setores são preservados em snapshots para futuras apresentações.
Relações e dados importados, sinais, documentos e anotações mantêm-se intactos.

Entradas exigem uma escolha explícita de relatório na confirmação. Saídas guardam
sempre essa obrigação e usam apenas validação simples. Não se oferece assinatura
nem se gera PDF; os respetivos dados ficam preparados para a Etapa 4.

## Isolamento da publicação inicial

Todas as migrações e operações de desenvolvimento desta etapa usam uma base
sintética distinta. A base que conserva a pré-visualização privada não recebe
migrações nem operações. Testes Django criam uma terceira base descartável.
Nenhuma migração contém pessoas, produtos ou stocks reais. A aplicação permanece
em desenvolvimento, sem autorização de uso operacional oficial.
