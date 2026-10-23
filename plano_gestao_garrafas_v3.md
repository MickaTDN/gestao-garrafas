# Gestão de Garrafas — plano funcional e estrutura de dados

**Estado:** protótipo v3 e plano funcional; ainda não é a aplicação definitiva.  
**Origem:** folha **Stock** do ficheiro `STOCKS_FÁBIO_2026(1).xlsx`.  
**Interface:** aplicação web instalável (PWA), adaptada a telemóvel e computador.

## 1. Dados já verificados no Excel

| Informação | Resultado |
| --- | ---: |
| Linhas com referências | 462 |
| Referências únicas após fusão de «PORMENOR TINTO 2022» | **461** |
| Total de garrafas em stock | **8 522** |
| Referências sem garrafas/caixa definidas | **35** |
| Corredor Esquerdo | 198 referências únicas |
| Corredor Direito | 150 referências |
| Patamar Superior Direito (antes «Patamar Superior») | 113 referências |
| Patamar Superior Esquerdo (novo) | 0 referências iniciais |

A referência «PORMENOR TINTO 2022» aparece duas vezes no mesmo local (80 + 0 garrafas); unificar numa referência e conservar a proveniência/histórico de ambas as linhas. Não preencher automaticamente as 35 capacidades de caixa desconhecidas. O stock dessas referências continua a ser apresentado em garrafas até ser configurada a capacidade da caixa.

## 2. Ecrãs da versão 1

1. **Painel principal** — stock total, total de referências, alertas ativos abaixo do mínimo, rascunhos e acessos rápidos.
2. **Consulta de stock** — pesquisa por nome/código, localização, garrafas, conversão caixas + unidades, stock mínimo se estiver ativado e histórico da referência.
3. **Referências** — criar, editar, desativar sem apagar histórico, capacidade da caixa, localização única e stock mínimo opcional/desligado por defeito.
4. **Entradas** — nome de quem entregou (selecionar existente ou criar novo), várias referências por movimento, quantidades em caixas e garrafas; campos de quantidade inicialmente vazios; criar referência sem sair do movimento; na confirmação perguntar se quer relatório e gerar PDF apenas se responder sim, com **caixas e unidades soltas por referência**.
5. **Saídas** — nome de quem levanta, várias referências, campos de quantidade inicialmente vazios e **sem** opção de criar nova referência; revisão e correção antes de validar; validação por botão **ou** assinatura desenhada no ecrã; relatório final PDF imprimível com nome, data, **caixas, unidades soltas, total de garrafas e stock final**.
6. **Inventário físico** — inventário parcial ou completo, contagem por caixas + garrafas, motivo de ajuste quando a contagem diverge, possibilidade de alterar a localização da referência (mesmo sem diferença de stock), confirmação e histórico dos ajustes e transferências.
7. **Histórico** — consultar movimentos por dia/período, referência e pessoa, abrir PDFs antigos; preservar importação dos tipos antigos apenas como histórico.
8. **Definições** — utilizadores (administrador/consulta), pessoas, gestão das quatro localizações físicas principais e dos setores que pertencem a cada uma (adicionar/remover quando estiverem livres), e gestão de backups (quando o servidor estiver pronto).


## 2A. Localizações físicas e setores (configuração v3)

Não existe qualquer setor superior chamado «Armazém principal». As localizações principais são:

| Localização principal | Setores configurados | Referências importadas inicialmente |
| --- | ---: | ---: |
| Corredor Esquerdo | 1–8 (8) | 198 |
| Patamar Superior Esquerdo | 1–5 (5) | 0 |
| Corredor Direito | 1–7 (7) | 150 |
| Patamar Superior Direito | 1–7 (7) | 113 |
| **Total** | **27** | **461** |

