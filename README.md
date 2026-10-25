# Gestão Vertente Aveludada

Aplicação web baseada no protótipo V3: **Django 5.2 LTS,
Python 3.12 e PostgreSQL 17**, com o mesmo estilo visual em computador e telemóvel.
As decisões estão em [docs/architecture.md](docs/architecture.md) e os requisitos
aprovados e etapas em [docs/roadmap.md](docs/roadmap.md).

O projeto inclui autenticação e dois perfis, migrações da base permanente,
painel e consultas de stock/fichas/histórico. A segunda etapa acrescenta gestão
de referências, localizações e setores e importação reconciliada, com
pré-visualização e confirmação explícita antes da publicação. O processo está
descrito em [docs/stage2.md](docs/stage2.md).

A terceira etapa acrescenta entradas, saídas, rascunhos próprios, inventários
parciais/completos, transferências e correções relacionadas, com conferência e
confirmação atómicas. Consulte [docs/stage3.md](docs/stage3.md). A Etapa 4
acrescenta PDFs privados imutáveis, assinatura desenhada, exportação XLSX,
PWA, gestão de utilizadores, proteção de login e backups/restauro sintéticos.
Os procedimentos estão em [docs/installation.md](docs/installation.md) e
[docs/recovery.md](docs/recovery.md). Infraestrutura e publicação reais continuam
separadas do código.
A aplicação ainda não é um registo operacional oficial. A publicação inicial
controlada dos dados reais continua a exigir autorização separada.

**Se existe uma pré-visualização privada pendente, use outra base de desenvolvimento.**
Não execute as migrações ou operações seguintes na base reservada à publicação.
Os testes usam exclusivamente dados sintéticos; nunca reutilize dados privados
como fixtures nem publique um lote apenas para experimentar os formulários.

## Windows 11 — piloto local (Etapa 5)

Use o [guia Windows](docs/windows11.md), depois de a informática aprovar Docker
Desktop/WSL2 e a execução dos scripts. `scripts/windows/Diagnostico.cmd` só verifica
pré-requisitos; `Instalar.cmd` prepara uma stack nova com dados fictícios e atalhos
por utilizador. PostgreSQL não publica portas e a aplicação fica em 127.0.0.1.
Não usa a `.env`, o Compose de desenvolvimento ou a base reservada à importação.
Não executar instruções Linux ou alterar políticas do Windows para contornar
bloqueios. Nada foi instalado num computador real por esta entrega.

## Melhorias da Etapa A

Entradas, Saídas e Inventário abrem diretamente o formulário. Mantêm-se a
conferência, confirmação atómica, auditoria e dados das instalações existentes.
Veja [o âmbito e as decisões](docs/etapa-a.md), os
[originais e ícones Copo com Vida](static/branding/README.md) e a
[atualização do piloto sem apagar dados](docs/windows11.md#atualização-da-etapa-a-num-piloto-existente).

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
exceções. A reconciliação usa decisões privadas ligadas ao lote e produz uma
pré-visualização por referência. Só depois de a rever deve ser confirmada a sua
publicação. Alterar a fonte, as decisões ou o destino invalida a confirmação
anterior. Um relatório criado não é uma publicação de stock.

Inventários iniciais vazios permanecem desconhecidos. A quantidade necessária
para conciliar o saldo oficial é identificada como inferida; nunca aparece como
uma contagem confirmada de zero. Texto autorizado como anotação conserva a
origem e a decisão de ausência de impacto. Números de documento não criam
pessoas fictícias. `openpyxl` não recalcula fórmulas; caches ausentes são
assinaladas. Não se inventam datas, horas, setores, capacidades ou histórico que
não conste da fonte. As outras folhas não são importadas.

`.env`, Excel, bases SQLite, relatórios, backups e documentos privados são
ignorados pelo Git. PDFs e assinaturas ficam em bytes privados PostgreSQL,
com leitura autenticada e checksum; não têm URLs públicas de media.
Não adicione dados reais a fixtures, migrações, screenshots ou exemplos.

## Testes e verificações

A suíte utiliza exclusivamente dados sintéticos e uma base de testes separada:

```sh
uv run ruff check .
uv run python manage.py check
uv run python manage.py makemigrations --check --dry-run
PG_TOOL_PREFIX='["docker","compose","exec","-T","-e","PGPASSWORD","db"]' \
DB_NAME=garrafas_stage4_synthetic DB_TEST_NAME=test_garrafas_stage4 \
uv run python manage.py test accounts inventory imports web tests.browser --noinput
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
Os testes criam e eliminam utilizadores e referências sintéticas numa base de testes;
verificam também assinatura por rato/toque, documentos, exportação e política PWA.
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
