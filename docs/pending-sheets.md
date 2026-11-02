# Etapa 2 — receção de folhas pendentes por ficheiro

Não cria movimentos, pessoas ou referências, não altera stock e não emite PDFs.
A interface administrativa está em Definições → Receber folhas pendentes.
Consulta, perfis personalizados e utilizadores anónimos não podem receber,
descarregar evidências ou revogar autorizações de envio. POST exige CSRF.
Não existe nesta entrega preparação Android, confirmação oficial ou API Wi-Fi.

## Contrato versionado

Ficheiro UTF-8 JSON, até 1 MiB: campos exatos `format=vertente-pending-sheet`,
`version=1`, `jwe=<compact JWE>`. JWE conforme RFC7516/7518, implementado pela
biblioteca jwcrypto bloqueada no uv.lock: RSA-OAEP-256 e A256GCM, sem compressão.
Cabeçalho protegido contém apenas alg, enc e kid (thumbprint RFC7638 da chave de
receção). Não se usam a chave de recuperação nem a chave ES256 para decifrar.

O plaintext JWE é o envelope ES256 existente da Etapa B, com
`format=vertente-sheet`, `version=1`, `algorithm=ES256`, `key_id`, `payload` e
`signature`. A assinatura usa a chave P-256 individual já provisionada e o
contexto `vertente-sheet-v1\0`, através de signed_snapshot; assinatura r||s de
64 bytes, payload UTF-8 e Base64URL sem padding, como os envelopes existentes.

Payload com campos exatos: source_id, device_id, authorization_revision, sheet_id,
revision, kind (entry/exit), physical_date (YYYY-MM-DD), person (1–200 caracteres),
notes (até 4000), lines (1–500). Cada linha contém reference_id (ID estável
exportado pela Etapa B, string até 100), boxes, units e box_capacity. Quantidades
inteiras, não negativas, até 2147483647; null mantém campos não indicados. Caixas
positivas exigem capacidade positiva; total positivo por linha e dentro do limite.
Não se inventam capacidades nem se confundem null e zero. Repetições da mesma
referência e propriedades JSON duplicadas são recusadas.

Data e pessoa são comunicadas pelo dispositivo: não se tornam data oficial nem
um registo de pessoa. Datas anteriores podem permanecer pendentes; as regras de
confirmação existentes não foram relaxadas. Referências desconhecidas, inativas
ou com capacidade alterada são assinaladas para conferência futura.

## Preparação pela informática

1. Aplicar migrações apenas num ambiente sintético/atualização autorizada, com
   backup verificado. Atualizar os grants SQL existentes depois das migrações.
2. Com a identidade ES256 da origem já preparada, executar `pending_sheet_setup`
   no ambiente administrativo nativo. Gera pending-reception.pem (RSA 3072) e
   pending-reception.public.json junto de signing.pem, fora do repositório.
   A chave pública é autenticada pela origem com o contexto
   `vertente-sheet-recipient-v1`, contendo source_id, jwk e key_id. O futuro
   Android deve validar esse envelope pela confiança da Etapa B antes de cifrar.
3. Reautorizar cada dispositivo através de vertente_device com fingerprint
   confirmado presencialmente e a opção explícita `--allow-sheets`. Dispositivos
   anteriores têm envio desligado e SPKI/validade não inventados; não são
   automaticamente autorizados. O formato das autorizações da PWA existente
   permanece inalterado. A permissão de receção é autoritativa no servidor.
4. Conservar a chave privada com ACL da instalação (aplicação/backup, nunca
   utilizadores comuns). No Windows nativo, herda o diretório privado signing.
   Só distribuir o ficheiro público assinado; nunca a chave privada.

Autorizações expiradas, revogadas ou com revisão antiga são recusadas na receção,
mesmo se a data física for anterior. Revogação de envio disponível na interface,
com auditoria. Não promete revogação instantânea da consulta offline Stock.
Não existe rotação destrutiva nesta etapa: o comando recusa substituir chaves.
Conservar chaves e backups; rotação com keyring exige alteração posterior revista.
Perder a chave não permite inventar uma substituta para abrir ficheiros antigos.

## Persistência, auditoria e concorrência

receive_sheet é o único serviço de receção, reutilizável por transporte futuro.
Usa a autorização administrativa persistente, o bloqueio transacional comum,
bloqueios de origem/dispositivo e unicidade SQL (source_id, sheet_id). UUID e
revisão são campos separados; uma revisão diferente não substitui a original.
Conteúdo igual, mesmo recifrado/reassinado, cria recibo duplicate e conserva uma
única folha. Conteúdo divergente cria recibo conflict com o novo ficheiro cifrado;
não funde nem sobrescreve. Transportes futuros devem reutilizar o mesmo UUID.

PostgreSQL guarda a folha, o ficheiro original de cada receção válida, hash,
administrador, instante, resultado e fotografia da autorização verificada.
Triggers e modelos impedem update/delete das evidências. Rejeições de validação
geram auditoria com hash, sem pessoas, observações, segredos ou erro criptográfico
bruto. Ficheiros inválidos não são conservados como folhas aceites.

## Backups e compatibilidade

Backups PostgreSQL incluem as novas tabelas, originais cifrados, snapshots e
auditoria. O backup nativo e o PR #25 já incluem todo o diretório signing: cobrem
também a chave de receção. Backups não nativos só da base não bastam: manter o
diretório de chaves segundo o procedimento existente. Não alterar backups antigos.
Recuperar com código que conheça as migrações novas; reversão com evidência ou
autorizações novas é bloqueada. A reposição de um backup preserva os UUID/hashes
que existiam nesse ponto. Não se promete recuperar receções posteriores à cópia.

PR #28: utiliza as mesmas views, CSRF, permissões e base; não acrescenta transporte
ou endpoints de dispositivo. Não integra nem altera #25/#28. A homologação conjunta
de migração/restauro e o ensaio Windows 11 continuam necessários antes de produção.

O pacote jwcrypto inclui vetores públicos com chaves de teste. São excluídos do
payload Windows; o scanner de material privado continua integral e obrigatório.
As únicas chaves da instalação são geradas posteriormente na pasta privada.
