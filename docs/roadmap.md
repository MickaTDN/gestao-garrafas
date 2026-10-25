# Etapas de desenvolvimento

Este documento conserva os requisitos aprovados do V3 e distingue a estrutura
inicial da entrega de cada fluxo completo. O visual e as regras do
[plano funcional](../plano_gestao_garrafas_v3.md) continuam a orientar as etapas.
A [arquitetura](architecture.md) explica as decisões técnicas.

## Etapa 1 — estrutura técnica e preparação da base

Inclui autenticação, perfis no servidor, esquema de base e migrações, localizações
e setores iniciais, consultas autenticadas, serviço transacional inicial e
inspeção/preparação do Excel. Não publica automaticamente dados reais nem
implementa todos os formulários do V3. As páginas de funcionalidades futuras
indicam esse estado.

Os testes devem demonstrar permissões, integridade do modelo, confirmação atómica,
rollback perante stock insuficiente, preservação dos snapshots, preparação
idempotente e tratamento de exceções de importação. A verificação em PostgreSQL é
necessária para os comportamentos dependentes de bloqueios por linha. As
contagens e resultados efetivamente executados são reportados na validação da
entrega; a presença de testes não equivale a tê-los executado.

## Etapa 2 — migração reconciliada e catálogo

Acrescenta a gestão de referências, localizações e setores e o processo de
reconciliação/publicação do Excel, descrito em [stage2.md](stage2.md). As decisões
por lote e os valores originais permanecem privados e auditáveis. A importação
liga uma pré-visualização à fonte, às decisões e ao estado do destino; só publica
após confirmação explícita e nova validação. Repetir o mesmo lote não duplica
stock nem histórico.

Os formulários de catálogo alteram atributos e estado de referências; não são
formulários de movimento nem permitem editar stock. A gestão protege
localizações e setores usados por referências, mesmo inativas. Não se inventam
setores, capacidades, pessoas, horas ou movimentos ausentes da fonte.

Critério de conclusão do código: cada saldo e exceção têm explicação auditável;
os testes demonstram publicação atómica, idempotência, todas as origens dos
duplicados e permissões de catálogo. A publicação dos dados reais é uma ação
separada: depende de apresentar a pré-visualização e obter confirmação, além de
uma regra de transição que evite alterações concorrentes no Excel e na aplicação.

## Etapa 3 — operações

Implementados formulários de entradas, saídas, rascunhos próprios e inventários
parciais/completos sobre os serviços transacionais. Incluem conferência, edição,
cancelamento, transferências com auditoria e correções através de novos movimentos
relacionados. As contagens físicas são separadas dos ajustes; vazios permanecem
por contar. Mudanças de stock exigem nova conferência, sem sobrescrita silenciosa.
Ver [stage3.md](stage3.md) e a [decisão 3](decisions/0003-operational-transactions.md).
A validação é simples; assinatura e geração de documentos ficam na Etapa 4.
Desenvolvimento e testes ocorrem apenas com dados sintéticos em bases isoladas.

Critério de conclusão: os rascunhos não alteram stock, a confirmação tem efeito
uma única vez, nunca há saldo negativo e falhas revertem o movimento completo.
Movimentos confirmados só são corrigidos através de novos movimentos relacionados.

## Etapa 4 — relatórios, PWA e operação

Implementados PDFs privados para novas confirmações, assinatura desenhada opcional
na saída, consulta/download/impressão dos documentos existentes, PWA sem escritas
offline, exportação XLSX, gestão de utilizadores e limitação de login. Inclui
backups PostgreSQL/documentos, cifragem, retenção, restauro sintético real e
configuração/documentação para um servidor futuro. As proteções anteriores de
stock, concorrência, proveniência e imutabilidade continuam em vigor.

**Código preparado não significa infraestrutura configurada ou aplicação oficial.**
Alojamento, DNS/HTTPS, PostgreSQL TLS/rede/conta restrita reais, chaves e destino de
backups, agendamento/alertas, restauro num segundo sistema, validação em dispositivos
e publicação inicial controlada continuam dependentes de configuração e autorização.
Não há merge, publicação real, contratação de serviços ou deploy automático.
Ver [instalação](installation.md), [recuperação](recovery.md) e
[decisão 4](decisions/0004-private-documents-and-recovery.md).

