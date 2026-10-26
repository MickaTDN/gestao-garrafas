# Copo com Vida — originais e ícones da aplicação de gestão

Os elementos foram fornecidos pelo utilizador no ZIP `Copo_com_Vida_para_Codex.zip`.
O ZIP contém apenas o logótipo completo e o recorte original do copo, extraídos
pelo utilizador de um PDF. A fatura não foi importada nem incluída no repositório.

## Originais preservados

Estes dois PNG são cópias byte a byte dos ficheiros recebidos, sem redesenho,
recompressão, vetorização ou alteração das proporções. Não contêm metadados:

| Ficheiro | Dimensões | SHA-256 |
| --- | --- | --- |
| `copo-com-vida-logo.png` | 1273×827, RGB | `58e89b8b1c0d930e8418bae77565367f7785e55740ac435c2d3ba88555c24948` |
| `copo-com-vida-simbolo-original.png` | 143×246, RGB | `e78fb04f5d1e027aa7803c347292cb935e8e021e470299cea2cf0d2242edf567` |

O logótipo completo é utilizado no login e nos **novos PDFs**. A imagem original
é embebida no PDF, sem alteração dos seus píxeis e com escala proporcional.
PDFs históricos guardados permanecem imutáveis; não são regenerados.

## Ícones derivados exclusivamente do recorte original

- `copo-com-vida-192.png` e `copo-com-vida-512.png`: ícones PWA, RGB opaco,
  fundo verde-escuro `#102e28`, traços e detalhes originais do copo a branco.
- `copo-com-vida.ico`: Windows, com tamanhos 16, 24, 32, 48, 64, 128 e 256 px.

A compilação remove apenas as margens vazias do recorte, converte a tinta
cinzento-escura numa máscara de opacidade branca, mantém os valores intermédios
das bordas e redimensiona uniformemente. Não desenha linhas, não preenche os
espaços interiores, não usa modelos generativos e não inventa detalhes. Mantém
os detalhes interiores do copo. O texto e a moldura do logótipo completo não
fazem parte do ícone, conforme o recorte fornecido.

O símbolo é centrado dentro de 72% do lado, preservando as proporções. Para este
original vertical, todos os píxeis ficam dentro da zona segura circular maskable
de raio 40% do lado. Os testes verificam essa condição nos dois PNG.

Para reconstruir os ícones, com as dependências bloqueadas do projeto:

```sh
uv run --frozen python scripts/build_brand_icons.py
```

O script usa apenas o PNG original local e escreve estes três ficheiros públicos.
Não lê `.env`, PDFs, Excel, ficheiros privados nem bases de dados.

Os originais recebidos são raster, não vetoriais. A versão de 512 px usa
reamostragem da mesma matriz; não ganha detalhe novo. Nos tamanhos Windows muito
pequenos, os detalhes interiores tornam-se menos visíveis. Não se redesenha o
símbolo para os acentuar. Um futuro original vetorial autorizado poderá melhorar
a nitidez, mantendo a identidade.

## Utilização e atualização

Mantêm-se os nomes **Gestão Vertente Aveludada** e **Stock Vertente Aveludada**.
Esta alteração aplica-se à aplicação principal; a aplicação Stock separada não
foi alterada.

O manifesto e a cache pública utilizam os PNG da marca. Uma alteração ao conteúdo
dos elementos muda a versão da cache. Reconstruir a imagem e reabrir a PWA para
receber os elementos revistos; o navegador pode atualizar o ícone instalado
apenas num arranque/atualização posterior.

`New-GGShortcuts` valida a instalação e copia apenas o `.ico` público do código
para a pasta privada do piloto. O atalho **Gestão Vertente Aveludada - Piloto**
usa essa cópia estável. Os atalhos de paragem e diagnóstico, o manifesto da
instalação, a configuração, os segredos, as bases e os volumes não são alterados.

Para uma instalação existente, seguir o [guia de atualização](../../docs/windows11.md#atualização-da-etapa-a-num-piloto-existente)
e repetir `New-GGShortcuts` com a mesma pasta do piloto, após revisão. Não foi
executado qualquer passo no Windows do utilizador. A mudança da marca não exige
reinstalar, migrar ou restaurar dados. A aceitação física do ícone no Windows e
na PWA instalada continua a ser uma verificação no dispositivo real.
