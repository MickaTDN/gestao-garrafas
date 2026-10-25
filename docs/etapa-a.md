# Etapa A — simplificação da aplicação principal

Esta página documenta a Etapa A / PR #8. A continuação **A2** tem migrações,
perfis e nova gestão de PDFs; ver [etapa-a2.md](etapa-a2.md), incluindo o
procedimento Windows distinto. A ausência de migrações abaixo refere-se só à A.

Branch `fix/entradas-saidas-diretas`, baseada em `stage5/windows-local-preflight`.
Esta entrega não inclui a aplicação Android de consulta das etapas posteriores.
Não há migrações, alterações ao esquema, regras de stock ou perfis de rede.
O nome visível passa a **Gestão Vertente Aveludada**; os identificadores técnicos
anteriores mantêm-se para não quebrar instalações existentes.

## Utilização

Entradas, Saídas e Inventário abrem diretamente o formulário. A pesquisa surge
antes dos resultados e das quantidades; data, pessoa (quando aplicável) e
observações surgem depois. Nas entradas e saídas a pesquisa usa apenas o nome,
sem filtros de localização/setor. No inventário conservam-se os filtros do âmbito.

Selecionar referências e usar **Adicionar selecionadas e guardar** apresenta as
linhas com Caixas e Garrafas soltas vazias. No inventário completo este botão
inclui todas as referências ativas abrangidas pela pesquisa, fixando o âmbito;
as contagens continuam vazias. A escolha Parcial/Completo conserva-se durante a
pesquisa inicial. Depois de incluídas as referências, o âmbito é fixo.

**Guardar operação** conserva o trabalho; **Guardar e conferir operação** abre a
conferência. Só a confirmação final altera o stock. As operações guardadas por
concluir aparecem no próprio ecrã do respetivo tipo, apenas para o administrador
que as criou, com continuação/cancelamento e paginação. O menu Rascunhos e o
atalho Os meus rascunhos foram removidos. A rota antiga continua protegida e
compatível com ligações anteriores, sem entrada na navegação.

Criar nova referência durante uma entrada guarda primeiro a operação, incluindo
quantidades e observações. A criação verifica duplicados ativos/inativos em todas
as localizações; reativar exige confirmação própria e conserva a identidade e o
histórico. Saídas e inventários não permitem criar referências.

Os setores são carregados da base e filtrados no navegador pela localização,
sem recarregar a página. Mudar de localização limpa um setor incompatível.
Pedidos forjados continuam sujeitos à validação do formulário e do domínio.

## Conferência e documentos

Entradas/saídas apresentam apenas Referência, Quantidade a entrar/a sair e Stock
final. Quantidades usam caixas/garrafas e omitem componentes zero; zero final é
`0 garrafas`. A quantidade movimentada conserva a decomposição introduzida
(ex.: `1 caixa + 8 garrafas`, mesmo com capacidade 6); o stock final usa caixas
completas e garrafas restantes. Capacidade desconhecida: apenas garrafas.

O PDF é opcional na entrada e obrigatório na saída e inventário. Mantêm-se data,
pessoa, observações, responsável e confirmação simples/assinatura. O inventário
conserva contagem, diferenças, motivos e transferências. Se stock ou configuração
mudarem após a conferência, não se apresenta um saldo final obsoleto como válido:
a interface exige nova conferência e o servidor volta a validar sob bloqueio.

Só os documentos novos usam esta apresentação. PDFs já guardados continuam
imutáveis, inclusive nome/marca antigos. Códigos, capacidade, valores originais,
stock anterior/posterior e proveniência permanecem no modelo e snapshots.
Os códigos continuam visíveis quando necessários à revisão de duplicados,
reativação ou rastreabilidade técnica; não prefixam os nomes nas listas normais.

## Decisões técnicas e segurança

- GET não cria movimentos, pessoas ou auditoria. O primeiro POST válido cria e
  guarda a operação interna na mesma transação; falhas revertem ambos os passos.
- Reutilizam-se `create_draft`, `save_draft`, `review_draft`, `confirm_movement` e
  `cancel_draft`; não existe escrita direta no saldo pelos novos formulários.
- Permanecem tokens de revisão, revisão otimista, bloqueios PostgreSQL,
  imutabilidade e correções exclusivamente por novos movimentos relacionados.
- A lista de referências selecionadas é validada contra a página de pesquisa.
  Campos técnicos forjados não alteram stock, estado, autor ou tipo.
- A apresentação de quantidades é partilhada entre conferência e PDF.
- A identidade é apenas visual. Não se renomeiam bases, projetos/volumes Docker,
  pastas privadas, variáveis de ambiente, códigos ou registos existentes.
- Os originais Copo com Vida estão preservados e aplicados no login, novos PDFs
  e ícones Windows/PWA. O copo foi derivado exclusivamente do recorte fornecido,
  sem redesenho. Proveniência e compilação estão em
  [static/branding/README.md](../static/branding/README.md).

## Validação

A suíte PostgreSQL inclui formulários diretos dos três tipos, primeiro POST
atómico, abandonos/cancelamento, permissões/CSRF, manipulação HTTP, duplicados e
reativação, entradas/saídas múltiplas, contagens zero/vazias, inventários e
transferências, concorrência real, histórico/importação, PDFs/assinaturas,
backup/restauro e perfil Windows. Testes Chromium usam computador e viewport
móvel, incluindo criação de referência durante a entrada, setores nos formulários,
conferência, PDFs, assinatura com rato/toque e perda de ligação da PWA.

Os testes utilizam novas bases e dados exclusivamente sintéticos. Não se liga à
base reservada à pré-visualização do Excel nem ao computador do utilizador.
A CI executa adicionalmente PowerShell 5.1/NTFS/atalhos num runner Windows e o
payload Docker em projetos sintéticos novos. Estes testes não substituem a
aceitação física Windows 11/WSL2 nem a validação do logótipo original.

A atualização manual, sem apagar os dados fictícios instalados, está descrita em
[windows11.md](windows11.md#atualização-da-etapa-a-num-piloto-existente).

## Identidade Copo com Vida concluída

O utilizador forneceu no ZIP o logótipo completo (1273×827) e o recorte original
do copo (143×246), sem dados da fatura. Ambos foram conservados byte a byte. O
logótipo completo aparece no login responsivo e nos novos PDFs. O símbolo da
barra lateral e os ícones PWA/Windows usam exclusivamente o copo original branco
sobre verde-escuro. Não se alteraram os nomes das aplicações nem a aplicação
Stock Vertente Aveludada separada.

Os PNG PWA têm 192/512 px; o ICO contém sete tamanhos de 16 a 256 px. O script
`scripts/build_brand_icons.py` documenta a compilação: margens vazias, máscara de
tinta e escala proporcional, sem reconstrução de detalhes. A origem é raster;
redimensionar não acrescenta detalhe e os tamanhos muito pequenos têm naturalmente
menos definição.

O ícone Windows é copiado para uma instalação validada, sem chamar Docker ou
bases de dados. Os testes verificam os originais por SHA-256, a conservação da
geometria, cores/margens, o ICO, manifesto/cache e a imagem original embebida no
PDF ao lado de uma assinatura sintética. Chromium verifica o login e os ficheiros
públicos em computador e telemóvel. Estes testes de marca não usam bases.

A instalação/atualização num dispositivo físico não foi executada. Seguir o guia
Windows existente e rever os ícones após atualizar a PWA/atalhos. PDFs históricos
permanecem inalterados.
