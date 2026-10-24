# Decisão 6 — uma aplicação, um PostgreSQL e proxy Wi-Fi local

Estado: preparado para ensaio sintético; infraestrutura empresarial pendente.

A Etapa 5 conserva HTTP exclusivamente loopback. A Etapa 6 nasce dessa branch,
com perfil distinto que reutiliza imagem/bootstrap/grants/PWA/serviços/documentos.
Novo projeto/cluster impede ligar à base reservada ao Excel. PC/Android partilham
a base desse ensaio; não existe base móvel nem Stock Vendas offline.

Nginx não privilegiado recebe a única porta publicada num IPv4 LAN específico,
certificados fornecidos pela informática e duas redes internas separam proxy/base.
Django só confia no IP exclusivo do proxy. Abrir HTTP do piloto na LAN não permitiria
PWA segura; publicar PostgreSQL ou duplicar a aplicação aumentaria superfícies.

DNS/endereço estável e CA confiável dependem da informática, não dos scripts.
Certificado clientAuth por dispositivo, CRL e allowlist complementam login e
firewall: NAT Docker Desktop pode ocultar o IP Android. O custo é configuração
PKI/MDM e aceitação física, sem atalhos que ignorem TLS ou políticas.

GET de ligação melhora o aviso; resposta de POST perdida não prova o resultado.
Sem filas/reenvios offline: consultar histórico/rascunhos e usar proteção transacional
existente contra duplicados. Não se alteram regras de stock. Publicação real,
infraestrutura, Android físico e merge continuam separados e não autorizados por
esta preparação. Ver [guia](../android-wifi.md).
