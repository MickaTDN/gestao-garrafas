# ADR0006 — Distribuição nativa Windows e atualizações conservadoras

Estado: proposta implementada para homologação sintética, PR em rascunho.

O objetivo é remover a dependência de Docker Desktop/WSL2 sem reescrever Django,
PostgreSQL ou a PWA da Etapa B. Inno Setup fornece assistente, UAC e desinstalação;
Python privado e wheels bloqueadas evitam um Python global. Waitress substitui
apenas Gunicorn no Windows. Um anfitrião .NET10 LTS autocontido implementa serviços
e atalhos sem consola. O navegador mantido pela empresa evita distribuir Chromium
ou exigir WebView2. NGINX reutiliza as proteções mTLS/CRL e o template revisto.

Serviços com contas virtuais e DACLs distintas separam cluster, aplicação,
backups e publicador. SQL web mantém os grants existentes; migrações usam owner.
ProgramFiles contém versões imutáveis, ProgramData contém dados e identidade.
Não adotar bases/pastas externas e não converter automaticamente pilotos Docker.

Não se pode tornar ficheiros, SCM e migrações uma transação ACID única. Por isso,
o atualizador grava diário, desativa autostart, exige backup cifrado efetivamente
restaurado e comparado antes de migrar e falha com os serviços bloqueados.
Não executa migrações inversas nem um rollback binário isolado. A recuperação
sempre cria uma instalação nova com o código correspondente ao backup.

Pacotes são assinados ECDSA-P256 e o instalador de distribuição exige
Authenticode com pin do editor. Atualizações usam confiança instalada. Chaves de
pacote, backup e exportação Android são independentes. Backups usam AES-GCM por
arquivo e RSA-OAEP para uma privada de recuperação cifrada e guardada à parte.

Consequências: instalação/manutenção requer informática; uso diário não. É
necessário gerir fornecedores, licenças, assinatura de código, recuperação e
homologação Windows11/Android. Artefactos sintéticos da CI não conferem confiança
de produção. A [documentação](../windows-native.md) explicita o procedimento e
as limitações, sem alterar bases existentes ou políticas do Windows.