A designação «Patamar Superior» do Excel é interpretada como «Patamar Superior Direito», por indicação do utilizador. Como as referências antigas não têm setor identificado no Excel, o `setor_id` começa vazio em todas elas; atribuição gradual na ficha da referência ou no inventário. Filtrar stock por localização principal ou por setor, sem imputar setores inventados. É possível adicionar/remover localizações e setores nas Definições, protegendo os que tenham referências atribuídas.

## 3. Regras essenciais

- A unidade contabilística é **a garrafa**. `caixas = parte inteira(stock / capacidade_caixa)`; `soltas = resto(stock / capacidade_caixa)`.
- Cada referência possui **uma localização principal** e **um setor dentro dessa localização** (o setor pode ficar por definir nos dados históricos importados). Alterar a localização principal ou o setor, incluindo durante o inventário físico, não altera o stock; a alteração fica registada no histórico. Não apagar localizações nem setores atribuídos a referências (inclusive inativas); transferi-las primeiro.
- **Alertas opcionais por referência**: desligados por defeito; quando ligados, configurar mínimo em garrafas. Alertar com `stock <= mínimo`.
- Entradas e saídas em **rascunho** não alteram stock. Após confirmação, o movimento é imutável. Nos formulários de entrada e saída, os campos de caixas e garrafas soltas começam **vazios**, sem introdução automática de quantidade; na seleção e após a adição da referência, mostrar o stock atual em **caixas completas e unidades soltas** (e total de garrafas).
- Em saídas, permitir escolher apenas referências já existentes e validar que não é pedido mais stock do que o disponível. Registar movimento e atualizar saldos numa única transação da base de dados para evitar inconsistências.
- O nome da pessoa é pesquisável. Se for novo, criar registo automaticamente, normalizando espaços e evitando duplicados por diferenças simples de maiúsculas/minúsculas.
- No relatório de entrada ou saída, discriminar **caixas completas e garrafas soltas por referência**, além do total de garrafas; quando possível, preservar as quantidades introduzidas em cada campo, mesmo que não correspondam à conversão canónica da soma. Guardar a capacidade da caixa associada à linha do movimento para que futuras alterações de configuração não modifiquem um documento histórico.
- No final de uma **entrada**, perguntar se o utilizador quer gerar relatório; guardar a opção no movimento e permitir reabrir/imprimir o relatório se foi gerado. Na saída, o relatório continua a ser obrigatório.
- Na saída, a pessoa confere no ecrã antes de validar. Pode corrigir quantidades durante essa conferência. Apenas depois de validada é emitida a versão final do relatório.
- A assinatura no ecrã é **assinatura desenhada** e guardada no relatório; não se deve confundir com assinatura digital qualificada.
- Correção posterior de um movimento confirmado: registar movimento de ajuste relacionado, nunca reescrever silenciosamente o documento antigo.
- O histórico da aplicação terá **novos tipos: entrada, saída e ajuste de inventário**. Movimentos antigos com etiquetas como «Acidente», «Daniel» ou «Ajuste» conservam o texto original no registo de migração para auditabilidade, sem permitir criar esses tipos antigos pela interface.
- O perfil **Consulta** pode consultar sem editar. O administrador faz as alterações. Os acessos reais precisam de autenticação no servidor, não apenas ocultação de botões.

## 4. Entidades da base de dados

| Tabela | Campos principais / finalidade |
| --- | --- |
| `utilizadores` | identidade, email/login, perfil, ativo |
| `localizacoes` | ID, nome e estado; quatro localizações principais, sem «Armazém principal» |
| `setores` | ID, localização principal a que pertence, nome e estado; 27 setores iniciais |
| `pessoas` | nome escolhido ou adicionado durante a entrada/saída |
| `referencias` | código gerado, designação, capacidade da caixa opcional na importação, `localizacao_id` principal única, `setor_id` único e opcional para registos ainda não classificados, alerta ativo/mínimo, ativa, saldo de consulta |
| `saldos_iniciais` | saldo base por referência na data do inventário inicial, com origem da linha do Excel |
| `movimentos` | ID, tipo, estado (rascunho/confirmado), data, pessoa, origem, dados da validação, motivo, opção de gerar relatório de entrada, relatório |
| `linhas_movimento` | referência, quantidade pedida/contada, impacto assinado no stock, stock antes e depois |
| `documentos` | caminho seguro do PDF e, quando existir, assinatura associada à saída |
| `mudancas_localizacao` | referência, localização principal e setor anteriores e novos, momento e operador, eventualmente associada a um inventário |
| `auditoria` | operador, operação, data, origem e eventual referência do movimento anterior |

