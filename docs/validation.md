# Validação das entregas

## Validação da primeira etapa

Executada na máquina de desenvolvimento com Python 3.12, as versões resolvidas
em `uv.lock`, PostgreSQL 17 via `compose.yaml` e Chromium local.

| Verificação | Resultado |
| --- | --- |
| `uv lock --check` e instalação congelada | Aprovados. |
| `ruff check .` | Aprovado. |
| `manage.py check` | Sem problemas. |
| `makemigrations --check --dry-run` | Nenhuma alteração de modelo sem migração. |
| `migrate --noinput` em PostgreSQL | Migrações aplicadas, incluindo configuração de localizações e triggers. |
| `manage.py test accounts inventory imports web tests.browser --noinput` | **57 testes executados e aprovados; nenhum ignorado.** |
| Recursos estáticos e `check --deploy --fail-level WARNING` no perfil de produção | Aprovados; não constituem um deploy. |
| Arranque real da aplicação | Login e CSS com HTTP 200; configuração privada inacessível por HTTP. |
| Preparação real do anexo, repetida | Lote único e proveniência preservados; nenhum catálogo, saldo ou movimento operacional publicado. |
| Reinício do PostgreSQL | Lote privado de preparação conservado no volume. |
| `git diff --check` | Aprovado. |

Os testes exercitam autenticação/CSRF, ambos os perfis, pesquisa e paginação,
validações de localização e setor, snapshots de quantidades/capacidade/nome,
rollback integral, duas saídas simultâneas sem exceder stock e proteção de
movimentos confirmados também por SQL direto. Os casos de importação usam Excel
sintético, incluindo sinais invertidos, vazios, duplicados, cache ausente,
divergências, dados órfãos e cabeçalhos inválidos. O navegador executa o fluxo de
login/consulta em dimensões de computador e telemóvel.

A inspeção do anexo real produziu exceções que exigem reconciliação. O comando
termina deliberadamente com estado 1 após guardar o relatório e o lote em
análise. Esse resultado não é uma importação aprovada. O relatório e os dados
individuais ficam fora do Git; não são fixtures nem documentação versionada.

A configuração de CI foi criada, mas não foi executada no GitHub nesta tarefa.
Não foram feitos deploy, restauro numa máquina cloud nova, importação definitiva,
teste de backups de produção ou testes das interfaces operacionais ainda por
implementar. As próximas entregas devem manter estes casos e acrescentar testes
aos fluxos definidos no [roadmap](roadmap.md).

## Validação da segunda etapa

O conjunto completo `manage.py test accounts inventory imports web tests.browser
--noinput` executou **131 testes, todos aprovados e sem casos ignorados**, em
PostgreSQL. Inclui os testes anteriores, publicação sintética reconciliada,
fusão de duplicados com proveniência, preservação de sinais, documentos e
observações, saldos iniciais desconhecidos, idempotência, rollback e rejeição de
prévias alteradas ou desatualizadas. Inclui ainda os formulários de catálogo,
as permissões de ambos os perfis, proteção de stock contra campos forjados,
relações protegidas e confirmação explícita/CSRF na publicação.

O reforço inclui confirmações simultâneas de uma ou duas prévias do mesmo lote,
publicação concorrente com criação de catálogo e desativação apenas com stock
exatamente zero. A desativação é recusada também por chamada direta ao serviço
e por pedido HTTP forjado; o stock é novamente verificado depois de abrir a
página de confirmação. Os testes confirmam a reativação, a preservação do
histórico e a exclusão de referências inativas do stock normal e do painel.

A criação manual também é testada contra designações equivalentes por espaços
e maiúsculas/minúsculas, incluindo referências inativas e outras localizações.
Os casos verificam a apresentação de todas as correspondências, a preservação
dos registos históricos, a confirmação de reativação e a serialização de duas
criações simultâneas. Um teste de importação sintética confirma que referências
históricas com o mesmo nome em localizações diferentes continuam separadas.

Os dois testes de navegador usam Chromium: consulta em dimensões de computador
e telemóvel e criação/edição de referência por administrador em telemóvel.
Ruff, verificação Django, ausência de migrações pendentes, recolha de recursos
estáticos no perfil de produção e `check --deploy --fail-level WARNING` passaram.

A pré-visualização real foi preparada e verificada individualmente contra a
fonte oficial, mantendo contagens iniciais ausentes como desconhecidas. As
decisões, valores individuais e os relatórios reais permanecem privados, fora
do Git. A fonte e o destino continuam ligados à impressão digital revista.
Até à confirmação explícita dessa prévia, o catálogo e o histórico operacionais
permanecem sem dados reais. Este estado não deve ser descrito como importação
real concluída; a publicação produz o seu próprio relatório de validação.

