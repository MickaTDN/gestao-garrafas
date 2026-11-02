# Folhas pendentes: transporte Wi-Fi opcional

Esta etapa acrescenta transporte à mesma PWA e ao mesmo serviço de receção do
PR #29. Não confirma operações, não gera PDFs e não altera o stock. Fábio e Daniel
mantêm identidades, permissões e cofres separados; as encomendas privadas não
participam no envio. A exportação manual continua disponível e usa a mesma
identidade/ficheiro imutável, incluindo quando o primeiro envio perdeu a resposta.

## Separação de acessos

| Acesso | Exemplo | Autorização |
| --- | --- | --- |
| Gestão local | HTTP loopback existente | Conta Django |
| Stock | `https://stock.empresa.example:8444` | Publicador GET-only + autorização individual |
| Gestão Android (PR #28) | HTTPS próprio, porta distinta | mTLS + conta Django/CSRF |
| Receção de folhas | `https://folhas.empresa.example:8446/v1/pending-sheets` | mTLS individual associado ao dispositivo + assinatura/cifra existentes |
| Backend da receção | `127.0.0.1:8767` | Segredo de proxy por instalação + processo verificado |

O serviço opcional `GVASheetReceiver` começa desativado. Não publica PostgreSQL,
Docker, administração ou outros endpoints. O publicador Stock continua apenas a
servir ficheiros por GET: não se transforma num proxy de escrita. O navegador usa
CORS para a origem HTTPS de receção explicitamente autorizada. Não utiliza sessões,
passwords nem cookies Django; o único endpoint isento de CSRF está no URLconf
isolado e exige Origin exata, mTLS, autorização e ficheiro autenticado. A Gestão
mantém as proteções de CSRF existentes.

## Configuração pela informática, sem alterações automáticas à rede

1. Definir DNS interno estável, IP RFC1918, portas distintas e firewall com IPs/CIDRs
   de dispositivos autorizados. Não criar encaminhamento no router. Garantir cadeia
   HTTPS confiável no Android; nunca ignorar avisos TLS.
2. Emitir certificado clientAuth individual por dispositivo e manter CRL atualizada.
   Conferir presencialmente a impressão SHA-256 DER do certificado e a identidade
   da PWA. Autorizar o dispositivo pelos procedimentos existentes da Etapa B/PR #29,
   incluindo permissão específica de folhas. Certificado e assinatura da PWA são
   verificações independentes, ambas obrigatórias.
3. Preparar uma pasta privada com `server-chain.crt`, `server.key`,
   `device-ca.crt`, `device-ca.crl` e `config.json`, por exemplo:

   ```json
   {
     "it_approved": true,
     "address": "192.168.10.10",
     "hostname": "folhas.empresa.example",
     "port": 8446,
     "backend_port": 8767,
     "stock_origin": "https://stock.empresa.example:8444",
     "clients": ["192.168.10.50/32"],
     "devices": {"IMPRESSAO_SHA256_HEXADECIMAL_64_CARACTERES": "UUID_DO_DISPOSITIVO"}
   }
   ```

   Os marcadores devem ser substituídos por valores reais aprovados; a configuração
   de exemplo não passa a validação. Não colocar material privado no repositório.
4. No assistente de manutenção elevado: **Configurar receção de folhas Wi-Fi**,
   selecionar o JSON. A configuração não ativa o acesso. Os certificados ficam na
   pasta privada do recetor, acessível apenas às contas necessárias; o serviço não
   recebe as credenciais de proprietário PostgreSQL.
5. Reiniciar explicitamente o publicador pelos procedimentos existentes para aplicar
   a CSP que permite apenas a nova origem. Transferir o ficheiro público assinado
   `tls/sheet-transport.public.json` para cada PWA, juntamente com a capacidade de
   folhas e a chave pública de receção já autenticadas no PR #30.
6. Após verificar DNS, certificados/CRL e firewall, **Ativar receção de folhas Wi-Fi**.
   Na PWA importar a configuração assinada e autorizar explicitamente o envio. Não há
   envio automático ao detetar rede. Desativar pelo assistente e/ou pela PWA quando
   necessário. Nenhuma destas ações instala certificados, altera DNS ou firewall.

Revogar pela autorização de dispositivo existente (bloqueio transacional na
receção), atualizar CRL e recarregar o serviço. Remover a associação do certificado
na configuração privada sob manutenção autorizada e reiniciar para futuras rotações.
Uma configuração existente nunca é substituída silenciosamente pelo assistente.
Não apagar dados, evidências ou cofres para renovar certificados.

## Confirmações e falhas

A folha preparada mantém UUID, revisão e ficheiro JWE exatos. Antes de enviar é
persistida uma tentativa com nonce aleatório no cofre cifrado. O servidor usa o mesmo
serviço transacional de importação manual e só devolve prova ES256 depois de criar
a receção. Uma falha de assinatura reverte a receção. A prova vincula origem,
dispositivo, UUID/revisão, SHA-256 do ficheiro, nonce, receção e resultado. A PWA
valida a assinatura com a confiança existente antes de indicar:

- **Por enviar:** ainda não existe tentativa/prova.
- **Recebido:** prova válida de receção pendente; não significa movimento confirmado.
- **Duplicado:** prova válida de repetição idêntica, sem nova folha oficial.
- **Conflito:** mesma identidade com conteúdo divergente; revisão administrativa.
- **Falha:** sem prova verificável para a tentativa; conservar e tentar novamente.

Resposta perdida: o servidor pode já ter recebido a folha. Tentar novamente envia
o mesmo ficheiro; o resultado será duplicado, sem alterar stock. Respostas atrasadas
não substituem a tentativa corrente. Uma prova válida anterior não desaparece por
uma falha posterior. Nunca tratar uma mensagem HTTP 200 não autenticada como prova.

## Backups e compatibilidade

O backup existente inclui base de dados/evidências, chaves de receção, configurações
privadas e o ficheiro público em `tls`; o backup cifrado da PWA inclui provas e
tentativas. Marcadores de aprovação em `runtime` não são restaurados: a rede exige
nova aprovação no destino. Não se altera o formato portátil do PR #25.

Base exata: PR #30 `2ad75e5`, que inclui PR #29. Reutilização seletiva do PR #28:
verificação do proprietário do listener, ciclo de proxy nativo e separação de contas;
não integra branches antigas. O PR #31 `4fd1881` é uma linha irmã: na integração
futura é necessária migração de junção entre as duas migrações `consultation.0005`
e `0006_sheet_action_guards`. Não renumerar migrações já aplicadas. A prova de
compatibilidade deve incluir receção seguida de conferência/confirmação explícita
do PR #31; a receção isolada nunca cria movimentos. Adaptar também as contagens dos
fixtures Windows quando as suites forem compostas. Os PR originais ficam intactos.

## Validação e homologação física

- Testes do serviço comum: idempotência ficheiro/Wi-Fi, conflito, revogação,
  adulteração, assinatura da prova/rollback, concorrência PostgreSQL, ausência de
  alteração de stock e recusa de cabeçalhos/origens/cookies forjados.
- Chromium/IndexedDB: ambos os perfis, cofre, falha de rede, repetição, provas
  adulteradas, persistência/backup e interface móvel.
- Integração HTTPS em runner isolado: NGINX mTLS real, PostgreSQL, Chromium Android,
  perda de resposta depois do commit, repetição e revogação sem bypass TLS.
- Windows descartável: serviço/conta virtual reais, certificado confiável apenas no
  cliente do teste, CRL, provas assinadas, atualização e recuperação das evidências.
  Nenhum instalador deste PR é publicado.

Pendente: Windows 11 Home/Pro e Android físicos, seleção de certificado de cliente
entre origens/portas pelo Chrome, DNS/firewall/CA da empresa, suspensão/retoma do
telefone, rotação/revogação real e recuperação noutro Windows com aprovação de rede
desativada. Os runners Windows Server e o viewport Android não homologam estes
comportamentos físicos. Parar perante aviso TLS, divergência de identidade/origem,
prova inválida ou conflito; conservar dados e solicitar revisão administrativa.
