# Novas referências em entradas: proposta e confirmação

Base: PR #33 `1d669833c4ea301bcbc3d6c9204bcda41c8b84de`.
Não altera a main, os PR anteriores ou instalações existentes.

## Stock Vertente Aveludada

Fábio e Daniel podem escolher **Propor nova referência** numa entrada. Introduzem
designação, capacidade de caixa quando conhecida e caixas/garrafas. Não preenchem
código, localização ou setor. As quantidades começam vazias; capacidade desconhecida
permite apenas garrafas individuais. Uma saída nunca permite propor referências.

Cada proposta recebe um UUID local estável, sem código oficial. Pode ser corrigida
enquanto a folha for rascunho. O cofre cifrado e o respetivo backup preservam os novos
campos, os valores vazios, os UUID e as versões já exportadas. Exportar congela a
mesma folha e não significa receção ou confirmação; o envio Wi-Fi continua opcional,
autenticado por dispositivo e com comprovativo assinado.

## Gestão oficial

Na entrada direta, **Criar nova referência** abre um formulário que já inclui caixas
e garrafas recebidas. Ao guardar, regressa à mesma entrada com a proposta e as
quantidades adicionadas; pode combiná-la com referências existentes. Pode corrigir
ou retirar a proposta antes de conferir. Guardar/cancelar/abandonar não cria a
referência nem modifica stock.

Nas folhas recebidas, as propostas aparecem identificadas na listagem e no detalhe:

1. Em **Corrigir a versão de trabalho**, o administrador confere a designação,
   capacidade e quantidades e escolhe localização e setor (opcional).
2. Pode associar a uma referência existente selecionando o respetivo identificador
   no catálogo da conferência e ajustando a capacidade explicitamente. Não se fundem
   linhas nem quantidades automaticamente. Uma referência inativa exige reativação
   explícita no catálogo antes de poder receber o movimento.
3. Pode retirar uma proposta com motivo, mantendo as restantes linhas, ou rejeitar
   toda a folha. A última linha não pode ser retirada para confirmar um movimento
   vazio; nesse caso deve rejeitar a folha.
4. Guarda a correção com motivo, confere e confirma explicitamente.

Só a confirmação cria referências oficiais, códigos `GAR-…` pelo serviço existente,
movimento, stock e documentos numa única transação. A entrada mantém a escolha de
PDF opcional; saídas mantêm PDF obrigatório. Numeração, assinaturas, datas oficiais
e restrições sobre correções históricas não mudam.

As capacidades existentes são preservadas: a entrada direta exige as permissões de
entrada e gestão de catálogo, incluindo perfis personalizados já autorizados. O
processamento de folhas recebidas continua exclusivo do Administrador; não se
concedem privilégios administrativos aos dispositivos ou a perfis personalizados.

Uma falha de PDF, permissão, stock, localização, duplicação ou integridade reverte
também as novas referências e respetivos eventos de criação. Originais recebidos
nunca são reescritos; as decisões e associações ficam no histórico separado da folha.
O movimento conserva o mapa de propostas para identidades oficiais efetivamente
criadas. A entrada direta conserva as propostas e o mapa nos metadados existentes.

## Duplicação e concorrência

A criação reutiliza o catálogo e o seu bloqueio transacional PostgreSQL. A pesquisa
é global e inclui inativas, ignorando maiúsculas/minúsculas e espaços desnecessários.
Os duplicados mostram códigos, locais e estados para associação ou revisão, sem
reativação automática nem fusão de referências históricas legítimas.

A validação é repetida ao confirmar: uma referência entretanto criada com a mesma
designação impede uma segunda criação. O código é atribuído sob o mesmo bloqueio,
com unicidade adicional na base. Reenvios por ficheiro/Wi-Fi e confirmações repetidas
continuam a usar a identidade original da folha e não criam outro stock/movimento.

## Compatibilidade e segurança

- Folhas sem propostas continuam a ser exportadas como versão 1, sem alterar o
  formato nem a assinatura. O novo recetor aceita integralmente essas folhas.
- Folhas com propostas usam versão 2, JWE RSA-OAEP-256/A256GCM e envelope ES256
  existentes; a assinatura usa o domínio `vertente-sheet-v2`. Não há algoritmo novo,
  chaves privadas novas na PWA ou localização/código escolhidos pelo dispositivo.
- Instalar primeiro o novo código no escritório. Recetores antigos recusam v2;
  nessa situação conservar o ficheiro original e atualizar, sem recriar a identidade.
- A receção de v2 nunca consulta o catálogo para criar referências nem atualiza stock.
  A proposta é evidência, não uma referência oficial ou autorização administrativa.
- Cofres mantêm esquema/contexto criptográfico v1 com extensão opcional por linha;
  backup `.gvabackup`/`.gvademo`, chaves, ficheiros e exportação manual/Wi-Fi mantêm-se.
- `consultation.0008_reference_proposal_protocol` é marcador de compatibilidade, sem
  alterações de dados. Impede que serviços antigos aceitem uma base com o novo
  protocolo; a reversão é recusada se existirem propostas/evidências novas. Nenhuma
  migração publicada é editada ou renumerada.

## Validação

Testes novos cobrem proposta offline de ambos os perfis, IndexedDB/cofre/backup,
v1/v2, interoperabilidade real PWA→recetor→aprovação, entradas diretas no navegador,
associação a inativas com reativação explícita, rejeição, conflitos, nomes duplicados,
PDF/rollback, confirmações repetidas e concorrência PostgreSQL. O ensaio HTTPS/mTLS
real inclui v2, receção mista, confirmação e retransmissão. O ciclo Windows sintético
inclui referências novas, saldo zero após saída, originais v1/v2 e rascunhos diretos
por aprovar, verificando a sua recuperação sem criar stock adicional.

Sem dados reais, migração em instalações existentes ou instaladores publicados.
Continua pendente homologação física Windows 11/Android e configuração empresarial
de certificados/rede. Resultados efetivos e limitações constam do novo PR draft.
