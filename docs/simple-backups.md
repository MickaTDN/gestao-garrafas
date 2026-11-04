# Backups portáteis: configurar uma vez

Base #35 c621b00; formato portátil e criptografia do #25 preservados.
Definições → Cópias de segurança → Criar backup abre o assistente elevado.
Na primeira vez definir e confirmar frase de pelo menos 16 caracteres. Guardá-la
separadamente do computador. Depois basta escolher um novo .gvabackup externo;
exportação só declara sucesso após autenticação, restauro de ensaio e hash.
Backups automáticos continuam a usar o envelope cifrado, sem ler o cofre local.

Em instalações novas retém-se material inicial apenas em DPAPI LocalMachine,
com DACL exclusiva Administradores/SYSTEM. Isso permite UAC com outra conta
administrativa: CurrentUser seria incompatível. A frase portátil configurada
substitui esse material no cofre; envelope existente nunca é substituído e exige
a frase original para voltar a associar um cofre perdido. O serviço web não
pode ler o cofre nem abrir caminhos arbitrários. Credenciais atravessam somente
o pipe stdin anónimo existente, não argumentos/logs ou temporários em claro.

Instalações anteriores podem exigir uma única associação da chave/kit original,
na opção Compatibilidade. Não se pode inventar essa chave nem recuperar backups
antigos sem ela. Recuperação normal usa apenas ficheiro e frase; mostra resumo
e exige confirmação de origem parada/histórico conferido. Cofre DPAPI copiado
é descartado no destino. A frase original permite configurá-lo novamente, sem
alterar backups anteriores. Backups antigos continuam nos procedimentos existentes.

Preservam-se rollback, retenção, provas/PDFs, identidades, gateways isolados e
aprovação de rede após restauro. Não há alteração de PWA ou dos protocolos.
Ensaios preparados para CI (ainda não executados nesta revisão): DPAPI real no Windows, backups consecutivos sem frase, restauro em
destino novo sem cofre, credencial errada, falha de restauro/rollback e evidências
existentes, EXEs 1.0→1.1. Linux omite apenas a chamada DPAPI real.

Pendente homologação em Windows 11: UAC com administrador diferente, ACL contra
utilizador normal, UI, dois computadores/VMs, perda do cofre e frase original,
restauro antigo e manutenção Wi-Fi desativada. Runners não substituem essa prova.
Não foram publicadas versões nem alteradas instalações reais.

## Estado desta revisão

Validação local: 92 testes nativos, 91 aprovados e 1 DPAPI omitido em Linux;
32 regressões de segurança aprovadas; Ruff, diff-check e política dos workflows
aprovados. Não existe dotnet neste ambiente. Windows/DPAPI real, Chromium,
PostgreSQL e ciclo EXE desta revisão ainda não foram executados. Não se considera
a funcionalidade concluída sem esses resultados e a homologação efetiva.
Push e criação do PR bloqueados por HTTP 401 Bad credentials no GitHub.
Branch local preservada: feature/simple-portable-backups. Após religar a
integração GitHub, enviar a branch e criar draft com destino a
integration/native-recovery-wifi-sheets, executar CI e corrigir eventuais falhas.
