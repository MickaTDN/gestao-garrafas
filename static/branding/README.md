# Elementos originais Copo com Vida

Nenhum logótipo original foi fornecido neste trabalho. Não desenhar substitutos.
Fornecer o original completo em SVG/PDF vetorial (ou PNG transparente de alta
resolução), e o símbolo original do copo em ficheiro separado, para preparar:

- `copo-com-vida-logo.png`: logótipo completo, RGB/RGBA, preferencialmente
  transparente, largura de pelo menos 1200 px. Utilizado no login e nos novos
  PDFs, sem distorção. Verificar o contraste sobre fundo branco.
- `copo-com-vida-192.png` e `copo-com-vida-512.png`: ícones quadrados PNG,
  respetivamente 192 e 512 px, fundo verde-escuro e símbolo original branco,
  sem redesenho. Manter o símbolo dentro da zona segura maskable (círculo
  central de 80% do lado).

Estes nomes são pontos de integração, não ficheiros já existentes. A interface
apresenta apenas o nome até existir o logótipo. A PWA conserva temporariamente
os ícones técnicos GG anteriormente fornecidos; não os considera identidade
Copo com Vida. O manifesto e a cache pública passam a usar os originais quando
estes forem acrescentados e a imagem Docker for reconstruída. PDFs históricos
não são regenerados nem recebem a nova marca retroativamente.
