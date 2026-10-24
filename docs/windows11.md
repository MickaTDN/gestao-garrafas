# Etapa 5 — piloto local no Windows 11

Esta entrega prepara uma instalação **exclusivamente sintética** para avaliação.
Não instala nada no computador real, não publica a aplicação e não migra o Excel.
A base reservada à pré-visualização não é utilizada, copiada, montada ou alterada.
Entradas, saídas, inventários, relatórios e permissões usam os serviços existentes.

## Escolha técnica

Reutilizamos a imagem Linux da Etapa 4, Django 5.2 LTS, Python 3.12, Gunicorn e
PostgreSQL 17 através de **Docker Desktop com backend Linux**, preferencialmente
WSL2 aprovado pela informática. Não há alojamento externo nem um PostgreSQL
instalado como serviço Windows. Após preparar as imagens, o arranque diário não
faz downloads, builds ou migrações e não necessita de acesso à Internet.
A instalação inicial pode precisar de acesso autorizado a Docker Hub/PyPI ou de
imagens preparadas pela informática; isso não é alojamento da aplicação.

| Abordagem | Alterações e permissões | Decisão |
| --- | --- | --- |
| Docker Desktop/WSL2 | Reutiliza imagem, Gunicorn, PostgreSQL, backups e bibliotecas Linux. A infraestrutura precisa de autorização da informática. | Escolhida: menor alteração na aplicação. |
| Python/PostgreSQL nativos no Windows | Exige distribuição/manutenção de runtimes, um servidor WSGI compatível com Windows em substituição do Gunicorn, processos e backups específicos. Também depende da aprovação da informática. | Não implementada; mais componentes para manter. |

Se a informática não autorizar Docker/WSL2, **não há um instalador alternativo que
contorne a restrição**. É necessária uma decisão conjunta sobre outra plataforma.
As condições/licenciamento do Docker Desktop na empresa também devem ser verificadas
pela informática; não é criada conta nem contratada licença automaticamente.

## O que a informática tem de aprovar primeiro

| Ação | Quem e porquê |
| --- | --- |
| Windows 11 cliente de 64 bits, RAM instalada ≥16 GB | Diagnóstico de leitura; não altera o sistema. Recomendam-se 40 GB livres; exige-se pelo menos 20 GB para preparar o piloto. |
| Virtualização no firmware, WSL2/Virtual Machine Platform/kernel e eventuais reinícios | Informática, com privilégios administrativos quando exigidos pelo Windows. Os scripts não ativam funcionalidades nem executam `wsl --install`. |
| Instalação/atualização do Docker Desktop e Compose | Informática. Docker Engine ≥28 e Compose ≥2.24; backend Linux. Aprovar distribuição, licença, recursos e atualização. |
| Acesso autorizado do utilizador ao Docker Desktop/named pipe | Informática; eventual associação a grupos/reinício de sessão. Acesso ao Docker tem poderes elevados sobre contentores; não é uma fronteira de segurança contra esse operador. |
| Execução do pacote PowerShell revisto | A informática valida origem/integridade e, se a política exigir, assina os scripts/aprova o editor. Não se usa `ExecutionPolicy Bypass`, `Set-ExecutionPolicy`, elevação ou desbloqueio automático. |
| Downloads e certificados de proxy corporativo | Informática configura confiança e acessos permitidos. Não ignorar erros TLS nem usar flags para desativar certificados. |
| Firewall/DNS/HTTPS para Android futuro | Fora do piloto. Nenhuma regra de firewall, encaminhamento de router ou porta de Internet é criada. |

O utilizador atual **não precisa de ser promovido a administrador** para os passos
diários depois de a informática disponibilizar os pré-requisitos e permissões
necessários. Se um passo for bloqueado, parar e pedir essa autorização; não tentar
executar à força ou usar ferramentas portáteis para contornar a política.

## Instalação, passo a passo, depois da aprovação

