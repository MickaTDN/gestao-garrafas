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

## Validação da segunda etapa

O conjunto completo `manage.py test accounts inventory imports web tests.browser
--noinput` executou **131 testes, todos aprovados e sem casos ignorados**, em
PostgreSQL. Inclui os testes anteriores, publicação sintética reconciliada,
fusão de duplicados com proveniência, preservação de sinais, documentos e
observações, saldos iniciais desconhecidos, idempotência, rollback e rejeição de
prévias alteradas ou desatualizadas. Inclui ainda os formulários de catálogo,
as permissões de ambos os perfis, proteção de stock contra campos forjados,
relações protegidas e confirmação explícita/CSRF na publicação.

O reforço inclui confirmações simultâneas de uma ou duas prévias do mesmo lote,
publicação concorrente com criação de catálogo e desativação apenas com stock
exatamente zero. A desativação é recusada também por chamada direta ao serviço
e por pedido HTTP forjado; o stock é novamente verificado depois de abrir a
página de confirmação. Os testes confirmam a reativação, a preservação do
histórico e a exclusão de referências inativas do stock normal e do painel.

A criação manual também é testada contra designações equivalentes por espaços
e maiúsculas/minúsculas, incluindo referências inativas e outras localizações.
Os casos verificam a apresentação de todas as correspondências, a preservação
dos registos históricos, a confirmação de reativação e a serialização de duas
criações simultâneas. Um teste de importação sintética confirma que referências
históricas com o mesmo nome em localizações diferentes continuam separadas.

Os dois testes de navegador usam Chromium: consulta em dimensões de computador
e telemóvel e criação/edição de referência por administrador em telemóvel.
Ruff, verificação Django, ausência de migrações pendentes, recolha de recursos
estáticos no perfil de produção e `check --deploy --fail-level WARNING` passaram.

A pré-visualização real foi preparada e verificada individualmente contra a
fonte oficial, mantendo contagens iniciais ausentes como desconhecidas. As
decisões, valores individuais e os relatórios reais permanecem privados, fora
do Git. A fonte e o destino continuam ligados à impressão digital revista.
Até à confirmação explícita dessa prévia, o catálogo e o histórico operacionais
permanecem sem dados reais. Este estado não deve ser descrito como importação
real concluída; a publicação produz o seu próprio relatório de validação.

Os movimentos operacionais da terceira etapa não foram implementados. Os
resultados de CI no GitHub devem ser consultados separadamente dos resultados
locais acima.
