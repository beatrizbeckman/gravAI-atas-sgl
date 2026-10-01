# Logos das atas

Imagens usadas no topo do `.docx`. O campo `logo` de um template (ex.: `"logo": "dell"` em `templates/dell.json`) é resolvido para `assets/<logo>.png` (ou `.jpg`/`.jpeg`) por `minutes/generate.py:resolve_logo`. Quando o arquivo não existe, a ata sai sem logo.

Coloque aqui, por exemplo, `dell.png` e `ufcg.png`. Imagens largas funcionam melhor (são renderizadas com 4,5 cm de largura).
