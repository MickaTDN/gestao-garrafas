# Decisão 5 — piloto Windows 11 local

Data: 2026-10-24 (Europe/Lisbon).

## Decisão

Reutilizar a imagem Linux/Django/Gunicorn da Etapa 4 com PostgreSQL 17 no Docker
Desktop/WSL2 aprovado pela informática. Uma stack nativa Windows precisaria de
outro WSGI/process manager, distribuição de Python/PostgreSQL/clientes e rotinas
operacionais próprias. Docker exige uma autorização inicial real, mas reduz as
alterações na aplicação e conserva o ambiente já validado.

A branch de preparação indicada apontava para o mesmo commit de main e não tinha
um script diferente publicado. Foi reutilizada, criando os assistentes sem
alterar serviços de entradas, saídas, inventários ou geração de documentos.

## Fronteiras

- Piloto só com dados fictícios, projeto/volumes/rede/segredos próprios; a base
  reservada à pré-visualização não é ligada, copiada ou adotada.
- Reutiliza migrações e `deploy/app-role.sql`. O processo separado de instalação
  tem o segredo de owner; o servidor web usa a conta restrita, sem esse segredo.
- Perfil específico recusa bases/servidores externos e exige marcador de instância.
  Não há importação de Excel ou contas/passwords predefinidas.
- Aplicação publicada apenas em 127.0.0.1. PostgreSQL não publica portas. Uma
  bridge web permite o encaminhamento local; a rede de dados continua interna.
- HTTP só no perfil loopback sintético; produção conserva HTTPS. Wi-Fi depende
  de proxy/certificados/firewall/hosts/CSRF revistos e autorização posterior.
- Política PowerShell, virtualização, WSL, Docker, grupos, licenciamento e firewall
  ficam com a informática. Não existe bypass, UAC/RunAs ou instalação automática.
- Pasta privada com ACL por utilizador/SYSTEM e segredos em ficheiros, fora do Git.
  O backend Docker/administrador da máquina mantém os seus poderes privilegiados.

## Ciclo de vida

Instalar é uma ação explícita que constrói a imagem, aplica migrações e cria a
semente sintética uma única vez. Repetir preserva segredos/stock e não duplica
saldos. Arrancar valida o estado e HTTP antes de abrir o browser, sem build,
download ou migração implícita. Parar conserva todos os volumes e fica disponível
mesmo se o diagnóstico de recursos estiver limitado.

Backup reutiliza o mecanismo da Etapa 4 no modo sintético. Recuperar cria outra
stack vazia, verifica e restaura apenas um backup do piloto, conserva a origem e
não muda os seus atalhos. Recusa destinos não vazios. A limpeza de projetos
aleatórios só existe no ensaio CI, não nos assistentes do utilizador.

A imagem normaliza permissões de leitura do código público e prepara o diretório
de backups para UID 10001. Continua com código root-owned e execução web sem root;
isto evita que a umask do checkout impeça leitura, sem dar escrita ao processo web.

## Validação e dependências reais

PowerShell/ACL/atalhos são testados num runner Windows com Docker simulado. O
payload Linux real é exercitado com novos volumes, confirmando persistência e
recuperação. Estes testes não provam uma instalação física Windows 11/WSL2.
A aceitação nesse PC depende de informática, proxy/CA, políticas de execução,
partilha de ficheiros do Docker Desktop, energia/disponibilidade e backup externo.
Não se criam serviços externos nem se considera o piloto uma publicação oficial.
