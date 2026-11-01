# Cópias portáteis e recuperação assistida

Estado: implementação para revisão e ensaio. A homologação Windows 11 entre VMs
continua obrigatória. Não distribuir estes binários como versão de produção sem
assinatura empresarial e aprovação. Nenhum instalador é publicado por este PR.

## Utilização

1. Na aplicação web, como administrador, abra **Definições → Cópias de segurança**.
   Também pode abrir o atalho **Gestão Vertente Aveludada** → **Cópias de segurança / recuperar**.
   A manutenção pede autorização administrativa Windows/UAC. A aplicação web e o
   perfil Consulta não recebem acesso às credenciais PostgreSQL nem aos serviços.
2. Escolha **Criar cópia de segurança** e um ficheiro `.gvabackup` novo num disco ou
   suporte externo autorizado, fora de Program Files e da pasta de dados.
3. Defina e conserve separadamente uma frase de pelo menos 16 caracteres. Na
   primeira exportação, uma demonstração criada nesta conta Windows utiliza o
   cofre existente. Caso contrário selecione o kit `.gvademo` e o seu código, ou a
   chave original e a sua frase, através dos seletores do assistente. Não é
   necessário abrir, copiar ou editar um `.pem`.
4. O assistente cria a cópia cifrada, autentica-a, restaura-a numa base temporária
   e compara todas as tabelas, PDFs binários e contadores. Só depois exporta o
   ficheiro e mostra o SHA-256. A ausência da mensagem de conclusão é uma falha,
   mesmo que exista um ficheiro parcial. Não elimine as cópias anteriores.
5. Na instalação escolha **Recuperar cópia de segurança**; também está disponível
   posteriormente no mesmo menu de manutenção. Selecione o ficheiro e a credencial.
   Um backup antigo continua a precisar do kit/código ou da chave/frase originais.
6. Reveja versão, origem e número de registos. Confirme expressamente a substituição
   pelo estado do backup e que a origem está parada. Alterações posteriores ao
   backup não fazem parte dessa fotografia. Não execute duas cópias da mesma origem.
7. Aguarde a validação do novo cluster, esquema, chaves, permissões e serviços.
   Só a conclusão **Recuperação verificada** autoriza abrir a aplicação.

Para reinstalar no mesmo Windows, a desinstalação conserva ProgramData e os
backups externos. O assistente de recuperação preserva a pasta anterior e cria
um cluster novo. Não elimine manualmente serviços, clusters ou `maintenance.json`.
Use um instalador autorizado, da mesma versão ou de versão compatível: o assistente
não efetua migrações de esquema durante o restauro. Um backup de esquema diferente
é recusado; o ambiente anterior é preservado. A reparação tradicional continua a
exigir exatamente o pacote original. A recuperação assistida verifica a assinatura
do código no destino e a compatibilidade efetiva de todas as migrações antes do
arranque, sem executar código antigo numa base mais recente.

## Dados e configurações

Incluídos: todas as tabelas PostgreSQL (referências, stock, operações, inventários,
utilizadores/perfis, PDFs, assinaturas, auditoria, origens e sequências Android,
alertas e dados de acompanhamento que efetivamente residem no servidor), documentos
persistentes em `runtime/web/documents`, chaves e configurações da instalação.
As operações de manutenção acrescentam eventos; não reescrevem o histórico.

**Dados exclusivamente locais da PWA Android não estão no Windows.** Limites,
encomendas e preferências locais devem ser exportados/restaurados com a função
própria da Stock Vertente Aveludada. O assistente informa esta limitação; não
simula uma recuperação desses dados nem acede remotamente ao navegador Android.

Os certificados são preservados dentro da cópia cifrada. O publicador HTTPS fica
**desativado** após o restauro: DNS, certificados e dispositivos/mTLS dependem da
máquina e da rede autorizada. Não se altera firewall ou política Windows. O destino
externo antigo dos backups automáticos é desativado no novo computador; a retenção
e a execução local diária continuam. Configure um novo destino empresarial
aprovado antes da utilização oficial. PostgreSQL continua apenas em loopback.

