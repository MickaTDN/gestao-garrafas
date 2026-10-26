# Etapa B — Stock Vertente Aveludada

Branch `stageb/stock-vertente-aveludada`, criada da `main` integrada até A4
(`161119b9de379d13af23c92ef002a5425c386e87`). Entrega em PR **em rascunho para main**;
não integra nem altera os PR #6/#7. Não requer instalação/testes no computador pessoal.
Todas as validações usam bases, chaves, certificados e dados sintéticos novos.

## Trabalho recuperado e âmbito

| Origem preservada | Componentes reutilizados | Adaptação B |
|---|---|---|
| PR #6, `d97eadd` | Arquitetura TLS/mTLS, certificados/CRL por dispositivo, DNS separado, restrições de rede, adaptador de teste Chromium | Usados pelo publicador estático separado; não se ativam as operações Wi-Fi da Gestão. |
| PR #7, `3b5bc4d` | Módulo `consultation`, identidade/contador, ES256/WebCrypto, IndexedDB transacional com duas cópias, shell PWA, DOM seguro, publicador Nginx, preparação PowerShell e testes | Protocolo v2 com receções, perfis assinados, cofre cifrado, atribuição FIFO, marca Copo com Vida e pesquisa apenas por nome. |

A recuperação é seletiva: não se substituem templates, serviços transacionais,
modelos de stock, renderizador PDF, passwords, perfis ou a PWA da Gestão por versões
antigas. Não há duas bases oficiais nem sincronização de movimentos. O publicador
não tem Django/PostgreSQL, rede da base, chave de assinatura ou API de escrita.

A consulta chama-se **Stock Vertente Aveludada**. Fundo creme, verdes da marca e
copo verde original; o compilador usa a mesma máscara do raster original da Copo
com Vida, sem traçar/redesenhar. Os ícones verdes-escuros/copo branco da Gestão e
o logótipo completo ficam intactos. `tests.vertente.branding` compara os píxeis.

## Utilização no Android

Depois da preparação autorizada descrita abaixo:

1. Chrome atualizado → URL HTTPS da consulta, distinto do URL da Gestão, sem avisos.
2. Menu **Instalar aplicação / Adicionar ao ecrã inicial**, ou botão Instalar.
3. Instalar origem pública, confirmar fingerprint por canal independente e exportar
   o pedido do dispositivo. A informática entrega a autorização assinada correta.
4. Proprietário: criar/desbloquear o cofre com frase-passe de pelo menos **16 caracteres**;
   preferir várias palavras aleatórias. Guardar uma cópia cifrada e a frase separadamente.
5. Em **Atualizações e cópias → Importar Stock**, escolher o ficheiro recebido por
   WhatsApp/email/meio autorizado. Não se integra nem lê automaticamente essas aplicações.
6. Após sucesso, pode apagar **manualmente** o ficheiro recebido: o stock está em IndexedDB.
   Não se apagam automaticamente ficheiros, documentos ou pastas do Android.

A abertura mostra as referências da última cópia, incluindo zero, e pesquisa dinâmica
pelo **nome**, ignorando acentos/maiúsculas. Clicar abre caixas/soltas, total,
localização e setor. Sem capacidade conhecida, mostra apenas garrafas. Não mostra
códigos técnicos na consulta normal. Os campos de encomenda começam vazios.

Data/hora da exportação e da importação permanecem visíveis. Após 24 horas, avisa
que a cópia está desatualizada; mesmo online não afirma stock em tempo real. O shell
abre da cache imediatamente e funciona sem o PC. Entradas/saídas/inventários oficiais
não existem nesta PWA. Não há APK, push, sincronização em segundo plano ou servidor externo.

## Perfis e fronteira de segurança offline

Não há seletor de perfil, registo livre ou passwords Django guardadas no Android.

- A PWA gera um par ECDSA P-256 por instalação, com chave privada **não exportável**
  em WebCrypto/IndexedDB. Um pedido prova posse da chave. O fingerprint é confirmado
  no aparelho com a informática, por canal independente do ficheiro recebido.
- A informática assina autorização ligada à origem, UUID e fingerprint do dispositivo,
  perfil, permissão de importar, revisão crescente e validade (1–365 dias).