1. Obter o código revisto do PR/versão aprovada. Guardar numa pasta local NTFS do
   utilizador, fora de OneDrive/partilhas/pastas temporárias, e conservar essa pasta.
   Não incluir Excel, dados reais ou ficheiros privados no checkout.
2. Abrir o Docker Desktop e aguardar pelo backend Linux. A informática decide os
   recursos WSL2: como referência, 4–6 GB para o conjunto inicial, deixando memória
   suficiente para Windows; não alteramos `.wslconfig` automaticamente.
3. Na pasta `scripts\windows`, abrir **Diagnostico.cmd**. É só leitura e mostra
   códigos de requisitos. Se a política do PowerShell bloquear o próprio script,
   entregar a mensagem à informática; não alterar a política.
4. Com todos os requisitos satisfeitos, abrir **Instalar.cmd**. O processo cria
   uma pasta privada em `%LOCALAPPDATA%\GestaoGarrafas\Piloto`, com ACL apenas do
   utilizador e SYSTEM, segredos aleatórios, manifesto e identificador único.
   Não substitui uma pasta preexistente desconhecida nem a `.env` do repositório.
5. A instalação constrói a imagem, inicia um PostgreSQL 17 novo, valida um marcador
   exclusivo, aplica migrações nessa base e reutiliza os grants da Etapa 4.
   Cria **três referências fictícias**, uma pessoa fictícia e saldos iniciais
   identificados como demonstração. Não cria lotes Excel nem atribui setores.
6. O assistente oferece criar o primeiro administrador. Escolher um identificador
   próprio e introduzir/confirmar uma password no terminal, sujeita à validação
   existente. Não existe conta/password predefinida e a password não vai em
   argumentos, ficheiros de instalação ou logs. Pode fazê-lo depois com
   **CriarUtilizador.cmd** na pasta privada do piloto.
7. São criados atalhos no ambiente de trabalho do utilizador: **Gestao de Garrafas
   - Piloto**, **Parar Gestao de Garrafas** e **Diagnostico Gestao de Garrafas**.
   São ficheiros `.lnk` por utilizador, não serviços ou tarefas privilegiadas.

Não existe atualizador automático. Conservar a versão revista do pacote; uma
atualização futura exige backup, avaliação de compatibilidade e validação pela
informática. Não usar alterações de ficheiros/hashes para forçar uma atualização.

A porta inicial é **8765**, em `http://127.0.0.1:8765/`. Se estiver ocupada, não é
terminado nenhum processo. A informática pode preparar outra porta, executando
o script aprovado `Instalar.ps1 -Port 8766`, antes de criar o piloto. Não editar
manualmente a configuração para publicar noutras interfaces.

Se o ambiente de trabalho estiver protegido e o atalho falhar, os dados permanecem
preparados; a informática pode criar o atalho por utilizador. Os `.cmd` instalados
na pasta privada continuam disponíveis. Não copiar apenas os segredos para um
checkout diferente nem mover a pasta preparada.

## Uso diário

- **Iniciar:** abrir o Docker Desktop, aguardar pelo motor e usar o atalho do piloto.
  O script valida o projeto/configuração, inicia os contentores existentes, verifica
  o marcador da base, a saúde da aplicação e a resposta HTTP local, e só depois abre
  o navegador. Não faz migrações, build ou pull de imagens nesta ação.
- **Parar:** usar o atalho de paragem. Dá até 45 segundos à aplicação/PostgreSQL e
  preserva volumes, documentos, backups e segredos. A paragem permanece disponível
  quando o diagnóstico de memória/disco/CIM não pode ser concluído.
- **Reabrir:** usar o atalho novamente. Fechar a janela do navegador não para a
  aplicação. O computador e o Docker Desktop precisam de estar ligados; suspensão,
  encerramento do Windows ou saída do Docker interrompem a disponibilidade.
