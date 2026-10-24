# Instalação e configuração — procedimento preparado, não executado em produção

O PR da Etapa 4 não instala um servidor, não cria DNS/contas externas, não ativa
backups de produção e não publica dados reais. As instruções seguintes destinam-se
a uma instalação futura autorizada. Não as executar sobre a base privada que
conserva a pré-visualização pendente.

Para **Windows 11 local**, seguir [windows11.md](windows11.md), não este
procedimento Linux/servidor. A Etapa 5 reutiliza a imagem em Docker Desktop aprovado
pela informática, com projeto sintético separado e acesso apenas por loopback.

## Requisitos

- Linux mantido, Docker/Compose v2 para a imagem, ou Python 3.12 + uv 0.12.23.
- PostgreSQL **17**, armazenamento persistente monitorizado, TLS com certificado
  cuja CA e nome sejam verificados pelo cliente, e acesso apenas pela rede privada.
- Conta proprietária para migrações e outra de aplicação sem superuser, CREATEDB,
  CREATEROLE, propriedade do esquema ou privilégios de criação.
- Proxy HTTPS com domínio/certificado real. O backend fica em loopback/rede privada.
- Destino de backup separado do volume/disco principal, cifragem GPG, chave privada
  guardada noutro local e monitorização de falhas. Um volume Docker não é backup.
- Como ponto inicial para este catálogo: 2 vCPU, 4 GiB RAM e 30 GiB de disco,
  dimensionados novamente após medir documentos, concorrência e retenção. Não é
  um benchmark nem uma garantia de capacidade.

## Desenvolvimento isolado

Preserve `.env` e a base reservada. Crie uma base vazia sintética separada,
por exemplo `garrafas_stage4_synthetic`, com os mesmos parâmetros locais de ligação.
Não copie o Excel ou dados privados para essa base.

```sh
UV_CACHE_DIR=/tmp/uv-cache uv sync --frozen
DB_NAME=garrafas_stage4_synthetic uv run python manage.py migrate --noinput
DB_NAME=garrafas_stage4_synthetic uv run python manage.py create_user OPERADOR_SINTETICO --role admin
DB_NAME=garrafas_stage4_synthetic uv run python manage.py runserver 127.0.0.1:8000
```

A conta pede uma password no terminal; não existe password predefinida.
Nos testes Docker locais, o cliente PostgreSQL 17 pode vir do serviço já iniciado:

```sh
PG_TOOL_PREFIX='["docker","compose","exec","-T","-e","PGPASSWORD","db"]' \
DB_NAME=garrafas_stage4_synthetic DB_TEST_NAME=test_garrafas_stage4 \
uv run python manage.py test accounts inventory imports web tests.browser --noinput
```

Com clientes PostgreSQL 17 instalados no host, omita `PG_TOOL_PREFIX`. A suíte
cria bases descartáveis e testa restauro em bases novas com prefixo próprio;
a conta de testes precisa de CREATEDB e CREATEROLE para esses testes específicos.
Esses privilégios **não** pertencem à conta de aplicação de produção.

## Imagem e configuração de servidor

`deploy/Dockerfile` inclui Python 3.12, dependências congeladas, clientes oficiais
PostgreSQL 17 e GPG. Executa como UID/GID 10001 e não executa migrações no arranque.
A `.dockerignore` exclui segredos, bases, relatórios e ficheiros privados.
A imagem serve recursos públicos; os documentos são bytes privados no PostgreSQL.

```sh
docker build -f deploy/Dockerfile -t gestao-garrafas:VERSAO_REVISTA .
```

`deploy/production.env.example` é um modelo sem segredos. Copie-o para um caminho
externo, como `/etc/garrafas/application.env`, com modo 0600 e proprietário
adequado. Gere segredos próprios com um gestor seguro; não os passe em argumentos,
commits ou logs. As variáveis do processo têm precedência sobre o `.env` local,
que não é incluído na imagem.

| Variável | Configuração necessária |
| --- | --- |
| `APP_ENV`, `DJANGO_DEBUG` | `production`, `0`. |
| `DJANGO_SECRET_KEY` | Segredo aleatório próprio, conservado entre reinícios. |
| `DJANGO_ALLOWED_HOSTS` | Domínios concretos; sem wildcard. |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | Origens HTTPS concretas. |
| `TRUST_HTTPS_PROXY` | `1` apenas com proxy que substitui cabeçalhos e backend privado. |
| `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT` | Base escolhida e conta restrita; segredo injetado em runtime. |
| `DB_SSLMODE`, `PGSSLROOTCERT` | `verify-full` e caminho da CA montada no contentor. |
| `LOGIN_ACCOUNT_LIMIT`, `LOGIN_ADDRESS_LIMIT`, `LOGIN_WINDOW_SECONDS` | Por defeito 5/30 tentativas por 900 s; ajustar após avaliar o uso. |
| `LOGIN_TRUSTED_PROXY_ADDRESSES` | Endereços exatos do peer do proxy observados pelo backend; vazio ignora X-Forwarded-For. Não confiar em toda uma rede pública. |
| `BACKUP_ROOT`, `BACKUP_RETENTION_COUNT` | Destino privado separado; por defeito manter 14 arquivos completos. |
| `BACKUP_GPG_RECIPIENT`, `GNUPGHOME` | Fingerprint/identificador da chave pública e diretório GPG privado configurado. Obrigatórios para criar backups em produção. |
| `BACKUP_TIMEOUT_SECONDS` | Tempo máximo das ferramentas, por defeito 600 s. Ajustar para o tamanho real. |

