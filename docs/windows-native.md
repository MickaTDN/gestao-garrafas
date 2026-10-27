# Etapa C — Instalação nativa e atualizações Windows

Estado: implementação para **validação sintética**, PR em rascunho. Não autoriza
instalação operacional nem publicação de dados reais. Não substitui uma
homologação Windows11/Android e da informática da empresa.

## Decisão técnica

Mantém Django5.2 LTS, Python3.12 e PostgreSQL17. A aplicação e a PWA Stock da
Etapa B são reutilizadas. Não há alterações a entradas, saídas, inventários,
permissões, assinaturas, PDFs, histórico ou às respetivas migrações.

O instalador **NSIS** reúne um Python privado (sem instalação global),
dependências exatas do `uv.lock`, PostgreSQL17 privado, **Waitress3** (WSGI
compatível com Windows), anfitrião **.NET10 LTS** e NGINX para o publicador opcional.
.NET é distribuído com o programa; não exige instalar separadamente esse runtime.
O Python é a distribuição mantida `python-build-standalone`; guardar origem,
licenças, versões e hashes dos fornecedores. Reavaliar as atualizações de segurança
antes de cada distribuição. Não usar o antigo Python3.12.10 embeddable sem os
patches posteriores de segurança.

Evita-se embutir um navegador ou depender de WebView2: o atalho abre uma pequena
janela de controlo e depois o navegador predefinido suportado. Não surge consola.
Chrome/Edge devem ser mantidos pela informática. Não há um segundo frontend nem
um executável que converta Django em servidor de desenvolvimento.

## Separação de ficheiros e privilégios

| Elemento | Local/identidade |
| --- | --- |
| Programa imutável | `%ProgramFiles%\GestaoVertenteAveludada-release\releases\VERSAO` |
| Dados privados | `%ProgramData%\GestaoVertenteAveludada` |
| Canal de validação | pastas com sufixo `synthetic`/`-Teste`, nunca adotam o piloto Docker |
| Base | `cluster`, apenas administradores/SYSTEM e `NT SERVICE\GVAPostgres17` |
| Aplicação | `NT SERVICE\GVAWeb`, SQL `gva_web` sem superuser, CREATEDB ou DDL |
| Migrações | administrador autorizado, SQL `gva_owner`, separado da aplicação |
| Backups | `NT SERVICE\GVABackup`, diretório privado, credenciais do owner |
| Publicador opcional | `NT SERVICE\GVAPublisher`, sem acesso à base/segredos de Django |
| Chaves Android | `signing`, fora do programa e conservadas nas atualizações |
| Certificados/CRL | `tls`, fora do programa; acesso do publicador e backup |

A conta de backup é sensível: pode ler os dados e chaves da instalação e criar
bases para ensaio. Proteger o computador, administradores, serviço, cópias e
credenciais. A conta de execução web não pode ler `owner.json`, alterar DACLs,
instalar atualizações nem autorizar dispositivos Android.

O serviço PostgreSQL usa apenas **127.0.0.1:55432**, autenticação SCRAM, `fsync`,
`synchronous_commit` e `full_page_writes` ativos. A aplicação usa apenas
**127.0.0.1:8765**. Portas ocupadas são recusadas; não se termina/adota outro
PostgreSQL. HTTP é uma exceção explícita apenas para loopback, sem proxy confiável,
DEBUG ou origens Wi-Fi. Não serve a aplicação operacional à rede.

Não é uma fronteira contra um administrador local nem contra malware executado
com os privilégios dos serviços. Recomenda-se uma estação empresarial controlada,
contas Windows individuais, bloqueio de ecrã e BitLocker conforme política da
empresa. Não implementar essas políticas automaticamente.

## Instalação inicial — utilizador e informática

1. A informática valida Windows11 x64, 16GB RAM, espaço para base, pelo menos duas
   cópias e restauro temporário; navegador atualizado e políticas de execução.
2. Obtém o instalador de uma origem autorizada e confirma versão, SHA-256 e editor
   Authenticode. Um hash isolado não autentica o editor.
3. Executa o `.exe`. A elevação UAC serve para ProgramFiles, serviços e DACLs.
   Não há necessidade de privilégios administrativos no uso diário.
4. O assistente explica os componentes. No modo de validação, só admite dados
   fictícios. Não existem palavras-passe predefinidas.
5. Introduz a conta inicial da aplicação, confirma a palavra-passe e uma frase
   de recuperação com pelo menos16 caracteres. Escolhe um **ficheiro novo** num
   suporte autorizado, separado da instalação, para a chave privada de recuperação.
