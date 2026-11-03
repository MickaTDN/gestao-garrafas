# PR #35 — par sintético para duas VMs

Origem única: `c621b00d732f98f9276af4c59c54e58d02fafa93`.
Novo workflow: `pr35-windows11-homologation.yml`. O workflow antigo de #25
mantém-se inalterado; não utilizar os seus artefactos para homologar #35.
Sem inputs de revisão, canal ou chaves. Gera os EXEs 1.0.0/1.1.0 com a mesma
chave temporária, instala, atualiza e testa backups portáteis, recuperação,
rollback, gateways, integridade e desinstalação no runner descartável.
Só depois do sucesso publica os dois EXEs, SHA256SUMS.txt e PROVENANCE.json.
O manifesto identifica separadamente SHA fonte, SHA workflow, execução e tentativa.
Nenhuma chave privada ou credencial é incluída nos artefactos públicos.

## Bloqueio de execução e alternativa para revisão

GitHub exige que workflow_dispatch esteja na branch por defeito. Além disso,
a política existente exige main para uploads. Este PR dependente não altera
main nem enfraquece essa política: neste estado não há instaladores novos
para descarregar. Não executar o workflow antigo como alternativa.

Após revisão e autorização separada do proprietário, pode preparar-se um PR
mínimo para main contendo apenas este novo workflow e os seus testes/política
necessários, sem integrar a aplicação #35. A seleção literal do código continuará
a apontar exclusivamente ao SHA acima. Não foi criado nem integrado esse PR.
Após aprovação: Actions → PR35 - Windows 11 integrated synthetic homologation →
Run workflow, main. Exigir execução verde e descarregar um único artefacto
UNAPPROVED-SYNTHETIC-UNSIGNED-c621b00… com execução/tentativa correspondentes.
Retenção: três dias. Sem releases ou assinatura empresarial de produção.

## Duas VMs Windows 11

1. Preservar snapshots e ficheiros da homologação anterior #25. Criar clones
   limpos separados para #35, sem substituir a VM antiga nem executar no anfitrião.
2. Transferir o ZIP do artefacto para ambas as VMs. Conferir PROVENANCE.json:
   source_commit exato acima, channel synthetic, production_approved false e
   execução/tentativa iguais nas duas. Nunca misturar EXEs de execuções diferentes.
3. Extrair e executar `Get-FileHash .\GVA-synthetic-1.0.0-win-x64.exe -Algorithm SHA256`
   e o equivalente para 1.1.0. Comparar com SHA256SUMS.txt e resumo da execução.
4. VM A: snapshot limpo, instalar 1.0.0 em demonstração automática; guardar kit
   de recuperação em local privado. Testar login, operações/PDFs e folhas.
   Criar backup portátil externo; guardar credencial de forma privada. Atualizar
   com 1.1.0 deste mesmo par, reiniciar e verificar histórico, PDFs e stocks.
5. VM B limpa: instalar 1.1.0 do mesmo par e recuperar a cópia da VM A pelo
   assistente. Manter A desligada/isolada antes de autorizar a identidade em B.
   Conferir utilizadores, stock, movimentos, PDFs, folhas e auditoria; confirmar
   que publicador e os dois gateways permanecem sem aprovação de rede.
6. Ensaiar credencial errada/cópia corrompida em snapshot descartável; verificar
   preservação da instalação. Testar backup após recuperação e desinstalação,
   garantindo conservação dos backups externos. Nunca apagar o único backup válido.

Parar se hash/SHA/canal não coincidir, teste falhar, Windows/antivírus bloquear,
serviço não arrancar ou surgir manutenção interrompida. Não ignorar avisos nem
reiniciar manualmente serviços bloqueados. Preservar diagnóstico sem segredos.

CI Windows Server não substitui estas duas VMs nem Android físico. DNS/firewall,
CA confiável, certificados individuais e testes Wi-Fi exigem autorização própria;
não se alteram automaticamente. Os EXEs são sintéticos, não Authenticode empresarial,
e não podem converter a instalação em produção.