- Não é criado arranque automático, serviço Windows, tarefa agendada ou início
  de sessão automático. Isso exige uma decisão operacional separada.

Documentos privados continuam em PostgreSQL, com as proteções e checksums da
Etapa 4. A interface e os movimentos não foram substituídos por uma versão offline.

## Persistência e isolamento

Cada preparação usa projeto `gg-win5-<identificador aleatório>`, rede de dados
interna e volumes próprios `pilot_database` e `pilot_backups`. O PostgreSQL **não
publica qualquer porta no Windows**; só os contentores do projeto lhe acedem.
A aplicação tem ainda uma bridge própria para encaminhar a porta HTTP, publicada
somente em **127.0.0.1**. Não se liga a redes/volumes externos ou a um Docker remoto.
Os scripts recusam `DOCKER_HOST` externo e contextos que não usem um named pipe
local do Docker Desktop. Nenhum comando usa o projeto Compose de desenvolvimento.

O perfil `config.windows_local` exige modo sintético explícito, hostname interno
`db` e nome fixo `garrafas_windows_synthetic`. Uma base com tabelas mas sem o
marcador esperado não é adotada. O utilizador web da base é restrito; o segredo
do proprietário só é montado no PostgreSQL e no processo pontual de inicialização/
recuperação, nunca no servidor web permanente.

HTTP e cookies sem Secure são uma exceção **deste perfil loopback**; debug está
desligado, hosts aceites são apenas localhost/127.0.0.1, não há origens Wi-Fi ou
proxies confiáveis. O perfil `production` mantém HTTPS/cookies seguros. Esta
configuração não deve ser publicada na rede nem usada como instalação oficial
com dados reais sem nova avaliação e autorização.

A ACL Windows protege os ficheiros do utilizador. No contentor, segredos são
montados só para leitura. O Docker Desktop/administrador do computador continua
privilegiado; o isolamento não promete proteção contra quem controla esse backend.

## Backup e recuperação de falhas

O volume Docker **não é backup**. Remover volumes, repor o Docker Desktop para
valores de fábrica, desinstalar com limpeza de dados ou perder o disco pode apagar
as bases. Não executar `down -v`, `volume rm` ou `system prune` sobre o piloto.
Os scripts do utilizador não contêm comandos de remoção/reset.

**Backup manual do piloto:** com a aplicação ligada, abrir **Backup.cmd** na pasta
privada. Escolher uma pasta nova num suporte local NTFS autorizado; uma pasta
existente não é substituída. Usa o comando de backup sintético da Etapa 4 e copia
os arquivos para essa pasta com ACL privada. A cópia noutro diretório do mesmo
disco não protege contra perda do computador. O piloto tem apenas dados fictícios;
os seus arquivos não são apresentados como backups de produção nem como cifragem
real configurada. Dados reais exigiriam a política de cifragem/chaves/destino e
agendamento aprovado descrita em [recovery.md](recovery.md).

**Restauro de avaliação:** abrir **Recuperar.cmd**, escolher um backup `.tar.gz`
próprio deste piloto, uma pasta **nova** e uma porta livre diferente, como 8766.
É criado outro projeto/volume PostgreSQL vazio; o arquivo é verificado e restaurado
nesse destino. São verificados os documentos e o marcador passa a identificar a
cópia; stock e histórico anteriores não são reescritos. A origem e os seus atalhos
não são substituídos. Abrir `Iniciar.cmd` na pasta nova e conferir a cópia antes de
pedir à informática qualquer mudança dos atalhos. As contas e passwords da
aplicação restaurada mantêm-se; sessões antigas podem exigir novo login.

O comando recusa arquivos que não sejam backups sintéticos deste piloto, pasta
existente e base de destino que já contenha tabelas. Uma falha conserva a origem e
a tentativa nova para diagnóstico; não faz rollback destrutivo nem tenta limpar
bases. Apenas aceitar backups próprios de origem confiável: checksum não autentica
um arquivo recebido de terceiros. `.gpg`/dados reais/restauro de produção seguem
outro procedimento, não este assistente.