6. Guarda a frase separadamente da chave e testa a recuperação com a informática.
   Os instaladores e artefactos nunca recebem essa chave ou frase.
7. Após a preparação, utiliza o atalho do ambiente de trabalho/menu Iniciar.
   A conta Django é individual; não é a conta de administrador do Windows.

O instalador cria sempre uma instalação nova ou atualiza uma instalação nativa
reconhecida. Recusa diretórios privados preexistentes desconhecidos, serviços
homónimos, portas ocupadas e versões repetidas. **Não converte automaticamente
um piloto Docker/WSL nem copia a base reservada ao Excel.** Qualquer futura
migração de uma instalação anterior requer um procedimento separado e autorizado.
Os canais usam os mesmos nomes de serviço: não são instalados simultaneamente no
mesmo Windows; usar VMs separadas para homologação e produção.

## Arranque, encerramento e diagnóstico

Os serviços arrancam automaticamente com o Windows, pela ordem das dependências.
O anfitrião só comunica disponibilidade após o processo ficar pronto. Várias
janelas podem abrir a mesma aplicação; não criam novas bases ou servidores.

Ao parar, Waitress deixa de aceitar trabalho e escoa pedidos; PostgreSQL recebe
`pg_ctl stop -m fast`: transações abertas são revertidas e as confirmadas têm WAL
persistente. Não se usa encerramento `immediate`, eliminação de processos ou
`fsync=off`. Se o Windows impuser um limite ao encerramento, PostgreSQL efetua
recuperação de WAL no arranque seguinte. Isto não protege contra avaria física do
disco, controlador sem garantias de flush ou perda do computador: usar backups.

A janela mostra a versão e o acesso local. Se existir `maintenance.json`, bloqueia
o uso e pede intervenção. Consultar estado dos serviços no Windows, fase do diário,
`runtime/postgres/server.log`, estado de backup em `runtime/backup` e registos
Windows. A aplicação não mostra SQL, passwords ou chaves nos erros. Não apagar
`maintenance.json`, `cluster`, WAL ou segredos para “tentar outra vez”.

## Atualização manual — 1.0.0 → 1.1.0 → 1.1.1

A informática executa o novo instalador e fornece a chave/frase de recuperação
pelo assistente. O utilizador normal não executa comandos.

1. Antes de copiar sobre qualquer versão instalada, o anfitrião valida assinatura
   do manifesto, canal, PostgreSQL17 e intervalo de versões. Não reinstala a mesma
   versão nem faz downgrade. Diretórios de versão nunca são sobrescritos.
2. A distribuição `release` exige assinatura Authenticode confiável e fingerprint
   SHA-256 do certificado do editor. Atualizações confiam na **política instalada**,
   não na chave declarada pelo próprio ficheiro recebido.
3. Verifica todos os ficheiros/tamanhos/hashes do payload autenticado por ECDSA-P256.
4. Obtém um bloqueio exclusivo e grava diário durável. Desativa arranque automático
   dos serviços **antes** de qualquer migração; depois para-os controladamente.
5. Liga apenas o PostgreSQL necessário à manutenção, em modo de arranque manual.
6. Cria backup cifrado de base+configurações+chaves+certificados, decifra-o com a chave
   fornecida e restaura numa base de ensaio nova. Compara todas as linhas, documentos
   binários, identidades e sequências antes de autorizar migrações.
7. Executa migrações com o novo código e a conta owner, reaplica os grants revistos,
   valida Django e ausência de migrações pendentes.
8. Só então aponta a instalação à nova versão, reconfigura serviços e verifica HTTP.
   Regista resultado/versões; mantém os dados e a identidade Android.

Interrupção/falha deixa diário, dados e backups. Os serviços não retomam com código
antigo sobre uma base possivelmente migrada. Não há migrações inversas automáticas.
Um reboot durante uma atualização não constitui aprovação de recuperação.
Uma falha de disco/energia exige revisão dos ficheiros e backup verificado, não
uma nova tentativa cega. A atomicidade PostgreSQL não torna DDL+ficheiros+SCM uma
única transação; o diário e a recusa de arranque tratam esta fronteira.

## Backups e retenção

O serviço faz backup ao iniciar e depois a cada24horas enquanto ligado. Assim,
um computador desligado à noite conserva uma cópia ao iniciar no dia seguinte.
**Não existe ainda uma garantia de cópia no momento de cada movimento**: definir
RPO/RTO com a empresa. Usar “Manutenção (informática) → Criar backup manual cifrado”
para uma cópia adicional; exige UAC.

