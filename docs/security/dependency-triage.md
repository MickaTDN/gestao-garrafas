# Etapa C.1 — Triagem das dependências

Data: 27-10-2026. Origem: consulta anterior do `pip-audit`/PyPI, conservada em
arquivo privado, e nova consulta após atualização. Os 44 registos brutos anteriores
incluíam duplicações de aliases: **41 avisos distintos**, 38 de Pillow e 3 de
cryptography. A tabela identifica cada aviso e o caminho funcional inspecionado;
não é uma afirmação de exploração demonstrada nem uma dispensa de atualizar.

Alterações: `pillow>=13.0.0,<14`, bloqueado em **13.0.0**;
`cryptography>=50.0.2,<51`, bloqueado em **50.0.2**. Django continua na série 5.2
LTS. Ferramentas de auditoria ficam num grupo `security` separado, não na
instalação de execução ou no instalador distribuído.

A assinatura já exigia PNG, dimensões limitadas, um só frame, tamanho máximo e
remoção de metadados. O autodetetor genérico podia tentar outros parsers **antes**
da rejeição de formato. As duas aberturas passam agora `formats=["PNG"]`.
Um teste verifica que ficheiros TIFF/GIF disfarçados nem chegam aos seus decoders;
outro confirma a preservação da assinatura válida e a remoção de metadados.
Não se alteraram regras de stock, conteúdo histórico, numeração ou serviços
transacionais.

