# Integração controlada: recuperação, Gestão Wi-Fi e folhas

Base: #34 `24c6904`; merges rastreáveis de #25 `b9fc725` e #28 `9a165de`.
Os PR originais e a main não são modificados. Não há alteração de protocolos
v1/v2 nem novas migrações: preserva-se a junção consultation.0007 e a 0008.
A CI mantém os ensaios de atualização de bases povoadas de ambas as linhas.

A Gestão local mantém o backend loopback e a única PostgreSQL 17 privada.
GVAPublisher é exclusivamente de leitura; GVASheetReceiver recebe envelopes;
GVAManagementWifi serve a Gestão com autenticação Django e CSRF. Fábio/Daniel
não recebem permissão de confirmação oficial. Mantêm-se originais, auditoria,
recibos, propostas e confirmação transacional/idempotente com PDFs oficiais.

Conflitos conciliados por blocos: CLI com todas as ações, assistente com
recuperação portátil e controlo independente de ambos os gateways, SCM com
seis serviços, paragem de ambos os gateways antes da PostgreSQL. Configuração
Wi-Fi acrescenta somente os grants exatos da sua conta, preservando os grants
do recetor e sem acesso às chaves privadas do publicador. Restauro reaplica
ACL próprias aos dois diretórios de certificados e aos seus ficheiros.

Backup mantém o fluxo do #25: cópia externa cifrada/autenticada, credencial,
pré-visualização e confirmação explícita; rollback preserva dados anteriores.
Não se simplificou o assistente. Segredos/configurações dos gateways entram no
backup cifrado; marcadores de aprovação runtime nunca entram. Após restauro,
o publicador fica desativado e os dois gateways exigem nova aprovação de rede.
Não se reutiliza automaticamente DNS, firewall ou confiança da máquina anterior.

## Verificações

CI: Django/PostgreSQL e Chromium (incluindo protocolos v1/v2, concorrência,
falhas de PDF e reenvios), migrações povoadas, políticas de segurança,
PowerShell, EXEs sintéticos 1.0→1.1, gateways HTTPS/mTLS reais, backup antigo e
portátil, restauro em destino novo, falha com rollback e desinstalação segura.
A fixture nativa preserva ensaios de inventário e folhas: sete movimentos
confirmados e sete números, seis PDFs e três assinaturas persistentes.
Não se publicam instaladores neste PR.

Pendente: Windows 11 Home/Pro e Android físicos, certificados empresariais,
revogação real e DNS/firewall aprovados; transferência entre duas VMs reais e
perda de Wi-Fi durante confirmação. Runners sintéticos não homologam a instalação
empresarial. Manter origem anterior isolada/parada na recuperação de identidade.
