# Etapa D — Obter e verificar instaladores sintéticos na VM

Destino autorizado: Windows 11 Pro x64 convidado no VirtualBox, 8 GB RAM,
3 vCPU, disco de 120 GB, TPM 2.0/UEFI/Secure Boot ativos e checkpoint limpo.
Os EXEs nunca devem ser executados no Windows Home anfitrião. A VM não torna
seguro partilhar pastas pessoais ou utilizar dados reais; manter isolamento.

## Código, versões e limites

Workflow: **Etapa D - Windows 11 synthetic homologation**,
`.github/workflows/windows11-homologation.yml`.

Fonte fixa: **ced00452f7cbeee9634dff87659572aa9aa05497**, a main aprovada
com os PR #22 e #23: dependências PostgreSQL privadas, diagnóstico/progresso do
instalador e demonstração automática. Não há campo que permita escolher outro
código/canal. A origem é fixada neste SHA aprovado; novos commits futuros na main
não são incluídos automaticamente sem outra revisão deste workflow.
O workflow histórico do PR #19 continua fixado a 5e34c6c e permanece inalterado.

Par sintético do ciclo existente: **1.0.0 → 1.1.0**, compilado na mesma execução
com a mesma autoridade temporária. A segunda versão inclui a migração fictícia
de ensaio para verificar a atualização; não são números de release operacional.

O canal synthetic é fixado no anfitrião, no manifesto assinado e na política de
confiança. A inicialização só aceita dados fictícios; pacotes de outro canal ou
assinante são recusados. As atualizações usam a política instalada. Não existe
conversão suportada para release. Não editar políticas, binários ou marcadores
para tentar convertê-lo. Uma futura instalação real terá canal, identidade de
pacotes e processo de aprovação próprios, sem reaproveitar esta base de testes.

A VM com 8 GB serve para os testes sintéticos. A exigência de 16 GB da distribuição
release não foi reduzida. Na primeira instalação limpa, a opção **Criar
demonstração automática** gera conta, palavra-passe, chave e frase de recuperação
exclusivas, sem preencher esses campos manualmente. Continua disponível a
configuração manual completa. Não há credenciais de produção nos instaladores.

## 1. Revisão e execução manual no GitHub

1. Rever este PR e a CI do código fonte escolhido. Integrar o workflow na main
   apenas após autorização do proprietário. O botão manual só aparecerá depois
   de o ficheiro estar na branch predefinida.
2. Abrir Actions → **Etapa D - Windows 11 synthetic homologation**.
3. Selecionar Run workflow, branch **main**, e confirmar. Não há inputs de código,
   versões, chaves ou canal. Só o repositório original/main pode executar o job.
4. Aguardar conclusão **verde**. Ler o resumo e confirmar o SHA fonte completo
   acima, ID da execução e tentativa. Falha/cancelamento não conta como aprovação.

O runner hospedado Windows Server 2025 audita primeiro o código do workflow e as
suas dependências. Depois seleciona e confirma a fonte aprovada, instala as suas
dependências bloqueadas e volta a auditar o runtime que vai entrar nos pacotes.
Executa as regressões WinForms/STA de progresso/erro e as
de demonstração (geração única, DPAPI, kit cifrado e rejeição de produção), unidades
nativas, ACL/NTFS, compilação dos dois EXEs e o ensaio real
de instalação, atualização, backups, recuperação e desinstalação. Isso não é
homologação Windows 11/VirtualBox. O ciclo EXE da CI usa o pedido de configuração
sintético existente; não interage com o novo assistente nem finge que o Windows
Server é Windows 11. A homologação gráfica na VM ainda será efetuada.

Os hashes dos EXEs são calculados antes dos ensaios e novamente antes de publicar.
O download só é preparado após sucesso de todas as etapas e validado por cópia.
A pasta de publicação é criada por rename atómico; falhas anteriores deixam-na
ausente. Apenas dois EXEs e SHA256SUMS.txt são permitidos no upload. O guard de
upload preserva a política existente do repositório; não são carregadas chaves,
certificados privados, pedidos, passwords, bases, dumps ou backups dos testes.

## 2. Transferir para a VM

Preferir abrir o GitHub e descarregar **pelo navegador dentro da VM**. Usar NAT
sem port forwarding; não é necessário ligar o PostgreSQL à rede ou publicar
serviços. Se a transferência for intermediada pelo anfitrião, guardar apenas o
ZIP como ficheiro inerte e transferi-lo por um meio controlado; não abrir os EXEs
no anfitrião, não montar pastas pessoais como partilhas permanentes.

Em Artifacts da execução verde descarregar o ZIP com prefixo
`UNAPPROVED-SYNTHETIC-UNSIGNED-ced00452f7cbeee9634dff87659572aa9aa05497-`,
seguido de ID da execução e tentativa. É necessário login GitHub. Retenção de
**3 dias**; arquivar o par e hashes. Ao repetir a execução/tentativa, obter o par
inteiro novo: não misturar versões assinadas por autoridades temporárias diferentes.

Extrair o ZIP para uma pasta nova **dentro da VM**. Devem existir exatamente:

- `GVA-synthetic-1.0.0-win-x64.exe`
- `GVA-synthetic-1.1.0-win-x64.exe`
- `SHA256SUMS.txt`

## 3. Verificar antes de executar qualquer EXE

No PowerShell dentro da VM, abrir a pasta extraída e calcular:

```powershell
Get-FileHash .\GVA-synthetic-1.0.0-win-x64.exe -Algorithm SHA256
Get-FileHash .\GVA-synthetic-1.1.0-win-x64.exe -Algorithm SHA256
Get-Content .\SHA256SUMS.txt
```

Comparar os dois valores completos com SHA256SUMS.txt **e com os hashes no resumo
da mesma execução no GitHub**. Confirmar commit fonte, execução e tentativa nos
comentários do checksum. Se faltar ficheiro, o hash não coincidir ou a proveniência
for diferente, parar: não instalar nem combinar ficheiros de outros ZIP.

SHA-256 comprova integridade relativamente à origem consultada; não substitui uma
assinatura de editor confiável. Estes EXEs **não têm Authenticode empresarial** e
são **SYNTHETIC / UNSIGNED / NOT APPROVED FOR PRODUCTION**. Se SmartScreen, Windows
ou antivírus bloquear/avisar, registar o resultado e parar. Não desativar proteção,
não criar exclusões, não ignorar avisos e não instalar certificados de teste no
anfitrião para contornar um bloqueio. Se necessário, preparar posteriormente uma
assinatura confiável de homologação e repetir a validação desse pacote.

## 4. Primeiro ensaio, apenas numa VM limpa e autorizada

1. Confirmar checkpoint e que não existem serviços GVA nem utilização das portas
   8765/55432. Não terminar serviços ou apagar dados de outras instalações.
2. Executar **1.0.0** pelo assistente. Confirmar que se trata da VM autorizada e
   selecionar **Criar demonstração automática**. A conta, palavra-passe e material
   de recuperação são gerados por instalação; não devem ser introduzidos nomes ou
   credenciais reais. A deteção da VM e os controlos de segurança mantêm-se ativos.
3. Na janela privada, revelar as credenciais apenas quando necessário e guardar
   o kit cifrado `.gvademo` e o código em locais privados separados. O cofre DPAPI
   está associado à conta Windows criadora; o kit não substitui o backup. Seguir
   [Demonstração automática](windows-synthetic-demo.md). O login normal continua
   obrigatório, utilizando a conta gerada. Abrir pelo atalho e criar apenas
   operações fictícias. Registar quantidades,
   documentos e identidades antes da atualização.
4. Fazer backup pelo menu de manutenção e conservar cópia, chave/frase e os EXEs.
5. Executar **1.1.0** do mesmo ZIP, fornecendo os elementos de recuperação pedidos.
   Confirmar que dados, contas, PDFs, histórico e numeração são preservados.
   Consultar os elementos gerados em **Dados privados da demonstração**, na
   manutenção sintética; não é necessário inventar novas credenciais de recuperação.
6. Testar reboot normal da VM pelo Windows e nova abertura. Nunca desligar o
   anfitrião para provocar uma falha.

Recuperação deve ser ensaiada numa VM/clone novo, com a origem parada e isolada;
o destino não pode já conter serviços/dados GVA. O instalador exige o payload
exato do backup. Desinstalar normalmente conserva dados e backups; não equivale
a uma limpeza completa. Não apagar cluster, chaves ou maintenance.json para
forçar uma repetição. Guardar evidência privada antes de repor um checkpoint.

A VM da instalação anterior que falhou deve permanecer preservada. Estes passos
destinam-se a uma VM/clone limpo novo, após autorização; não reparam nem adotam
automaticamente o cluster, serviços ou diário antigos. O modo **Configuração manual /
recuperar backup** fica disponível para ensaiar o assistente completo separadamente.

Não executar `windows_smoke.py` na VM fingindo GITHUB_ACTIONS=true. É uma rotina
privilegiada limitada à CI e inclui falhas destrutivas. O reboot_probe atual
aceita apenas Hyper-V; a adaptação segura a VirtualBox é trabalho separado.
Este PR prepara os downloads e o ensaio manual, não automatiza a VM nem reinicia
qualquer computador. A matriz completa de homologação continua pendente.

## Nota sobre a infraestrutura de testes

A regressão HTTPS/offline da CI revelou uma utilização do mesmo socket SSL por
threads de leitura/escrita diferentes no adaptador sintético de dispositivo. O
adaptador passou a multiplexar as duas direções num único event loop, com I/O TLS não bloqueante, e
a aguardar o fim dos handlers antes de abandonar o contexto de teste. Certificados,
verificação TLS/mTLS, hostname e regras da aplicação não foram alterados.

Uma regressão com TLS real em loopback, certificado de cliente e payload fictício
falhou antes da correção por acesso ao mesmo socket em threads diferentes e passou
depois dela. A CI Linux ativa faulthandler para melhorar os diagnósticos de erros
nativos. Esta correção não prova, por si só, a causa exata do anterior código 139,
que não tinha traceback. O timeout da navegação não foi aumentado e não foram ignoradas falhas.
