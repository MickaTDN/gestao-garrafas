# Gestão de Garrafas

Primeira etapa da aplicação web baseada no protótipo V3: **Django 5.2 LTS,
Python 3.12 e PostgreSQL 17**, com o mesmo estilo visual em computador e telemóvel.
As decisões estão em [docs/architecture.md](docs/architecture.md) e os requisitos
aprovados e etapas em [docs/roadmap.md](docs/roadmap.md).

Já existem autenticação e dois perfis, migrações da base permanente, painel,
consulta de stock/fichas/histórico, preparação auditável do Excel e serviço de
confirmação transacional testável. Os formulários de operações, publicação da
importação, PDFs, assinatura e PWA serão desenvolvidos nas etapas seguintes.
As páginas dessas áreas identificam o estado de implementação.

## Executar em desenvolvimento

Requisitos: Python 3.12, [uv](https://docs.astral.sh/uv/) e Docker com Compose v2.
Use o checkout existente; não é necessário criar um worktree. Na raiz do projeto:

```sh
python3 scripts/bootstrap.py
uv sync --frozen
docker compose up -d --wait db
uv run python manage.py migrate --noinput
uv run python manage.py create_user o-seu-utilizador --role admin
uv run python manage.py runserver 127.0.0.1:8000
```

A criação da conta pede uma palavra-passe no terminal, valida-a e guarda apenas o
hash. Para o segundo perfil use `--role viewer`. Não há conta predefinida nem
registo público. Em automação, `create_user --password-env NOME_DA_VARIAVEL` lê uma
variável injetada, sem imprimir o valor. Nunca passe passwords em argumentos.

O bootstrap gera `.env` com segredos aleatórios locais e permissões restritas,
preservando um ficheiro existente. Não há dados de catálogo reais nas migrações:
apenas as quatro localizações e os 27 setores aprovados. A base começa vazia.

O volume Docker `postgres_data` conserva os dados entre reinícios. Pode parar e
reiniciar com `docker compose stop db` / `docker compose up -d --wait db`.
`docker compose down` conserva o volume; adicionar `-v` elimina a base. O volume
local não é backup nem garantia de restauro entre máquinas cloud. Não há
configuração de produção ou publicação automática nesta entrega.

Para uma experiência local sem Docker, `DB_ENGINE=sqlite` é uma opção explícita
de desenvolvimento, após executar o bootstrap. Não deve ser usada para produção
nem para validar concorrência ou os triggers PostgreSQL.

## Excel e privacidade

O anexo atualizado é lido fora do checkout e não é incluído no Git. O protótipo
HTML conservou as interações de demonstração e passou a usar apenas três
referências fictícias. O plano funcional contém exemplos anonimizados e descreve
uma fotografia histórica, não uma seed atualizada. O histórico Git anterior não
foi reescrito.

Para analisar um ficheiro, indique caminhos privados fora de qualquer checkout:

```sh
uv run python manage.py inspect_stock_excel /caminho/privado/stock.xlsx \
  --report /caminho/privado/inspecao.json
```

Acrescente `--stage` para guardar um lote e as linhas originais na área de
preparação da base, sem criar referências operacionais nem publicar stock ou
movimentos. O SHA-256 impede duplicação do mesmo ficheiro. O relatório não é
sobrescrito; use outro nome numa nova inspeção. Não execute esta operação em CI.

O relatório preserva fórmulas, caches, valores, tipos, coordenadas, cabeçalhos e
exceções. Valores vazios e texto não numérico exigem decisões explícitas antes
da migração definitiva. `openpyxl` não recalcula fórmulas; caches ausentes são
assinaladas. Não se inventam datas, horas, setores, capacidades ou histórico que
não conste da fonte. As outras folhas não são importadas automaticamente.

`.env`, Excel, bases SQLite, relatórios, backups e documentos privados são
ignorados pelo Git. PDFs e assinaturas não terão URLs públicas de media.
Não adicione dados reais a fixtures, migrações, screenshots ou exemplos.

## Testes e verificações

A suíte utiliza exclusivamente dados sintéticos e uma base de testes separada:

```sh
uv run ruff check .
uv run python manage.py check
uv run python manage.py makemigrations --check --dry-run
uv run python manage.py test accounts inventory imports web --noinput
```

O PostgreSQL deve estar disponível para verificar bloqueios, concorrência e
imutabilidade também por SQL. Execute apenas uma suíte por base de testes;
processos independentes podem definir nomes distintos em `DB_TEST_NAME`.

Para verificar também o fluxo num navegador em computador e telemóvel:

```sh
uv run playwright install chromium
uv run python manage.py test tests.browser --noinput
```

Se Chromium já estiver instalado, a suíte usa-o; pode indicar `CHROMIUM_PATH`.
Em Linux sem dependências gráficas, use `playwright install --with-deps chromium`.
O teste cria e elimina utilizadores e referências sintéticas numa base de testes.
O workflow [CI](.github/workflows/ci.yml) executa as verificações em PostgreSQL,
o navegador e a configuração de produção.

Para verificar os recursos estáticos e as opções de segurança de produção:

```sh
APP_ENV=production DJANGO_DEBUG=0 uv run python manage.py collectstatic --noinput
APP_ENV=production DJANGO_DEBUG=0 uv run python manage.py check --deploy --fail-level WARNING
```

Este comando não faz deploy nem prova disponibilidade de HTTPS ou backups.
Produção requer segredos próprios, domínio/CSRF configurados, PostgreSQL com TLS,
proteção de login, permissões mínimas e restauro de backup comprovado, conforme
a arquitetura. As instruções locais não devem ser usadas como configuração final.
