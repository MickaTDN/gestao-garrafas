# Etapa 4 — decisões sobre folhas pendentes

Base: PR #29, revisão d9eafe9. Não altera a PWA Android nem o protocolo de ficheiros.
O PR #30 permanece numa branch irmã, sem integração automática.

## Fluxo administrativo

1. **Entradas pendentes / Saídas pendentes**, no menu da Gestão, com filtros por
   estado e paginação. Origem Fábio/Daniel determinada pela autorização imutável
   guardada na receção, nunca pela pessoa que entregou/levantou. Pessoa, data física,
   referências, caixas, garrafas, capacidades e observações são mostradas separadamente.
2. Abrir a folha, consultar originais e eventuais ficheiros divergentes. A primeira
   folha recebida e todos os ficheiros permanecem imutáveis. Um conflito não substitui
   essa folha. Exige conferência explícita dos conflitos e um motivo antes de prosseguir.
3. Corrigir uma **versão de trabalho**, com motivo obrigatório. Pode associar uma
   referência desconhecida a uma referência existente, corrigir pessoa/data comunicada,
   observações, capacidade e quantidades, retirar linhas ou preencher a linha adicional.
   As correções mostram 30 linhas por página, sem aumentar limites globais de pedidos.
   Guarde antes de mudar de página; as restantes linhas são preservadas no servidor.
   Pode repetir a edição para acrescentar outras linhas, até 500. Não cria referências
   nem atribui localizações automaticamente. A operação anterior permanece auditada.
4. **Conferir folha** valida referências ativas, capacidade atual, localização/setor,
   quantidades positivas e stock disponível. Guarda uma fotografia do catálogo/stock,
   versão de stock, conflitos conhecidos, data oficial e token exclusivo. Não cria
   rascunhos operacionais, pessoas, documentos ou movimentos nesta fase.
5. **Confirmar movimento oficial**, com checkbox explícita. Entradas exigem escolha
   de PDF; saídas mantêm PDF obrigatório e validação simples ou assinatura desenhada,
   com o componente e validações existentes. Só agora se executam create_draft,
   save_draft, review_draft e confirm_movement, dentro da mesma transação. O rascunho
   operacional interno não fica exposto para edição ou confirmação por outro caminho.
6. Em alternativa, **Rejeitar folha**, com motivo obrigatório, sem stock ou documentos.
   Confirmação e rejeição são decisões terminais. Correções posteriores de movimentos
   confirmados continuam a usar os ajustes relacionados existentes, sem reescrever dados.

Depois da confirmação, a folha liga ao movimento numerado e ao PDF existente, quando
aplicável. Reabrir, atualizar a página ou repetir um pedido com o mesmo token devolve
o mesmo movimento. Não volta a produzir PDF, assinatura, número ou efeito quantitativo.
As listagens permitem consultar decisões concluídas e a auditoria.

## Datas e concorrência

A data física é informação comunicada, conservada no original, nas versões de trabalho
e na proveniência do movimento. **A data oficial é a data atual do servidor**, tal como
nas operações existentes; não é editável através do pedido HTTP. Uma conferência de
outro dia exige nova conferência. Não se alteram as regras de datas de confirm_movement.

Se o stock/capacidade/localização/setor/estado mudar, incluindo stock que mudou e voltou
ao mesmo número (ABA), a confirmação recusa e exige nova conferência. Novos conflitos
de ficheiros também invalidam a conferência. Repetições idênticas de receção não a
invalidam nem criam uma nova folha. Uma receção posterior não reabre uma decisão terminal.

Ordem dos bloqueios: autorização comum → catálogo → folha recebida → referências em
ordem estável. A confirmação reutiliza os mesmos bloqueios e serviços das operações.
Só administradores podem decidir; Consulta e perfis operacionais personalizados não
podem processar pendentes. CSRF e validação da sessão mantêm-se.

Stock, pessoa, movimento, numeração anual, assinatura, PDF e decisão final são atómicos.
Uma falha de validação ou produção do PDF reverte tudo; a conferência permanece para
repetição segura. É guardada uma categoria de falha na auditoria, sem conteúdos, assinatura,
credenciais ou tracebacks. Falha de comunicação depois do commit não permite duplicar:
o token original identifica o mesmo resultado já confirmado.

## Persistência e integridade

SheetAction é um registo separado, append-only, com sequência única por folha, ator,
motivo, fotografia da versão de trabalho e decisão. Uma relação exclusiva liga a única
confirmação ao movimento oficial. PostgreSQL protege update/delete, a sequência, o estado
terminal e a correspondência com o movimento confirmado. A folha e os recibos do PR #29
não são modificados. Não há outra base ou outro livro de stock.

Migrações consultation.0005/0006 e grants aditivos: INSERT na tabela de decisões;
nenhuma autorização de alteração/eliminação de evidências. Aplicar como proprietário
do esquema numa atualização autorizada, repetindo os grants existentes. A reversão
destrutiva com decisões é recusada. Não iniciar código antigo sobre este esquema migrado.

Backups/restauros Windows incluem automaticamente as novas tabelas, ligações, PDFs,
auditoria e originais, além das chaves já incluídas por #29/#25. Não se migram nem se
alteram instalações existentes nesta tarefa. O ensaio nativo acrescenta entrada e saída
pendentes confirmadas, com efeito líquido zero, correção auditada, PDF/assinatura e
identidade oficial, verificando restauro real e repetição idempotente após recuperação.
O probe de migração sintético segue a última migração aprovada, sem criar folhas rivais
no grafo e sem entrar em pacotes de produção.

## Validação e limites

Testes de serviços, HTTP/CSRF, Chromium computador/telemóvel, adulteração de pedidos,
rollback de PDF e da decisão final, imutabilidade, datas, múltiplas referências,
capacidades desconhecidas, idempotência e concorrência real PostgreSQL. Ensaios nativos
Windows decorrem exclusivamente no runner sintético. Homologação física Windows 11 e
homologação conjunta com #25/#28/#30 permanecem necessárias antes de produção.

Sem envio Wi-Fi, alterações Android, publicação de instaladores ou dados reais.