**Stock de controlo:** saldo inicial + soma dos impactos de movimentos confirmados. Pode existir um campo de saldo em cache para consultas rápidas, desde que seja atualizado na mesma transação e conciliável com o histórico.

## 5. Estratégia de importação do Excel

1. Fazer uma cópia de segurança do ficheiro original, sem lhe alterar fórmulas ou dados.
2. Ler exclusivamente a folha **Stock**; identificar os grupos de localização pelo cabeçalho da respetiva zona.
3. Importar referências e códigos automáticos `GAR-0001`, etc. Unir os dois registos de «PORMENOR TINTO 2022», preservando a linha de origem dos movimentos e evitando somar movimentos duas vezes.
4. Tratar a coluna «Inventário» de **06/01/2025** como saldo inicial. Um valor vazio pode representar zero, mas deve ser validado na reconciliação.
5. Transformar cada coluna de movimento do Excel em movimentos datados, com uma linha por referência afetada. Preservar os **sinais reais** de cada célula; entradas negativas e saídas positivas são correções intencionais.
6. Registar também as etiquetas originais dos movimentos especiais antigos num campo de origem. Não inventar horas para movimentos que no Excel só têm data.
7. Para cada referência, comparar **saldo inicial + movimentos importados** com o stock atual indicado no Excel. Apresentar eventuais diferenças antes da importação definitiva.
8. Depois da reconciliação, carregar os movimentos e gerar o stock corrente de forma consistente. Não ligar dois sistemas simultâneos a alterar o stock sem uma regra de migração clara.

## 6. Segurança e continuidade

- Base de dados centralizada (por exemplo, PostgreSQL) e acesso HTTPS; sessões protegidas e permissões verificadas no servidor.
- Backups automáticos diários em armazenamento separado, com retenção de versões e testes ocasionais de recuperação.
- PDFs e assinaturas guardados em armazenamento privado, acessível apenas aos perfis autorizados.
- Restringir remoção de referências com histórico: **desativar** em vez de apagar.
- Exportação de dados para Excel quando necessária, mas Excel deixa de ser a fonte principal após migração.

## 7. Etapas de desenvolvimento

**Etapa A — Protótipo e decisões:** ecrãs navegáveis para confirmar usabilidade; importação de referências e stocks em modo demonstração.

**Etapa B — Base de dados e migração:** criar estrutura e autenticação; importar e reconciliar histórico Excel, incluindo correções com sinais invertidos.

**Etapa C — Operações reais:** entradas, saídas, rascunhos, inventários, saldos e regras de permissões, todos transacionais.

**Etapa D — Relatórios e segurança:** PDF de saída com os dois métodos de validação, PDF de entrada opcional, histórico completo de localizações, alertas escolhidos, backups e testes num telemóvel e computador.

### Sobre o ficheiro de protótipo

O HTML de demonstração atualizado (v3) mostra as 461 referências e os stocks atualmente existentes no Excel, com pesquisa, rascunhos, inventário com mudança de localização, 4 localizações e 27 setores geríveis, setores antigos por atribuir, relatórios com caixas e unidades, campos de quantidade vazios, entradas com relatório opcional, saídas sem criação de referência e relatórios para impressão **apenas nesta sessão**. Não está ligado à Internet, não possui base de dados centralizada, nem autenticação real, nem cópias automáticas. Por isso, **não deve ser usado como sistema oficial de registo**.
