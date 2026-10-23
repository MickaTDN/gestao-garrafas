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

Resolver as exceções encontradas no Excel, preservar a fonte original e registar
decisões por lote. Implementar a publicação atómica e idempotente de saldos e
movimentos, com relatório por referência. Incluir a gestão de referências,
localizações, setores e pessoas, mantendo o histórico. Não inventar setores,
capacidades de caixa, horas nem movimentos ausentes da fonte.

Critério de conclusão: cada saldo e exceção têm explicação auditável; repetir uma
importação não duplica registos. A consulta permite verificar os movimentos
originais e a sua origem. A migração definitiva é precedida de backup e de uma
regra de transição que evite alterações concorrentes no Excel e na aplicação.

## Etapa 3 — operações reais

Construir os formulários de entradas, saídas, rascunhos e inventário sobre os
serviços transacionais. Incluir revisão, correção antes da confirmação e
transferências de localização/setor com auditoria. Testar duas operações
concorrentes sobre a mesma referência, além dos fluxos e permissões de cada
perfil em computador e telemóvel.

Critério de conclusão: os rascunhos não alteram stock, a confirmação tem efeito
uma única vez, nunca há saldo negativo e falhas revertem o movimento completo.
Movimentos confirmados só são corrigidos através de novos movimentos relacionados.

## Etapa 4 — relatórios, PWA e operação

Entregar relatórios privados, assinatura desenhada e reabertura dos documentos
históricos. Finalizar instalação PWA e testes em dispositivos, exportação,
backups e recuperação. Concluir os requisitos de produção e segurança descritos
na arquitetura antes de usar a aplicação como registo oficial.

Critério de conclusão: impressão e PDFs mantêm quantidades históricas e permissões;
um backup é restaurado com sucesso; a aplicação tem domínio HTTPS, gestão de
segredos e procedimentos de operação. A PWA não implica escritas de stock offline.

## Matriz de requisitos aprovados

