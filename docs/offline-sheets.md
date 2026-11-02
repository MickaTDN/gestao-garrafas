# Etapa 3 — folhas pendentes na Stock Vertente Aveludada

PR dependente de #29, sem integração de branches anteriores. A mesma PWA apresenta
**Preparar folhas → Preparar entrada / Preparar saída**. Os nomes visíveis são
**Fábio** (`owner`) e **Daniel** (`employee`), incluindo a escolha no assistente de
ativação. A escolha só é aceite se corresponder à autorização assinada; não concede
permissões nem permite trocar livremente de perfil. Utilizar dispositivos/perfis
de navegador separados, como na Etapa B. As encomendas continuam exclusivas de Fábio.

## Preparação pela informática

1. Manter a origem e a identidade individual da Etapa B, verificadas presencialmente.
2. Aplicar o procedimento do PR #29: `pending_sheet_setup` e reautorização através
   de `vertente_device --allow-sheets`, com fingerprint confirmado. Não regenerar
   identidades nem substituir chaves existentes.
3. Exportar a permissão pública assinada da mesma revisão:
   `pending_sheet_authorize --device <UUID> --output <pasta-privada-absoluta>/folhas-permissao.json`.
   O comando não concede novas permissões: recusa dispositivos não autorizados,
   expirados ou revogados. A autorização original de consulta mantém o seu formato.
4. Na PWA, importar a permissão individual e `pending-reception.public.json` em
   **Preparar folhas → Autorizações e chave de receção**. Só estes ficheiros públicos
   assinados são transferidos; nunca o PEM privado. São verificados pela origem
   já fixada, dispositivo, chave e revisão. Não há confiança por nome de ficheiro.
5. Criar uma frase-passe individual dos rascunhos, com pelo menos 16 caracteres,
   distinta da frase do cofre de encomendas. Não é guardada nem recuperável.

Fábio e Daniel podem preparar apenas quando a respetiva permissão assinada o permite.
Sem ligação, uma revogação posterior não pode ser conhecida imediatamente pela PWA;
o escritório repete obrigatoriamente a validação atual de revogação/validade/revisão.
Uma permissão de consulta ou de importação de stock não é permissão de folhas.

## Utilização offline

Guardar, reabrir, editar e cancelar rascunhos locais. Pode guardar campos ainda
vazios; caixas e garrafas começam vazias e não se convertem implicitamente em zero.
Para exportar são obrigatórios pessoa, data física, pelo menos uma referência e
quantidade inteira positiva por linha. Caixas exigem capacidade conhecida. Não se
impede preparar uma saída superior à fotografia de stock: é uma comunicação
pendente, nunca uma reserva ou confirmação oficial. O escritório validará o stock
atual na etapa de conferência futura.

A pesquisa ignora acentos e maiúsculas, por designação/identificador. Cada linha
conserva a capacidade da cópia utilizada, mesmo após novas importações de stock.
Referências ausentes de cópias posteriores não são apagadas dos rascunhos. O serviço
do PR #29 assinala desconhecidas/inativas/capacidades divergentes, sem criar referências.

Guardar alterações antes de sair ou exportar. Rever a folha e confirmar a exportação
disponibiliza um `.vasheet` JWE RFC7516/7518, gerado por **jose**, RSA-OAEP-256/A256GCM.
O envelope ES256 interno usa a identidade não exportável da Etapa B, o contexto
`vertente-sheet-v1\0` e exatamente os campos do PR #29. Sem bibliotecas remotas/CDN
em execução, sem protocolos criptográficos alternativos.

O UUID é criado uma vez; cada edição/cancelamento incrementa a revisão. A exportação
persiste atomicamente o ficheiro antes de o oferecer para descarga. Depois, a folha
fica imutável: reexportar devolve exatamente o mesmo ficheiro, UUID e revisão, mesmo
se a primeira descarga foi cancelada. Não há reescrita ou reassinatura silenciosa.
**Exportada não significa recebida nem confirmada pelo escritório.** O cancelamento
local não comunica ao escritório nem anula um ficheiro já transferido. Não existe
envio Wi-Fi ou confirmação oficial nesta entrega.

## Proteção, cópias e recuperação

Rascunhos/pessoas/observações/ficheiros exportados são guardados cifrados e autenticados
em IndexedDB, num cofre separado das encomendas. Reutiliza PBKDF2-SHA256/600000 e
AES-256-GCM da Etapa B, com salt/IV aleatórios e contexto separado por origem e
dispositivo. A chave de sessão fica apenas em memória; bloqueio após cinco minutos
de inatividade, bloqueio explícito ou recarregamento. Campos privados são ocultos
quando a aplicação passa para segundo plano. CSP e publicador só de leitura mantidos.

Exportar uma cópia cifrada de folhas e guardar a frase-passe separadamente em suporte
autorizado. Recuperar junta folhas ausentes e recusa qualquer conflito com uma folha
local: não reverte exportações ou revisões silenciosamente. Frase errada, corrupção,
origem/dispositivo errado e falhas de persistência preservam a cópia anterior.

**Limitação:** esta cópia recupera o cofre de folhas no mesmo perfil/dispositivo com
a identidade original; não exporta a chave privada não extraível. Limpar todo o Chrome,
desinstalar ou trocar de dispositivo pode perder essa identidade. Não prometer
recuperação automática noutro dispositivo. Cópias antigas de rascunhos podem anteceder
exportações: qualquer reenvio conserva UUID e será deduplicado ou assinalado como
conflito pelo escritório. As cópias de encomendas existentes mantêm-se independentes.

Backups Windows/PR #25 continuam a cobrir os pendentes já recebidos, originais e chaves
do servidor. Rascunhos guardados exclusivamente no Android não existem no Windows.
Não há alterações de esquema ou regras de stock nesta etapa.

## Build e validação

`npm ci --ignore-scripts`, `node scripts/build_jose.mjs` e
`python scripts/build_vertente.py`. O bundle JOSE versionado contém licença MIT,
é reproduzível a partir do package-lock e verificado na CI; npm audit também é
obrigatório. Node/npm não são necessários no Android nem no Windows instalado.

Testes Chromium/IndexedDB cobrem ambos os perfis, offline, proteção/persistência,
quantidades, cancelamento, imutabilidade, cópias e falhas/concorrência. Interoperabilidade
gera realmente o ficheiro no Chromium e recebe-o no serviço PostgreSQL do PR #29;
valida duplicados, adulteração e recusas de dispositivos desautorizados, sem stock,
movimentos ou documentos oficiais. Regressões da consulta, cofre, FIFO e HTTPS/mTLS
continuam nos testes existentes.

Antes de produção: homologar fisicamente em Android, incluindo seleção de ficheiros,
downloads/pastas autorizadas, bloqueio/segundo plano, atualização da PWA e recuperação;
homologar em conjunto Windows/PR #25/#28/#29. Nenhuma instalação existente é alterada.
