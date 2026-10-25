# Etapa 7 — Vertente Aveludada

Aplicação pessoal de **consulta e planeamento de reposições**. O stock oficial
continua exclusivamente na Gestão de Garrafas/PostgreSQL do escritório. Esta PWA
não cria entradas, saídas, inventários, compras ou alterações de stock oficial.
Não requer Google Play, subscrição, servidor externo ou ligação permanente.

Entrega em branch própria a partir da Etapa 6, com PR em rascunho para essa branch.
PR #5/#6 e `main` não são integrados nem modificados diretamente. Todo o ensaio usa
dados fictícios e bases novas; a base reservada à pré-visualização Excel não é usada.

## Experiência e funcionamento offline

O nome, manifesto, ecrã inicial e monograma original **VA** pertencem à Vertente
Aveludada. O ícone geométrico usa formas próprias, sem marcas, fontes ou imagens
de terceiros. Não se cria uma segunda aplicação de gestão operacional.

O painel apresenta indicadores clicáveis de referências ativas, stock zero, stock
baixo, por encomendar e acompanhamentos abertos. A lista geral inclui todas as
ativas, mesmo zero. A pesquisa ignora acentos e maiúsculas; há filtros e paginação
progressiva de 50 referências. Capacidades desconhecidas permanecem desconhecidas.
Com capacidade conhecida, caixas completas = divisão inteira e soltas = resto.

**A fotografia nunca é apresentada como stock em tempo real**, mesmo com Internet.
Mostra data/hora da exportação e da importação. Mais de 24 horas gera aviso de
cópia desatualizada; esse prazo é informativo, não é uma garantia de atualidade.
Relógios incorretos também exigem revisão. Os dados não desaparecem por perder Wi-Fi
ou desligar o PC, depois da instalação/importação bem-sucedidas.

O shell offline contém apenas HTML/CSS/JS, manifesto e ícones. IndexedDB contém
fotografias assinadas, chaves **públicas**, limites e acompanhamentos. Não contém
passwords de contas, pessoas, assinaturas, PDFs, movimentos ou chaves privadas.
Não há notificações push, sincronização de movimentos ou pedidos à base oficial.
O arranque usa o shell em cache, sem esperar pelo computador do escritório mesmo
que o Android continue online através de dados móveis ou de outra rede Wi-Fi.

## Alertas e encomendas

1. Abrir uma referência → **Configurar alerta mínimo** → indicar garrafas → guardar.
   Não há alertas ativados por defeito; os limites são independentes dos da aplicação
   do escritório. `stock <= limite` significa stock baixo, incluindo igualdade e zero.
2. Alterar ou **Desativar alerta** na mesma ficha. Não altera stock nem encerra encomendas.
3. Com stock baixo, **Já encomendada** pede confirmação e regista ID estável, data/hora
   local e acompanhamento aberto. Não produz qualquer encomenda documental/compra.
4. Sai da lista **Por encomendar** e mantém-se em **Stock baixo** enquanto o limite
   continuar a ser atingido. A lista **Já encomendadas** mostra os acompanhamentos abertos.
5. **Anular marcação** corrige um engano; **Encerrar acompanhamento** termina-o
   manualmente. Ambos exigem confirmação e preservam o registo no histórico local.

Uma subida de stock após importação **não encerra** uma encomenda. A reposição só
entra no stock oficial por uma entrada confirmada no escritório. Se uma referência
desaparecer/desativar-se, o acompanhamento e o limite mantêm-se; aparece como
**Ausente ou desativada**, sem quantidade ativa inventada. Se regressar com o mesmo
ID, retoma a ligação aos mesmos dados locais. Indicadores de encomendas incluem
os abertos ausentes e assinalam explicitamente quantos estão fora da cópia ativa.

## Origem separada e instalação inicial autorizada