Na segunda etapa os movimentos operacionais ainda não estavam implementados. Os
resultados de CI no GitHub devem ser consultados separadamente dos resultados
locais acima.

## Validação da terceira etapa

Executada em 2026-10-23, com Python 3.12, Django 5.2 LTS, PostgreSQL 17 e
Chromium. A suíte completa `manage.py test accounts inventory imports web
tests.browser --noinput` executou **201 testes, todos aprovados e sem casos
ignorados**, numa base de testes descartável e sintética. Inclui os 131 casos
anteriores e 70 novos casos.

- Entradas/saídas simples e com várias referências, quantidades introduzidas
  separadamente, capacidades desconhecidas, vazios e zeros explícitos.
- Guardar, editar, reabrir e cancelar rascunhos sem alterar stock; controlo de
  proprietário e revisão, conferência obrigatória e confirmação única.
- Stock insuficiente, referências inativas, reativação explícita, duplicados
  globais, permissões, CSRF e campos/identificadores/tokens/formsets forjados.
- Inventários parciais/completos, contagens positivas/negativas/nulas em relação
  ao saldo, zero físico, referências por contar, pesquisa e paginação de âmbito.
- Mudanças de stock durante a contagem e após conferência, inclusive stock
  alterado e reposto no mesmo valor; nova conferência explícita.
- Transferências sem diferença quantitativa, validação de setor, rollback de
  stock/localização/snapshots/auditoria após falha de escrita intermédia.
- Correções com motivo e relação, sem reescrever o original; imutabilidade ORM e
  SQL de movimentos, linhas, fontes, transferências e eventos de auditoria.

Os **10 novos testes transacionais PostgreSQL** usam conexões separadas para
saídas concorrentes com várias referências, dupla confirmação, inventários em
conflito, inventário versus entrada, edição/cancelamento versus confirmação e
observação real da espera por bloqueio de linha. Também verificam falha tardia,
validações e proteções SQL. Continuam os casos anteriores de concorrência de
saídas, catálogo e importação/publicação sintética.

Os **8 testes Chromium** incluem os dois casos anteriores e seis fluxos novos:
entrada, saída e inventário, cada um em computador (1366×900) e telemóvel
(390×844). Verificam campos inicialmente vazios, totais calculados no navegador,
persistência de rascunho, conferência, confirmação, saldos, transferências,
ausência de erros JavaScript e ausência de transbordo horizontal. Screenshots
sintéticos foram revistos localmente, fora do Git. Estes testes não substituem
os testes da assinatura/PWA e de dispositivos previstos para a Etapa 4.

Ruff, `manage.py check`, ausência de alterações de modelo sem migração,
`git diff --check`, recursos estáticos e `check --deploy --fail-level WARNING`
passaram. As migrações novas foram aplicadas exclusivamente na base sintética e
nas bases de testes. A CI executa estas verificações; o resultado remoto deve
ser consultado no PR da Etapa 3, separadamente desta execução local.

A impressão digital integral das tabelas protegidas foi comparada antes/depois:
pré-visualização privada, lote, proveniência, catálogo, livro, localizações,
setores e registo de migrações mantiveram-se idênticos. A base reservada continua
com uma pré-visualização não publicada, sem referências ou movimentos
operacionais. O Excel não foi reimportado, os ficheiros privados não foram
alterados e não houve publicação, operações reais, deploy ou merge.

## Validação da quarta etapa

Execução local em 2026-10-23, Python 3.12, Django 5.2 LTS, PostgreSQL 17:
**267 testes aprovados, nenhum ignorado**. Inclui os 201 anteriores e 66 novos.
A alteração dos testes antigos limita-se às funcionalidades agora entregues:
documentos passam a existir e a assinatura passa a ser selecionável, mas continua
a exigir bytes válidos; mantêm-se invariantes de stock, permissões e histórico.

- 15 casos de documentos: entrada opcional, saída obrigatória, inventário,
  assinatura, PNG inválido/vazio/dimensões/tamanho, snapshots, correções,
  imutabilidade ORM/SQL, PDF multipágina e rollback quando a geração falha.
- 16 casos novos de contas/login: criação e edição com reautenticação, perfis,
  desativação sem perda de identidade, auto-desativação/despromoção recusadas,
  CSRF/campos forjados, passwords fracas, limites/expiração de login, cabeçalhos
  de proxy e rejeição de corpos acima do limite.