`backup-policy.json` é administrativo: `retain` entre2e1000 (14 por defeito) e
`copy_to` opcional para um diretório empresarial existente e autorizado. A cópia
externa requer permissões da conta de serviço/máquina, capacidade e disponibilidade.
Não gravar credenciais de partilha no programa. A informática configura e valida
esse destino; a retenção local **não apaga as cópias empresariais**.

Cada arquivo `.gvabackup` contém pg_dump custom consistente, esquema de evidências,
configurações, credenciais, assinatura Android e certificados. Usa uma fotografia
PostgreSQL exportada e bloqueios coordenados com os serviços existentes. PDFs,
assinaturas de validação e histórico pertencem ao dump, sem regeneração.

AES-256-GCM autentica metadados e conteúdo; RSA-OAEP-SHA256 envolve uma chave de
dados aleatória. A chave privada RSA3072 é cifrada com a frase escolhida e guardada
separadamente. A rotina diária possui apenas a chave pública. Não pode decifrar as
cópias. Verifica o arquivo antes da cifragem e a cópia empresarial por SHA-256;
a autenticação GCM e o restauro real são verificados na recuperação e antes de
atualizações. Não confundir checksum de transporte com prova de recuperabilidade.

A retenção só ocorre depois de publicar uma cópia completa; uma falha de destino
empresarial conserva a cópia local e não aplica retenção. Monitorizar ficheiros de
último sucesso/falha e efetuar restauros regulares. Não há alertas externos.
Sem chave **e** frase, não existe recuperação. Guardar duas cópias protegidas da
chave, a frase em cofre separado e os instaladores exatos das versões dos backups.
Uma cópia no mesmo disco não protege contra avaria/roubo.

## Recuperação consistente

1. Parar/isolar a instalação com falha. Não apagar nem substituir a base original.
2. Preparar uma **VM/Windows novo isolado**, mesma versão do instalador do backup.
3. No assistente inicial escolher recuperação, selecionar arquivo, chave privada e
   frase. O destino deve ser novo e sem os serviços da aplicação.
4. A rotina autentica/valida todos os membros antes de extrair. Restaura apenas
   nomes/caminhos permitidos para um diretório privado; nunca extrai paths livres.
5. Cria cluster/base novos, preserva contas, passwords, dados e chaves do arquivo.
   Compara integralmente as evidências do PostgreSQL restaurado com as do backup.
6. Mantém os serviços desativados e o diário. A informática confere o sistema e,
   antes de aprovar o arranque, verifica identidade, sequência e **todos os recibos
   de entradas já exportados para Android** depois do backup. Não reutilizar IDs,
   aumentar contadores sem prova nem deixar duas instalações com a mesma origem.
7. O botão administrativo de aprovação exige confirmação explícita dessa revisão.
   Só depois autoriza arranque local. Não expõe o publicador à rede automaticamente
   sem DNS/firewall já aprovados. Uma recuperação pode perder trabalho posterior ao
   backup: documentar a janela e recuperar os registos necessários.
8. Aplicar futuras atualizações pelo instalador normal, após validar a versão
   restaurada. Nunca iniciar código antigo numa base mais recente.

Rotação da chave de backup: preparar e guardar novo par com cerimónia autorizada,
validar restauro antes de substituir a chave **pública** de backup; conservar todas
as privadas antigas enquanto existirem cópias que as usem. Não regenerar a chave
Android para recuperar um backup. A rotação Android usa o procedimento assinado da
[Etapa B](etapa-b.md), conservando origem e histórico.

## Stock Android, sem Docker

A Etapa B permanece byte a byte nos seus serviços, interface, IndexedDB e formatos.
O publicador nativo usa o mesmo template NGINX: origem separada, HTTPS TLS1.2/1.3,
certificado de cliente obrigatório, CA e CRL, lista de redes/dispositivos,
CSP e apenas GET de ficheiros públicos. **Não há proxy para Django/PostgreSQL**.

A informática prepara um JSON junto dos quatro ficheiros abaixo, sem os colocar
no repositório/instalador:

```json
{
  "it_approved": true,
  "address": "192.168.10.20",
  "hostname": "stock.empresa.internal",
  "port": 8444,
  "clients": ["192.168.10.30/32"]
}
```

Ficheiros: `server-chain.crt`, `server.key`, `device-ca.crt`, `device-ca.crl`.
São exemplos fictícios, não parâmetros da empresa. Certificado SAN, DNS estável,
confiança Android, emissão/revogação por dispositivo, CRL atualizada e firewall
específica dependem da informática. Não criar port forwarding nem exceções globais.

