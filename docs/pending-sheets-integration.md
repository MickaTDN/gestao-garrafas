# Integração controlada das folhas pendentes

Base: PR #32 `a537f2981798aa17098bee1c01c9c45008efadbe`, que contém #30/#29.
Segunda origem: PR #31 `4fd188146a87ca17be4a310f4e1280d218ff9fac`.
Ambas as revisões são antepassados da nova branch; os PR originais e a main não
são modificados. O novo PR tem como destino `feature/pending-sheet-wifi` (#32).

## Comportamento conjunto

1. Fábio/Daniel preparam folhas nos cofres offline existentes. Exportar ou enviar
   não confirma movimentos; identidades, permissões e encomendas privadas mantêm-se.
2. Ficheiro e Wi-Fi utilizam o mesmo serviço de receção e a mesma unicidade
   `(source_id, sheet_id)`. Repetição idêntica gera evidência de duplicado; conteúdo
   divergente gera conflito, sem substituir originais ou a versão de trabalho.
3. Comprovativos assinados vinculam dispositivo, revisão, ficheiro e tentativa.
   A resposta perdida permite reenviar o ficheiro original, sem outra identidade.
4. As listas Entradas pendentes/Saídas pendentes conduzem à conferência existente.
   Apenas o administrador pode corrigir com motivo, rejeitar ou confirmar. Todas
   as decisões permanecem separadas dos originais imutáveis e auditadas.
5. Só confirmação explícita cria movimento/numeração oficial, PDF conforme as regras
   existentes e alteração de stock numa transação. Falha de PDF reverte todos os
   efeitos oficiais. Repetir a confirmação consulta o mesmo movimento, mesmo após
   retransmissão por Wi-Fi, reimportação manual ou recuperação Windows.

Não se alteram assinaturas, regras de datas, cálculo de quantidades ou validação de
stock disponível. A receção não adquire permissões administrativas.

## Migrações preservadas

```
0004_sheet_evidence_guards
 ├── 0005_wifi_receipt_actor ────────────────────┐
 └── 0005_sheetaction → 0006_sheet_action_guards ─┤
                                        0007_merge_review_wifi
```

A junção não contém operações de dados/esquema: depende dos dois ramos originais,
sem os renumerar ou editar. O campo nullable do responsável permite identificar
receções de dispositivos sem inventar utilizadores; as decisões administrativas
mantêm responsável obrigatório. As proteções PostgreSQL de imutabilidade e sequência
continuam instaladas. Migrações inversas não contornam as proibições existentes.

Testes de migração criam bases sintéticas povoadas em cada ramo, aplicam a junção e
verificam ficheiros originais, decisões, responsáveis, stocks e triggers. Não executar
esses ensaios numa instalação existente. A atualização normal é apenas para a frente.
O verificador de CI confirma antepassados, bytes das migrações publicadas e uma única
folha no grafo. O probe sintético Windows passa a suceder à junção, sem criar ramo.

## Conflitos e ensaios conjuntos

Único conflito de merge: fixture `tests/native_windows/windows_smoke.py`.
Conservadas todas as asserções e fluxos de ambas as origens, ajustando apenas as
contagens à união: quatro folhas, seis receções (duas de dispositivo), cinco decisões,
quatro movimentos confirmados/números oficiais e saldo sintético inalterado de 33.
Entradas/saídas oficiais, PDFs e assinaturas do #31 coexistem com o recetor do #32.
A recuperação repete confirmações e verifica idempotência e aprovação de rede ausente.

Testes adicionais:

- Receção mista, permissões, confirmação de entrada e saída assinada/PDF, falha de
  PDF, conflito e rejeição, preservando originais e números oficiais.
- Concorrência PostgreSQL: ficheiro/Wi-Fi em paralelo, duas confirmações e reenvio.
- Chromium HTTPS/mTLS: preparação real, commit seguido de resposta truncada,
  reenvio, offline/reabertura, importação manual, confirmação administrativa,
  retransmissão após confirmação e revogação.
- Todos os testes anteriores continuam na suite, incluindo os fluxos de conferência
  em computador/telemóvel do #31; a confirmação integrada deixou de ser opcional.

## Compatibilidade futura e limites

Os PR #25 (backup portátil) e #28 (Gestão Android administrativa) não são integrados.
Mantêm-se contratos de backup: base/evidências, secrets/signing/tls; aprovação de rede
em runtime excluída. O recetor utiliza conta e backend distintos, não lê TLS do
publicador nem credenciais de proprietário PostgreSQL. O #28 continua separado da
receção de folhas e do publicador exclusivamente de leitura.

A composição futura exige conciliação das ações do assistente, CLI, ACLs e fixtures
Windows, mantendo as ações/contas de ambos os lados. Não resolver por substituição
integral nem renumerar migrações já aplicadas. Ensaios unitários temporários de
compatibilidade não equivalem a um ciclo Windows conjunto com #25/#28.

Verificação nesta composição: 14 testes unitários do conjunto portátil/recetor com
`#25 b9fc725` e 10 dos gateways com `#28 812237e` passaram em árvores temporárias.
As resoluções nessa árvore servem apenas para ensaio de contratos; não são commits
de integração desses PRs. Permanecem quatro ficheiros em conflito futuro com #25
(assistente, CLI, ACLs e fixture Windows), cinco com #28 (também ciclo de serviços).

Continuam pendentes Windows 11 Home/Pro e Android físicos, CA/certificados individuais,
DNS e firewall da empresa, perda real de Wi-Fi/suspensão e seleção de certificados
pelo Chrome. Rede desativada por defeito, ativação explícita pela informática. Não há
instalação real, publicação de instaladores ou alteração de backups/bases existentes.

Procedimentos específicos: [Wi-Fi](pending-sheets-wifi.md),
[conferência](pending-sheet-review.md). Os resultados finais da CI e os limites
efetivamente testados estão registados no PR de integração.