A PWA deve usar **outro hostname HTTPS**, não apenas outra pasta da aplicação
principal. Exemplo fictício: `vertente.wifi.example.invalid:8444`, distinto de
`garrafas.wifi.example.invalid:8443`. Cookies são associados a host, não a porta;
por isso mudar apenas a porta não é a separação recomendada. Não há CORS nem
autorização CSRF entre as duas aplicações.
Manter o URL estável: mudar hostname ou porta cria outra origem de armazenamento.
Antes dessa mudança, exportar as preferências e seguir o mesmo restauro de um novo aparelho.

Reutiliza-se o padrão da [Etapa 6](android-wifi.md): Docker Desktop/WSL2 local,
Nginx não privilegiado, certificado servidor confiável e certificado clientAuth por
dispositivo, CRL e allowlist, sujeitos a aprovação da informática. O publicador
estático tem projeto/rede próprios, **sem PostgreSQL, backend, volumes de dados,
socket Docker ou chave de assinatura**. Só publica o shell, por uma lista explícita
de URLs; ficheiros colocados acidentalmente noutras URLs não são servidos.

A informática tem de aprovar/providenciar:

- DNS interno/reserva de IP, hostname distinto e certificado SAN correto, cadeia
  confiável no Chrome/Android, certificados de dispositivo e CRL atuais.
- Firewall/SSID/VLAN limitados aos dispositivos/rede autorizados; verificar NAT
  Docker Desktop no host, sem alargar silenciosamente a origem. Sem router/UPnP/Internet.
- Pré-requisitos Windows da Etapa 5, execução de scripts, pastas NTFS privadas,
  imagens/dependências aprovadas e aceitação física. O utilizador sem privilégios
  de administrador não deve tentar contornar esses requisitos.

Procedimento de preparação **posterior, só num ensaio sintético novo**:

1. Adaptar [installation.example.json](../deploy/vertente/installation.example.json)
   fora do checkout. `Host` difere de `OfficeHost`, `BindIP` é IPv4 RFC1918 específica,
   porta por defeito 8444, origens autorizadas explícitas. O domínio `.invalid` não existe.
2. A informática fornece `server-chain.crt`, `server.key`, `device-ca.crt` e
   `device-ca.crl` em `TlsSource`. Nunca incluir chaves da CA ou do dispositivo no servidor.
3. Executar no checkout revisto, sob políticas normais de PowerShell:

   ```powershell
   .\scripts\windows-vertente\Preparar.ps1 -Configuration 'C:\ConfiguracaoAprovada\vertente.json' -ITApproved
   ```

   Só prepara uma pasta privada **nova**, por defeito
   `%LOCALAPPDATA%\GestaoGarrafas\VertentePublisher`; não inicia serviços ou altera
   Windows/DNS/firewall/certificados. `-ITApproved` declara aprovação já obtida,
   não concede privilégios. Refusa hostname igual ao escritório, wildcard de rede,
   pasta existente, partilhas e sobreposição com código. Não adota instalações anteriores.
4. Rever `publisher.env`, Nginx, certificados, origens e Compose. Não alterar a
   configuração sem nova revisão. Depois, na pasta do checkout, a informática pode usar:

   ```powershell
   docker compose --env-file "$env:LOCALAPPDATA\GestaoGarrafas\VertentePublisher\publisher.env" -f deploy/vertente/compose.yaml run --rm consultation nginx -t
   docker compose --env-file "$env:LOCALAPPDATA\GestaoGarrafas\VertentePublisher\publisher.env" -f deploy/vertente/compose.yaml up -d
   ```

   Este serviço só serve ficheiros públicos da PWA, nunca dados de stock ou chaves.
   `stop consultation` para; `logs --tail 30 consultation` ajuda no diagnóstico.
   A renovação TLS requer paragem, novos ficheiros aprovados e revisão/teste antes
   do arranque. Não há renovação automática nem instalação de confiança por script.
5. No Chrome Android autorizado, abrir o URL HTTPS sem avisos, selecionar certificado
   de dispositivo e usar **Instalar / Adicionar ao ecrã inicial**. Confirmar o nome
   e ícone Vertente Aveludada. Não ignorar erros TLS nem usar HTTP/IP temporário.
