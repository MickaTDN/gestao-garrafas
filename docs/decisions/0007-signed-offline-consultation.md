# Decisão 7 — Vertente Aveludada offline por fotografias assinadas

Uma PWA estática autónoma, em **hostname/origem separados**, mantém IndexedDB local
de consulta e acompanhamento. Reutiliza-se apenas a exportação do stock oficial e
o padrão de publicação HTTPS local da Etapa 6. Não há segundo ledger, movimentos
offline, base PostgreSQL Android ou credenciais do escritório no dispositivo.

Importar fotografias completas evita dependências de movimentos em falta/repetidos.
P-256/SHA-256 nativo WebCrypto é amplamente suportado em Chrome Android; o backend
usa `cryptography`. A assinatura cobre bytes UTF-8 exatos, não uma recanonicalização
em JavaScript. SPKI/fingerprint são instalados por canal independente e confirmação;
o ficheiro de stock nunca fornece a sua própria chave de confiança.

O UUID é persistente na base do escritório e cada referência usa PK qualificada por
essa origem. Uma linha bloqueada serializa sequências de exportação; um único SELECT
das referências ativas cria uma fotografia PostgreSQL consistente, com zero incluído.
Não se toca nos saldos. Contador/assinatura/auditoria da exportação são atómicos.

IndexedDB substitui stock/marcador numa transação, preservando preferências. Mantém
duas cópias verificáveis e um high-water mark mesmo se recuperar a anterior. Ausência
da referência nunca apaga acompanhamento. Encomenda é estado pessoal, não stock.

Backup local de preferências usa AES-GCM e PBKDF2, sem guardar frase-passe. Chaves
privadas ficam apenas no escritório e seu backup cifrado autorizado. Reenrolamento
de chave exige fingerprint independente; revogação não destrói as cópias já aceites.

Atualização automática Wi-Fi fica adiada, para evitar sessão entre origens e CORS
numa aplicação que deve funcionar sem rede. O transporte pode evoluir mantendo o
mesmo formato/validador. Não se criam serviços externos ou custos. Instalação real,
MDM/Android físico, recuperação operacional e publicação de dados continuam sujeitos
a revisão/autorização próprias. Procedimentos em [guia](../vertente-aveludada.md).