HTTPS e cookies seguros são impostos pelo perfil de produção. O POST está limitado
a 1 MiB e assinaturas a 256 KiB. Não configurar `/media/` público. O proxy pode
aplicar também 1 MiB, como em `deploy/Caddyfile.example`. O browser abre PDFs pelo
endpoint autenticado; imprime com os controlos nativos do visualizador.

`deploy/compose.server.yaml` prepara apenas a aplicação, ligada a PostgreSQL
privado previamente configurado. O seu ficheiro privado de interpolação Compose,
fora do Git, define `DEPLOY_ENV_FILE`, `BACKUP_HOST_ROOT`, `GPG_HOST_HOME`,
`DB_CA_CERT_FILE` e opcionalmente `APP_PORT`. O destino de backups e o diretório
GPG devem pertencer ao UID 10001 e ter modo 0700. A chave privada GPG não deve
estar nesse contentor. Montar apenas a chave pública necessária à cifragem.
A CA é montada como read-only. Não existe contratação de serviços ou DNS neste
procedimento.

## Base, migrações e privilégios

1. O operador cria uma base **nova** e contas distintas de proprietário/aplicação.
   Use um canal administrativo seguro e password prompt/gestor de segredos; não
   existe SQL com passwords predefinidas no repositório.
2. Aplicar migrações usando a conta proprietária e configuração privada de
   migrações. Na imagem, executar `python manage.py migrate --noinput` num processo
   pontual com essa configuração. Não fazer do arranque web um migrador privilegiado.
3. Como proprietário, aplicar `deploy/app-role.sql` com `psql`, indicando a conta
   da aplicação. Exemplo com serviço libpq privado configurado pelo operador:

   ```sh
   PGSERVICE=garrafas_migrations psql -v app_role=garrafas_app -f deploy/app-role.sql
   ```

4. Executar o processo web com a conta **restrita**, nunca com a de migrações.
   Esta pode confirmar movimentos e criar documentos, mas não apagar o livro,
   documentos/auditoria, criar tabelas ou alterar migrações. Reaplicar/rever grants
   após novas migrações. Os testes exercitam esses privilégios numa base sintética.
5. Criar o primeiro Administrador explicitamente com `create_user`, via terminal
   e configuração da conta de aplicação. As contas seguintes são geridas pela
   interface com reautenticação do administrador.

PostgreSQL deve usar SCRAM, `hostssl` restrito à rede/conta certas, certificados
válidos e firewall. O esquema SQL não substitui essas configurações externas.
Não restaurar nem copiar a base reservada para experimentar este procedimento.

## Proxy, sessões e logs

`deploy/Caddyfile.example` é apenas um modelo. Requer domínio e DNS autorizados,
certificado e avaliação do servidor antes de ser ativado. O proxy substitui
X-Forwarded-Proto/X-Forwarded-For, limita o corpo e encaminha para loopback.
Em Docker, o backend pode observar o gateway interno em vez de 127.0.0.1:
confirmar esse endereço antes de preencher a lista de proxies confiáveis.
Nunca aceitar um cabeçalho de IP de um cliente público diretamente.

Login tem limite por identidade e endereço, partilhado entre workers PostgreSQL.
A espera termina após a janela configurada. Buckets contêm apenas HMAC e
contadores; avaliar retenção e limpeza periódica dos antigos pelo operador, sem
apagar auditoria. Sessões têm cookies HttpOnly, SameSite
Lax e Secure em produção, e expiram ao fechar o browser ou após oito horas.

O Gunicorn usa logs de método/caminho/estado/duração, sem query string, POST,
passwords ou imagens. Configure acesso e retenção desses logs. Debug fica desligado.
O controlo de acesso continua no servidor, incluindo PDFs, assinaturas e Excel.

## Verificar antes de qualquer ativação

- `manage.py check --deploy --fail-level WARNING`, esquema sem migrações em falta,
  e testes completos no PostgreSQL de avaliação.
- HTTPS/certificado e hostname reais; cookies, login, CSRF e proxy validados por
  fora da rede; PostgreSQL TLS verificado com a conta restrita.
- Manifesto e instalação em Android/iOS/browsers realmente utilizados. Os testes
  Chromium validam elegibilidade e toque, mas não substituem dispositivos físicos.
- PDF A4, nome, caixas/unidades, assinatura e impressão em impressoras do armazém.
- Capacidade, monitorização, alertas de falha de backup, recuperação num segundo
  sistema e responsáveis de operação/retencão definidos.
- Publicação inicial controlada, separada, revista e expressamente autorizada.
  A pré-visualização privada atual permanece sem publicação nesta entrega.

Código preparado, infraestrutura configurada e aplicação operacional são estados
distintos. Só depois destas verificações e das autorizações pode haver ativação.