- 21 casos novos de relatórios, exportação e PWA: autenticação, inexistência real
  de documentos, integridade, downloads, filtros, valores desconhecidos, prevenção
  de fórmulas, dados históricos, cache privada proibida e assets com hash de produção.
- 8 casos de backup, incluindo pg_dump/pg_restore reais numa base nova, validação
  dos documentos restaurados e triggers, retenção, falha sem destruir backups,
  rejeição de destino existente/arquivo corrompido e cifragem/decifragem GPG com
  chave temporária sintética. O arquivo e a chave não foram incluídos no Git.
- 1 teste usa efetivamente uma conta PostgreSQL restrita: confirma uma saída com
  PDF/assinatura, mas não cria tabelas, altera migrações ou elimina o livro/documentos.
- 1 teste de reservas de login concorrentes usa seis conexões PostgreSQL reais
  e comprova que o limite não é excedido.
- **12 testes Chromium** no total, quatro novos: assinatura com rato em computador,
  assinatura com toque em telemóvel e limpeza/repetição, criação de utilizador e
  download XLSX em móvel, e PWA em perfil persistente com elegibilidade de instalação,
  cache apenas pública, fallback offline e impossibilidade de confirmar sem rede.

Ruff, `check`, migrações coerentes, recursos estáticos e `check --deploy` passaram.
O PDF A4 foi ainda renderizado e inspecionado visualmente com dados sintéticos.
A CI executa a suíte e valida a imagem preparada, sem arranque de servidor público
nem deployment. O resultado remoto está ligado ao PR, distinto da execução local.
A construção local da imagem encontrou restrições TLS da rede do executor; não
se desativou validação TLS. A validação da imagem em CI é registada separadamente.

As únicas migrações/escritas foram para bases sintéticas/de testes. A base reservada,
a pré-visualização e os ficheiros privados são comparados por fingerprints antes
e depois. Não foi reimportado o Excel, publicado stock real, contratado serviço,
ativado agendamento de produção, comprado domínio ou feito deploy/merge.

Não foram testados Android/iOS físicos, impressoras do armazém, domínio/TLS real,
backup remoto de produção, recuperação num segundo servidor real ou capacidade
sob carga de produção. Estes pontos exigem infraestrutura e validação operacional,
não podem ser declarados concluídos a partir dos testes sintéticos.

## Validação da quinta etapa

Execução em 2026-10-24 (Europe/Lisbon), com a aplicação das etapas anteriores
mantida. **275 testes Django aprovados, nenhum ignorado**: os 267 anteriores,
incluindo 12 casos Chromium, e 8 casos novos do perfil Windows. A instância
PostgreSQL 17 de regressão foi criada num projeto/volume novos, com credenciais
aleatórias e porta exclusiva em loopback. Nem sequer foi usada a ligação da base
reservada. Não foram aplicadas migrações nessa base nem lido/importado o Excel.

Os casos novos verificam o modo sintético explícito, recusa de servidores/bases
externos ou reservados/SQLite, hosts apenas locais, ausência de proxies/CSRF Wi-Fi,
segredos de ficheiro, seleção de owner apenas na preparação, cookies HTTP limitados
a este perfil e ausência de comandos destrutivos/de bypass nos assistentes.

**24 testes PowerShell 5.1** exercitam parsing, diagnóstico com Docker simulado,
recusa de contexto remoto, requisitos, segredos distintos, ACL NTFS, caminhos com
espaços/acentos/apóstrofo/dólar, repetição sem regenerar segredos, pasta desconhecida,
instalação incompleta, separação entre código/segredos/backups, arranque sem migrações/build, paragem que conserva volumes,
configuração alterada, segredo em falta, criação interativa sem credenciais
predefinidas, recusa de restauro sobre origem e atalhos por utilizador. Executam-se
num runner Windows descartável; não se instala Docker/WSL nem se testa um PC real.

O **ensaio real do payload Compose** usa duas stacks sintéticas novas. Verifica:

- PostgreSQL sem portas publicadas e apenas HTTP 127.0.0.1, volumes/projetos próprios.
- Migrações, grants, 4 localizações/27 setores e três referências fictícias; nenhuma
  conta/password predefinida ou lote de importação.
