# Validação da primeira etapa

Executada na máquina de desenvolvimento com Python 3.12, as versões resolvidas
em `uv.lock`, PostgreSQL 17 via `compose.yaml` e Chromium local.

| Verificação | Resultado |
| --- | --- |
| `uv lock --check` e instalação congelada | Aprovados. |
| `ruff check .` | Aprovado. |
| `manage.py check` | Sem problemas. |
| `makemigrations --check --dry-run` | Nenhuma alteração de modelo sem migração. |
| `migrate --noinput` em PostgreSQL | Migrações aplicadas, incluindo configuração de localizações e triggers. |
| `manage.py test accounts inventory imports web tests.browser --noinput` | **57 testes executados e aprovados; nenhum ignorado.** |
| Recursos estáticos e `check --deploy --fail-level WARNING` no perfil de produção | Aprovados; não constituem um deploy. |
| Arranque real da aplicação | Login e CSS com HTTP 200; configuração privada inacessível por HTTP. |
| Preparação real do anexo, repetida | Lote único e proveniência preservados; nenhum catálogo, saldo ou movimento operacional publicado. |
| Reinício do PostgreSQL | Lote privado de preparação conservado no volume. |
| `git diff --check` | Aprovado. |

Os testes exercitam autenticação/CSRF, ambos os perfis, pesquisa e paginação,
validações de localização e setor, snapshots de quantidades/capacidade/nome,
rollback integral, duas saídas simultâneas sem exceder stock e proteção de
movimentos confirmados também por SQL direto. Os casos de importação usam Excel
sintético, incluindo sinais invertidos, vazios, duplicados, cache ausente,
divergências, dados órfãos e cabeçalhos inválidos. O navegador executa o fluxo de
login/consulta em dimensões de computador e telemóvel.

A inspeção do anexo real produziu exceções que exigem reconciliação. O comando
termina deliberadamente com estado 1 após guardar o relatório e o lote em
análise. Esse resultado não é uma importação aprovada. O relatório e os dados
individuais ficam fora do Git; não são fixtures nem documentação versionada.

A configuração de CI foi criada, mas não foi executada no GitHub nesta tarefa.
Não foram feitos deploy, restauro numa máquina cloud nova, importação definitiva,
teste de backups de produção ou testes das interfaces operacionais ainda por
implementar. As próximas entregas devem manter estes casos e acrescentar testes
aos fluxos definidos no [roadmap](roadmap.md).
