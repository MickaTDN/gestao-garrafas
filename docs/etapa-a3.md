# Etapa A3 — numeração, palavras-passe e inventário

Branch `fix/etapa-a3-correcoes`, baseada na última revisão A2 / PR #9
(`23e6cbf`). PR em rascunho destinado a `fix/etapa-a2-utilizacao`.
Mantém Django 5.2 LTS, Python 3.12, PostgreSQL 17 e os originais Copo com Vida.
Não integra main nem as aplicações Android das outras branches.

## Número oficial e identificador técnico

Um movimento e o seu relatório são entidades distintas. As páginas de movimento,
confirmação e histórico apresentam o `ReportNumber` efetivamente atribuído:
`Mov-N/AA`. As listas/ações de relatórios consultam também a identidade anual do
documento, em vez de construir um número a partir da chave do movimento.
O PDF conserva o snapshot/número emitido na A2.

Antes da emissão: **Em preparação · ID técnico N**. Movimento confirmado sem
relatório ou histórico sem número anual: **Identificador técnico MOV-N**.
Os PDFs históricos conservam a identificação anterior. Não existe numeração
retroativa, conversão de IDs, consumo de sequência por GET ou alteração de relações.
Eliminar/regenerar bytes conserva o número oficial. O renderizador `pdf_v3.py`,
fontes, logótipo e auxiliares de apresentação A2 ficam inalterados, para preservar
a reprodução fiel dos documentos anteriores.

## A minha conta e reposição de palavras-passe

**Definições → A minha conta** está disponível a todos os utilizadores
autenticados, incluindo Consulta/Substituto. Estes perfis só veem a sua conta;
as áreas administrativas continuam protegidas nos URLs e serviços.

Alterar a própria palavra-passe exige a atual, duas novas iguais e as validações
nativas Django. Não é permitido reutilizar a palavra-passe atual/temporária.
Os campos são secretos e não se preenchem após uma falha. Guardam-se apenas os
hashes Django. A sessão atual recebe uma nova chave/hash de autenticação por
`update_session_auth_hash`; outras sessões deixam de autenticar no próximo pedido.

Em **Gerir utilizadores → Repor palavra-passe**, apenas um Administrador pode
definir uma palavra-passe temporária de outra conta. Exige a sua palavra-passe
atual e confirmação explícita. A sua própria conta usa o fluxo anterior.
A reposição não mostra a palavra-passe antiga nem ativa uma conta desativada.
Comunicar a temporária por meio autorizado; não existe envio automático por email.

A reposição invalida as sessões anteriores e marca `must_change_password=True`.
O próximo login vai diretamente para A minha conta, mesmo com `next` a apontar
para outro URL. Middleware bloqueia consultas/operações até à alteração; POST
direto recebe 403. Os serviços de domínio recusam capacidades de contas com essa
marca, incluindo objetos de utilizador antigos. Só mudar a própria palavra-passe
corretamente limpa a marca. Logout e recursos públicos da PWA mantêm-se disponíveis.

CSRF aplica-se aos dois formulários. POSTs e variáveis sensíveis são protegidos;
auditoria regista apenas ação, responsável e ID da conta, sem palavras-passe,
hashes, tokens ou texto livre que possa conter segredos. Pedidos manipulados com
IDs, perfil ou estado não alteram outra conta através de A minha conta.

As alterações/reposições reservam tentativas antes da validação, com HMACs e
bloqueios PostgreSQL. Valores por defeito: 5 tentativas por utilizador e 30 por
endereço, em 15 minutos, separadas para alteração/reposição. Incluem tentativas
com sucesso; tentativas inválidas não anulam o contador. As configurações
`LOGIN_ACCOUNT_LIMIT`, `LOGIN_ADDRESS_LIMIT`, `LOGIN_WINDOW_SECONDS` são reutilizadas,
mas os namespaces são distintos e não consomem nem limpam os limites do login.
O limite devolve HTTP 429; voltar à página após o intervalo permite tentar de novo.

## Inventário físico

A seleção parcial reutiliza pesquisa dinâmica pelo nome, clique direto e as
linhas expansíveis da A2. Não usa checkboxes/Adicionar. Os filtros de localização
e setor mantêm-se. Caixas/soltas começam vazias; Confirmar quantidade guarda a
contagem física e minimiza a linha. O resumo conserva a decomposição introduzida.
Expandir permite editar; remover é possível no inventário parcial.
Nenhum destes passos altera stock/localização.

Os setores vêm da base. A interface retira opções de outras localizações do
seletor nativo, ordena numericamente e limpa o setor ao mudar de localização.
O servidor valida novamente a associação, inclusive em pedidos HTTP forjados.
Referências são agrupadas por localização e setor numérico (1, 2, 9, 10), depois
por designação. Setores não numéricos surgem depois dos numéricos; referências
sem setor surgem no fim da respetiva localização. Nunca são ocultadas por isso.
O cálculo aceita os nomes configurados “Setor 1”, “Setor 10” e os números simples,
sem reescrever designações ou dados existentes.

Na seleção parcial, pesquisar novas referências não filtra nem apaga as linhas
já selecionadas/quantidades em edição. A ordenação/paginação das linhas é estável
e uma adição abre a página da nova referência. No inventário completo, a pesquisa
filtra a navegação das contagens, conservando o âmbito original e o progresso
global. Guardar antes de mudar de página ou filtrar contagens completas.

**Completo:** escolher o âmbito/filtros e Preparar inventário completo fixa todas
as referências abrangidas. Cada contagem pode minimizar/editar como a parcial.
Não se pode retirar uma referência do âmbito e continuar a chamar-lhe completo:
o botão **Limpar contagem** mantém a referência e repõe o estado “ainda não contado”.
Para mudar o âmbito, cancelar sem alterar stock e iniciar outro inventário.