## Segurança e compatibilidade

- Formato GVABACKUP1 e RSA-OAEP/AES-256-GCM preservados. Novos backups acrescentam
  um envelope da chave original, cifrado com AES-256-GCM e Scrypt (N=131072, r=8,
  p=1, sal de 16 bytes). Os parâmetros não são controláveis pelo ficheiro recebido.
- O serviço diário conserva apenas o envelope cifrado e a chave pública. Não
  conhece a credencial nem recebe a chave privada em claro. As antigas chaves
  continuam válidas para todos os backups que usam essa identidade.
- Os novos pedidos do assistente passam por stdin, nunca pela linha de comando,
  ficheiros de pedidos temporários ou logs. O restauro exige espaço temporário
  privado para a base e configurações, com ACL restrita; estes dados não são logs.
- Kits `.gvademo` v1 são abertos em memória com o código original. A importação do
  kit sintético no canal de produção é recusada. Chaves perdidas não são inventadas.
- A fotografia é autenticada antes de parar serviços. A confirmação está vinculada
  ao SHA-256 da cópia, pacote e marcador do destino; um ficheiro trocado exige
  nova conferência. A assinatura do pacote é validada com a confiança do destino,
  nunca com uma autoridade escolhida pelo backup.
- A substituição preserva a pasta anterior (`*-Preserved-<id>`). Uma falha conserva
  também o candidato (`*-Failed-<id>`); a reposição automática só retoma o cluster
  original após verificar esquema e saúde. Se isso falhar, o diário mantém o
  arranque bloqueado. Uma interrupção de energia exige diagnóstico: não há
  eliminação nem escolha automática entre duas pastas de dados.
- Os backups automáticos também fazem um restauro de ensaio enquanto a fotografia
  privada está disponível, antes de cifrar/publicar. Não precisam da chave privada.
- O diário bloqueia os pedidos à aplicação durante a troca; a autorização de
  arranque para verificar a saúde dos serviços não autoriza novos movimentos.
- Retenção só elimina cópias locais com recibos de autenticação ligados ao hash.
  Cópias antigas sem esse recibo e a última cópia com restauro de ensaio verificado
  ficam protegidas. O número pode exceder o alvo de retenção para preservar essas
  evidências. Backups externos nunca são eliminados pela retenção/desinstalação.

## Homologação obrigatória

Em VMs descartáveis, dados fictícios, snapshots e versões assinadas para testes:

1. Instalar; criar entradas, saídas/inventários com PDF, perfis e alterações de stock.
2. Exportar cópia portátil; verificar SHA-256; guardar a credencial separadamente.
3. Testar credencial errada, corrupção e cancelamento: não parar nem alterar origem.
4. Recuperar sobre instalação existente após conferência; comparar dados, PDFs,
   assinaturas, utilizadores, chaves e contadores; verificar a pasta preservada.
5. Desinstalar/reinstalar e recuperar; confirmar sobrevivência do backup externo.
6. Desligar a origem; transferir só o backup/credencial para outra VM limpa; recuperar
   sem cofre DPAPI ou ficheiro PEM da primeira VM. Comparar evidências e testar login.
7. Repetir com `.gvabackup`/`.gvademo` antigos, usando o código original, sem editar chaves.
8. Testar falha do restauro e corte de energia apenas em snapshots descartáveis.
   Verificar dados anteriores, diagnóstico, bloqueio e ausência de falso sucesso.
9. Validar backups automáticos, reinstalação, reinício Windows, retenção e UAC com
   utilizador comum. Rever acesso Wi-Fi/certificados com a informática, separadamente.

A CI Windows Server testa serviços/ACL/PostgreSQL reais, mas não comprova VirtualBox,
Windows 11 Home/Pro, migração entre duas máquinas, perda de energia ou interação
visual do novo assistente. Registar esses resultados antes de homologar.
