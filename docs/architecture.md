# Arquitetura

Estado: base técnica, catálogo/importação reconciliada e operações da Etapa 3. A
publicação dos dados reais exige revisão da pré-visualização e confirmação
explícita; a existência do importador não prova que essa publicação ocorreu.
Esta aplicação ainda não substitui todos os fluxos do registo operacional
existente. O [plano V3](../plano_gestao_garrafas_v3.md) continua
a definir as funcionalidades aprovadas; a [sequência de entrega](roadmap.md)
identifica o que já existe e o que falta implementar.

## Aplicação e interface

Adota-se um monólito modular com **Django 5.2 LTS, Python 3.12 e PostgreSQL 17**.
Uma aplicação serve HTML responsivo para computador e telemóvel. Os templates
reutilizam a linguagem visual do V3: cores, cartões, navegação lateral, tabelas e
adaptação móvel. Não há duas aplicações nem duas regras de stock para manter.

O servidor concentra autenticação, permissões, validação e transações. A primeira
etapa não necessita de uma SPA, framework JavaScript, API pública ou processo de
compilação frontend. As consultas funcionam com formulários GET e paginação. Pode
adicionar-se interação progressiva quando os formulários operacionais o exigirem,
mantendo as mesmas regras no servidor.

Entradas, saídas, rascunhos, contagens e correções relacionadas têm formulários
operacionais. A interface identifica os PDFs como futuros e não oferece assinatura.
A entrega não autoriza publicação inicial de dados nem uso operacional oficial.

| Módulo | Responsabilidade |
| --- | --- |
| `config` | Configuração por ambiente, URLs e pontos de entrada WSGI/ASGI. |
| `accounts` | Utilizador próprio, dois perfis e criação explícita de contas. |
| `inventory` | Referências, localizações, saldos, movimentos e auditoria. |
| `imports` | Leitura do Excel, preparação, reconciliação, pré-visualização e publicação confirmada de lotes. |
| `web` | Consultas e páginas autenticadas; não contém regras de stock. |
| `templates` / `static` | Apresentação responsiva, sem dados reais embutidos. |

## Persistência e invariantes

PostgreSQL é a base permanente. O serviço local Docker usa um volume nomeado;
reiniciar a aplicação ou o contentor não deve apagar a base. Remover o volume
explicitamente elimina dados. Um volume persistente não é uma cópia de segurança.
O modo SQLite é apenas uma alternativa local explícita: não valida bloqueios por
linha nem concorrência de produção.

O modelo distingue os seguintes elementos:

- **Catálogo:** `Location`, `Sector`, `Person` e `Reference`. Uma referência tem
  uma localização e um setor opcional dessa localização. A capacidade da caixa
  pode continuar desconhecida. O mínimo nulo significa alerta desligado.
- **Livro de movimentos:** `OpeningBalance`, `Movement` e `MovementLine`. As
  quantidades são inteiras e assinadas em garrafas. O stock atual é um saldo de
  consulta que deverá reconciliar com o saldo inicial e os movimentos confirmados.
- **Proveniência:** `ImportBatch` e `LegacyRow` identificam ficheiro, folha, linha
  e valores originais, para que a migração não destrua informação.
- **Evidência:** `LocationChange`, `AuditEvent` e `Document` preparam o histórico de
  transferências, operações e metadados de documentos privados. A geração e
  disponibilização de ficheiros são etapas posteriores.

As relações históricas usam proteção contra eliminação. A desativação preserva
referências e pessoas; não se apagam registos usados pelo histórico. Validações de
modelo e restrições de base cobrem identidades únicas e valores admissíveis. As
regras entre várias linhas ou tabelas pertencem aos serviços transacionais.

A gestão de catálogo não aceita alterações de stock pelos formulários. A criação
de uma referência começa com saldo zero; editar a designação, capacidade, alerta,
localização ou setor não recalcula nem altera o saldo. As alterações de
localização e setor ficam registadas com o operador, incluindo transferências
sem diferença quantitativa. Uma referência desativada continua a proteger as
suas relações e o histórico.

