# Falha inicial PostgreSQL — investigação e correção

O ensaio VirtualBox/Windows 11 Pro com o artefacto sintético da execução
41184012084 falhou antes de criar PG_VERSION. As consultas de leitura indicaram:

- initdb.exe e postgres.exe --version: -1073741515 = 0xC0000135 (DLL não encontrada);
- vcruntime140.dll, vcruntime140_1.dll e msvcp140.dll ausentes em PostgreSQL/bin e System32;
- NT SERVICE/GVAPostgres17 com Modify nos diretórios cluster e runtime/postgres;
- o 7023/«Função incorreta» era um código genérico de saída do serviço, não uma
  indicação de que se devesse mudar a conta virtual ou conceder permissões globais.

A CI tinha um runtime global Visual C++ no runner, mascarando a dependência.
O arquivo PostgreSQL bin/lib/share por si só não assegurava execução num Windows
limpo. O build agora exige um input msvc x64 com SHA-256, signers_sha256 aprovados,
versão, origem e direitos de redistribuição revistos. As DLLs release do diretório
redistribuível Microsoft são validadas (PE x64, assinatura Authenticode válida,
editor Microsoft e fingerprint) e colocadas apenas no payload NOVO PostgreSQL/bin
e NGINX. Não se modifica System32, não se instala um runtime global, não se muda
PATH global nem se copia um conjunto arbitrário de DLLs do computador.

Os inputs de CI provêm do diretório x64 release CRT do Visual Studio no runner;
são sintéticos e não substituem a revisão independente/licenciamento dos inputs
de produção. O inventário assinado do pacote inclui as DLLs. A conta virtual e
as ACL privadas de serviços permanecem iguais.

O ensaio nativo consulta também os módulos do PostgreSQL em execução e exige que
o CRT carregado pertença ao pacote privado. Não remove nem renomeia DLLs do
sistema para simular um Windows limpo.

Há também verificação --version antes de registar serviços/arrancar o cluster.
TEMP/TMP dos filhos PostgreSQL apontam a uma pasta privada da própria identidade.
Erros registam apenas comando, código e categoria allowlisted em
runtime/postgres/startup-diagnostic.json; stdout/stderr e passwords não são gravados.
O launcher pg_ctl usa DEVNULL em vez de pipes capturados: no Windows o servidor
persistente pode herdar os handles e impedir communicate de terminar apesar de
pg_ctl já ter saído. O log privado do servidor PostgreSQL continua disponível.
Uma regressão com processos reais verifica que o launcher regressa enquanto o
filho continua em execução, e que falhas de arranque continuam a ser recusadas.
O assistente mostra progresso indeterminado, fase e erro visível, restaura os
controlos após falha e não consulta controlos WinForms a partir da thread worker.
O limite SCM do PostgreSQL acompanha os limites dos comandos filhos; timeout pede
paragem cooperativa, nunca termina à força o cluster.

## Preservar a instalação que falhou

Não apagar cluster, maintenance.json, chaves ou serviços; não iniciar código antigo
sobre dados mais recentes nem adotar automaticamente uma pasta parcial. Este PR
não fornece uma rotina de limpeza/reparação dessa VM. Preservar a evidência e
planear o próximo ensaio num ambiente descartável limpo mediante autorização.
Não há novos instaladores publicados por esta correção.

## Consultas que não expõem credenciais

```powershell
$r='C:\ProgramData\GestaoVertenteAveludada-Teste'
$s=Get-Content "$r\installation.json" -Raw | ConvertFrom-Json
Get-Content "$r\maintenance.json" -Raw | ConvertFrom-Json | Select-Object phase,failed,version
Test-Path "$r\cluster\PG_VERSION"
& "$($s.release)\postgres\bin\initdb.exe" --version
"initdb exit=$LASTEXITCODE"
& "$($s.release)\postgres\bin\postgres.exe" --version
"postgres exit=$LASTEXITCODE"
icacls.exe "$r\cluster"
icacls.exe "$r\runtime\postgres"
```

Não partilhar bootstrap-password, secrets, pedidos privados, chaves, dumps ou logs
SQL integrais. Os testes de regressão utilizam só ficheiros/processos simulados ou
runners Windows descartáveis. Uma passagem em Windows Server não homologa a VM
Windows 11 do utilizador; será necessário revalidar nela após aprovação do build.