6. Configurar a origem pública e importar um stock assinado, conforme abaixo.
   Antes de sair da rede, testar reabertura em modo de avião, pesquisa e dados locais.

Atualizações do código exigem revisão, `python scripts/build_vertente.py`, paragem
do publicador, substituição coordenada dos ficheiros e novo arranque. O service
worker tem versão derivada do conteúdo e espera o fecho da versão anterior antes
de ativar a nova; não apaga IndexedDB nem repõe preferências durante atualizações.
`--check` verifica que o shell gerado corresponde ao código. Não guardar ficheiros
recebidos ou backups no diretório público `vertente/`.

## Preparação de assinatura no escritório

Formato de ficheiro v1: JSON `vertente-stock`, algoritmo **ECDSA P-256/SHA-256 (ES256)**,
key ID SHA-256 do SPKI público, payload UTF-8 em Base64URL e assinatura de 64 bytes
`r || s`. Verifica-se a assinatura dos bytes exatos antes de interpretar os dados.
Hashes sem chave não são usados como prova de autenticidade.

A migração `consultation/0001` acrescenta apenas identidade UUID/counter de exportação.
Não cria referências, stocks ou contas. **Não executar migrações na base reservada**.
O código não assume que os dados reais já foram publicados. Reaplicar os grants de
`deploy/app-role.sql` com o owner após migrações numa instalação autorizada; a conta
web lê referências e só modifica os metadados de exportação/auditoria.

Numa stack sintética preparada pela informática, criar uma chave num diretório
privado dedicado **fora do checkout**, montado só durante a preparação, por exemplo
`/keys`. O Python usado é o da imagem existente; não é preciso instalar Python no Android.

```text
python manage.py vertente_setup --directory /keys
```

O comando cria `signing.pem` (privado, exclusivo, sem sobrescrever) e
`origin.vatrust.json` (UUID e chave pública), com ficheiros 0600 no Linux. No Windows,
a pasta de origem tem de ter ACL NTFS restrita ao operador/SYSTEM, validada pela
informática; modos POSIX no contentor não substituem ACLs. Não é criada conta/password.

Montar a **chave privada apenas na aplicação do escritório**, só de leitura, e definir
`VERTENTE_SIGNING_KEY_FILE`. O overlay opcional
[`export.compose.yaml`](../deploy/vertente/export.compose.yaml) lê `VA_SIGNING_KEY_FILE`
externo ao código. Acrescenta-se explicitamente ao Compose original durante uma
instalação revista; não abrir o mesmo volume noutra base ou alterar projetos existentes.
Arranque diário não cria/regera chaves nem migra. Sem chave/origem configuradas,
a exportação falha fechada com instrução para contactar a informática.

Depois de ativar esse overlay, **todos os arranques/paragens/recriações da aplicação
do escritório devem usar o mesmo projeto, env-file, Compose base e overlay**, com
`VA_SIGNING_KEY_FILE` definido pelo processo aprovado. A informática deve preparar
o respetivo atalho/rotina, conservando a verificação de contexto Docker local da
Etapa 5. Os atalhos base das Etapas 5/6 não incluem este overlay: não os usar como
rotina diária dessa configuração, pois podem recriar o serviço sem a chave e
desativar a exportação. Isso não apaga stock nem preferências; recuperar a
configuração revista, sem regenerar chaves ou inicializar/adotar outra base.

**Instalar confiança no Android:** transferir apenas `origin.vatrust.json`.
Em **Atualizações e cópias → Origem e chave autorizadas**, selecionar o ficheiro,
introduzir o fingerprint SHA-256 completo confirmado pela informática por canal
independente e confirmar o UUID/fingerprint apresentados. Não copiar apenas o
fingerprint do mesmo ficheiro não verificado. A origem fica fixada: outro UUID é recusado.
Não há download automático de chaves indicado por um remetente ou atualização.

## Exportar e importar stock

