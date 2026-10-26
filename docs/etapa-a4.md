# Etapa A4 — numeração do movimento e lista de trabalho de inventário

Branch `fix/etapa-a4-numeracao-inventario`, baseada na última revisão A3 / PR #10
(`54dffe4`), com PR em rascunho destinado a `fix/etapa-a3-correcoes`.
Mantém Django 5.2 LTS, Python 3.12, PostgreSQL 17 e a identidade Copo com Vida.
Não altera as aplicações Android nem integra outras branches ou main.

**Esta entrega não pede instalação ou testes no computador pessoal.** A instalação
A3 existente permanece intacta. A validação usa exclusivamente bases sintéticas
novas e recuperação automática em ambientes isolados, incluindo a CI Windows.
Uma futura instalação na empresa continua a exigir revisão técnica e autorização
próprias; esta entrega prepara código e evidência de validação, sem deployment.

## Alteração 26 — número anual independente do PDF

Cada nova confirmação de Entrada, Saída ou Inventário recebe `Mov-N/AA`, usando
o ano completo da data oficial. Entradas/saídas partilham o mesmo contador anual;
inventários/correções continuam a usar essa sequência, preservando o comportamento
anterior. Não existem contadores por tipo nem conversão do ID interno em número.

O contador e a identidade são atribuídos na transação da confirmação, juntamente
com stock, localização, documentos e auditoria. Qualquer falha reverte tudo.
Rascunhos, conferência, cancelamento e consultas não consomem números.
O ano novo começa em 1; continuam as regras A2/A3 de data local e confirmação no
mesmo dia, sem eliminar operações antigas. Tentativas repetidas não confirmam
nem alteram stock duas vezes.

`ReportNumber` conserva o nome técnico e os IDs existentes, mas representa a
**identidade anual do movimento**. A ligação OneToOne ao movimento mantém-se
obrigatória; a ligação ao PDF passa a aceitar NULL numa entrada sem relatório.
`ReportSequence` continua a ser o único contador, bloqueado por ano em PostgreSQL.
Unicidade por ano/número e por movimento, imutabilidade e proibição de reutilização
continuam protegidas no ORM, triggers e conta restrita. Novas confirmações do
workflow operacional exigem a identidade também na base, com verificação diferida
no commit, inclusive perante inserção/atualização SQL direta.

Uma entrada sem PDF recebe número, mas **não cria um documento fictício**. A opção
de relatório continua a ser Sim/Não. Saídas e inventários mantêm PDF obrigatório.
Quando há PDF, o gerador recebe o número já reservado para a confirmação; não
volta a chamar o contador. Mensagem, detalhe, histórico, lista de relatórios e PDF
apresentam a identidade efetivamente atribuída. Antes: Em preparação e ID técnico.

A lista Relatórios pode apresentar lacunas na sequência: corresponde apenas aos
ficheiros existentes, enquanto o Histórico inclui movimentos sem PDF. Eliminar
bytes não liberta o número; regenerar mantém os bytes, hash, data e número originais.
O renderizador `pdf_v3.py`, fontes/logótipo e auxiliares de apresentação ficam
inalterados para conservar as receitas A2/A3.

**Compatibilidade histórica:** a migração não preenche números retroativamente.
Movimentos A2/A3 sem PDF continuam com identificação técnica; PDFs anteriores
`MOV-id` mantêm a sua identificação e conteúdo. Os números anuais já emitidos,
associações, contador, metadados, assinaturas e provas de reprodução não são
reescritos. Só confirmações executadas com A4 seguem a nova regra.

Não se implementa emissão tardia de PDF para entradas confirmadas sem relatório.
Uma eventual funcionalidade futura terá de reutilizar a identidade existente,
sem reservar outro número, e introduzir um serviço auditado para associar a nova
evidência, preservando as proteções de imutabilidade. A A4 não abre uma exceção
genérica para reescrever identidades ou anexar documentos a movimentos confirmados.

## Alteração 27 — inventário como lista de trabalho

Escolher uma localização mostra todas as referências ativas abrangidas, por setor
numérico e designação, com paginação. Nomes como Setor 9/Setor 10 e números simples
mantêm a ordenação A3. Setores não numéricos seguem os numéricos; sem setor aparece
no fim da respetiva localização, com **Sem setor definido**. Todos os nomes e
associações vêm da base, sem listas fixas ou atribuições automáticas.

Cada resultado mostra designação e setor. Na pesquisa por nome sem localização,
mostra também a localização. O mesmo se aplica à linha de contagem minimizada;
quando uma única localização é suficiente para identificar a linha, não a repete.
Se o inventário parcial já inclui referências de outros locais, essas contagens
continuam visíveis com a sua localização: pesquisar não muda o âmbito selecionado.

