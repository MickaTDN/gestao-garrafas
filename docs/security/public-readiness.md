# Etapa C.1 — Preparação para acesso público

Data: 27 de outubro de 2026. Esta é uma preparação para revisão, não uma alteração
de visibilidade, aprovação de distribuição ou homologação Windows.

## Decisão atual e âmbito

**A publicação continua dependente de verificações pendentes.** O proprietário
aceitou expressamente a divulgação das referências de garrafas e quantidades de
stock históricas. Por isso, o catálogo original de 461 referências/8 522 garrafas
não é agora um bloqueio por ser stock. Não foi apagado, alterado ou reescrito.
Essa autorização não inclui automaticamente dados pessoais ou outros dados
confidenciais. O histórico foi preservado integralmente.

A base desta branch é `main` em `b31e6a3b60ef1dbb32fb9950a85336d39bed6a65`.
As mesmas correções são coordenadas com a linha do PR #13, sem integrar PR nem
reescrever commits existentes. O histórico e os cabeçalhos foram obtidos por Git;
a API GitHub está bloqueada neste ambiente com HTTP 403 no túnel de rede. Não se
confundem metadados da auditoria anterior com uma nova consulta administrativa.

Reavaliação: clone independente, todas as dez branches remotas anteriores à nova
branch de segurança, refs dos 13 PR e refs de merge anunciados, 112 commits,
834 conteúdos de ficheiros distintos e zero tags anunciadas. Gitleaks 8.30.1,
com binário de release oficial verificado por SHA-256, analisou os patches dos
99 commits sem merge; foi também aplicado aos 834 blobs, para incluir conteúdos
que não surgem como patches de commits sem merge. Os quatro alertas no modo Git
e oito ocorrências nas versões dos blobs correspondem aos mesmos falsos positivos
de código de leitura/verificação de chaves, não a chaves privadas literais.
O conteúdo novo é também revisto antes de publicação da branch.

## Dados, credenciais e privacidade

Não foi identificada uma credencial real válida nos objetos Git inspecionados.
Não se encontraram Excel, dumps de dados, bases SQLite, PDFs privados, ficheiros
PEM/PFX/P12 privados nem `.env` com valores reais no histórico alcançável. Os
SQL encontrados definem permissões; não são cópias de dados. Os exemplos de
configuração deixam segredos vazios. Existem textos e marcadores sintéticos em
testes, além de geração de chaves efémeras em execução; não são chaves empresariais.

Existem **dois endereços Gmail em identidades de autoria de commits** e um
primeiro nome de pessoa no protótipo histórico. Não são passwords. A publicação
de autoria Git é habitual, mas esses dados pessoais não passam a estar aprovados
pela autorização para publicar stocks. O proprietário deve confirmar a identidade
e a autorização dos titulares antes de tornar o histórico público. Os valores
ficam apenas no relatório privado; não são repetidos nesta documentação ou no PR.
Mudar o email de futuros commits não retira emails históricos. Não foi tentada
qualquer remoção ou reescrita. Os novos commits técnicos usam um endereço noreply.

A documentação e o protótipo identificam localizações internas e os processos da
empresa; o proprietário deve confirmar que esse contexto e a identidade visual
podem ser publicados. Não se identificou outro conjunto de clientes, assinaturas,
contactos ou documentação de compras real nos objetos inspecionados. Isto não
substitui a classificação de confidencialidade pelo titular dos dados.

A ausência de deteção de segredos não é uma garantia absoluta. Não se abriram
bases reais, ficheiros de configuração privados locais ou os anexos da conversa.
A base reservada ao Excel e os backups/instalações existentes não foram usados.

## Correções efetuadas

- Pillow atualizado de 12.3.0 para **13.0.0** e cryptography de 48.0.1 para
  **50.0.2**, com limites mínimos corrigidos e lockfiles atualizados.
- Descodificação de assinaturas explicitamente limitada ao plugin PNG, em vez de
  tentar parsers de outros formatos antes de verificar o tipo.
- Actions fixadas a SHAs completos de releases oficiais; checkout sem persistência
  de credenciais. Não se acrescentaram tokens, passwords ou certificados privados.
- Workflows com `contents: read`, runners hospedados standard, limites de duração,
  concorrência que cancela revisões ultrapassadas e nomes estáveis dos checks.
- Novo workflow `Security`: política local de privilégios/artefactos, testes com
  casos adversariais, Zizmor e consulta de vulnerabilidades do lockfile exportado
  com hashes. Ferramentas separadas no grupo `security`; não entram no instalador
  de execução. Dependabot propõe atualizações por PR, sem aprovação/merge automático.