No escritório, entrar com conta individual Administrador ou Consulta, abrir
**Exportar → Exportar stock para Vertente Aveludada**, e confirmar o download.
O POST exige sessão e CSRF. O ficheiro contém apenas UUID de origem, UUID de atualização,
sequência, data/hora UTC e referências ativas com PK estável, código, designação,
garrafas e capacidade nullable. O ID é qualificado pelo UUID de origem; não é o nome.
Desativadas ficam fora; zero continua incluído. Pessoas, histórico, PDFs, assinaturas,
locais internos, mínimos pessoais e credenciais não são exportados.

Uma linha de identidade bloqueada serializa exportações e atribui sequência crescente.
Todas as referências/campos são obtidos por **um único SELECT**, cuja fotografia
PostgreSQL inclui apenas dados confirmados no instante dessa instrução. Não há
paginação SQL entre instantes nem leitura de alterações ainda por confirmar. A
operação não altera quantidades nem cria movimentos. Falhas de assinatura revertem
contador e auditoria da exportação. O relógio do servidor não pode recuar.

Enviar o ficheiro `vertente-stock.vastock.json` por WhatsApp/email/meio autorizado,
sem integrar esses serviços no código. A assinatura garante autenticidade/integridade,
**não cifra a fotografia de stock**: restringir destinatários e proteger o transporte.
Não partilhar a chave privada nem publicá-la no publicador estático.

No Android: **Atualizações e cópias → Importar atualização de stock**, escolher o
ficheiro. Pode importar mesmo sem rede. O processo valida formato/versão, chave ativa,
assinatura, origem, sequência, UUID/data, campos/quantidades/capacidades e duplicados.
Recusa versões não suportadas, ficheiros repetidos/antigos, origem errada, chaves
revogadas/desconhecidas, datas mais de cinco minutos no futuro e conteúdo inválido.
Requer relógios corretos e um Chrome atualizado com WebCrypto/IndexedDB.

A substituição da **fotografia completa** e do marcador da atualização é uma única
transação IndexedDB. Não soma stocks/movimentos/diferenças. Alertas e encomendas
não são repostos. Revalida confiança/marcador dentro da transação para detetar outra
janela que tenha atualizado durante a verificação. Erro, falta de espaço ou falha
de escrita conservam a cópia anterior. Mantém as duas últimas cópias verificadas;
se a atual ficar ilegível, tenta a anterior e avisa. O maior número aceite é mantido
para impedir que essa recuperação permita uma importação antiga.

Limites v1: ficheiro até 4 MiB, até 10 000 referências por fotografia, inteiros
não negativos até 2 147 483 647 e capacidade positiva ou desconhecida. Sem recalcular
capacidades, mínimos globais ou alertas de todas as referências automaticamente.

## Chaves: rotação, revogação e recuperação

- **Backup:** guardar, por processo aprovado pela informática, cópia cifrada da
  chave privada em suporte separado, a chave pública/fingerprint e backup PostgreSQL
  com UUID e sequência. Não incluir a chave privada no dump/ficheiro de stock/Android
  ou Git. Usar cifragem autenticada/cofre ou ferramenta aprovada; não colocar frases-passe
  em argumentos, scripts, logs ou código. Testar restauro e fingerprint numa stack fictícia.
- **Rotação:** executar `vertente_setup` noutro diretório novo, com a mesma base/UUID.
  Confirmar o novo ficheiro público/fingerprint no Android por canal independente,
  depois mudar o mount/segredo do escritório numa janela revista. Chaves antigas
  deixam de aceitar novas importações, mas permitem verificar cópias históricas já
  guardadas. Não muda IDs, sequência, limites ou encomendas. Não há rotação silenciosa.
- **Perda/compromisso:** suspender exportações, revogar/rodar a chave, reenrolar o
  fingerprint novo. Uma chave perdida não se extrai do Android; restaurar a cópia
  privada cifrada ou emitir nova chave para a mesma origem. Reinstalar uma origem
  diferente não é uma recuperação: é recusada para proteger dados existentes.
