# Originais Copo com Vida

A marca foi apresentada como imagem na conversa. O respetivo ficheiro binário
não ficou disponível nos anexos acessíveis ao ambiente de desenvolvimento; por
isso **os elementos finais ainda não estão integrados**. Não reconstruir o copo
por geração de imagem, vetorização aproximada ou desenho genérico.

Para concluir, anexar o ficheiro original como PNG, SVG ou PDF, preferencialmente
vetorial, ou o símbolo do copo original em separado. A pré-visualização tem pouca
resolução no copo; ampliar um recorte para 512 px não recupera os detalhes. Se só
existir esse raster, é necessário verificar a qualidade do recorte e documentar
essa limitação, conservando a geometria original.

## Ficheiros de integração

- `copo-com-vida-logo.png`: logótipo **completo**, RGB/RGBA, sem redesenho nem
  alteração das proporções. Preferencialmente transparente ou com fundo branco,
  largura de pelo menos 1200 px quando disponível. Usado no login e nos novos PDFs.
- `copo-com-vida-192.png` e `copo-com-vida-512.png`: ícones quadrados PNG de 192 e
  512 px, fundo verde-escuro `#102e28` e símbolo original branco. Preservar também
  os elementos interiores do copo. Não incluir o texto ou a moldura do logótipo
  completo no ícone. Manter o símbolo dentro da zona segura maskable (círculo
  central de 80% do lado).
- `copo-com-vida.ico`: a mesma composição para Windows, com tamanhos 16, 24, 32,
  48, 64, 128 e 256 px, sem alterar o desenho original entre tamanhos.

São pontos de integração, não ficheiros finais já existentes. Enquanto faltarem,
a interface apresenta o nome Gestão Vertente Aveludada e a PWA conserva os ícones
GG anteriores; esses ícones não são a identidade Copo com Vida. A aplicação Stock
Vertente Aveludada é independente e não é renomeada nem alterada neste PR.

## Windows e PWA

O manifesto e a cache pública selecionam os PNG originais quando existirem.
Uma alteração ao conteúdo do logótipo/ícones altera a versão da cache. Reconstruir
a imagem e reabrir a PWA para receber os elementos revistos; o navegador pode
atualizar o ícone instalado apenas num arranque/atualização posterior.

`New-GGShortcuts` valida a instalação e copia apenas o `.ico` público do código
para a pasta privada do piloto. O atalho **Gestão Vertente Aveludada - Piloto**
passa a apontar para essa cópia estável, sem alterar os atalhos de paragem e
diagnóstico, as bases, o manifesto, a configuração, os segredos ou os volumes.
Repetir a criação dos atalhos atualiza o ícone quando o original existir. Se o
ficheiro de origem estiver temporariamente ausente, uma cópia já instalada é
preservada; não se gera nenhum substituto.

Para uma instalação existente, seguir o guia de atualização aprovado e repetir
`New-GGShortcuts` com a mesma pasta do piloto. Não foi executado qualquer passo no
Windows do utilizador. Não é necessário reinstalar, migrar ou restaurar dados para
mudar o ícone. PDFs históricos permanecem imutáveis; só os novos usam a marca.
