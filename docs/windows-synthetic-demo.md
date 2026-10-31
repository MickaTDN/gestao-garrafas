# Demonstração automática — exclusivamente VM de homologação

Melhoria independente da correção PostgreSQL/CRT. O canal release, assinatura,
contas de serviço, SQL, ACL de dados, backups e recuperação não são alterados.
A correção do runtime PostgreSQL no PR separado continua necessária para instalar
num Windows limpo sem as DLLs CRT. Esta melhoria não repara a instalação parcial
que falhou e não permite adotá-la ou apagar os seus dados.

## Primeira instalação

Num instalador sintético, antes do assistente completo, há duas opções:

- Criar demonstração automática numa VM Windows 11 autorizada e descartável.
- Configuração manual / recuperar backup: conserva o assistente completo.

O modo automático verifica canal synthetic, versão cliente Windows 11, hardware
VirtualBox/Hyper-V reconhecido, confirmação explícita e ausência da pasta de dados.
Não usa GITHUB_ACTIONS para simular uma VM nem permite uma instalação sobre estado
parcial. O reconhecimento do hardware é uma proteção contra enganos operacionais,
não uma fronteira contra um administrador que controle o sistema.

São gerados por CSPRNG, separadamente por instalação:

- Identificador de administrador fictício, sem nome de pessoa.
- Palavra-passe forte da demonstração.
- Frase de recuperação independente e caminho novo para a chave privada cifrada.
- Chave/código independente de 256 bits para o kit portátil.

O utilizador não precisa de preencher esses campos. O processo existente continua
a gerar a chave RSA de recuperação e a identidade de assinatura; não se introduz
nenhuma chave/palavra-passe universal. O login da aplicação mantém autenticação:
a janela permite consultar as credenciais geradas e abrir o navegador, sem criar
um bypass de login ou um token de autenticação em URLs.

## Guardar os dados de teste

O cofre local em LocalAppData/GVA-Homologacao/<id>/demo.vault usa DPAPI CurrentUser,
com UI proibida na operação criptográfica. A pasta tem ACL apenas para a identidade
que a criou, administradores e SYSTEM. Não contém JSON com passwords em claro;
o índice active.txt tem apenas um caminho, não segredos.

A janela mostra passwords, frase e código ocultos; revelar exige ação explícita.
Não há cópia automática para clipboard nem impressão em logs. A manutenção do
canal sintético permite reabrir os dados sob a conta Windows criadora, com a
mesma elevação usada na instalação. Outra conta Windows não consegue decifrar
esse cofre DPAPI. Perder a VM/perfil pode perder o cofre: ele não é portátil.

O botão Guardar kit cria um ficheiro NOVO .gvademo cifrado/autenticado AES-256-GCM,
com nonce aleatório e código de 256 bits gerado separadamente. Inclui credenciais
fictícias, frase de recuperação e a chave RSA que já está cifrada. A validade do
PKCS8 cifrado e da frase é verificada antes de exportar/aceitar a chave.

O código nunca é incluído no kit. Guardar ficheiro e código separadamente num
suporte privado autorizado. Não enviar para GitHub, chat, emails abertos ou logs.
Não se substituem ficheiros existentes. A recuperação precisa também do backup
cifrado da base e dos instaladores exatos; o kit não contém nem substitui a base.
Sem código e sem cofre Windows recuperável, não existe um segredo mestre de resgate.

## Atualização e recuperação

Para atualizar, consultar os dados privados na manutenção e utilizar o caminho da
chave/frase gerados. A atualização mantém a validação de assinatura, backup/restauro
prévio e regras de versão existentes.

Numa VM NOVA, a janela inicial permite Abrir kit cifrado, informar o código e
extrair a chave ainda cifrada para um ficheiro novo escolhido pelo utilizador.
Exige autenticação GCM e PKCS8; código errado ou kit alterado são recusados. Isso
não importa uma base nem inicia serviços. Depois usar Configuração manual /
recuperar backup, com arquivo de backup, chave e frase. A origem deve estar parada
ou isolada; mantém-se a aprovação administrativa antes de ativar a cópia recuperada.

O modo release não mostra estas opções e rejeita os helpers/kit. Não há conversão
suportada synthetic → release. A produção continua a exigir configuração manual,
assinatura de editor, validações e identidade próprias, sem adotar a base de teste.

## Testes e limites

Testes Windows próprios verificam rejeição de release/host físico/Server/VM não
confirmada/estado existente; geração exclusiva; ACL e DPAPI; kit cifrado, roundtrip,
código errado e alteração de conteúdo. Usam apenas material fictício temporário e
não instalam serviços ou dados. O ciclo nativo manual de CI permanece intacto.

A experiência gráfica automática completa e a prova real no VirtualBox Windows 11
continuam pendentes de um futuro build autorizado e da homologação. Não se gera
nem publica novo instalador como parte desta alteração. A pasta/cluster/journal da
VM que falhou permanecem preservados; não há qualquer rotina de limpeza automática.
