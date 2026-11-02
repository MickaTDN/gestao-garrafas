# Homologação sintética do PR #25

Fonte fixada: `b9fc7257b3d70abeadc2da2d005ed52bbc5fdad4`. O workflow
`windows11-homologation.yml` compila 1.0.0 e 1.1.0 na mesma execução e testa
instalação, atualização, backup portátil, recuperação, rollback e preservação
dos dados antes de disponibilizar os ficheiros. Não gera uma release oficial.

## Bloqueio de distribuição

A política existente exige execução manual a partir da `main`. Esta alteração
do workflow precisa primeiro de revisão e integração autorizada pelo proprietário.
Não executar a versão antiga da main: está fixada num commit anterior ao PR #25.
Não alterar a condição de segurança para publicar a partir de uma branch de PR.

Após essa integração autorizada, executar manualmente **Etapa D - Windows 11
synthetic homologation**, selecionando main. Só descarregar se o job completo
terminar com sucesso. O artefacto dura três dias e contém exclusivamente dois
EXE, `SHA256SUMS.txt` e `PROVENANCE.json`. O manifesto identifica a fonte, a revisão
do workflow, a execução, a tentativa e os hashes dos dois instaladores testados.
Guardar o par da mesma execução/tentativa; não misturar autoridades sintéticas.

## Duas VMs Windows 11 descartáveis

1. Criar snapshots e transferir o artefacto do GitHub para dentro das VMs.
   Comparar `Get-FileHash .\GVA-synthetic-1.0.0-win-x64.exe -Algorithm SHA256`
   e o equivalente 1.1.0 com SHA256SUMS e o resumo da execução no GitHub.
   Conferir commit e tentativa no manifesto.
2. Na VM A, instalar 1.0.0, criar apenas dados fictícios e testar a atualização
   para 1.1.0. Confirmar referências, movimentos, PDFs, assinatura e utilizadores.
3. Já em 1.1.0, criar uma cópia portátil externa e guardar a credencial separada.
   Desligar/isolar a VM A antes de ativar outra cópia da mesma origem.
4. Na VM B limpa, instalar 1.1.0 do mesmo par e escolher recuperar a cópia portátil.
   Rever o resumo e confirmar origem isolada e histórico. Comparar dados, PDFs,
   permissões e identidade; testar login e nova cópia de segurança.
5. Com snapshots, repetir reinstalação e recuperação sobre dados existentes,
   credencial errada, ficheiro corrompido e cancelamento. Conferir preservação dos
   dados anteriores. Os kits antigos exigem o código/chave correspondentes;
   não presumir recuperação sem esse material.

Parar perante hashes divergentes, versão/esquema incompatível, erro do assistente,
diário de manutenção pendente, serviços indisponíveis ou bloqueio Windows/antivírus.
Não desativar proteções nem apagar clusters, serviços ou diários manualmente.
Não executar estes instaladores no anfitrião ou num computador de produção.

Os EXE sintéticos não têm aprovação/assinatura empresarial de produção. Testes
Windows Server da CI não homologam a interação visual, reinício/perda de energia
ou migração entre Windows 11 Home/Pro. A tarefa abrange apenas dados Windows.