- `activate`, consultas e serviços locais verificam assinatura, chave, origem, validade
  e prova de posse. Repetições/recuos de autorização são recusados. O perfil é fixado
  nesse armazenamento; não se misturam Proprietário/Empregado no mesmo perfil de navegador.
- Empregado consulta stock/localizações. Só importa se o ficheiro de autorização
  o permitir. Chamadas diretas às funções de encomendas, desbloqueio, backup/restore
  ou importação sem permissão são recusadas, além dos controlos da interface.
- Encomendas, notas, receções associadas e arquivo do Proprietário ficam num cofre
  **AES-GCM-256**, com PBKDF2-SHA256/600 000 iterações, salt e IV aleatórios, e origem
  autenticada como AAD. Não ficam tabelas de encomendas/alertas em claro.
  A frase-passe não é guardada; a chave derivada só existe em memória durante uso.
- O cofre bloqueia explicitamente ou após 5 minutos de inatividade. A interface fica
  oculta em segundo plano; ao regressar verifica sessão/validade. Uma passagem breve
  pelo seletor de ficheiros não destrói o formulário. Recarregar/fechar exige desbloqueio.
- Empregados não recebem o cofre/backup nem a frase-passe do Proprietário. Usar aparelhos
  ou perfis Android/navegador **separados**, com bloqueio de ecrã e gestão empresarial.

**Limite real, sem promessas de segurança impossíveis:** alguém que controla totalmente
um aparelho/browser pode modificar o JavaScript ou ler um ficheiro de stock que recebeu.
Autorizações locais não são DRM nem substituem MDM/perfil gerido. A garantia de
confidencialidade dos dados do Proprietário vem da separação e da cifragem; um Empregado
não obtém esses dados ao alterar um menu/ficheiro de perfil. Compromisso do aparelho
**durante** o desbloqueio pode capturar dados/chave em uso. WebCrypto não prova Android
Keystore/hardware seguro. Restrições fortes no aparelho exigem configuração autorizada
pela informática, não contornos implementados pela aplicação.

A revogação não é instantânea offline: a validade expira localmente; a CRL/mTLS limita
novos acessos ao publicador e a informática pode emitir revisão nova. Um cliente fora
da rede não conhece revogações novas. Relógio correto e políticas MDM são requisitos;
não se promete resistência absoluta à alteração do relógio/rollback completo do browser.
Não se guardam credenciais, pessoas, PDFs ou assinaturas no ficheiro de stock.

## Exportar Stock na Gestão

O menu e o painel principal usam **Exportar Stock**. Administrador/Consulta e perfis
personalizados com capacidade `export` podem exportar; a permissão persistente e a
alteração obrigatória de password são revalidadas no servidor. O POST exige CSRF.
O mecanismo XLSX anterior permanece interno para compatibilidade e testes, sem opção
Excel no menu. A etiqueta da capacidade passa a Exportar Stock, sem mudar atribuições.

Formato `vertente-stock`, **v2**, ES256 (P-256/SHA256), bytes UTF-8 exatos Base64URL,
assinatura de 64 bytes `r||s`. Assina também o contexto `vertente-stock-v2\0`, impedindo
reutilização entre tipos de ficheiro. O identificador da chave é SHA256 do SPKI público.

Inclui UUID da origem, UUID único/contador da atualização, instante UTC e todas as
referências ativas (zero incluído), ID estável, nome, garrafas, capacidade nullable,
localização, setor nullable e mínimo nullable. Exclui pessoas, contas, credenciais,
notas/documentos privados, assinaturas, PDFs e histórico completo.

As Entradas operacionais **confirmadas** (`workflow_version=1`, tipo entry) incluem
ID estável da linha, ID do movimento/referência, data de negócio, instante de confirmação,
quantidade recebida em garrafas e caixas/soltas/capacidade efetivamente guardadas.
Não inclui rascunhos, saídas, inventários ou correções de inventário como receções.
Preserva IDs e não infere receções pela subida do saldo.

O serviço usa a transação e o bloqueio de autorização **já existente** nos serviços
operacionais, seguido do bloqueio da identidade de exportação. Confirmações, alterações
de catálogo e revogações ficam serializadas com a leitura. Stock e Entradas são lidos
num estado estável; não há uma entrada parcialmente visível nem uma confirmação ainda
por commit escondida atrás do fim da cobertura. Não se modifica `confirm_movement`,
nem stock/histórico. Falhas revertem contador e auditoria da exportação.