- **Restauro da base:** preservar UUID e metadados. Uma base restaurada pode ter
  sequência inferior à já aceite no Android. Primeiro reconciliar integralmente o
  **stock oficial** com a informática; nunca aumentar sequência para fazer passar
  stock antigo. Só depois, se necessário, recuperar o contador, explicitamente:

  ```text
  python manage.py vertente_sequence --source UUID_CONFIRMADO --after MAIOR_SEQUENCIA_ACEITE --reason "Reconciliação e recuperação revistas" --confirm-reconciled
  ```

  Só altera metadados de exportação, nunca quantidades. Recusa origem diferente,
  recuo e falta de confirmação, e deixa auditoria. UUID/maior sequência podem ser
  consultados em **Origem e chave autorizadas**. Não podem existir duas origens
  operacionais exportando com o mesmo UUID/chave após clonar um backup.

## Backup das preferências do proprietário

Em **Proteger preferências**, escolher/repetir frase-passe de pelo menos 12 caracteres
e exportar `vertente-preferencias.vaprefs.json`. A frase-passe não é guardada. O ficheiro
usa PBKDF2-SHA256 (600 000 iterações, salt aleatório) e AES-GCM-256 com IV aleatório
e autenticação. Contém apenas origem, alertas, acompanhamentos/datas/estados e os
códigos/designações necessários a identificar referências históricas, sem stock,
credenciais, PDFs ou chaves. Não enviar a frase-passe junto do backup.

Para trocar de telemóvel: instalar a PWA no URL autorizado, reenrolar a mesma origem
com fingerprint independente, importar a fotografia assinada recente e **Restaurar
preferências** com ficheiro/frase-passe. Apresenta os totais e exige confirmação para
substituir as preferências; o stock não é alterado. Origem errada, frase-passe errada,
ficheiro alterado ou falha de escrita não substituem os dados locais. Limites v1:
até 10 000 registos por coleção; pedir evolução do formato antes de ultrapassar limites.

Sem a frase-passe não há recuperação do backup cifrado. Sem backup, limpar os dados
do Chrome, desinstalar, trocar/perder o aparelho ou remoção de armazenamento pelo
sistema pode eliminar as preferências. Pedir armazenamento persistente ao browser
ajuda mas não substitui backup. O stock recupera-se por uma nova fotografia do escritório.
Não há recuperação automática por cloud. Proteger o Android com bloqueio de ecrã,
cifragem/MDM aprovados; IndexedDB não constitui autenticação contra quem desbloqueou
o dispositivo. O backup é cifrado; os dados de consulta em uso ficam no armazenamento
isolado do browser e dependem da proteção do dispositivo.

## Wi-Fi e validação física pendentes

Atualização direta pelo Wi-Fi fica para melhoria futura: autenticação entre origens,
gestão segura de sessão/CSRF/CORS e transição offline acrescentariam complexidade.
Não se alargam permissões da aplicação principal. Hoje pode descarregar o ficheiro
autenticado na infraestrutura da Etapa 6 e importá-lo, com a mesma validação criptográfica.
Nunca se abre PostgreSQL ou se guardam passwords para sincronizar em segundo plano.

Os testes automáticos não instalam a PWA no Android real. A aceitação física inclui:
certificados/MDM/seleção clientAuth em Chrome e PWA; instalação/ícone; abertura em
modo avião e após reinício; ficheiros recebidos por aplicações autorizadas; seletor
de ficheiros/permissões Android; importação após muito tempo offline; relógios;
backup/restore noutro aparelho; limites de armazenamento/limpeza; acessibilidade/touch;
DNS/NAT/firewall e ausência de acesso por redes não autorizadas. O ensaio HTTPS usa
um adaptador efémero de certificado só de teste, como na Etapa 6, sem ignorar TLS.

Não foram instalados serviços no PC real nem dispositivos reais, publicados stocks,
ligada a base reservada, criadas contas externas/custos ou feitos merges.