- Proposta de ruleset e CODEOWNERS para encaminhar a revisão de ficheiros sensíveis.
- No PR #13: testes continuam a construir e exercitar os EXE sintéticos, mas PR e
  push deixam de carregar instaladores como artefactos. O upload sintético só é
  permitido numa execução manual em `refs/heads/main` do repositório original,
  depois de o workflow existir nessa branch. Retenção futura de três dias e nome
  `UNAPPROVED-SYNTHETIC-UNSIGNED-NOT-FOR-DISTRIBUTION-*`. Nada foi removido dos
  artefactos antigos.

Os 41 avisos anteriores são tratados individualmente em
[dependency-triage.md](dependency-triage.md), com função afetada, utilização pela
aplicação e versão corrigida. A nova consulta de execução não encontrou avisos
conhecidos na data da execução; não há uma lista de CVE ignorados na CI.
Branches históricas continuam a representar versões antigas: não são fontes
aprovadas para uma nova instalação ou distribuição.

A nova versão de Pillow alterou o resultado de reamostragem do ícone Stock de
192 px. Não se regeneraram imagens, ícones, shell offline nem identidade visual.
O teste passa a verificar o hash do raster original e de todos os píxeis RGB dos
dois ícones aprovados. Deteta qualquer alteração à arte aprovada e não obriga a
mudar o logótipo por uma atualização de segurança. Os PDFs sintéticos anteriores
foram também comparados byte a byte entre as duas versões de dependências.

## Fronteira de confiança dos workflows

Não se usam `pull_request_target`, `workflow_run`, runners da empresa, secrets de
produção, environments privilegiados ou permissões de escrita nos workflows de
teste. PR externos podem executar código arbitrário, mas apenas em runners
hospedados/efémeros com token de leitura e dados sintéticos. O proprietário deve
confirmar em **Settings → Actions → General** a aprovação de execuções de todos
os colaboradores externos e manter o token padrão em leitura. Não enviar secrets
ou tokens de escrita a forks nem ligar runners da empresa a esta CI.

O verificador local não é uma fronteira contra um autor malicioso que altere os
próprios testes. A confiança vem das permissões efetivas do GitHub, aprovação de
código, refs protegidos e ausência de segredos/distribuição oficial na CI.
Um hash, o sucesso dos testes ou um nome de artefacto não aprovam um instalador.
Um PR pode alterar o seu workflow: nenhum dos seus artefactos deve ser tratado
como uma versão oficial, mesmo que o nome tenha sido manipulado.

**Não existe workflow de publicação oficial.** Não se concedeu `contents: write`,
`packages: write` ou OIDC de publicação. A autorização de uma distribuição oficial
continua a ser uma decisão humana sobre uma revisão aprovada, seguida de assinatura
empresarial Authenticode válida e verificação da identidade do editor. A chave
empresarial permanece fora do repositório e da CI de PR. A chave ES256 efémera
sintética não substitui Authenticode empresarial nem constitui autorização de
publicação. O canal sintético não deve ser usado numa instalação operacional.

## Proteção proposta da main

Ficheiro: [main-ruleset.public.json](../../.github/security/main-ruleset.public.json).
É uma proposta **desativada** (`enforcement: disabled`); não foi enviada/ativada no
GitHub. O plano Free permite rulesets de **branch** em repositórios públicos.
Não se usa um push ruleset pago, Evaluate ou uma regra de workflow obrigatória
reservada a outros planos; usam-se checks normais de Actions.

Quando ativado após revisão, exige:

1. Pull Request para alterações normais; bloqueio de eliminação e force-push.
2. Branch atualizada com a base e checks de GitHub Actions aprovados:
   `django-postgresql`, `windows-powershell` e `workflow-and-dependency-security`.
3. Conversas de revisão resolvidas; sem bypass permanente de contribuidores.

Não se exige uma segunda aprovação humana nem CODEOWNER obrigatório: um único
mantenedor não pode aprovar o seu próprio PR. Isso não impede solicitar revisão
humana de contribuições externas. O proprietário mantém administração para
editar/desativar um ruleset mal configurado; não recebe um bypass geral de push
direto. Não se configura `Restrict updates`, que poderia bloquear também PR
legítimos. Em caso de check renomeado ou indisponível, corrigir apenas esse check
no ruleset e registar o motivo, sem forçar a main ou apagar histórico.