## Retenção, ficheiros perdidos e recuperação

Cada stock transporta uma janela **completa** de Entradas dos últimos 180 dias
(opções 90/30/1 dia para ambientes de maior volume), com `coverage.from/until` assinados.
Limites: **8 MiB**, 10 000 referências, 10 000 linhas de Entrada, inteiros não negativos
até 2 147 483 647. Exceder o limite **recusa** a exportação; nunca trunca Entradas.

Assim, perder exportações intermédias não perde movimentos: a nova inclui a janela
completa e os IDs deduplicam. Não se usa apenas a data do ficheiro anterior. Se um
Proprietário regressar após mais de 180 dias, uma janela menor for escolhida ou faltar
história após recuperação, as encomendas afetadas ficam com aviso **Histórico de receções
incompleto**. A cópia de stock atualiza, mas a aplicação não presume receções através
nesse intervalo nem distribui o saldo líquido. Uma lacuna da encomenda anterior bloqueia
atribuições FIFO posteriores da mesma referência que dependam desse intervalo.

A informática recupera janelas antigas diretamente dos movimentos imutáveis existentes,
sem alterar stock, em ficheiros `vertente-receipts` v1, com contexto/assinatura próprios:

```text
python manage.py vertente_receipts --from 2026-01-01T00:00:00Z --until 2026-02-01T00:00:00Z --output /pasta-privada/rececoes-01.vareceipts.json
```

O fim não pode estar no futuro. O comando recusa destinos existentes/públicos/no código
ou janelas com mais de 10 000 linhas/8 MiB. Dividir em períodos menores e contíguos,
com sobreposição permitida. Não há omissão silenciosa nem crescimento ilimitado de um
ficheiro. Para uma encomenda com lacuna, cobrir desde o instante de registo apresentado
até à janela recente; importar as partes em qualquer ordem. Ao completar a cobertura,
a atribuição ocorre automaticamente. Repetir partes não duplica quantidades.
Ficheiros de recuperação não substituem o stock nem fazem recuar o seu marcador.

O arquivo local é limitado a 100 000 registos por coleção, 1 000 intervalos e cerca de
8 MiB de dados do cofre antes de cifrar. Ao atingir o limite, recusa guardar/importar,
conserva tudo e pede backup/assistência; não apaga histórico. Uma futura função de arquivo
explícito poderá ampliar esse limite. O backup cifrado pode ter cerca de 11 MiB; o seletor
de restauro admite 16 MiB. Isto é uma limitação documentada, não armazenamento ilimitado.

## Importação e encomendas

Antes de escrever, verifica formato/tipo, versão, assinatura/contexto, origem fixada,
quantidades, capacidades, campos/IDs únicos, datas e sequência. Rejeita stock repetido,
antigo, incompleto, adulterado ou de outra origem. v1 da Etapa 7 é recusado: falta-lhe
informação de Entradas; pedir novo v2. Não executa código, fórmulas ou HTML do ficheiro;
a interface usa `textContent`. Importação não faz pedidos à base oficial.

A fotografia completa, marcador e cofre atualizado são escritos numa única transação
IndexedDB. Cifragem/validação acontecem antes; a transação verifica revisão/confiança/
autorização para detetar outra janela. Falha de espaço/escrita/concorrência conserva
stock e encomendas anteriores, inclusive deduplicação. Mantém duas fotografias assinadas;
se a última ficar ilegível, recupera a anterior, avisa e conserva o maior marcador aceite.

O Proprietário pode criar encomenda para **qualquer referência ativa importada**, sem
exigir stock baixo, com quantidade opcional, data e nota. Guarda separadamente caixas,
soltas e capacidade. Vazio = sem quantidade; zero, negativos, frações ou caixas sem
capacidade são recusados. A data de encomenda é informativa; elegibilidade usa o instante
real de **registo local**, conservado após edição, para não converter retrodatação em receção.

Regra automática expressamente pedida: mesma referência e confirmação posterior ao
registo; **não prova vínculo a fornecedor/compra**. Comparações são em garrafas:

- FIFO pelo instante de registo; empates resolvidos pelo UUID da encomenda.
- Uma linha de Entrada distribui apenas a quantidade ainda não atribuída. Encomendas
  quantitativas recebem até ao que falta; o remanescente passa à próxima elegível.