- Confirmação com conta PostgreSQL restrita, PDF e assinatura pelos serviços atuais.
- Repetição da instalação sem duplicar saldos ou apagar a operação sintética.
- Paragem/rearranque com os mesmos volumes, saldos e documentos.
- Backup, restauro numa segunda stack vazia e checksums dos documentos restaurados.
- Recusa de segundo restauro no destino não vazio e preservação do stock/instância
  da origem. A limpeza automática existe só neste teste, para namespaces aleatórios
  que o próprio processo criou, nunca nos scripts do utilizador.

A imagem foi construída e o ensaio passou também no ambiente de desenvolvimento.
A CA confiada pelo executor foi montada temporariamente no build local; a verificação
TLS não foi desativada nem a CA incorporada na imagem. A CI constrói o Dockerfile
normal e repete os testes de aplicação, Windows e contentores. Resultado remoto
no PR da Etapa 5. Ruff e coerência do esquema continuam verificados.

Os IDs/montagens dos contentores preexistentes são comparados antes/depois, sem
consultar ou modificar o conteúdo de bases privadas. O piloto não monta o volume
reservado. Não houve instalação no PC do utilizador, elevação, alteração de política,
ativação de WSL, firewall, alojamento externo, publicação real ou merge.

Pendente: aceitação física Windows 11/Docker Desktop/WSL2 por informática, políticas
corporativas, consola interativa/partilha de ficheiros, proxy/CA, arranque após
suspensão/reinício, suporte externo de backup, impressoras e eventual Wi-Fi Android
com HTTPS autorizado. Não se afirma que o runner Windows CI prove esses pontos.

## Etapa A — formulários diretos e Gestão Vertente Aveludada

Validação em 2026-10-25, branch `fix/entradas-saidas-diretas`, baseada na Etapa 5
(`16ac7c4`). Nenhuma operação foi executada no PC Windows instalado ou na base
reservada à pré-visualização. Foi criado outro PostgreSQL 17 com credenciais
aleatórias e dados exclusivamente fictícios.

- `ruff check .`: passou.
- `manage.py check`: passou; `makemigrations --check --dry-run`: sem alterações.
- `manage.py test accounts inventory imports web tests.browser tests.windows.test_profile --noinput`:
  **291 testes passaram**, incluindo 14 Chromium em computador/viewport móvel e
  8 verificações do perfil Windows. Inclui concorrência real PostgreSQL,
  importação sintética, PDFs, assinatura com rato/toque e backup/restauro.
- O teste de rollback do primeiro POST foi reforçado para provocar falha dentro
  de `save_draft`, depois da criação interna; repetição individual: passou,
  sem movimento, pessoa ou auditoria órfãos.
- `collectstatic --noinput` e `check --deploy --fail-level WARNING` com configuração
  de produção: passaram. A verificação não efetuou deploy.
- Payload Docker da Etapa 5 num projeto novo: passou. Inclui arranque local,
  PostgreSQL sem portas, conta restrita, PDFs/assinatura, persistência após paragem,
  backup, restauro noutro projeto vazio e recusa de sobrescrever um destino usado.
  A imagem local reutilizou a base de dependências da Etapa 5 com o código novo;
  a CI reconstrói a imagem normal a partir do Dockerfile do repositório.
- PowerShell 5.1/NTFS/atalhos: execução no job Windows da CI, não neste ambiente
  Linux. O resultado final deve ser consultado nos checks do PR.

Na primeira execução completa foram identificadas duas incompatibilidades dos
seletores dos novos testes de criação de referência e um gesto tátil iniciado sob
navegação fixa. Os rótulos foram uniformizados e o teste verifica agora que o alvo
tátil é o canvas visível. Os quatro cenários afetados passaram isoladamente e a
suíte completa seguinte passou. Capturas sintéticas foram inspecionadas localmente;
não se publicam relatórios/capturas privados.

Pendente de aceitação: atualização física Windows 11/WSL2, políticas/permissões do
utilizador e incorporação/contraste dos originais Copo com Vida ainda não fornecidos.
Não há merge, publicação de dados reais ou alterações à aplicação Android separada.

## Identidade Copo com Vida — originais recebidos no ZIP

Foram recebidos apenas dois PNG públicos da marca: logótipo completo 1273×827 e
recorte original do copo 143×246, sem metadados ou outros dados da fatura. Foram
copiados byte a byte e os SHA-256 estão documentados. Os ícones PNG/ICO usam
exclusivamente a máscara dos píxeis originais, escala proporcional e as cores
aprovadas; não há reconstrução, vetorização ou geração do símbolo.

Validação local desta continuação, sem ligar a qualquer base existente:

- **17 testes passaram**, incluindo sete testes de marca, oito do perfil Windows
  e dois Chromium públicos (computador e telemóvel). As classes são SimpleTestCase,
  não preparam bases e foram executadas com a porta de base deliberadamente
  indisponível. Verificam originais, máscara, cores, margem maskable, ICO,
  manifesto/cache e o logótipo embebido sem alteração ao lado de uma assinatura
  sintética, além da entrega HTTP dos ficheiros e proporções do login real.
- Ruff e verificação de whitespace: passaram.
- `collectstatic` e verificações de produção sem warnings: passaram. Os URLs com
  hash dos três PNG da marca constam da cache pública; nenhum acesso à base.
- Login móvel/computador, ícone de 512 px e PDF sintético com assinatura foram
  inspecionados visualmente. As capturas e o PDF são apenas locais; não se incluem
  documentos privados ou a fatura no Git.

A regressão completa Django/PostgreSQL/Chromium, PowerShell e payload Docker é
executada pela CI deste commit em ambientes sintéticos novos. Os resultados
finais estão nos checks do PR. O código não contém migrações ou alterações a
regras de stock. PDFs históricos não são reescritos. A aceitação física dos
ícones instalados no Windows/PWA depende de atualização manual posterior; não
foi instalado ou atualizado nada no computador do utilizador.

## Etapa B — Stock Vertente Aveludada sobre main A4

Branch `stageb/stock-vertente-aveludada`, PR em rascunho para `main`; as branches
#6/#7 não foram alteradas. Recuperação seletiva dos componentes documentada em
[etapa-b.md](etapa-b.md). Nenhum serviço, stock ou base existente foi adotado.

A suite local final passou **458 testes**, incluindo **51 Chromium** (27 Gestão,
24 Stock). Inclui autorização assinada de dispositivos/perfis, cofre cifrado,
importação atómica, falhas IndexedDB, FIFO/receções parciais/sem quantidade,
capacidades históricas, datas válidas, duplicações/recuos/origem/assinatura,
lacunas e recuperação por janelas, backup em aparelho novo, offline, CSP e
regressões A4. Node verifica sintaxe dos módulos; Ruff, Django, migrações e
`check --deploy` em configuração de produção também passaram.

O publicador foi ensaiado separadamente com TLS/mTLS real confiável, certificados
revogados recusados, ausência de API/ficheiros privados, elegibilidade PWA e
consulta/encomendas offline. As esperas de ativação usam eventos de service worker,
sem polling `eval` incompatível com a CSP. Avisos de sucesso só aparecem depois
da atualização da interface; navegação aguarda estado e ignora leituras ultrapassadas.

Exportação usando a conta PostgreSQL restrita passou, com stock inalterado, zero,
capacidade desconhecida, identidade/contador estáveis e nenhuma importação Excel.
Recuperação **imagem A4 anterior → imagem B** passou em projetos sintéticos novos,
com origem preservada, recusa de destino ocupado/migração no local, passwords,
numeração independente do PDF e reprodução fiel de evidências assinadas. Os volumes
sintéticos novos foram preservados nos ensaios locais.

O build local limpo encontrou DNS indisponível no download Debian do Docker. Para
os ensaios locais, usou-se a imagem A4 de validação em cache mais o código B e wheels
das dependências novas, verificadas contra os hashes de `uv.lock`, sem rede no build.
A CI mantém o build **limpo original**, sem esse atalho. Na primeira revisão publicada,
a CI passou a suite/build/recuperação/exportação restrita e **37 verificações PowerShell**
(29 piloto, 8 publicador), mas o ensaio HTTPS final falhou. As correções e esperas CSP
foram acrescentadas; o estado da revisão final será registado no PR, sem assumir que
resultados de outra revisão bastam. Não se considera o PR validado enquanto a CI final
não estiver verde.

Ficam por validar fisicamente Android/Chrome, certificados/MDM, Wi-Fi/DNS/firewall/NAT,
seletor/transferência de ficheiros e políticas de armazenamento. Sem testes no PC pessoal,
sem publicação de dados reais, sem acesso à base reservada e sem merge automático.

O Chrome do runner pode anunciar `ERR_NETWORK_CHANGED` ao descobrir a rede Docker
no primeiro acesso. Só o GET inicial do shell do ensaio pode repetir esse erro
específico, no máximo três tentativas curtas. Erros TLS/autenticação continuam a
falhar; não há repetição de POST nem alteração de segurança na aplicação.