**Parcial:** clicar num resultado novo adiciona a referência e abre diretamente
a sua contagem. A pesquisa/localização/página da lista conservam-se. Resultados já
selecionados continuam na lista com a contagem guardada ou Ainda não contado;
clicar abre a linha existente, sem criar outra ou alterar auditoria/stock. Na mesma
página, a abertura é local no navegador e conserva campos ainda em edição.
Entre páginas, usa o URL de contagem correspondente; guardar antes de navegar.

**Completo:** todas as referências do âmbito fixado continuam presentes, com
linhas inicialmente minimizadas. Clicar no resumo abre a referência. Os filtros
ajudam a navegar as contagens; não retiram referências do âmbito nem apagam valores.
Limpar contagem repõe **Ainda não contado**, conservando a referência obrigatória.

Confirmar quantidade guarda e minimiza a linha. O resumo conserva **nome, setor e
quantidade física**, mesmo fechado. Uma contagem ainda não conferida individualmente
é identificada como Por conferir. Zero é explícito e distingue-se de vazio.
Expandir/editar/remover no parcial e limpar no completo não alteram stock.
Caixas/garrafas começam vazias, sem copiar stock nem inventar capacidades.

Mantêm-se conferência final, motivos, transferências de localização/setor, seleção
de setores dependente da localização, validação simples/assinatura PNG e PDF
obrigatório. Alterações de stock/configuração desde a contagem exigem nova
conferência explícita. Só a confirmação final altera stock/localização, numa
transação única, com bloqueios, auditoria e reversão completa em caso de erro.
Abrir/minimizar e pesquisar são leituras; não confirmam movimentos ou contagens.

## Migração e recuperação A3 → A4

Única migração nova: `inventory.0014_movement_number_without_pdf`.

- Torna facultativa apenas a FK de `ReportNumber` para o documento.
- Adapta a guarda de inserção à identidade do movimento e à evidência PDF opcional.
- Acrescenta verificações de confirmação operacional no commit PostgreSQL.
- Não renomeia tabelas, registos, contas, perfis, referências ou documentos.
- Não muda passwords ou a alteração obrigatória da A3.
- Não reinicia nem corrige o contador anual.
- Não exige novos privilégios de UPDATE/DELETE para identidades: continuam proibidos.

A reversão da migração é recusada se houver identidades de movimentos sem PDF,
pois o esquema A3 não as consegue representar. Não eliminar números para forçar
reversão nem usar código A3 sobre uma base A4. Uma futura recuperação deve usar
backup integral e código compatível; o dump inclui identidades sem documento,
contadores, contas/perfis, flags de password, auditoria e receitas de reprodução.

A validação automática recupera uma base A3 sintética para um projeto novo e
verifica arquivo, migrações, contas, saldos, históricos, contadores e PDFs assinados.
A origem é preservada; uma tentativa de migração direta e um destino já ocupado
são recusados. O manifesto A3 também é recusado pelo instalador A4 antes de build
ou migrações. O arranque diário nunca migra. Estes controlos não são uma instrução
para atualizar o piloto pessoal: **nenhuma atualização deve ser executada aí**.

Para a futura preparação na empresa, a informática deverá rever a versão e o
backup, usar uma cópia independente/vazia, aplicar migrações só à cópia, comparar
dados e evidências e testar recuperação antes de decidir qualquer integração.
Não há instruções nesta entrega para substituir volumes, apagar backups, migrar
a base reservada ao Excel ou publicar os dados reais.

## Validação automática e limites

Testes Django/PostgreSQL abrangem sequência comum com/sem PDF, preparação,
duplicação, ano novo e meia-noite, concorrência real, falhas após atribuição,
imutabilidade SQL, dados A3 sem numeração, migração e regeneração byte a byte.
Incluem também permissões/passwords A3, entradas/saídas, inventários, importação
sintética, auditoria, assinatura e backup/restauro, para detetar regressões.

Chromium verifica computador e telemóvel: pesquisa por nome/localização, setor
visível, seleção direta, reabertura sem escritas, minimização/edição/remoção,
inventário completo e limpeza, zero/vazio, conservação de contagens, assinatura
e entrada sem PDF com número visível. A CI executa build limpo, payload Docker com
conta PostgreSQL restrita e PowerShell 5.1/NTFS/atalhos num runner Windows descartável.

O ensaio adicional usa uma imagem A3 e preserva os volumes sintéticos novos:
`tests/windows/smoke_stack.py --image IMAGEM_A4 --previous-image IMAGEM_A3 --preserve-volumes`.
Nunca adota volumes existentes. O resultado é evidência automatizada, não validação
física da futura infraestrutura empresarial ou uma publicação operacional oficial.

Não se exige qualquer teste no computador pessoal. Permanecem para uma futura
aceitação técnica na empresa: Docker Desktop/WSL2 e políticas autorizadas, integração
com atalhos/PWA, impressora e dispositivos físicos. A CI não comprova esses fatores.
Não houve instalação em dispositivos reais, merge, custos de alojamento ou alteração
da aplicação Stock Vertente Aveludada.