**Não exigir ainda `windows-native-synthetic` à main.** Acrescentar esse check
apenas depois de o workflow do PR #13 ser integrado por decisão do proprietário,
ter corrido num SHA aprovado e estar disponível nas futuras revisões de PR.
Adicionar agora um check inexistente bloquearia o desenvolvimento. Os nomes
propostos devem ser confirmados no GitHub antes de ativar a regra.

## Artefactos, logs e limitações de acesso

Na auditoria anterior do mesmo dia foram inventariados 32 artefactos, cerca de
11,14 GB, e 193 execuções. Os downloads de binários e logs foram bloqueados pela
rede do ambiente. Nesta etapa, a API GitHub está também bloqueada, embora Git por
HTTPS e PyPI estejam disponíveis. Não há uma nova certificação dos metadados nem
do conteúdo desses artefactos/logs. **Não foram inspecionados os 32 binários.**
A designação sintética e os filtros de empacotamento não provam o seu conteúdo.

Continuam por confirmar pelo proprietário: settings efetivos de Actions, tokens,
aprovação de forks, runners, nomes de secrets/variáveis, proteção detalhada,
secret-scanning alerts, webhooks, Packages e deployments. A API não devolve os
valores já guardados de secrets, mesmo a um administrador. Na consulta anterior
main aparecia com `protected: false`; nenhuma proteção efetiva foi alterada nesta
etapa. As listagens anteriores não tinham releases, tags, forks ou caches, mas só
a enumeração Git de branches/tags/refs foi atualizada nesta etapa.

Não se pode declarar esta parte da auditoria concluída sem acesso autorizado aos
conteúdos e às configurações. Não se contornaram bloqueios nem se apagaram
artefactos, ficheiros privados, branches, dados ou histórico para os ocultar.

## Testes e validação

Resultados finais locais:

| Verificação | Resultado |
|---|---|
| Django/PostgreSQL 17, na branch de segurança baseada em main | **460 passaram**, sem falhas ou skips. |
| Chromium computador/telemóvel, incluído nos 460 | **51 passaram**, incluindo fluxos da Gestão e Stock offline. |
| Testes unitários nativos, na linha do PR #13 | **24 passaram**; não substituem instalação Windows real. |
| Política de workflows e proposta de ruleset | **13 passaram** em cada linha; não contar a repetição como testes distintos. |
| Zizmor offline, persona auditor, todos os níveis de severidade/confiança, sem ignores | Sem achados nos dois workflows principais e nos três da linha C. |
| pip-audit dos dois lockfiles de execução | **Zero avisos conhecidos** na consulta de 27-10-2026. |
| PDFs sintéticos emitidos com dependências antigas | **Três reproduzidos byte a byte** após atualização. |
| Migrações e verificações estáticas | Migração numa base nova, sem alterações de esquema; Django check, Ruff, shell PWA e sintaxe JavaScript aprovados. |
| CI remota e instalação Windows/PowerShell 5.1 | **Pendentes**, não se afirma aprovação. |

A primeira execução
com dependências novas tinha 459 testes bem-sucedidos e uma falha no teste que
recalculava os píxeis do ícone; essa causa foi identificada e corrigida conforme
explicado acima. Não foi ocultada como um problema de rede ou uma falha de stock.

Comandos preparados/executados no ambiente sintético, conforme disponibilidade:

```sh
uv sync --frozen --group security
uv run --group security python -m unittest discover -s tests/security -v
uv run --group security python scripts/check_workflows.py
uv run --group security zizmor --offline --persona auditor --min-severity informational --min-confidence low --no-ignores .github/workflows
uv export --frozen --no-dev --no-emit-project --format requirements-txt --output-file /caminho/privado/runtime.txt
uv run --group security pip-audit --disable-pip --no-deps --require-hashes -r /caminho/privado/runtime.txt
python manage.py test accounts inventory imports web consultation tests.browser tests.windows.test_profile tests.vertente.browser tests.vertente.branding --noinput
# Apenas na linha do PR #13:
python manage.py test tests.native_windows --noinput
```

A base dos testes é uma instância PostgreSQL 17 nova, com nome sintético e porta
loopback própria; nenhum comando usou a base reservada à importação. Confirmaram-se
migrações limpas, sem novas alterações de esquema, e a reprodução de três PDFs
sintéticos criados com as dependências anteriores. A suite inclui concorrência,
permissões, stock, inventários, PDFs, backups e Chromium em computador/telemóvel.

