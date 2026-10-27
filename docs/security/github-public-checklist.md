# Verificações manuais no GitHub antes do acesso público

Repositório: `MickaTDN/gestao-garrafas`. Atualizado em 27-10-2026.
Preencher cada item com o resultado e, quando aplicável, o SHA ou execução revista.
**Nenhum checkbox representa uma configuração já aplicada.** A API deste ambiente
continua bloqueada; Git permite verificar os commits, mas não certifica settings,
estados de rascunho ou resultados de Actions.

## Antes de alterar a visibilidade

- [ ] **PR #14 e #13:** ambos abertos e **Draft**, destino previsto `main`, branches
  `security/etapa-c1-public-readiness` e `stagec/windows-native-installer`.
  Confirmar os últimos SHAs em **Commits** e rever **Files changed**. Verificar que
  não há alterações inesperadas, ficheiros privados ou dados pessoais novos.
  Não clicar em **Ready for review** ou **Merge** nesta preparação.
- [ ] **Privacidade do histórico:** confirmar autorização dos titulares dos dois
  emails Gmail de autoria e do primeiro nome no protótipo original, identificados
  no relatório privado. Rever o contexto comercial/localizações e a identidade
  visual que ficam visíveis. A autorização de divulgação dos stocks já está
  registada; não aprova automaticamente estes outros dados. Se faltar autorização
  para algo que deva permanecer privado, suspender a publicação. Não reescrever
  histórico ou apagar conteúdo nesta tarefa.
- [ ] **Segredos e variáveis:** em **Settings → Secrets and variables → Actions**,
  rever os nomes e âmbito das entradas; garantir que os testes não recebem segredos
  de produção, chaves empresariais, certificados privados ou credenciais internas.
  Rever também Dependabot/Codespaces, se usados. Não copiar valores para chat,
  issues, PR ou relatórios públicos. Os valores de secrets já guardados não podem
  ser recuperados pela API para provar o seu conteúdo.
- [ ] **Logs e artefactos de Actions:** abrir as execuções e inspecionar em ambiente
  autorizado os ficheiros para download e os logs ainda existentes. A auditoria
  anterior inventariou 32 artefactos, mas não conseguiu ler o interior dos binários
  ou os logs. Procurar configurações, dados pessoais, passwords, chaves ou outros
  ficheiros privados; o nome sintético não prova ausência deles. Não executar os
  instaladores para esta inspeção nem partilhar URLs temporários assinados.
- [ ] **Outras publicações:** rever **Releases**, **Packages**, **Settings → Pages**,
  deployments e anexos/comentários de PR/issues que possam ficar acessíveis.
  Confirmar que não existem publicações privadas inesperadas. A falta de acesso
  da integração não prova que essas áreas estejam vazias.
- [ ] **Execução de contribuições externas:** em **Settings → Actions → General**,
  exigir aprovação de execuções de todos os colaboradores externos, conforme as
  opções disponíveis. Rever código e alterações de workflow antes de aprovar.
  Manter o token padrão com acesso de leitura e desativar a opção que permite às
  Actions criar/aprovar PR. Não enviar tokens de escrita ou secrets a forks.
- [ ] **Runners e Actions permitidas:** em **Settings → Actions**, confirmar runners
  standard hospedados pelo GitHub, sem ligação a runners da empresa. O job nativo
  com serviços/ACLs deve recusar forks. Confirmar que a política de Actions permite
  apenas as dependências necessárias e os SHAs revistos do ficheiro
  `.github/security/approved-actions.json`, sem bloquear os próprios testes.
- [ ] **Acessos e integrações:** rever colaboradores com escrita/administração,
  GitHub Apps, webhooks e environments. O proprietário deve manter administração;
  nenhum contexto de testes deve dar acesso a infraestrutura ou segredos de
  produção. Confirmar que o dono pode gerir as proteções sem bypass permanente
  para alterações normais.
- [ ] **CI das revisões atuais:** abrir **Checks/Actions** dos últimos commits dos
  dois PR. Distinguir falha de código, testes não iniciados por faturação e jobs
  `skipped`. Não chamar verde a uma execução que não testou a revisão atual.
  Os resultados locais estão no relatório; instalação Windows real e respetiva
  homologação continuam pendentes. O uso de runners gratuitos depois de público
  não exige declarar esses testes já aprovados antes da mudança.
- [ ] **Plano de proteção e custos:** rever
  [main-ruleset.public.json](../../.github/security/main-ruleset.public.json),
  inicialmente `disabled`. Confirmar que se trata de ruleset de **branch**,
  disponível no Free público, e preparar a sua ativação imediata depois da mudança.
  Não exigir aprovações humanas impossíveis para um único mantenedor, Evaluate,
  regras pagas ou checks inexistentes. Confirmar runners standard e regras de
  armazenamento/retencão; não selecionar larger runners pagos.
- [ ] **Decisão do proprietário:** registar que as verificações de privacidade,
  segredos e conteúdo publicado ficaram resolvidas. Se houver uma credencial real,
  revogá-la/rodá-la antes de publicar; apagar um commit não a revoga. Se restarem
  conteúdos confidenciais ou áreas relevantes sem inspeção, manter privado.
  Só o proprietário deverá então usar **Settings → General → Danger Zone →
  Change repository visibility**. Não há script que execute essa mudança.

## Imediatamente depois da mudança manual, antes de integrar PR

- [ ] **Ativar a proteção da main:** em **Settings → Rules → Rulesets**, importar ou
  reproduzir a proposta, confirmar os contextos dos checks no GitHub e ativar.
  Exigir PR, impedir force-push e eliminação, exigir branch atualizada, conversas
  resolvidas e os checks `django-postgresql`, `windows-powershell` e
  `workflow-and-dependency-security`. Durante esta janela, limitar escrita ao
  proprietário e não integrar PR até concluir as proteções.
- [ ] **Não bloquear a evolução:** confirmar que o proprietário pode gerir o
  ruleset e que um PR legítimo tem um caminho para aprovação. Não exigir ainda
  `windows-native-synthetic` sem o workflow e a política de PR correspondentes.
  Um estado `skipped` num fork não homologa Windows; código externo do instalador
  deve ser revisto e testado numa branch interna autorizada antes de integração.
- [ ] **Reexecutar CI:** executar/reexecutar os jobs dos SHAs finais de #14 e #13,
  incluindo PowerShell e Windows nativo quando aplicável. Confirmar execução real
  de instalação, atualização e recuperação no runner Windows. A visibilidade por
  si só não garante novo disparo. Rever falhas e não integrar código com checks
  obrigatórios pendentes ou falhados.
- [ ] **Proteção contínua:** confirmar opções disponíveis de secret scanning,
  push protection, Dependabot e comunicação privada de vulnerabilidades. Não
  ativar produtos pagos sem autorização. Os instaladores de testes continuam
  não aprovados; distribuição oficial requer autorização e Authenticode empresarial.

## Estado da preparação de integração

Os manifestos dos dois PR foram alinhados com Waitress 3.0.2, Pillow 13.0.0 e
cryptography 50.0.2. O lockfile foi regenerado por uv, sem atualizações de pacotes
alheios à resolução. A simulação estática da junção deixou de apresentar os dois
conflitos de dependências. Uma simulação não integra PR nem substitui a CI ou a
revisão dos SHAs finais; voltar a verificar conflitos se alguma branch mudar.
