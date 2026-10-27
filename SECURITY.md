# Segurança

Não coloque passwords, chaves privadas, tokens, dados pessoais, assinaturas,
documentos privados ou backups em issues, Pull Requests ou artefactos de CI.
Use apenas dados sintéticos para reproduzir problemas.

Para uma vulnerabilidade, utilize **Security → Advisories → Report a vulnerability**
quando o proprietário tiver ativado a comunicação privada. Se essa opção não
estiver disponível, solicite ao proprietário um canal privado antes de enviar
detalhes sensíveis. Não publique uma prova de conceito com dados reais.

Os artefactos de testes não são versões oficiais. A distribuição Windows exige
revisão da versão, autorização explícita e assinatura empresarial Authenticode
válida, conforme `docs/windows-native.md` na linha da Etapa C. A CI não tem
chaves de produção nem um workflow de publicação de versões oficiais.

Consulte `docs/security/public-readiness.md` para os limites da auditoria,
proteções propostas e condições ainda pendentes antes da publicação do código.
