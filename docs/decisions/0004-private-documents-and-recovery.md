# Decisão 4 — documentos privados, PWA e recuperação

Data: 2026-10-23. Arquitetura mantida: Django 5.2 LTS, Python 3.12, PostgreSQL 17.

## Documentos na mesma transação do stock

Guardar um ficheiro no disco e confirmar uma transação SQL não constitui uma
única transação. Uma falha entre essas ações pode deixar stock sem PDF ou um
ficheiro sem movimento. Nesta aplicação, os PDFs e PNGs pequenos ficam em
`Document.payload` (bytea), com tamanho, tipo, SHA-256 e snapshot dos dados.
PostgreSQL é o armazenamento privado persistente; não existe URL de media pública.
A confirmação grava stock, assinatura, PDF e auditoria na mesma transação.
Uma falha na geração/armazenamento reverte tudo, incluindo a assinatura.

O custo é aumentar o tamanho da base e dos backups. Para este volume e documentos
limitados a 8 MiB, privilegia-se integridade e recuperação simples. Uma futura
migração para armazenamento de objetos exige um protocolo de publicação/outbox,
verificação e recuperação, sem alterar documentos históricos.

ReportLab gera A4 paginado com fontes incorporadas. Os valores vêm dos snapshots
no momento da confirmação: designação, capacidade, caixas/unidades efetivamente
introduzidas, contagem, saldos, motivos, pessoa, responsável e transferências.
Texto é escapado antes da composição. O PDF é guardado uma única vez, não é
recalculado ao abrir. Correções geram documentos novos relacionados, preservando
o original. Não são criados PDFs retroativos para Excel ou movimentos anteriores
sem ficheiro. Metadados antigos sem bytes não são documentos disponíveis.

A entrada exige escolha explícita; «Não» confirma sem documento. Saídas e
inventários geram PDF obrigatoriamente. Assinatura é opção apenas da saída.

## Assinatura e acesso

Canvas com Pointer Events suporta rato e toque, limpeza e nova assinatura.
O servidor só aceita PNG limitado a 256 KiB, dimensões até 2048×1024 e uma imagem
única não vazia; verifica descodificação, rejeita outros formatos disfarçados e
remove metadados ao recodificar. O limite global de POST é 1 MiB. Confirmar com
assinatura exige bytes válidos; um metadado ou campo de validação forjado não
substitui a imagem. É assinatura desenhada, não assinatura digital qualificada.

Consulta e Administrador podem abrir documentos de movimentos confirmados após
autenticação. O endpoint verifica tamanho/checksum em cada leitura e falha fechado
com HTTP 503 se houver corrupção. Download e impressão usam o PDF original.
Não há acesso público por chave de armazenamento nem geração por GET.
Documentos confirmados têm proteções ORM e trigger PostgreSQL; existe no máximo
um documento guardado de cada tipo por movimento.

## PWA e exportações

Manifesto, ícones e service worker dão elegibilidade de instalação nos browsers
compatíveis, exigindo HTTPS fora de localhost. Só entram na Cache Storage uma
lista fechada de recursos públicos e a página genérica offline. Os nomes com hash
da recolha estática de produção são usados nessa lista. A versão da cache deriva
do conteúdo dos recursos; atualizações eliminam apenas caches públicas antigas
da aplicação. Páginas de stock, login, documentos e assinaturas nunca são guardadas.
POST não é intercetado, não existe fila/sincronização de escritas. Offline mostra
uma mensagem genérica e bloqueia os botões de escrita; sem servidor não confirma.

Exportações XLSX respeitam autenticação, filtros e estado. Textos iniciados por
caracteres interpretáveis como fórmulas são escapados; números negativos continuam
numéricos. Ausência de capacidade/contagem mantém-se vazia, não zero. Não entram
hashes de passwords, ficheiros, assinaturas ou payloads brutos da importação.
Os campos originais de documento/etiqueta do histórico mantêm-se quando aplicáveis.

## Utilizadores e proteção de login

Gestão de contas exige Administrador, CSRF e palavra-passe atual do operador;
alterações de perfil/estado exigem motivo e confirmação. Não se apagam contas,
não se permite desativação/despromoção da própria conta e mantém-se um
administrador ativo. Campos de superutilizador/staff não são aceites pelo formulário.

A limitação de login usa buckets PostgreSQL por identidade e endereço, com
identificadores HMAC sem nomes/IP em claro. Reserva tentativas antes da verificação
da password, sob bloqueio, para não permitir bypass concorrente. A janela e limites
são configuráveis. Cabeçalhos de endereço são ignorados salvo se o peer estiver
numa lista explícita de proxies confiáveis e fornecer um único endereço válido.
O proxy deve substituir esses cabeçalhos e o backend não pode estar exposto.

## Backups

O comando cria um pg_dump custom PostgreSQL 17, cópias verificadas dos documentos
e manifesto com checksums/tamanhos. Um bloqueio de sessão coordenado com as
confirmações impede que novos documentos entrem entre dump e cópia. Isto pausa
escritas de stock durante o backup; convém agendar fora de horas e monitorizar
crescimento. A base contém os bytes, pelo que o dump já conserva os documentos;
as cópias separadas permitem inspecionar a integridade e recuperar ficheiros.

Arquivos são preparados num diretório 0700 externo ao checkout, publicados por
rename atómico com modo 0600, e só depois é aplicada retenção. Produção exige
cifragem GPG para uma chave pública configurada pelo operador. A chave privada
fica separada. O temporizador systemd é um modelo, não está instalado/ativado.

O restauro automatizado desta entrega aceita apenas backups marcados sintéticos
e uma base nova `garrafas_restore_...`. Nunca remove/substitui um destino existente.
Depois do pg_restore verifica os bytes dos documentos na própria base restaurada.
O procedimento de produção é manual, para um destino novo, com revisão e
verificação antes de mudar a aplicação. Checksum comprova integridade, não a
origem de um arquivo não confiável: só restaurar backups próprios protegidos.

## Estado operacional

A imagem e configurações preparam um servidor sem o publicar. HTTPS, PostgreSQL
com TLS, conta restrita, armazenamento separado, chave de backups, monitorização,
retenção legal, recuperação num segundo sistema e validação em dispositivos reais
continuam dependentes da infraestrutura e dos seus operadores. A validação
sintética não prova que existem backups ou operação de produção.