- Sem quantidade: a primeira Entrada elegível entrega-lhe todo o remanescente e fecha-a;
  não se inventa uma divisão para outra encomenda.
- Estados: A aguardar entrada, Parcialmente recebida, Recebida, Cancelada. Mostra recebido,
  falta receber e datas/Entradas associadas. Não exige confirmação manual da associação.
- Edição de quantidade só antes de qualquer receção. Cancelar conserva quantidades já
  associadas, que não serão reutilizadas noutra encomenda; criar outra para novo pedido.
- Subida de stock por inventário/ajuste sem Entrada não recebe encomendas.
- Referências ausentes/desativadas ficam identificadas, fora do stock ativo e com
  acompanhamento preservado. Não há fusão automática por nome.

Alertas usam os mínimos **configurados na Gestão** (`stock <= mínimo`, incluindo igualdade).
São independentes das encomendas, não ativados automaticamente no Android nem editados
pelo Empregado. A B não conserva o modelo antigo de mínimos pessoais da Etapa 7.

## Backup e troca de aparelho

Proprietário desbloqueado → Atualizações e cópias → frase-passe do backup/repetição →
Exportar cópia cifrada. Guardar em suporte autorizado fora do publicador e partilhar a
frase por outro canal. Inclui apenas origem, encomendas/notas, receções/atribuições,
cobertura e marcador necessários à recuperação; não contém passwords, chave de dispositivo,
chave privada de assinatura, PDFs ou stock oficial.

No aparelho novo: instalar, confirmar mesma origem, obter **nova autorização assinada**,
criar cofre, escolher backup/frase e rever a confirmação de substituição. O restauro
não muda stock. O marcador recuperado impede importar stock anterior ao backup; permite
reabrir o mesmo ficheiro exato quando ainda não existe fotografia local. IDs/atribuições
preservados impedem contar Entradas outra vez. Pedir janelas assinadas se houver lacunas.

Frase errada, dados alterados, origem/perfil errado ou falha de escrita deixam o anterior
intacto. Limpeza/desinstalação/perda/remoção de armazenamento pelo Android podem eliminar
dados: não há garantia de retenção indefinida ou recuperação sem backup/frase. O novo
armazenamento B é separado de `vertente-aveludada` da Etapa 7; não lê nem apaga dados antigos.
Backups legados v1 não são convertidos automaticamente. Se existirem ensaios legados a
preservar, arquivá-los na versão original e planear conversão explícita; não limpar o browser.

## Instalação empresarial: preparação posterior pela informática

Não executar isto no PC pessoal ou numa base/volume existente para testar. É um roteiro
para uma futura instalação autorizada e isolada, **não uma publicação automática**.

1. Rever migrações/código, Docker Desktop/WSL2, RAM/espaço e políticas corporativas.
   Perfis da Gestão/contas/passwords permanecem os existentes.
2. Usar DNS interno/IP estável para o publicador **distinto do escritório**, certificado
   SAN/serverAuth e CA confiada no Android/Chrome, certificados clientAuth por dispositivo,
   CA/CRL válidas. Provisionar confiança por MDM/processo aprovado, sem ignorar avisos TLS.
3. Rever SSID/VLAN/ACL/firewall para IP/porta/clients autorizados (8444 por defeito),
   inclusive NAT/WSL2, IPv6/VPN/convidados. Não abrir router/UPnP/Internet, PostgreSQL,
   Docker TCP ou interfaces administrativas. Nenhum script altera essas políticas.
4. Compilar/rever shell com `python scripts/build_vertente.py`. Adaptar
   `deploy/vertente/installation.example.json` **fora** do código. Preparar pasta NTFS nova:

   ```powershell
   .\scripts\windows-vertente\Preparar.ps1 -Configuration 'C:\ConfiguracaoAutorizada\stock.json' -ITApproved
   ```

   Só prepara configuração privada; não inicia Docker ou concede privilégios. A informática
   revê ACL NTFS, certificados, lista de clientes e Compose antes de `nginx -t`/arranque.
   O publicador estático usa `deploy/vertente/compose.yaml`, sem base de dados/volumes de stock.
   `stop consultation` conserva configuração. Renovação exige parar, substituir certificados
   aprovados, testar e só depois voltar a iniciar; não muda dados IndexedDB.