| Aviso | Versão instalada afetada | Análise do caminho da aplicação | Tratamento nesta branch |
|---|---|---|---|
| [CVE-2026-69248](https://github.com/advisories/GHSA-m2h6-j472-rp4c) | cryptography 48.0.1 | Verificador de cadeias X.509 / DNS wildcard. Não se usa o verificador pyca de cadeias; exportação e pacotes usam ES256. | Corrigido em 50.0.2. |
| [CVE-2026-69247](https://github.com/advisories/GHSA-g6cj-pr64-35w5) | cryptography 48.0.1 | Desencriptação PKCS7 / RSA PKCS#1 v1.5. Não se chamam pkcs7_decrypt_*; o caminho ES256 não é este algoritmo. | Corrigido em 50.0.2. |
| [CVE-2026-69249](https://github.com/advisories/GHSA-jwv3-5hgf-82ww) | cryptography 48.0.1 | Cadeias X.509 duplicadas / consumo de CPU. Não se usa o construtor de cadeias pyca nos caminhos inspecionados. | Corrigido em 50.0.2. |
| [CVE-2026-112394](https://github.com/advisories/GHSA-4558-3h8r-v8xp) | pillow 12.3.0 | Raw P;2L/P;4L. Não se fornecem buffers raw nem estes modos à biblioteca. | Corrigido em 13.0.0. |
| [CVE-2026-112396](https://github.com/advisories/GHSA-4rr5-89j8-mwwm) | pillow 12.3.0 | Gravação TIFF / erro de libtiff. A assinatura é regravada como PNG, nunca TIFF. | Corrigido em 13.0.0. |
| [CVE-2026-112392](https://github.com/advisories/GHSA-27h8-gf7j-v5hc) | pillow 12.3.0 | Filtros rank/median em imagem vazia. Não se usam estes filtros; dimensões da assinatura são limitadas. | Corrigido em 13.0.0. |
| [CVE-2026-112895](https://github.com/advisories/GHSA-p4wg-p73j-c528) | pillow 12.3.0 | Pillow PdfParser ao acrescentar páginas. Os relatórios usam ReportLab, não Image.save(PDF, append=True). | Corrigido em 13.0.0. |
| [CVE-2026-112400](https://github.com/advisories/GHSA-65qm-jvmh-6pqg) | pillow 12.3.0 | GIF seek após rejeição de dimensão. Não se percorrem frames GIF; a whitelist impede até a seleção deste plugin. | Corrigido em 13.0.0. |
| [CVE-2026-112397](https://github.com/advisories/GHSA-58r4-6rv3-gfh8) | pillow 12.3.0 | MorphOp com largura zero. Não se usa ImageMorph; assinatura tem dimensões mínimas. | Corrigido em 13.0.0. |
| [CVE-2026-112896](https://github.com/advisories/GHSA-pchr-8j38-3x4p) | pillow 12.3.0 | Metadados TIFF ao regravar. Não se regravam TIFF nem os seus metadados. | Corrigido em 13.0.0. |
| [CVE-2026-112897](https://github.com/advisories/GHSA-q45j-58j2-45rg) | pillow 12.3.0 | Descodificação de strips TIFF JPEG. TIFF não é carregado; agora nem o plugin é selecionado para assinaturas. | Corrigido em 13.0.0. |
| [CVE-2026-112395](https://github.com/advisories/GHSA-462x-pgg6-55fp) | pillow 12.3.0 | Descodificação de tiles TIFF. Não se carregam tiles TIFF; formato permitido é PNG. | Corrigido em 13.0.0. |
| [CVE-2026-112404](https://github.com/advisories/GHSA-c6hw-5grf-ff96) | pillow 12.3.0 | TIFF tiles/RGBA. Não se carrega TIFF; converter uma assinatura PNG para RGBA não usa esse decoder. | Corrigido em 13.0.0. |
| [CVE-2026-112899](https://github.com/advisories/GHSA-vx6w-vv9f-6gvg) | pillow 12.3.0 | EPS / Ghostscript / escala. Não se chama Ghostscript nem se aceitam EPS como assinatura. | Corrigido em 13.0.0. |
| [CVE-2026-112402](https://github.com/advisories/GHSA-7mwm-ghpf-9vrm) | pillow 12.3.0 | Transformação affine em falha de alocação. Não se usam transformações affine em assinaturas. | Corrigido em 13.0.0. |
| [CVE-2026-112900](https://github.com/advisories/GHSA-w889-685w-c8fh) | pillow 12.3.0 | EPS / opções de linha de comando. Não se chama Ghostscript; assinaturas são buffers em memória PNG. | Corrigido em 13.0.0. |
| [CVE-2026-112893](https://github.com/advisories/GHSA-j4m9-6w36-pw47) | pillow 12.3.0 | Texto com FreeType stroke. Não se desenha texto com stroke em Pillow; PDFs usam ReportLab. | Corrigido em 13.0.0. |
| [CVE-2026-112891](https://github.com/advisories/GHSA-fc9g-5qg7-mf45) | pillow 12.3.0 | Gravação GIF / comentários extensos. Não se gravam GIF; saída canónica é PNG. | Corrigido em 13.0.0. |
| [CVE-2026-112405](https://github.com/advisories/GHSA-cp9v-662q-vvx9) | pillow 12.3.0 | Image.merge com bandas I/F e IPTC. Não se fornecem estas bandas a merge nem se aceitam IPTC. | Corrigido em 13.0.0. |
| [CVE-2026-112390](https://github.com/advisories/GHSA-22hg-r758-rrw9) | pillow 12.3.0 | MIC / enumeração n_frames. MIC não é percorrido; whitelist PNG impede a sua seleção. | Corrigido em 13.0.0. |
| [CVE-2026-112401](https://github.com/advisories/GHSA-74r2-7ff9-mjj2) | pillow 12.3.0 | GIF / comentários no Image.open. Relevante para o antigo autodetetor antes da validação de formato; agora apenas o plugin PNG é tentado. | Corrigido em 13.0.0. |
| [CVE-2026-112901](https://github.com/advisories/GHSA-xgh8-jp6q-p5x8) | pillow 12.3.0 | XBM / expressão regular no Image.open. Relevante para o antigo autodetetor antes da validação; whitelist PNG impede o parser XBM. | Corrigido em 13.0.0. |
| [CVE-2026-112391](https://github.com/advisories/GHSA-254f-3936-288h) | pillow 12.3.0 | Pillow PdfParser / recursão. Não se usa o parser PDF de Pillow ou append=True; relatórios usam ReportLab. | Corrigido em 13.0.0. |
| [CVE-2026-112894](https://github.com/advisories/GHSA-jg86-v3jv-hrpm) | pillow 12.3.0 | Pillow PDF save_all. Não se produzem PDFs por Pillow save_all. | Corrigido em 13.0.0. |
| [CVE-2026-112406](https://github.com/advisories/GHSA-f2g6-542v-9j58) | pillow 12.3.0 | Pillow PdfParser / ciclos na árvore. Não se usa o parser/reescrita de PDFs de Pillow. | Corrigido em 13.0.0. |
| [CVE-2026-112399](https://github.com/advisories/GHSA-5xm2-6676-qcp9) | pillow 12.3.0 | APNG / disposal e carregamento de frames. Não se percorrem frames; assinaturas com vários frames são rejeitadas. PNG permanece uma superfície relevante. | Corrigido em 13.0.0. |
| [CVE-2026-112892](https://github.com/advisories/GHSA-gg2r-wvfm-q9rx) | pillow 12.3.0 | MSP / expansão RLE. Não se carrega MSP; whitelist impede o seu plugin. | Corrigido em 13.0.0. |
| [CVE-2026-112393](https://github.com/advisories/GHSA-332p-7hrc-92wf) | pillow 12.3.0 | Gravação TIFF para BytesIO. Não se grava TIFF; BytesIO de PNG não chama este encoder. | Corrigido em 13.0.0. |
| [CVE-2026-96638](https://github.com/advisories/GHSA-24rc-8hj2-v98c) | pillow 12.3.0 | BMP / expansão RLE. Não se carrega BMP; whitelist impede o seu plugin. | Corrigido em 13.0.0. |
| [CVE-2026-96641](https://github.com/advisories/GHSA-4rm8-3hmm-39fg) | pillow 12.3.0 | Dimensões/coordenadas de imagem nativa. Não se aceitam coordenadas arbitrárias de crop; dimensões de assinaturas são limitadas. | Corrigido em 13.0.0. |
| [CVE-2026-96640](https://github.com/advisories/GHSA-mrfp-p49p-3hf2) | pillow 12.3.0 | Pillow PDF append / árvore de páginas. Não se acrescentam imagens a PDFs através do parser de Pillow. | Corrigido em 13.0.0. |
| [CVE-2026-96642](https://github.com/advisories/GHSA-3j72-p6qg-6xp7) | pillow 12.3.0 | TarIO / tamanho negativo. Não se usa PIL.TarIO; os backups usam tarfile com validação própria. | Corrigido em 13.0.0. |
| [CVE-2026-96639](https://github.com/advisories/GHSA-v9pv-5gc8-w2m6) | pillow 12.3.0 | Imagem multi-frame / mudança de modo. Não se percorrem frames; assinaturas multiframe são rejeitadas. | Corrigido em 13.0.0. |
| [CVE-2026-96643](https://github.com/advisories/GHSA-g4qv-2jxx-769h) | pillow 12.3.0 | PNG / processamento EXIF quadrático. Superfície relevante: assinaturas PNG são dados do utilizador. Limite de 256 KiB e remoção de metadados ajudam; atualização corrige a biblioteca. | Corrigido em 13.0.0. |
| [CVE-2026-96637](https://github.com/advisories/GHSA-g842-9rc4-69pw) | pillow 12.3.0 | SPIDER / seek e decompression bomb. Não se aceitam SPIDER nem se percorrem os seus frames. | Corrigido em 13.0.0. |
| [CVE-2026-96644](https://github.com/advisories/GHSA-9v9v-9qvf-h2hj) | pillow 12.3.0 | WMF/EMF / decoder nativo Windows. Não se aceitam metaficheiros; whitelist PNG é especialmente relevante no Windows. | Corrigido em 13.0.0. |
| [CVE-2026-96778](https://github.com/advisories/GHSA-g7cr-3p24-7wf7) | pillow 12.3.0 | JPEG / gravação ICC + comentário. Não se regravam assinaturas como JPEG ou conservam ICC/comentários. | Corrigido em 13.0.0. |
| [CVE-2026-96636](https://github.com/advisories/GHSA-p8hx-v2p6-rp84) | pillow 12.3.0 | MPO/DCX / frames posteriores. Não se aceitam estes formatos nem se percorrem frames. | Corrigido em 13.0.0. |
| [GHSA-78g4-xqwv-q3g8](https://github.com/advisories/GHSA-78g4-xqwv-q3g8) | pillow 12.3.0 | JPEG2000 / OpenJPEG das wheels. Não se carregam JPEG2000; apenas PNG é descodificado na assinatura. | Corrigido em 13.0.0. |
| [CVE-2026-114501](https://github.com/advisories/GHSA-654x-cwwv-5j9c) | pillow 12.3.0 | Exportação Arrow com alinhamento. Não se usa Arrow nem PILLOW_ALIGNMENT personalizado. | Corrigido em 13.0.0. |
| [CVE-2026-112398](https://github.com/advisories/GHSA-5x8w-8jj5-q52h) | pillow 12.3.0 | FlashPix / FPX e JPEG tiles. Não se aceita FPX; whitelist impede o plugin mesmo se olefile vier a existir. | Corrigido em 13.0.0. |

## Verificação e limites

A consulta posterior das dependências de execução, exportadas do lockfile com
hashes, não identificou vulnerabilidades conhecidas na data da execução.
A CI passa a repetir essa consulta; poderá falhar se forem publicados novos
avisos. Não há uma lista de avisos ignorados no pipeline.

A antiga branch Stage 7 contém cryptography 46.0.7, com o aviso adicional
`GHSA-537c-gmf6-5ccf` (correção indicada em 48.0.1). Esta preparação não reescreve
branches históricas. As correções são aplicadas na nova branch baseada em main e
coordenadas com o PR #13; versões antigas não devem ser usadas para distribuir
instaladores ou executar uma instalação nova.

A reprodução de três PDFs sintéticos emitidos sob Pillow 12.3.0/cryptography
48.0.1 foi validada byte a byte com as versões novas: entrada, saída simples e
saída assinada. A restante validação e os limites Windows constam de
`public-readiness.md`. Não se abriram PDFs ou assinaturas reais nesta tarefa.