## Etapa 5 — instalação local no Windows 11

Piloto preparado para Windows 11 de 64 bits com pelo menos 16 GB de RAM, usando
a imagem existente em Docker Desktop/WSL2. Inclui diagnóstico, preparação privada,
atalhos de arranque/paragem, conta escolhida pelo utilizador, backup e restauro
num novo projeto. A base é nova e fictícia; a reservada à importação não é usada.

As autorizações e a instalação de pré-requisitos ficam com a informática, sem
bypass de políticas. Android por Wi-Fi está apenas desenhado, não aberto. Não
se implementa Stock Vendas offline. Testes de shell Windows CI e de payload Linux
não substituem a aceitação num PC Windows 11 real autorizado. Ver
[windows11.md](windows11.md) e [decisão 5](decisions/0005-windows-local.md).

## Matriz de requisitos aprovados

| Requisito | Estado nesta entrega | Etapa de conclusão |
| --- | --- | --- |
| Aspeto V3 em computador e telemóvel | Estrutura visual reutilizada nas páginas iniciais. | 1, com regressão visual nas etapas seguintes. |
| Autenticação e perfis Administrador/Consulta | Utilizador e autorização no servidor; criação explícita de contas. | 1; gestão administrativa com reautenticação na etapa 4. |
| Base permanente e migrações | Esquema PostgreSQL; persistência local por volume. | 1; alojamento de produção em 4. |
| Painel: stock, referências, alertas, rascunhos e acessos rápidos | Consulta dos registos presentes; rascunhos do próprio administrador e acessos aos fluxos. | 1; acompanhamento dos fluxos em 3. |
| Stock por designação/código, localização e setor | Consulta paginada funcional. | 1. |
| Ficha com garrafas e equivalência caixas/unidades | Consulta da base; capacidade desconhecida permanece vazia. | 1. |
| Criar, editar e desativar referências sem apagar histórico | Formulários de gestão para administradores; stock fora dos campos editáveis. | 2. |
| Código automático de referência | Geração automática e identidade única. | 2. |
| Mínimo opcional, desligado por defeito; alerta quando stock ≤ mínimo | Ativação individual no formulário; mínimo nulo quando desligado. | 2. |
| Uma localização e um setor da mesma localização; setor antigo por definir | Modelo e validação; sem atribuição inventada na migração. | 1 para estrutura, 2 para gestão. |
| Quatro localizações físicas e respetivos setores V3 | Migração de configuração sem catálogo de produtos reais. | 1. |
| Adicionar/remover localizações e setores apenas quando livres, incluindo referências inativas | Formulários de gestão, confirmação de eliminação e relações protegidas. | 2. |
| Pessoas pesquisáveis e criação sem duplicados de espaços/maiúsculas | Pesquisa pelo nome nos formulários e criação normalizada, sem duplicados simples. | 3. |
| Entradas com várias referências e criação de referência sem abandonar movimento | Formulário com várias linhas; guarda antes de criar ou reativar referência, com proteção contra duplicados. | 3. |
| Campos de caixas e garrafas inicialmente vazios | Campos vazios nos formulários e persistência de NULL separada de zero explícito. | 3. |
| Mostrar stock em caixas, unidades soltas e total antes/depois de adicionar referência | Stock atual e previsto com equivalência, calculados progressivamente e validados no servidor. | 3. |
| Rascunhos persistentes sem efeito no saldo | Guardar, reabrir, editar e cancelar os próprios rascunhos; revisão otimista e auditoria. | 3. |
| Saídas apenas de referências existentes e sem exceder stock | Formulário completo; confirmação repete validação de estado e stock sob bloqueio. | 3. |
| Revisão da saída e correção de quantidades antes de validar | Página de conferência, regresso à edição e invalidação de conferências antigas. | 3. |
| Confirmação simples ou assinatura desenhada na saída | Confirmação simples ou assinatura PNG verificada no servidor e incluída no PDF. | 3–4. |
| Relatório opcional na entrada e obrigatório na saída | Escolha explícita na entrada; saída obrigatória; PDF persistido atomicamente na confirmação. | 4. |
| Relatórios com caixas/unidades por referência, total e stock final | PDF A4 paginado com snapshots e quantidades exatas, sem recalcular documentos antigos. | 4. |
| Conservar capacidade e quantidades introduzidas para documentos antigos | Serviço prepara snapshots sem depender da configuração futura. | 1 para base, 4 para documentos. |
| Inventário parcial/completo com contagem e motivo quando há diferença | Seleção filtrada, paginação, contagem física, motivo, zero explícito e conflitos com nova conferência. | 3. |
| Mudar localização/setor no inventário, inclusive sem diferença de stock | Transferências no inventário, inclusive sem diferença quantitativa, atómicas com o stock. | 3 para inventário. |
| Histórico de ajustes e mudanças de localização | Histórico de operações, contagens, transferências, responsáveis e correções relacionadas. | 2 para migração, 3 para ajustes. |
| Movimentos confirmados imutáveis; ajustes posteriores relacionados | Proteções ORM e PostgreSQL sobre livro, proveniência e transferências; auditoria de acréscimo e ajustes relacionados. | 1 para base; fluxo completo em 3. |
| Histórico por data/período, referência e pessoa | Consulta funcional; depende da confirmação da publicação dos dados reais. | 1 para consulta, 2 para migração. |
| Reabrir e imprimir PDFs históricos | Abrir/imprimir/descarregar apenas PDFs guardados e verificados, com autenticação. | 4. |
| Excel: ler Stock sem alterar original | Leitura e relatório de preparação. | 1. |
| Excel: proveniência por ficheiro, folha, linha e coluna | SHA-256, valores brutos e publicação ligada à pré-visualização confirmada. | 1 para preparação, 2 para publicação. |
| Excel: preservar sinais e etiquetas antigas sem permitir novos tipos legados pela interface | Importador legado mantém sinais e cabeçalhos; testes sintéticos. Publicação real exige confirmação. | 2. |
| Excel: duplicados reconciliados conservando cada origem | Unificação com ligação às linhas e células originais; conflitos bloqueiam publicação. | 2. |
| Excel: saldo inicial + movimentos reconciliam por referência | Reconciliação individual, relatório e confirmação; inventário vazio fica desconhecido com parcela inferida separada. | 2. |
| Excel: preservar datas sem inventar horas, inclusive datas repetidas | Data separada de instante e coluna de origem conservada. | 1 para modelo, 2 para publicação. |
| Backups automáticos separados, retenção e restauro testado | Comandos, cifragem e timer preparados; restauro sintético comprovado. Infraestrutura/agendamento reais pendentes. | 4. |
| PDFs/assinaturas privados e permissões de acesso | Bytes privados PostgreSQL, acesso autenticado, checksum e imutabilidade. Política legal/infraestrutura real a definir. | 4. |
| Exportação para Excel | Exportações filtradas de stock/catálogo/configuração/histórico/transferências, com proteção de fórmulas. | 4. |
| Aplicação PWA instalável | Manifesto, ícones e cache apenas pública; elegibilidade Chromium validada. Instalação física/HTTPS real pendentes. | 4. |
| Dados reais e credenciais fora do código | `.env`, anexos, relatórios e bases privadas ignorados; fixtures sintéticas. | Obrigatório em todas as etapas. |

Não se considera concluída a preservação operacional de todo o histórico enquanto
o lote reconciliado não tiver sido publicado e verificado. A fonte disponível
define a cobertura: dados históricos ausentes requerem uma fonte complementar,
não a criação de movimentos para preencher lacunas.

## Etapa A — melhorias da aplicação principal no piloto

Formulários diretos, continuação dentro de cada operação, pesquisa por nome nas
entradas/saídas, setores dependentes da localização, conferência/PDF simplificados
e nome Gestão Vertente Aveludada. Sem alteração das regras de stock ou bases
instaladas. Identidade Copo com Vida depende de fornecer os originais. Ver
[etapa-a.md](etapa-a.md) e o procedimento de atualização do piloto em
[windows11.md](windows11.md#atualização-da-etapa-a-num-piloto-existente).