`confirm_movement` é o ponto de entrada para confirmar operações:
verifica o perfil, bloqueia movimento, linhas e referências, valida sinais e
quantidades e atualiza todos os saldos numa única transação. As referências são
bloqueadas por ordem estável para reduzir conflitos entre operações concorrentes.
Uma saída sem stock ou uma linha inválida reverte a operação completa. Rascunhos
não alteram saldos. Os formulários delegam o ciclo de rascunho/conferência em
`inventory.operations`, sem aceitar stock ou impacto assinado do navegador.

Na confirmação conservam-se designação, capacidade, quantidades introduzidas e
saldos antes/depois. Alterar a capacidade futura de uma referência não pode
reescrever um relatório histórico. Movimentos confirmados são imutáveis através
dos caminhos ORM suportados; correções devem criar um novo movimento relacionado.
Em PostgreSQL, a migração `inventory/0003` acrescenta triggers que também recusam
alterações e eliminações de movimentos confirmados e inserções, alterações ou
eliminações das suas linhas, mesmo por SQL direto. O bloqueio do movimento pai
serializa essas alterações com a confirmação. Estes triggers não existem no modo
SQLite.

O dono da base ou uma conta com privilégios administrativos pode remover ou
desativar as proteções. Os triggers também não substituem o serviço que valida a
operação e concilia os saldos. Produção exigirá uma conta de aplicação com
privilégios restritos, uma conta separada para migrações e controlo de operação e
auditoria.

As decisões de revisão otimista, tokens de conferência, contagem física separada
porque o ajuste pode ter outro sinal, âmbito dos inventários e bloqueios estão em
[decisão 3](decisions/0003-operational-transactions.md). Os procedimentos e limites
estão em [stage3.md](stage3.md). A confirmação guarda o utilizador responsável e
snapshots dos nomes de pessoas; transferências conservam rótulos de localização e
setor. O histórico apresenta estes dados e permite criar um novo ajuste relacionado.
Triggers adicionais protegem transferências confirmadas e a auditoria de acréscimo.

## Datas, pessoas e histórico legado

A aplicação usa `Europe/Lisbon`, com instantes novos armazenados com fuso horário.
`Movement.date` conserva a data de negócio. `occurred_at` é um instante opcional;
fica vazio para movimentos legados que apenas têm uma data. Não se fabrica uma
hora à meia-noite para aparentar precisão inexistente.

Uma coluna histórica conserva a sua posição de origem. Datas repetidas ou fora da
ordem cronológica não autorizam a fundir movimentos. As etiquetas antigas ficam
preservadas em `original_label`; não passam a novos tipos operacionais. Entradas
negativas e saídas positivas conservam os sinais do Excel.

Os nomes de pessoas novos têm espaços normalizados e uma chave de comparação
sem diferenças de maiúsculas/minúsculas. Os valores brutos da importação mantêm-se
separados dessa normalização, inclusive quando um cabeçalho está mal tipado.

## Importação reconciliada e confirmação

O anexo é uma fonte de dados, não uma fonte de instruções executáveis. Não se
executam macros nem se altera o livro original. O leitor considera apenas a
folha `Stock`, usando as fórmulas e os valores em cache existentes; `openpyxl` não
recalcula fórmulas.

1. **Inspeção e preparação:** calcular SHA-256, guardar coordenadas e valores
   brutos, identificar cabeçalhos, capacidades desconhecidas e exceções, e produzir
   reconciliação por linha. O lote identifica o mesmo ficheiro sem duplicar a sua
   preparação. O modo de preparação não publica referências, saldos ou movimentos.
2. **Reconciliação e pré-visualização:** aplicar decisões explícitas de migração,
   comparar cada saldo calculado com o saldo oficial e apresentar os resultados.
   O objeto de pré-visualização conserva as decisões, os totais, as linhas e as
   impressões digitais da fonte e do estado de destino. Ainda não altera o
   catálogo, saldos ou histórico operacional.
3. **Publicação confirmada:** exigir confirmação da pré-visualização e revalidar
   fonte, decisões e destino antes de uma transação que cria catálogo, saldos e
   histórico. O lote é bloqueado durante a publicação. Uma repetição do mesmo
   lote não volta a somar stock nem duplica movimentos. Um ficheiro diferente
   não pode sobrescrever silenciosamente um catálogo que já tem dados.