| Requisito | Estado nesta entrega | Etapa de conclusão |
| --- | --- | --- |
| Aspeto V3 em computador e telemóvel | Estrutura visual reutilizada nas páginas iniciais. | 1, com regressão visual nas etapas seguintes. |
| Autenticação e perfis Administrador/Consulta | Utilizador e autorização no servidor; criação explícita de contas. | 1; gestão de utilizadores na interface em 2. |
| Base permanente e migrações | Esquema PostgreSQL; persistência local por volume. | 1; alojamento de produção em 4. |
| Painel: stock, referências, alertas, rascunhos e acessos rápidos | Consulta dos registos já presentes na base; áreas futuras identificadas. | 1; acompanhamento dos fluxos em 3. |
| Stock por designação/código, localização e setor | Consulta paginada preparada. | 1. |
| Ficha com garrafas e equivalência caixas/unidades | Consulta da base; capacidade desconhecida permanece vazia. | 1. |
| Criar, editar e desativar referências sem apagar histórico | Modelo e relações protegidas; formulários pendentes. | 2. |
| Código automático de referência | Campo único no modelo; gerador operacional pendente. | 2. |
| Mínimo opcional, desligado por defeito; alerta quando stock ≤ mínimo | Mínimo nulo e consulta dos alertas. Edição pendente. | 2. |
| Uma localização e um setor da mesma localização; setor antigo por definir | Modelo e validação; sem atribuição inventada na migração. | 1 para estrutura, 2 para gestão. |
| Quatro localizações físicas e respetivos setores V3 | Migração de configuração sem catálogo de produtos reais. | 1. |
| Adicionar/remover localizações e setores apenas quando livres, incluindo referências inativas | Proteção das relações; gestão e testes de interface pendentes. | 2. |
| Pessoas pesquisáveis e criação sem duplicados de espaços/maiúsculas | Modelo e resolução normalizada; pesquisa e integração nos formulários pendentes. | 3. |
| Entradas com várias referências e criação de referência sem abandonar movimento | Modelo preparado; formulário pendente. | 3. |
| Campos de caixas e garrafas inicialmente vazios | Mantido como requisito de formulário; não entregue por um simples valor zero no modelo. | 3. |
| Mostrar stock em caixas, unidades soltas e total antes/depois de adicionar referência | Consulta inicial; integração no movimento pendente. | 3. |
| Rascunhos persistentes sem efeito no saldo | Estado no modelo e regra no serviço; guardar/reabrir pelo formulário pendente. | 3. |
| Saídas apenas de referências existentes e sem exceder stock | Serviço inicial valida referência e saldo numa transação; formulário pendente. | 3. |
| Revisão da saída e correção de quantidades antes de validar | Modelo suporta rascunho; conferência visual pendente. | 3. |
| Confirmação simples ou assinatura desenhada na saída | Campo de validação e metadados privados; captura e verificação do ficheiro pendentes. | 3–4. |
| Relatório opcional na entrada e obrigatório na saída | Opção no modelo; serviço impõe opção para saída. Geração pendente. | 4. |
| Relatórios com caixas/unidades por referência, total e stock final | Campos de snapshot preparados; apresentação/PDF pendentes. | 4. |
| Conservar capacidade e quantidades introduzidas para documentos antigos | Serviço prepara snapshots sem depender da configuração futura. | 1 para base, 4 para documentos. |
| Inventário parcial/completo com contagem e motivo quando há diferença | Tipo e motivo preparados no serviço; seleção e contagem pendentes. | 3. |
| Mudar localização/setor no inventário, inclusive sem diferença de stock | Modelo de transferência preparado; serviço e formulário específicos pendentes. | 3. |
| Histórico de ajustes e mudanças de localização | Entidades preparadas; consulta de movimentos inicial. | 3. |
| Movimentos confirmados imutáveis; ajustes posteriores relacionados | Proteções ORM e triggers PostgreSQL sobre movimentos e linhas; campo de relação preparado. Os triggers não existem no modo SQLite. | 1 para base; fluxo completo em 3. |
| Histórico por data/período, referência e pessoa | Consulta preparada; depende dos dados efetivamente migrados. | 1 para consulta, 2 para migração. |
| Reabrir e imprimir PDFs históricos | Metadados de documentos preparados; acesso e geração pendentes. | 4. |
| Excel: ler Stock sem alterar original | Leitura e relatório de preparação. | 1. |
| Excel: proveniência por ficheiro, folha, linha e coluna | Preparação com SHA-256 e valores brutos; sem publicação automática. | 1 para preparação, 2 para publicação. |
| Excel: preservar sinais e etiquetas antigas sem permitir novos tipos legados pela interface | Estrutura preparada e casos sintéticos de importação. | 2 para histórico publicado. |
| Excel: duplicados reconciliados conservando cada origem | Deteção na preparação; decisão e fusão auditáveis pendentes. | 2. |
| Excel: saldo inicial + movimentos reconciliam por referência | Relatório candidato; vazios e texto inesperado exigem decisões explícitas. | 2. |
| Excel: preservar datas sem inventar horas, inclusive datas repetidas | Data separada de instante e coluna de origem conservada. | 1 para modelo, 2 para publicação. |
| Backups automáticos separados, retenção e restauro testado | Não configurados nesta etapa. Volume local não os substitui. | 4. |
| PDFs/assinaturas privados e permissões de acesso | Metadados e diretório privado; entrega e retenção pendentes. | 4. |
| Exportação para Excel | Requisito conservado; ainda sem exportador. | 4. |
| Aplicação PWA instalável | Arquitetura responsiva inicial; manifesto e service worker pendentes. | 4. |
| Dados reais e credenciais fora do código | `.env`, anexos, relatórios e bases privadas ignorados; fixtures sintéticas. | Obrigatório em todas as etapas. |

Não se considera concluída a preservação operacional de todo o histórico enquanto
o lote reconciliado não tiver sido publicado e verificado. A fonte disponível
define a cobertura: dados históricos ausentes requerem uma fonte complementar,
não a criação de movimentos para preencher lacunas.
