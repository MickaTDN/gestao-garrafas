# Validação Etapa C

Este relatório acompanha o PR em rascunho. Usam-se apenas dados sintéticos novos.
Não se acede à base reservada ao Excel, a instalações Windows ou a dados reais.

## Evidência local

- 13 testes iniciais de assinatura/inventário/versionamento, cifragem autenticada,
  validação/extração de arquivo e interrupção das fases do atualizador: aprovados.
- Após acrescentar o perfil nativo e rede: 18 testes nativos; com os9 testes de
  backup existentes, **27 aprovados** em PostgreSQL17 sintético.
- Primeira regressão: 471 executados;7 erros de ferramentas de backup devidos à
  porta do contentor no adaptador do ambiente de ensaio. Corrigido o adaptador
  privado, sem alterar a aplicação; os9 testes de backup passaram depois.
- Regressão completa e CI da revisão final: resultados a completar após execução.

## Automação Windows

`windows-native.yml` compila instaladores1.0.0/1.1.0 e tenta instalação real de
EXE em runner WindowsServer2025 descartável. Compilação/instalação de teste não é
homologação física em Windows11. A autoridade de pacotes é temporária sintética;
nenhuma chave de produção ou privada vai para os artefactos.

Casos de automação: primeira instalação, serviços, PostgreSQL17, persistência no
stop/start, atualização, backup cifrado/restauro com comparação de todas as linhas,
recusa de downgrade, identidade/chave Android e desinstalação sem destruição.
Interrupções em todas as fases também são exercitadas por testes unitários.

## Homologação ainda obrigatória

- VM Windows11Pro realmente limpa, runtimes/antivírus/políticas empresariais.
- Reinício real e interrupção/reboot a meio de uma atualização.
- Sessão Windows sem administrador: aplicação e teste negativo de acesso a segredos.
- Certificado empresarial Authenticode, timestamp, cadeia/revogação e SmartScreen.
- Atualização entre esquemas históricos distintos e recuperação de avaria/energia.
- Destino empresarial de backup, retenção, monitorização e recuperação de chaves.
- Publicador nativo com certificados/CRL reais e Android físico no Wi-Fi aprovado.

Nenhuma dessas validações deve ser apresentada como concluída por existir código
ou uma simulação. Não efetuar instalação operacional antes da aprovação da empresa.
