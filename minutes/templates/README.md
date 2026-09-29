# Templates de ata

Cada JSON descreve um modelo de ata: o que vai no cabeçalho, quais seções existem, em que ordem, o que cada uma deve conter e o tom do texto. O mesmo arquivo alimenta duas coisas: a montagem do prompt para o LLM e a geração do `.docx`. A ata personalizada (`custom`) usa a mesma estrutura, mas montada em memória a partir do que o usuário pediu na requisição.

## Campos do topo

| Campo | Uso |
|---|---|
| `id`, `name` | Identificador enviado pelo SGL e nome exibido. |
| `title`, `subtitle`, `logo`, `footer` | Só para o `.docx`. `{projeto}` no `footer` é substituído pelo valor do cabeçalho. |
| `language`, `tone` | Vão para o prompt. |
| `header` | Campos da tabela do cabeçalho. `source: request` vem do SGL, nunca do LLM. |
| `participants` | Lista de presentes. `source: transcript` usa os falantes da transcrição; o SGL pode sobrescrever. `inline: true` renderiza numa linha em vez de tabela. |
| `sections` | Corpo da ata, na ordem em que aparecem no documento. |

## Seções

Campos comuns: `key` (chave no JSON de saída do LLM), `title`, `type`, `required`, `allow_empty`, `instructions` (texto que vai para o prompt) e `group` (seções com o mesmo `group` são renderizadas sob esse título, como as bandas escuras abaixo de "RESUMO DA REUNIÃO").

| `type` | O que o LLM devolve | Campos extras |
|---|---|---|
| `paragraph` | string | |
| `bullets` | lista de strings | |
| `topics` | lista de `{titulo, resumo}` | `min_items` |
| `table` | lista de objetos com as chaves de `columns` | `id_prefix` (o ID é gerado no código, não pelo LLM), `columns` |
| `record` | um objeto com as chaves de `fields` | `fields` |

Colunas e campos aceitam `label`, `format`, `values` (valores permitidos), `default` e `instructions`.

Regra geral que todo prompt deve carregar: `required` com `allow_empty: true` significa que a seção sempre aparece na ata, mesmo que vazia; o modelo não inventa conteúdo para preenchê-la.
