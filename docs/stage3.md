# Etapa 3 — operações, conferência e inventário

Esta entrega mantém Django 5.2 LTS, Python 3.12, PostgreSQL 17 e o visual V3.
Implementa fluxos funcionais, testados com dados sintéticos; não publica o Excel,
não põe a aplicação em produção e não autoriza utilização operacional oficial.
As [decisões técnicas](decisions/0003-operational-transactions.md) explicam os
bloqueios, a conferência, a compatibilidade interna e o esquema de contagens.

## Entradas e saídas

1. Criar rascunho em **Entradas** ou **Saídas**.
2. Pesquisar pessoas existentes pelo nome ou introduzir um novo nome.
3. Pesquisar referências por código/designação/localização/setor e selecionar
   várias. Adicionar e guardar não altera stock.
4. Introduzir caixas e/ou garrafas soltas. Ambos os campos começam vazios;
   preservam-se as quantidades exatas, mesmo uma decomposição não canónica.
   Capacidade desconhecida permite apenas garrafas individuais, sem inventar
   capacidade. A página mostra stock atual e previsto, total e equivalência.
5. Guardar e reabrir por **Os meus rascunhos**, ou **Guardar e conferir**.
6. Rever todas as linhas, voltar a corrigir se necessário e confirmar
   explicitamente. A confirmação volta a validar o stock e é uma transação única.

Na entrada, a confirmação pergunta se pretende um futuro relatório. Na saída,
a marcação é obrigatória e a validação é apenas simples. Guardam-se dados e opções,
mas não se gera PDF nem se permite assinatura nesta etapa. Zero total e negativos
não são movimentos válidos de entrada/saída. Referências inativas são recusadas.

A entrada permite guardar o rascunho e abrir a criação de referência. O serviço
de catálogo existente pesquisa globalmente designações normalizadas, em todas
as localizações e estados; correspondências apresentam código, localização e
estado. Referências históricas legítimas não são fundidas. A referência inativa
pode ser reativada numa página com confirmação explícita, preservando identidade
e histórico; depois é adicionada à entrada. Saídas e inventários não oferecem
criação de referências. Esses caminhos também recusam pedidos forjados.

## Rascunhos e permissões

Só administradores criam, editam, cancelam, conferem ou confirmam operações. Cada
administrador acede aos seus rascunhos. Revisões impedem que uma janela antiga
sobrescreva a versão mais recente. Campos incompletos de quantidade permanecem
NULL, distintos de zero, e bloqueiam confirmação. Cancelar preserva dados e gera
auditoria sem alterar stock. Repetir uma confirmação não tem um segundo efeito.

Consulta pode ver stock e movimentos confirmados, sem aceder a rascunhos nem
modificar informação. CSRF e permissões são verificados no servidor. Campos de
stock, impacto, tipo, proprietário, estado e validação enviados pelo navegador
não têm autoridade para alterar esses valores.

## Inventário parcial ou completo

O parcial permite escolher referências ativas. O completo inclui todas as ativas
abrangidas pelos filtros de criação; a lista fica fixada. Na contagem, pesquisa
por código/designação/localização/setor e paginação de 30 linhas permitem navegar
um catálogo de centenas. Deve guardar antes de pesquisar ou mudar de página.

Campos vazios significam **ainda não contado**. Um zero introduzido é uma contagem
explícita; a confirmação exige contagem em todas as linhas abrangidas. O total
contado é independente do ajuste: `diferença = contado - stock atual`. Uma
contagem com diferença exige motivo de linha ou motivo geral. Conservam-se os
valores introduzidos, capacidade, contagem, base observada, diferença e saldos.

Se stock, versão ou configuração mudar depois da contagem, o servidor mostra a
divergência e exige nova conferência. Reguardar os mesmos valores não aceita a
mudança silenciosamente. Após rever os valores atuais, o botão **Conferi novamente
as contagens com o stock atual** aceita explicitamente a base das linhas dessa
página. Uma alteração posterior voltará a bloquear confirmação.

Pode escolher uma localização de destino e um setor dessa localização, ou nenhum
setor. Nada muda no catálogo enquanto o inventário é rascunho. A confirmação
regista transferências mesmo com diferença quantitativa zero. Todas as alterações
de stock/localização/setor/auditoria são revertidas se qualquer linha falhar.
As quatro localizações e os 27 setores continuam configurados pelas migrações
estruturais; não há atribuição automática a referências.

## Histórico e correções

O histórico apresenta tipo, data e responsável, pessoa, referências, caixas e
garrafas introduzidas, capacidade, contagem física, diferenças, stock anterior e
posterior, motivos e transferências. A ficha confirmada acrescenta auditoria e
relações de correção. Datas sem hora, sinais, documentos, anotações e proveniência
Excel conservam-se nos campos e fontes anteriores.

Para corrigir, abrir um movimento confirmado e escolher **Registar correção
relacionada**. É criado um novo inventário parcial com motivo obrigatório e as
referências ativas do original. Contar o stock físico correto, rever e confirmar;
não se reaplica automaticamente a quantidade original nem se edita o documento.
Se uma referência estiver inativa, a reativação explícita pelo catálogo é um passo
administrativo separado antes da contagem. Movimentos, linhas, proveniência e
transferências confirmados são imutáveis; auditoria é apenas de acréscimo.

## Ambiente de desenvolvimento e validação

A base que contém a pré-visualização pendente permanece reservada. Não executar
migrações de Etapa 3, criar operações, reimportar Excel nem publicar lotes nessa
base durante a avaliação. Não alterar `.env` para a fazer receber dados de teste.
Use PostgreSQL distinto ou uma base sintética separada explicitamente criada pelo
administrador de desenvolvimento. Só nessa base execute migrações, criação de
contas sintéticas e servidor, com `DB_NAME` definido em cada comando.

Exemplo, depois de criar a base vazia `garrafas_stage3_synthetic` no PostgreSQL:

```sh
DB_NAME=garrafas_stage3_synthetic uv run python manage.py migrate --noinput
DB_NAME=garrafas_stage3_synthetic uv run python manage.py create_user operador-sintetico --role admin
DB_NAME=garrafas_stage3_synthetic uv run python manage.py runserver
DB_NAME=garrafas_stage3_synthetic DB_TEST_NAME=test_garrafas_stage3 uv run python manage.py test accounts inventory imports web tests.browser --noinput
```

A suíte cria e elimina a sua própria base de testes. Usa conexões PostgreSQL reais
para concorrência, incluindo observação de espera por bloqueio de linha, e
Chromium em 1366×900 e 390×844 para entrada, saída e inventário. A CI executa a
mesma suíte. `BROWSER_ARTIFACT_DIR` permite guardar screenshots sintéticos fora do
checkout para revisão local. Nunca capturar dados reais para incluir no Git.

Não foram publicados dados reais nem alterada a pré-visualização. PDFs privados,
assinatura desenhada, PWA, exportação Excel, alojamento, segurança de operação,
backups automáticos e restauro comprovado continuam na Etapa 4. A publicação
inicial requer uma janela controlada e confirmação explícita separada.
