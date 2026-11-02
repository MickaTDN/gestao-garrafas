# Gestão completa por Wi-Fi no Windows nativo

Estado: implementação para revisão, não homologada em dispositivos reais.
O publicador Stock, PWA offline e respetivos perfis não são modificados.

## Arquitetura e configuração administrativa

GVAManagementWifi é um serviço opcional, desativado por defeito. Executa o Nginx
privado com HTTPS/mTLS e um backend Django separado em loopback, usando a MESMA
base PostgreSQL 17 e o mesmo utilizador SQL restrito da aplicação. O serviço não
recebe owner.json. O HTTP local mantém as configurações e cookies existentes;
o HTTPS usa cookies Secure com nomes distintos, autenticação e CSRF obrigatórios.
Certificados de cliente não substituem as contas e permissões Django.

A informática prepara DNS interno estável, certificado de servidor confiável no
Android, CA de dispositivos e CRL válida. Cada pessoa/dispositivo recebe certificado
individual, chave privada protegida e conta Django individual. Revogar através da
CA/CRL, parar o serviço, substituir a CRL por via administrativa e reativar/testar.
Não basta desativar uma conta para revogar o certificado nem o inverso.

Preparar numa pasta privada config.json e server-chain.crt, server.key,
device-ca.crt, device-ca.crl. Exemplo config.json (sem credenciais):

```json
{"it_approved":true,"address":"192.168.20.10","hostname":"gestao.example.internal","port":8443,"backend_port":8766,"clients":["192.168.20.50/32"]}
```

Pela interface de manutenção Python nativa, elevada pela informática, usar a ação
`configure-management-wifi` com pedido `{"configuration":"CAMINHO/config.json"}`
no mecanismo de pedidos privados existente. Depois usar `control-management-wifi`
com `{"enable":true,"it_network_ready":true}`. Desativar com `{"enable":false}`.
Não colocar passwords/chaves em argumentos, logs ou repositório. Não editar os
ficheiros gerados enquanto o serviço está ativo. Nenhum destes comandos deve
ser executado nesta fase numa instalação real sem homologação/autorização.

A configuração não altera DNS, firewall, trust stores nem certificados reais.
A informática deve permitir só HTTPS e dispositivos/redes aprovados. PostgreSQL,
backend, HTTP local e interfaces administrativas nunca recebem binds LAN.
Não criar port forwarding. Nunca ignorar avisos de segurança do Android.

## Proteções e recuperação

O proxy substitui Host/cabeçalhos de encaminhamento e autentica-se ao backend com
segredo aleatório privado: ser um processo em loopback não basta. Não há retries
automáticos de operações pelo proxy. Confirmar continua a usar os serviços
transacionais existentes, incluindo proteção contra confirmação duplicada.
Uma falha de resposta não significa que o movimento não foi confirmado: consultar
o mesmo movimento antes de repetir. Não há confirmação offline nem cache privada.

Configuração/certificados ficam em secrets/management-wifi, abrangidos pelo backup
atual e pelo PR #25. A aprovação de arranque fica exclusivamente em runtime/wifi,
fora da cobertura de restauro; recuperar exige nova autorização no destino.
Comparação mecânica com o commit b9fc725 do PR #25 identificou conflitos de
integração em native_windows/cli.py e native_windows/install.py: preservar as
novas ações de ambas as etapas e combinar os direitos de leitura Wi-Fi com a
proteção explícita da chave de recuperação. Não integrar automaticamente. O
ensaio conjunto com esse PR continua necessário antes de homologar recuperação.
Atualizações param este serviço antes de parar PostgreSQL. O publicador Stock
continua separado. Não instalar versões antigas após migrações mais recentes.

## Homologação pendente

Em VMs descartáveis com dados fictícios: testar login próprio/Consulta, entrada,
saída com assinatura/PDF e inventário no Chromium Android; comparar stock/histórico
no PC; testar CSRF ausente/inválido, certificado ausente/errado/expirado/revogado,
DNS/Host/cabeçalhos forjados, redes não autorizadas, perda de ligação durante
confirmação e repetição do mesmo movimento. Verificar rollback e backups PR #25,
reinício Windows e ausência de arranque Wi-Fi após recuperação. Verificar também
que Stock offline/publicador continuam iguais. A instalação física da CA/mTLS no
Android e a firewall/DNS empresariais exigem validação da informática.
