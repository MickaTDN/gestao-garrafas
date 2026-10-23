# Segunda etapa — catálogo e importação reconciliada

Esta entrega desenvolve a gestão de referências, localizações e setores e o
processo de publicação do histórico disponível na folha `Stock`. Não implementa
os movimentos operacionais da terceira etapa. Os requisitos originais continuam
registados no [roadmap](roadmap.md).

## Separar preparação, revisão e publicação

O comando de inspeção da primeira etapa continua a ler o ficheiro em modo apenas
de leitura e a guardar proveniência no lote de preparação. Uma inspeção com
exceções não desaparece nem é silenciosamente transformada numa importação
aprovada.

O processo de reconciliação recebe o lote e um conjunto de decisões privadas.
Essas decisões não pertencem a fixtures, migrações, documentação versionada ou
corpos de Pull Requests. Podem identificar uma anotação sem impacto, distinguir
um número de documento de uma pessoa e declarar o tratamento do inventário
inicial desconhecido.

A API de serviço é:

```python
from imports.reconciliation import build_preview, publish_preview

preview = build_preview(batch_id, resolutions, actor=administrator)

# Só depois de apresentar e rever esta pré-visualização:
result = publish_preview(
    preview.pk,
    actor=administrator,
    confirmation_token=preview.confirmation_token,
)
```

As duas operações exigem um administrador. Criar a pré-visualização não publica
referências nem movimentos. A publicação exige confirmação explícita e valida
que a fonte, as decisões e o destino continuam a corresponder à pré-visualização.
Uma alteração obriga a gerar e rever uma nova pré-visualização. Um token não deve
ser registado em logs nem guardado em documentação pública.

O contrato de decisões inclui os seguintes campos:

| Campo | Finalidade |
| --- | --- |
| `schema_version` | Versão do contrato de reconciliação. |
| `expected_total` | Total oficial esperado, fornecido na configuração privada. |
| `expected_references` | Número esperado de referências únicas. |
| `blank_opening_policy` | Política explícita `unknown_derived` para contagens iniciais ausentes. |
| `annotations` | Decisões por coordenada, com valor original e justificação. |
| `document_headers` | Decisões por coluna, com valor original, número de documento e justificação. |

Estes valores são específicos do lote. Não há totais reais, coordenadas de
exceções reais ou números de documentos reais fixados no código.

## Usar os comandos e a interface

Depois da inspeção com `--stage`, um administrador pode criar a pré-visualização
com caminhos privados fora de qualquer checkout:

```sh
uv run python manage.py preview_stock_import ID_DO_LOTE \
  --decisions /caminho/privado/decisoes.json \
  --actor UTILIZADOR_ADMINISTRADOR \
  --report /caminho/privado/previsualizacao.json
```

O resumo enviado para o terminal contém apenas agregados. O relatório detalhado,
com valores individuais e decisões, deve permanecer privado. O relatório tem de
ser apresentado e revisto antes da operação seguinte:

```sh
uv run python manage.py publish_stock_import UUID_DA_PREVIA \
  --actor UTILIZADOR_ADMINISTRADOR \
  --confirmation TOKEN_DA_PREVIA \
  --report /caminho/privado/publicacao.json
```

Não execute o segundo comando enquanto a pré-visualização ainda aguarda
confirmação. A opção `--confirmation` identifica a pré-visualização explicitamente
aceite; não torna uma pré-visualização inválida ou desatualizada publicável.
Nenhum destes comandos deve ser incluído no arranque automático do ambiente.

Na interface, `/importacoes/` apresenta as pré-visualizações ao administrador.
A página `/importacoes/<uuid>/` mostra os totais e a reconciliação detalhada.
Publicar usa POST e exige a opção de confirmação, a introdução do total exibido
e o token correspondente. O perfil Consulta não pode aceder a esta área.

## Contagens iniciais desconhecidas

Um campo vazio no inventário inicial significa que a contagem da fonte não está
disponível. A importação mantém `OpeningBalance.quantity` nulo e conserva o valor
bruto vazio. Para demonstrar a reconciliação, calcula separadamente:

`quantidade inferida = saldo oficial − soma dos movimentos quantitativos disponíveis`

Essa quantidade é uma parcela de reconciliação, não a confirmação de uma
contagem física. Pode resultar em zero sem que a interface apresente “contagem
confirmada: zero”. Um zero fornecido explicitamente na fonte continua distinto
de um campo vazio. A decisão e a sua fundamentação permanecem auditáveis.

## Preservar histórico e duplicados

Cada ficheiro é identificado por SHA-256. As coordenadas da folha, cabeçalhos,
valores e tipos originais mantêm-se no lote. A unificação de referências usa uma
identidade normalizada e a localização; conserva a ligação a todas as linhas
originais. Capacidades de caixa incompatíveis não são resolvidas escolhendo
automaticamente uma das linhas.

Cada coluna histórica conserva data e etiqueta originais. Datas iguais não
autorizam a fundir colunas distintas. Entradas negativas e saídas positivas
mantêm o seu impacto assinado; não são convertidas para as validações do novo
fluxo operacional. Quando só existe data, não é criada uma hora artificial.

Os documentos identificados num cabeçalho são guardados como documentos. A
pessoa pode permanecer nula; não se cria uma pessoa com o nome de um número ou
de uma data mal formatada. Observações autorizadas mantêm o texto, a coordenada
e a decisão de não lhes atribuir uma quantidade.

Na publicação, o saldo corrente recebe o saldo oficial reconciliado uma única
vez. A importação do histórico não volta a acrescentar os movimentos a esse
saldo. Repetir o mesmo lote é idempotente. A importação de outro ficheiro sobre
um catálogo existente é bloqueada; uma atualização posterior exigirá um fluxo
próprio e decisões sobre a fonte oficial.

## Gestão de catálogo

Apenas administradores podem criar ou modificar referências, localizações e
setores. O perfil Consulta continua a consultar stock e histórico, sem obter
permissões de escrita através de pedidos HTTP diretos.

Os formulários de referência permitem designação, capacidade de caixa opcional,
alerta individual e mínimo, localização, setor e estado ativo/inativo. Um alerta
desligado conserva o mínimo nulo. Ativar um alerta exige um mínimo válido,
incluindo zero quando escolhido explicitamente. Desativar uma referência não
apaga o histórico. O stock não é um campo editável destes formulários.

As alterações de localização e setor não mudam o saldo e ficam auditadas. O setor
tem de pertencer à localização escolhida. A gestão de localizações e setores
protege os que tenham referências associadas, incluindo referências inativas.
Eliminar exige uma operação POST confirmada; uma visita GET não elimina dados.

## Validação e publicação dos dados reais

Os testes automáticos usam exclusivamente ficheiros e identidades sintéticos.
Devem demonstrar reconciliação por referência, duplicados com todas as origens,
sinais históricos, contagem inicial desconhecida, ausência de dupla soma,
idempotência, reversão integral e rejeição de confirmações desatualizadas.
Os testes de catálogo cobrem permissões, validações e proteção das relações.

A pré-visualização real e o relatório de validação permanecem privados, fora do
Git. O resumo da entrega deve distinguir entre resultados previstos na
pré-visualização e dados efetivamente publicados. A publicação real depende da
confirmação posterior à apresentação dessa pré-visualização; o pedido de
desenvolver o importador não substitui essa confirmação.

Os fluxos operacionais de entrada, saída, rascunho e inventário, assim como PDFs,
assinatura, exportação, PWA e requisitos de produção, continuam nas etapas
seguintes. Não se deve apresentar esta entrega como implementação desses fluxos.
