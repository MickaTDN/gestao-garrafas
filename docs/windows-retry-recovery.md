# Correções de homologação Windows 11 (base #39)

A pasta releases/1.1.0 era criada antes de verificar/preparar a atualização.
Uma falha anterior às migrações deixava a cópia incompleta e a guarda NSIS
recusava qualquer repetição. Agora o preflight verifica assinatura, versão,
canal, ausência de manutenção e disponibilidade do cofre antes da cópia.
Quando existe uma pasta da versão pretendida, confirma registo da versão
anterior e hash do manifesto ativo e escolhe uma pasta nova com GUID. A pasta
anterior fica intacta, sem renomear, apagar, reutilizar ou executar os seus bytes.
O destino novo continua sujeito à verificação completa do pacote assinado.
Não há retry sobre uma versão ativa, downgrade ou manutenção pós-migração.

A ausência/perda do cofre produz orientação Cópias de segurança antes de copiar
para Program Files. A atualização continua a criar backup cifrado e restaurá-lo
numa base nova antes de migrar. Não se alterou retenção, ACL ou confiança.

A recuperação aceitava um intervalo de versões, mas restaurava sem migrações e
exigia schema atual. O pacote sintético 1.1.0 inclui uma migração de ensaio que
não existe no backup 1.0.0: a falha era detetada tarde, em schema/identidade.
Agora autentica a cópia e recusa antecipadamente versões diferentes ou código
não correspondente ao hash do pacote original. Usar o instalador exato da cópia,
recuperar e conferir os dados, e só depois atualizar normalmente. Nunca migrar
no assistente de recuperação ou arrancar schema incompatível. Backups antigos
mantêm credenciais/procedimentos existentes; conservar o instalador original.

Testes preparados: guardas .NET de retry/manifesto adulterado/diário, EXE real
com pasta órfã adulterada preservada, atualização para destino novo, rejeição
antecipada autenticada de 1.0→1.1 sem alterações ao root, restauro exato seguido
de atualização e restantes provas Windows/backup/rollback já existentes.
Pendente repetir em Windows 11 com os casos reais, UAC e cortes de energia;
CI Windows Server não substitui homologação física. Sem publicação/merge.