| Sintoma | Ação segura |
| --- | --- |
| Docker ausente/WSL desativado/acesso negado | Diagnóstico e informática; sem elevação ou instalação automática. |
| Política PowerShell bloqueia | Pedir revisão/assinatura/autorização; não alterar execução nem desbloquear à força. |
| Porta ocupada | Não terminar processos; informática escolhe outra porta antes da preparação. |
| Build falha por rede/certificado | Verificar proxy/CA com a informática; não desativar TLS. Repetir a instalação explícita preserva segredos e dados. |
| Instalação interrompida com manifesto válido | Reabrir `Instalar.cmd` na pasta preparada; migrações são idempotentes e a semente só é aplicada uma vez. |
| Pasta parcial sem manifesto ou segredo em falta | Não regenerar chaves/passwords nem apagar a pasta/volumes. Entregar à informática para diagnóstico. |
| Arranque sem imagem local | A ação não a descarrega implicitamente; informática retoma a instalação aprovada. |
| Aplicação indisponível após suspensão/reinício | Iniciar Docker Desktop e usar o atalho; se necessário parar e iniciar, sem eliminar volumes. |
| Configuração/manifesto alterados | Execução recusada; não editar hashes para forçar aceitação. Rever a cópia com a informática. |
| Base/documento corrompido ou perda de disco | Preservar origem, usar backup próprio num destino novo e conferir com a informática. |

Conservar também a pasta privada de configuração/segredos em armazenamento
protegido aprovado pela informática. Não enviar segredos, relatórios, assinaturas
ou a base para issues/PRs. O diagnóstico mostra códigos; não recolhe configurações
Docker completas, passwords, SQL, assinaturas ou ficheiros privados.

## Android por Wi-Fi — arquitetura preparada, acesso ainda fechado

O Django já é responsivo e PWA. O Android futuro usará o mesmo servidor e a mesma
base, não uma segunda aplicação ou cópia de stock. Para o ativar serão necessários:

1. Aprovação de informática, rede Wi-Fi/sub-rede e dispositivos autorizados.
2. Endereço/DNS interno estável e proxy HTTPS com certificado confiado pelos
   dispositivos; não apresentar avisos TLS como algo a ignorar.
3. Regras mínimas de firewall apenas para HTTPS dessa rede, sem abrir PostgreSQL,
   Docker API ou qualquer encaminhamento para Internet/router.
4. Perfil HTTPS com hosts/CSRF/cookies/proxy revistos e testes de permissões,
   confidencialidade, PWA e concorrência. O perfil loopback desta etapa não serve.
5. Disponibilidade, energia, backups e responsáveis operacionais definidos.

Nenhum destes passos é executado automaticamente. `127.0.0.1` no telefone aponta
para o telefone, não para o PC. Sem ligação ao servidor não há confirmação de
entradas, saídas ou inventários. **Stock Vendas offline não faz parte desta etapa.**

## Validação e limites

Ver [validation.md](validation.md). A aplicação é testada numa instância PostgreSQL
nova, sem sequer usar a ligação à base reservada. Há testes de PowerShell 5.1 num
runner Windows descartável, incluindo ACLs e atalhos, com Docker simulado; e um
ensaio real do payload Compose em contentores Linux novos para instalação,
movimento/PDF/assinatura, paragem/rearranque, backup, restauro separado e recusa de
sobrescrita. O runner Windows CI não é um PC Windows 11 empresarial com WSL2.

Ainda falta uma aceitação presencial, autorizada pela informática, num Windows 11
real: Docker Desktop/WSL2 e políticas, proxy/CA, caminhos do utilizador, reinício/
suspensão, proteção do disco, abertura/ impressão, cópia externa e restauro.
Nada foi instalado no computador do utilizador e não é declarada operação oficial.
