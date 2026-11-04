# Atualizações Windows simplificadas

Base PR #38, 16dcc2c. Abrir o EXE autorizado, aceitar UAC quando solicitado,
Instalar e Terminar. O NSIS preserva os gates de preflight/assinatura, canal,
versão e hashes. Na instalação existente, após verify, o host abre apenas
progresso e executa update sem ficheiros de pedidos, frases ou caminhos PEM.
A instalação inicial e recuperação mantêm os assistentes próprios.

Ações transacionais e diário existentes são reutilizados. A chave em memória
é obtida do cofre DPAPI administrador-only: bootstrap de instalação nova ou
frase portátil configurada. A correspondência com a chave pública é validada
antes de parar serviços; perda do cofre recusa claramente e exige configuração
com a frase original em Cópias de segurança. Instalações antigas mantêm a via
CLI de compatibilidade autenticada; não se inventam chaves nem se muda a confiança.

Antes das migrações: backup cifrado, autenticação, restauro numa base nova e
comparação integral das evidências. Mantêm-se retenção, serviços privados,
NTFS, gateways, identidades e dados. Nenhuma atualização configura firewall/DNS.
Falha comprovadamente anterior à entrada em migrate pode reativar a versão
inalterada apenas após verificações de schema e saúde. Se essa recuperação
falhar, o diário bloqueia os serviços. Após entrar em migrate, nunca executar
código antigo nem migrações inversas: mantém-se recuperação verificada existente,
com preservação de dados. Não se afirma rollback automático após migração.

A confirmação final do NSIS só surge após ativação e saúde verificadas. Erros
não são mascarados. Não há bypass de SmartScreen, antivírus ou Authenticode.

CI: atualização sintética EXE 1.0→1.1 sem chave/frase no pedido, bases povoadas,
PDFs, identidade, backups e recuperação do #38, testes de falhas em cada fase,
rollback apenas antes da migração, DPAPI, segurança, PostgreSQL/Chromium.
Pendente Windows 11 Home/Pro: percurso visual Instalar/Terminar, UAC com conta
administrativa diferente, corte de energia real, antivírus empresarial e rede
Android física. Pacotes não foram publicados; não há homologação física implícita.