A preparação de workflows não é execução Windows bem-sucedida. PowerShell 5.1,
NTFS, instalação real do EXE, serviços Windows, atualização 1.0→1.1, recuperação
com versão exata e restauro em Windows continuam dependentes da execução e aprovação
dos jobs **standard** Windows. Não se instalaram aplicações em dispositivos reais.
Os testes HTTPS/mTLS e o acesso/instalação num Android físico também devem ser
distinguidos: um smoke test sintético não homologa o Wi-Fi da empresa.

O volume que contém o daemon Docker ficou sem espaço disponível; o espaço de
trabalho temporário permitiu concluir os testes de aplicação. Não se fizeram
limpezas Docker nem se apagaram volumes ou ficheiros para libertar espaço.
Não se executaram novos builds/smokes de containers de implantação ou o smoke
HTTPS/mTLS com nginx nesta etapa. Esses comandos permanecem no workflow existente
para execução num runner limpo. A suite de aplicação cobre os backups e restauros
PostgreSQL sintéticos; isso não homologa os caminhos de recuperação Windows.

## Procedimento do proprietário antes/depois da mudança de visibilidade

1. Rever este PR e as alterações coordenadas do PR #13. Resolver a revisão dos
   dados pessoais/contexto comercial remanescentes; não assumir consentimento
   apenas pela autorização de stocks. Se existir informação que não possa ser
   pública, parar: não há autorização nesta tarefa para reescrever o histórico.
2. Inspecionar artefactos/logs e configurações acima em ambiente com acesso
   autorizado. Se aparecer uma credencial real, revogá-la/rodá-la antes de qualquer
   decisão de publicação; apagar um commit não revoga uma credencial.
3. Confirmar colaboradores com escrita e aprovação de execuções de PR externos.
   Preparar a regra pública sem a ativar no plano privado incompatível. Não fazer
   merges enquanto não estiverem revistos e aprovados os checks exigidos.
4. Só depois da revisão final favorável, o proprietário poderá ir a **Settings →
   General → Danger Zone → Change repository visibility → Make public** e confirmar
   os avisos do GitHub. **Esta ação não é executada por scripts deste PR.** Cópias
   públicas feitas por terceiros não desaparecem ao voltar a privado.
5. Na janela da alteração, limitar escrita ao proprietário e não integrar PR até
   concluir as proteções. Em **Settings → Rules → Rulesets**, importar/reproduzir a
   proposta. Confirmar os nomes dos três checks no GitHub e ativar o ruleset. Não
   usar Evaluate, restrições de updates ou aprovações humanas impossíveis para um
   único mantenedor. Confirmar que um PR normal pode passar pelo processo.
6. Reexecutar os workflows dos **SHAs finais** nas Actions. A alteração de
   visibilidade, por si, não garante uma nova execução. Verificar jobs, sistema
   operativo, artefactos e conclusão real, incluindo o job Windows do PR #13.
   Repetir jobs anteriormente impedidos por faturação; não usar resultados de uma
   revisão anterior como aprovação. Manter os PR em revisão até essa confirmação.
7. Configurar reporting privado de vulnerabilidades, Dependabot e secret scanning/
   push protection conforme a disponibilidade da conta pública. Confirmar no
   painel de faturação os runners standard e as regras de armazenamento/retencão.
   Não usar larger runners pagos ou contratar serviços externos.
8. A eventual integração dos PR continua manual e fora desta tarefa. Quando #13
   for integrado e o check nativo estiver efetivamente verde, acrescentá-lo aos
   checks obrigatórios; só depois considerar a homologação automatizada Windows.
   Validações em Windows/Android físicos e instalação na empresa continuam fases
   distintas, não realizadas aqui.

## Fontes oficiais verificadas

O domínio docs.github.com estava indisponível. Foi consultada a origem oficial
`github/docs` por Git, revisão `4e811c0cc9c2fbdf38741d44fa2461620c0d25dc`:

- [Disponibilidade de rulesets no Free público](https://github.com/github/docs/blob/4e811c0cc9c2fbdf38741d44fa2461620c0d25dc/data/reusables/gated-features/repo-rules.md).
- [Proteção de branches no Free público](https://github.com/github/docs/blob/4e811c0cc9c2fbdf38741d44fa2461620c0d25dc/data/reusables/gated-features/protected-branches.md).
- [Faturação Actions: execução standard gratuita em público; armazenamento tem regras próprias](https://github.com/github/docs/blob/4e811c0cc9c2fbdf38741d44fa2461620c0d25dc/content/billing/concepts/product-billing/github-actions.md).

Estas fontes confirmam a disponibilidade do produto, não a configuração efetiva
da conta nem o resultado de um job. A assinatura empresarial do instalador e a
revisão final de privacidade continuam obrigatórias independentemente do custo
dos runners.