Vazio continua a ser desconhecido; **zero tem de ser introduzido explicitamente**.
Uma diferença exige motivo. Capacidade desconhecida permite só garrafas.
Alterações de contagem/localização invalidam a conferência individual. Stock
alterado desde a contagem exige nova conferência explícita, preservando a proteção
contra alterações concorrentes e stock negativo.

A regra A2 de confirmação no mesmo dia local mantém-se, sem apagar operações
antigas. A conferência final mantém diferenças, transferências, auditoria e PDF obrigatório.
A validação do inventário reutiliza confirmação simples ou assinatura PNG de
rato/toque, com o mesmo serviço verificado das saídas. Assinatura desenhada não
é assinatura digital qualificada. Stock, localização, assinatura, documento e
auditoria são confirmados atomicamente, com reversão completa em caso de erro.

## Migração e compatibilidade

`accounts.0005_required_password_change` acrescenta apenas o booleano
`must_change_password`, inicialmente falso. Não muda passwords/hashes, perfis,
saldos, movimentos, documentos, sequências ou assinaturas existentes. Não é
preciso conceder novos privilégios à conta restrita: já tem UPDATE em accounts_user.
O contador de tentativas reutiliza a tabela existente de limites.

O backup PostgreSQL inclui a marca obrigatória, sessões/hashes, auditoria e todas
as receitas/provas de reprodução A2. A reversão da migração é recusada se houver
alterações obrigatórias pendentes. Mesmo sem essas marcas, não executar código
A2 sobre uma base A3: o código anterior não impõe esta regra de segurança.

## Atualização manual A2 → A3 no Windows

**Não foi executada no computador do utilizador.** A origem A2 instalada na porta
8766 mantém-se intacta. A recuperação deve ser feita pelo utilizador/informática
após rever o PR, usando uma cópia independente só com os dados fictícios do piloto.

1. Na instalação A2, fazer Backup.cmd para suporte/pasta autorizados. Verificar
   o arquivo e conservar também código/imagem A2 e a pasta privada/segredos,
   protegidos e fora de Git. Anotar contas, perfis, saldos, movimentos e números.
2. Parar a A2 com os scripts originais. Não apagar/adotar volumes, backups,
   contentores, manifestos ou segredos. Não mudar a branch na pasta Source da A2.
3. Obter o código A3 revisto numa **nova pasta de código**. Confirmar espaço para
   imagem, arquivo e base recuperada e uma porta loopback livre, por exemplo 8767.
   Não alterar políticas do Windows, WSL2, firewall ou privilégios.
4. Na raiz da nova cópia A3, usar PowerShell aprovado e caminhos reais revistos:

   ```powershell
   $ErrorActionPreference = 'Stop'
   Import-Module .\scripts\windows\Common.psm1 -Force
   $a3 = Recover-GGPilot -Archive 'C:\BackupsAutorizados\piloto-a2.tar.gz' `
       -NewHomePath "$env:LOCALAPPDATA\GestaoGarrafasA3" `
       -SourceRoot (Get-Location).Path -Port 8767
   Start-GGPilot -HomePath $a3.Home
   ```

   Usar o módulo **A3**, não Recuperar.cmd da instalação antiga. A pasta tem de
   ser nova e a base de destino vazia. O restauro verifica o arquivo/documentos;
   só a cópia aplica a migração e recebe a sua identidade de instalação.
   Se falhar, preservar a tentativa para diagnóstico, sem forçar hashes/manifestos.
   Instalar diretamente sobre um manifesto A2 e migrar uma base semeada sem esta
   recuperação são recusados. O arranque diário não migra.
5. Confirmar a porta 8767 no navegador e validar contas, perfis, saldos, histórico,
   documentos e assinaturas. Conferir números anuais antigos, entrada sem PDF,
   eliminação/regeneração fiel, troca/reposição de passwords numa conta fictícia,
   sessões e inventários parciais/completos, zero, setor e transferência.
   Confirmar persistência após paragem/arranque e testar novo backup/restauro num
   destino independente. Não usar as duas cópias em paralelo como se fossem atuais.
6. Só após aceitação, `New-GGShortcuts -HomePath $a3.Home` troca explicitamente o
   atalho para a cópia A3. A recuperação não troca atalhos sozinha. Manter a A2
   parada e preservada, com os seus backups e imagem.

**Reversão:** antes de usar a A3, parar a cópia e arrancar a origem A2 com código
e scripts originais, repondo explicitamente os atalhos. Depois de movimentos ou
alterações de contas/passwords na A3, a A2 preservada está desatualizada. Conservar
a A3, fazer backup e recuperar o arquivo recente com código compatível; não
apontar A2 à base A3 nem forçar migrações inversas para perder a alteração obrigatória.

## Validação e limites

Os testes usam bases sintéticas novas: numeração com e sem documento/histórico,
ano novo e regeneração; palavras-passe, CSRF, sessões, perfis, obrigatoriedade,
tentativas concorrentes; setores e ordenação, seleção/minimização, edição/remoção,
zero/vazio, inventários completos, transferências e conflitos; migração e recuperação
de PDFs A2 assinados e eliminados. A CI inclui PostgreSQL, Chromium, build limpo,
payload de recuperação e PowerShell 5.1/NTFS/atalhos.

Falta aceitação física Windows 11/WSL2/Docker Desktop: políticas empresariais,
espaço e cópia protegida, atalhos/PWA, menus de setores e impressão. A assinatura
em Chromium móvel não substitui validação num dispositivo real. Nenhuma base real,
pré-visualização Excel ou instalação existente é utilizada nos testes. Não há
importação/publicação, atualização do Windows, merge ou alteração da aplicação
Stock Vertente Aveludada.