Vazios e texto inesperado não são convertidos silenciosamente em zero. Uma soma
candidata que reproduza o comportamento `SUM` do Excel deve ficar identificada
como hipótese de reconciliação. Não basta coincidir com o total global: cada
referência deve reconciliar e cada exceção precisa de uma decisão registada.

Um saldo inicial explicitamente fornecido é distinto de um campo vazio.
`OpeningBalance.quantity` pode ficar nulo quando a contagem original é
desconhecida. Nessa situação guarda-se separadamente a quantidade inferida para
reconciliação, obtida a partir do saldo oficial e da soma dos movimentos
disponíveis. A base e a interface identificam essa inferência; um resultado
aritmético zero não transforma uma ausência de contagem numa contagem confirmada.

Ao unir referências duplicadas, cada linha original mantém a sua proveniência.
Uma linha de movimento agregada pode apontar para múltiplas linhas/células da
fonte. Conflitos que impeçam identificar uma referência ou a sua capacidade
bloqueiam a publicação em vez de escolher um valor arbitrário. As capacidades
desconhecidas e os setores ausentes permanecem vazios.

Cabeçalhos reconhecidos como documentos conservam o valor original e um campo
próprio de número de documento. Não são convertidos em pessoas; quando o nome
não existe, a relação de pessoa fica vazia. Uma célula autorizada como anotação
mantém o texto e a decisão de ausência de impacto, sem criar uma quantidade
inventada. Os movimentos legados conservam sinais, datas e etiquetas originais.

O saldo atual é atribuído uma única vez a partir do saldo oficial reconciliado.
Os movimentos históricos são importados para explicar esse saldo, não para serem
novamente adicionados a ele. As datas sem hora continuam sem hora; saldos
intermédios que não possam ser demonstrados a partir da fonte não são inventados.

Os contratos e procedimentos da segunda etapa estão em [stage2.md](stage2.md).

O plano e o protótipo contêm uma fotografia anterior; não substituem a validação
do Excel atualizado. Uma data de inventário inicial não prova a existência de
movimentos de todos os anos seguintes. A cobertura efetiva é determinada pelas
colunas encontradas no ficheiro, sem prometer histórico ausente da fonte.

## Identidade, segredos e ficheiros privados

Há dois perfis da aplicação: **Administrador** e **Consulta**. O segundo é o
perfil por defeito. A autenticação usa passwords com hash e sessões Django; a
autorização é verificada nas vistas e serviços, não num seletor de demonstração.
Não existe registo público nem conta com password predefinida. Logout usa POST e
as operações de formulário usam proteção CSRF.

O bootstrap cria segredos locais aleatórios em `.env`, ignorado pelo Git, sem
substituir um ficheiro existente. Produção deve injetar segredos próprios pelo
ambiente. Excel, bases locais, relatórios de importação, backups, PDFs e
assinaturas não pertencem ao repositório. Os testes usam exclusivamente dados
sintéticos. Não se devem registar valores de credenciais em logs.

Documentos ficam em armazenamento privado e não em `static`. O modelo guarda
chave e checksum; o acesso autenticado a documentos e a política de retenção serão
implementados com os relatórios. Não está configurada uma rota pública de media.

## Produção e evolução

Os pontos de entrada Django e a dependência Gunicorn preparam uma futura execução
atrás de proxy HTTPS. O perfil de produção exige PostgreSQL, desliga o modo debug
e ativa cookies seguros e redirecionamento HTTPS. Hosts e origens CSRF têm de ser
configurados para o domínio real; cabeçalhos de proxy só devem ser aceites de um
proxy que remova valores fornecidos pelo cliente.

Antes de uso oficial faltam, além das funcionalidades do roadmap: alojamento,
TLS e gestão de segredos, conta de base com privilégios mínimos, proteção contra
tentativas repetidas de login, observabilidade, políticas de retenção e backups
automáticos separados com um restauro comprovado. O serviço Docker é destinado a
desenvolvimento, não uma configuração de produção concluída.

A PWA instalável mantém-se no plano. A primeira versão operacional continuará a
exigir ligação para consultar e alterar stock. Um futuro service worker poderá
guardar recursos estáticos; escritas offline e saldos em cache exigem um desenho
específico para evitar conflitos, e não são assumidos nesta etapa.