5. Só numa instância da Gestão expressamente autorizada, aplicar as migrações novas e os
   grants restritos. `consultation.0001` cria identidade/contador; `0002` autorizações de
   dispositivo. Não migram stock/histórico. O perfil Windows passa a CodeTrack B e recusa
   manifests A4/A3/A2/legados antes de build/migração. Arranque diário continua sem migrar.
6. Criar chave fora do código em suporte privado aprovado:

   ```text
   python manage.py vertente_setup --directory /pasta-privada/nova-chave
   ```

   `signing.pem` só no escritório, montado read-only por
   `deploy/vertente/export.compose.yaml` e `VA_SIGNING_KEY_FILE`. `origin.vatrust.json` contém
   só origem/chave pública; confirmar fingerprint independente no Android. Não copiar a
   chave privada para publicador, telemóvel, ficheiro de stock, repositório ou backup de dados.
   O overlay tem de fazer parte **da mesma rotina aprovada** de arranque/paragem/recriação
   da Gestão. Atalhos locais base não o incluem automaticamente: a informática deve rever
   a rotina e não recriar o serviço sem esse overlay. Falta de chave recusa exportação.
7. Recolher pedido do aparelho e confirmar fingerprint mostrado. Emitir autorização com
   o processo de preparação/owner da base (o web role não pode escrever autorizações):

   ```text
   python manage.py vertente_device --request /pasta-privada/aparelho.varequest.json --role owner --confirmed-device-fingerprint FINGERPRINT_CONFIRMADO --output /pasta-privada/aparelho.vagrant.json
   python manage.py vertente_device --request /pasta-privada/outro.varequest.json --role employee --allow-import --confirmed-device-fingerprint OUTRO_FINGERPRINT --output /pasta-privada/outro.vagrant.json
   ```

   Omitir `--allow-import` para Empregado só de consulta; `--days` entre 1 e 365 limita validade.
   Renovação no mesmo dispositivo/perfil incrementa revisão e exige outro ficheiro novo.
   Mudança de perfil usa armazenamento/dispositivo separado, sem misturar cofre do proprietário.

### Chaves e recuperação da origem

Guardar cópia **cifrada** da chave privada, fingerprint, UUID, contador e autorizações,
com custódia separada/restrita e restauro ensaiado. O backup PostgreSQL não contém a chave
privada de assinatura. Uma cópia da base com a mesma identidade não pode tornar-se segunda
origem operacional concorrente. Depois de restauro, reconciliar stock **e o histórico completo de Entradas/IDs**, sem
reutilizar identificadores de movimentos perdidos, e preservar a maior sequência antes de `vertente_sequence`; nunca aumentar um contador para fazer passar stock antigo.

Rotação normal: `vertente_setup --directory NOVA_PASTA --previous-key CHAVE_ANTERIOR` produz
nova chave e prova de rotação assinada. Confirmar fingerprint novo, importar confiança e
renovar autorizações com a nova chave; não aceitar nova chave apenas porque alguém enviou
um ficheiro. As chaves antigas verificam fotografias já guardadas, mas não novas importações.
Se a chave anterior se perdeu/foi comprometida, parar exportações e seguir recuperação
supervisionada: backup cifrado do Proprietário, origem confirmada, novo perfil de navegador,
nova confiança/autorizações e restauro; não existe botão para contornar a raiz fixada.

## Validação e aceitação física

A CI executa Django/PostgreSQL, regressões A4, Chromium principal/consulta, PowerShell,
build Docker, migrações sintéticas, backup/restore, exportação sob conta restrita e
publicador HTTPS/mTLS real. A PKI/NSS/adaptador usados em Chromium são **efémeros só de teste**,
sem ignorar TLS e sem modificar confiança do host. Não são infraestrutura empresarial.

Pendente num Android e Wi-Fi reais autorizados: instalação/ícone, seleção/renovação de
certificados em Chrome/PWA/MDM, DNS/firewall/NAT/IPv6, permissões do seletor de ficheiros,
ficheiros WhatsApp/email, abrir após reinício/modo avião, touch/acessibilidade, relógios,
limites/remoção de armazenamento, cofre/bloqueio, backup/restauro noutro aparelho e CRL/expiração.
Estas verificações não são pedidos de testes no computador pessoal. Não houve deployment,
dados reais, acesso à pré-visualização Excel, instalação física, serviços externos ou merge.