“Manutenção → Preparar publicador” valida a configuração e `nginx -t`, instala o
serviço **desativado**. A ativação é uma ação posterior da informática, após
revisão de certificados, IP e firewall. Não altera políticas ou rede por conta própria.
Os comandos `vertente_device`, `vertente_receipts`, `vertente_sequence` continuam
na ferramenta privada da instalação, para a informática; a autorização dos papéis
Proprietário/Empregado mantém prova de posse e fingerprint independente.

Os ficheiros assinados anteriores permanecem verificáveis. Configuração, chaves,
origem, sequência, autorizações e recibos fazem parte da recuperação. Preferências
e encomendas offline continuam no Android e nos seus backups cifrados, não no PC.

## Compilar e distribuir — informática/desenvolvimento

1. Usar Windows descartável, Python de build, uv0.12.23, .NET10 SDK e NSIS3.
2. Obter/rever arquivos Python3.12 atualizado, PostgreSQL17 e NGINX Windows;
   validar SHA-256 por origem independente e guardar versões/licenças. Não instalar
   globalmente PostgreSQL ou Python durante o empacotamento.
3. Criar chave **ECDSA-P256 de pacotes**, distinta das chaves de backup e Android.
   Guardar privada cifrada fora do checkout; `GVA_PACKAGE_KEY_PASSWORD` é apenas
   injeção privada no processo de build, nunca parte do pacote.
4. Criar política pública JSON com `channel=release`, `public_key` PEM e
   `authenticode_sha256` (SHA-256 DER do certificado da empresa). Fixar essa política
   no anfitrião e guardar cópia na instalação. `synthetic` usa outra identidade e
   não permite base operacional; não se converte um canal no outro.
5. Passar `inputs.json` com `python`, `postgres`, `nginx`, cada qual com `archive`
   absoluto, `sha256`, `version` e `source` público sem credenciais.
6. Executar `scripts/native/build_package.py` com `--version`, `--minimum-version`,
   `--policy`, `--key`, `--inputs`, `--output` novo fora do checkout.
7. Compilar `deploy/native/installer.nsi` com `Version`, `Bundle`, `Channel` e assinatura Authenticode empresarial com signtool. Assinar também o
   desinstalador; timestamp e validação de cadeia/revogação são obrigatórios.
8. Verificar a assinatura final e publicar apenas instalador, versão, SHA-256 e
   instruções. Nunca publicar chave de assinatura, recuperação, certificados de
   clientes/servidor, configuração privada, backup ou credenciais.

Não há segredo predefinido nem confiança de produção guardada neste repositório.
A política de pacotes instalada não muda automaticamente: uma rotação do editor
ou da chave ECDSA exige transição autorizada/verificável pela informática, com a
chave anterior ainda disponível. Não substituir a política por uma recebida de
origem desconhecida para contornar uma recusa. Perda das chaves exige um processo
supervisionado de recuperação, não desativar verificações.

## Testes e limites de homologação

A CI compila instaladores **sintéticos não assinados**, com autoridade temporária,
nomes que indicam teste, SHA-256 e retenção14dias. Só carrega `artifacts/*.exe` e
hashes, nunca o diretório de trabalho ou chave temporária. O script de inputs de
CI não constitui uma aprovação de versões/fornecedores para produção.

A execução hospedada é Windows Server2025. Testa executáveis reais, serviços,
PG17, arranque/paragem, dados fictícios, atualização1.0→1.1, restauro e recusa de
versões antigas. Os testes unitários interrompem cada fase da atualização. A
regressão inclui Django/PostgreSQL, Chromium e PowerShell das etapas anteriores.
O [relatório](windows-native-validation.md) distingue resultados de pendências.

Ainda exige VM **Windows11 Pro limpa** e validação empresarial: reboot real
(incluindo interrupção de migração), sessão Windows sem privilégios, políticas
UAC/AppLocker/WDAC, eventuais runtimes VC++ exigidos pelo fornecedor, ACLs efetivas,
antivírus/SmartScreen, Authenticode real/timestamp/revogação, atualização com
migrações históricas representativas, falha de disco/espaço, destino empresarial,
recuperação após avaria e Android físico com mTLS/CRL/Wi-Fi real. Não declarar
instalação empresarial pronta até esses testes serem aprovados. Não foi instalado
nada em computadores pessoais/da empresa ou em bases existentes.
