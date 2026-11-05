# Avaliação das atas por formulário

Guia para aplicar a avaliação da geração de atas: pessoas leem trechos da reunião e dizem se cada ata está coerente com eles e qual LLM agiu melhor. Os resultados entram no TCC.

**Situação em 04/11:** as atas foram geradas em 03/11 e três entram no formulário (A, B e C); o `qwen` falhou (ver [Gerar as atas](#gerar-as-atas)). O sorteio está feito e o formulário está montado. Este guia traz a reunião, os trechos, as perguntas do formulário e como analisar as respostas.

## Passo a passo

1. ~~Gere as atas (próxima seção).~~ Feito em 03/11: três atas, o `qwen` falhou.
2. Confira se elas saíram completas, sem corrigir nada. Se uma falhar, registre a falha.
3. ~~Sorteie qual modelo será a Ata A, a B e a C.~~ Feito: o resultado está em `chave_avaliacao.md`, fora do repositório e fora do que for compartilhado.
4. ~~Monte o formulário.~~ Feito: é um formulário próprio que mostra as atas dentro da página, então não há PDF nem Drive. Confira se o texto das atas na página é igual ao `ata.docx`, seção por seção, e se nenhum modelo é citado.
5. Abra o link numa janela anônima e no celular, faça um envio completo de teste, confira a linha na planilha e depois apague ou marque esse teste.
6. Faça um piloto com uma pessoa, veja o tempo registrado e ajuste o que ela não entender.
7. Envie o formulário e analise as respostas como descrito em [Análise](#análise-para-o-tcc).

## Gerar as atas

A reunião é a **ES2004a**, kickoff de um projeto de controle remoto, com 298 falas e cerca de 19 min. Foi escolhida por ser a mais curta do dataset e ter decisões, propostas em aberto, conversa fora do assunto e um gabarito humano. Quatro modelos foram testados, cobrindo casos diferentes:

| Modelo | Por que entra |
|---|---|
| `openai/gpt-oss-120b` (Groq) | Padrão do serviço |
| `qwen/qwen3.8-27b` (Groq) | O que mais se destacou nos testes iniciais |
| `liquid/lfm-2.5-2.6b:free` (OpenRouter) | Modelo pequeno, para ver se o formulário percebe diferença de qualidade |
| `gemini-3-flash-preview` (Google) | Fez atas mais completas que o `gpt-oss-120b` na [comparação anterior](../README.md#gemini-3-flash-preview-x-gpt-oss-120b); o formulário confirma ou não essa leitura |

```bash
uv run python experiments/run_experiments.py \
  --transcripts datasets/reunioes/ES2004a/transcricao.json \
  --models groq:openai/gpt-oss-120b groq:qwen/qwen3.8-27b openrouter:liquid/lfm-2.5-2.6b:free gemini:gemini-3-flash-preview \
  --max-chars 24000 \
  --out experiments/results/avaliacao_forms
```

O Gemini precisa da variável `GEMINI_API_KEY` no `.env`.

Com `--max-chars 24000`, a reunião não é dividida em partes. Isso importa porque a divisão já fez esta reunião perder decisões em testes anteriores. Se a cota gratuita do Gemini acabar (já acabou na rodada de 02/11), rode de novo com o mesmo `--out` no dia seguinte (o que já deu certo é pulado).

### Resultado da rodada de 03/11

| Modelo | Status | Partes | Tempo (s) | Tokens in+out |
|---|---|---|---|---|
| `gemini-3-flash-preview` | ok | 1 | 13,2 | 8 719 + 1 069 |
| `openai/gpt-oss-120b` | ok | 1 | 4,4 | 7 770 + 1 519 |
| `liquid/lfm-2.5-2.6b:free` | ok | 1 | 9,9 | 8 379 + 3 313 |
| `qwen/qwen3.8-27b` | falhou (`llm_unreachable`, 413) | | | |

As três que deram certo foram geradas sem dividir a reunião, com o prompt atual (depois da troca do exemplo de nome), e nenhuma resposta foi cortada (`finish_reason: stop`).

**O `qwen` ficou de fora do formulário.** No plano gratuito do Groq, esse modelo aceita no máximo 7 000 tokens de entrada por minuto, e o pedido com a reunião inteira tem 8 758. Não é cota que renova: rodar de novo não resolve. Para ele caber, todas as atas teriam que ser geradas com `--max-chars 12000`, em partes, que é justamente o que fez esta reunião perder decisões antes. Preferi manter as três atas na reunião inteira e registrar a falha como resultado: o modelo não comporta uma reunião de 19 min no plano gratuito.

A ata da ES2004a que já existe em `experiments/results/gemini/` não serve aqui: foi gerada em duas partes de 12 mil caracteres e com o prompt anterior ao ajuste do exemplo de nome.

Cada ata fica em `experiments/results/avaliacao_forms/ES2004a__<provedor>__<modelo>/ata.docx`.

## Montar o formulário

O formulário não é o Google Forms: é uma página própria que reproduz as funções que importam para a análise e grava as respostas numa planilha.

- **Às cegas:** as atas se chamam só A, B e C, e nem o formulário nem o código citam os modelos.
- **Ordem:** as linhas das grades são embaralhadas para cada pessoa, para a Ata A não ser sempre a primeira. A ordem que cada pessoa viu fica gravada na planilha.
- **Acesso às atas:** as atas aparecem dentro do formulário, num painel ao lado no computador e no botão "Ler as atas" no celular.
- **Trecho:** cada seção mostra o trecho, com os números das falas.
- **Tempo:** cada resposta registra quantos minutos a pessoa levou. Com 7 trechos e três atas, a estimativa é de 15 a 20 min; confirme no piloto. Se passar muito disso, corte primeiro o T7 e depois o T6. Como o rascunho é salvo, quem fecha a página e volta depois fica com um tempo inflado: na análise use a mediana e descarte os tempos absurdos.
- **Rascunho:** quem fecha a página no meio continua de onde parou, no mesmo navegador.
- **Login:** confira numa janela anônima que o link abre sem pedir conta.
- **Dados pessoais:** não colete e-mail nem nome.
- **Avaliadores:** convide quem participa de reuniões de projeto, como colegas do lab e gerentes. Tente reunir pelo menos 8 respostas e não participe como respondente, porque você conhece os modelos.

### Texto de abertura

> Este formulário faz parte de um Trabalho de Conclusão de Curso sobre geração automática de atas de reunião. Você vai comparar trechos de uma reunião com três atas geradas por sistemas diferentes (A, B e C). Não existe resposta certa: queremos sua opinião. Leva cerca de 20 minutos. A participação é voluntária e anônima, e as respostas serão usadas de forma agregada. Ao continuar, você concorda em participar. A reunião vem de um conjunto público de pesquisa, traduzido para o português, e pode ter marcas da fala e da tradução.

## Perguntas do formulário

### Seção 1 · Perfil

1. **Com que frequência você participa de reuniões de projeto?** Múltipla escolha: quase todo dia / toda semana / algumas vezes por mês / raramente.
2. **Você já escreveu atas de reunião?** Múltipla escolha: nunca / poucas vezes / muitas vezes.
3. **Qual é o seu papel principal hoje?** Múltipla escolha: estudante / desenvolvedor(a) / gerente ou coordenador(a) / professor(a) / outro (com campo de texto).

### Seções 2 a 8 · Uma seção por trecho

Cole o trecho e repita estas perguntas:

- **A. "A ata está coerente com este trecho."** Grade obrigatória, uma linha por ata (A, B, C). Colunas:
  - 1 · Discordo totalmente
  - 2 · Discordo
  - 3 · Nem concordo nem discordo
  - 4 · Concordo
  - 5 · Concordo totalmente
  - A ata não trata deste assunto
- **B. Comentário (opcional):** "Alguma ata errou, omitiu ou inventou algo sobre este trecho? Qual e o quê?"

**No T7**, troque a pergunta A por: "A ata deu a este trecho a importância adequada." Use as mesmas colunas.

### Seção 9 · Comparação das atas inteiras

4. **Avalie cada ata.** Uma grade por afirmação, com linhas A, B e C e escala de 1 a 5:
   - "A ata traz o que foi importante na reunião." *(completude)*
   - "A ata não traz informações que não foram ditas." *(fidelidade)*
   - "Decisões, ideias em aberto e tarefas estão nas seções certas." *(organização)*
   - "O texto é claro e tem linguagem de ata." *(clareza)*
   - "Eu usaria esta ata com poucos ajustes." *(utilidade)*
5. **Ordene as atas da melhor para a pior.** Linhas 1º, 2º e 3º lugar e colunas A, B e C, com uma ata por lugar.
6. **Por que você escolheu a primeira colocada?** Resposta curta, obrigatória.
7. **Encontrou alguma informação inventada?** Obrigatória. Caixas de seleção: Ata A / Ata B / Ata C / não encontrei. Acrescente: "Se sim, qual?" (opcional). Se alguém marcar "não encontrei" junto com uma ata, conte só a ata.
8. **Quanto tempo você levaria para deixar a melhor ata pronta para enviar?** Múltipla escolha: nada a ajustar / até 5 min / 5 a 15 min / mais de 15 min / seria mais rápido escrever do zero.
9. **O que mais faltou nas atas?** Parágrafo, opcional.

## Trechos para colocar no formulário

As frases são cópia exata da transcrição, inclusive os erros. O campo "Para sua conferência" é só para você: **não coloque no formulário**, porque induziria a resposta.

### T1 · Preço, custo e meta de lucro

**[111] Paula:** Ok. Isso foi divertido, né. Hum, financeiramente, temos um preço de venda de vinte e cinco euros, que eu realmente não sei quanto isso dá em libras, de jeito nenhum. Alguma ideia?

*[…]*

**[140] Paula:** É, hum, o custo de produção tá em doze e cinquenta, então

**[141] Diego:** Hmm.

**[142] Ulisses:** Ok, margem bem grande.

**[143] Paula:** metade do preço de venda é consumida por construir isso.

**[144] Diego:** É.

**[145] Marina:** Mm.

**[146] Paula:** Hum, e a meta de lucro é cinquenta milhões de euros,

**[147] Marina:** Mm-hmm.

**[148] Paula:** que é, uh

**[149] Marina:** No nosso primeiro ano?

**[150] Paula:** Sim, sim, hum, acho que sim. Hum

> **Para sua conferência:** Preço de venda de 25 euros, custo de produção de 12,50 euros e meta de lucro de 50 milhões de euros. O "primeiro ano" veio em uma pergunta da Marina, e a Paula respondeu "acho que sim", então não é certeza.

### T2 · Público e mercado

**[153] Marina:** Você tem alcance de mercado internacional e você disse antes que tem que ser, hum, acessível e utilizável por praticamente todas as faixas etárias

**[154] Paula:** Mm-hmm.

**[155] Marina:** Só que a gente não está focando no mercado empresarial, nada específico, é todo mundo

**[156] Paula:** Não, é.

**[157] Marina:** amigável para todo mundo. Ok.

**[158] Paula:** Então

**[159] Marina:** Grande grupo-alvo.

**[160] Paula:** sim, sim, eu não acho que a gente precise, eu não acho que seja um caso de se preocupar com diferentes idiomas e coisas assim, hum, fazer disso um ponto chave,

**[161] Marina:** Não.

**[162] Paula:** só que vai estar no mercado internacional, tipo Austrália, América, coisas assim.

> **Para sua conferência:** Mercado internacional, todas as faixas etárias, sem foco no mercado empresarial e sem tratar idiomas como ponto-chave.

### T3 · Menu na tela e botões básicos

**[203] Marina:** Na verdade isso só levanta uma questão, eu me pergunto o que o pessoal de design pensa, mas sabe, num celular, você pode apertar uma tecla e ele te dá um menu, tem uma exibição de menu,

**[204] Ulisses:** Mm-hmm. Menu, certo.

**[205] Marina:** Eu me pergunto se incorporar isso no design de um controle remoto poderia ser útil,

**[206] Diego:** É.

**[207] Ulisses:** Uh uh

**[208] Marina:** então você tem um display L_C_D_ pequeno.

**[209] Ulisses:** Certo, eu estava pensando na mesma linha que você, ao invés de ter muitos botões e complicar pro usuário, talvez ter um display L_C_D_ ou algo assim, tipo um celular, sim, e com menus.

**[210] Marina:** Com menus, sim, sim.

**[211] Ulisses:** E se for meio que parecido com o que você tem no celular, as pessoas podem achar mais fácil navegar e explorar, talvez.

**[212] Marina:** É.

*[…]*

**[244] Paula:** É. Ou que tal meio que uma função dupla? Tipo, você tem os botões básicos só para reproduzir, volume, coisas de programa.

**[245] Marina:** Mm-hmm.

**[246] Paula:** e também, então um menu pra entrar com imagens óbvias, símbolos óbvios e é lá que você controla gravação e coisas assim.

> **Para sua conferência:** Marina propõe display com menu, como no celular; Ulisses apoia; Paula sugere função dupla, com botões básicos e um menu para o resto. É uma direção do grupo, sem uma frase formal de decisão.

### T4 · Tampa flip

**[247] Marina:** É. Mm-hmm. Mm. A outra coisa é, só ch chucking nas características de design de celular de novo, poderia ter um controle remoto com tampa flip, então quando você abre a tampa, sua tela... você pode ter uma tela maior no flip.

**[248] Paula:** Mm-hmm.

**[249] Ulisses:** Mm, ok. S

**[250] Paula:** Eu acho que isso é uma questão de custo, eu não, eu não sei quanto a gente vai saber sobre

**[251] Diego:** Y

**[252] Ulisses:** Pode ser

**[253] Marina:** É?

**[254] Ulisses:** pode economizar um pouquinho de espaço, é i ao invés de parecer volumoso, pode parecer pequeno.

**[255] Marina:** Mm-hmm.

**[256] Paula:** Sim, não, isso é importante.

**[257] Ulisses:** Mas pode ter implicações de custo.

**[258] Diego:** É.

**[259] Marina:** É, tipo menor.

> **Para sua conferência:** Marina sugere a tampa flip. Paula e Ulisses levantam o custo, e Ulisses também cita que economiza espaço. Ninguém recusa formalmente: o gabarito diz "recusaram", mas a transcrição é mais fraca que isso. Uma ata que registre como ideia em aberto por causa do custo está correta.

### T5 · Material e aparência

**[261] Marina:** E não há razão pra a gente fazer parecer tão fashion e estiloso quanto um celular, ainda pode ser plástico leve, sabe?

**[262] Paula:** Mm.

**[263] Ulisses:** Certo.

**[264] Marina:** Algo que seja fácil de moldar e produzir.

*[…]*

**[270] Diego:** É. Só, só uma coisinha rápida sobre o, hum

**[271] Paula:** Claro.

**[272] Diego:** sobre o que você está dizendo sobre o, hum, precisa ser fashion? Tipo, eu dei uma olhada rápida no site da empresa e é tipo, hum, colocamos moda nos eletrônicos, então eu acho que a coisa toda de design pode ser qui

**[273] Marina:** Ah, certo.

**[274] Ulisses:** Ok.

**[275] Paula:** Ok.

**[276] Marina:** Ok.

**[277] Diego:** Quero dizer, você não, você, ainda pode ter plástico

**[278] Marina:** Claro b y yeah.

**[279] Diego:** e ficaria bem legal mas

**[280] Marina:** Mas é, quero dizer, não precisa ser isso, sabe, isso era meu ponto principal,

**[281] Diego:** É.

**[282] Marina:** a gente não precisa usar metal, eu não sei se usar plástico deixa mais barato,

**[283] Paula:** Mm.

**[284] Marina:** Eu presumo que seria.

**[285] Paula:** Eu faria

**[286] Diego:** É. É.

**[287] Marina:** É, é, é.

**[288] Paula:** provavelmente seria. Quero dizer, tem os controles remotos da Sky e tudo mais. Eles são meio moldados e parecem um pouco diferentes, e os controles remotos da Telewest são de plástico prata, que parece um pouco mais inteligente,

**[289] Marina:** Certo.

**[290] Paula:** então, sim, eu acho que isso são coisas que a gente pode pensar.

> **Para sua conferência:** Plástico leve, fácil de moldar, provavelmente mais barato, e a preocupação do Diego com moda. O plástico prata aparece como exemplo da Telewest. A própria Paula fecha com "coisas que a gente pode pensar", então é uma escolha provisória.

### T6 · Próximos passos

**[269] Paula:** a gente tem meia hora antes da próxima reunião, então todo mundo vai se separar e fazer suas coisas individuais. Um, eu acho que é mais ou menos isso e depois a gente volta e se comunica de novo e eu faço outra apresentação fantástica no PowerPoint.

*[…]*

**[292] Paula:** Ok, então vamos parar por aí. Ok?

**[293] Diego:** Ok.

**[294] Marina:** Tá.

**[295] Paula:** Então, a gente se vê em meia hora.

> **Para sua conferência:** Trabalho individual, nova reunião em meia hora e apresentação da Paula em PowerPoint. Nenhuma data ou tarefa com prazo além disso.

### T7 · Controle: a dinâmica dos animais

**[16] Paula:** Ok, certo. Vamos praticar com as canetas e desenhar nosso animal favorito no quadro branco, eu vou primeiro, e hum resumir as características desse animal.

*[…]*

**[19] Paula:** Ok, vou deixar espaço pro resto. Hum, o que falta? Estamos sem azul. Ok. Não vou pedir pra vocês adivinharem, vou dizer que era pra ser um tigre.

**[20] Ulisses:** Mm.

**[21] Paula:** E eu vejo eles como majestosos, independentes e orgulhosos.

**[22] Ulisses:** Ah, desculpa. Mm-hmm.

> **Para sua conferência:** É só a dinâmica de integração. Basta uma menção curta; tratar "tigre" como decisão ou tarefa é erro.

### Trechos reservas

Use se quiser substituir algum trecho depois do piloto.

#### R1 · Objetivo do produto e etapas do projeto

**[14] Paula:** Hum, eu sou a Sarah, a Gerente de Projeto, e essa é a nossa primeira reunião, surpreendentemente. Ok, essa é a nossa agenda, hum, vamos fazer algumas coisas, nos conhecer um pouco melhor pra ficar mais à vontade uns com os outros. Hum, depois vamos fazer treinamento de ferramenta, falar sobre o plano do projeto, discutir nossas próprias ideias e tudo mais, hum, e temos vinte e cinco minutos pra fazer isso, pelo que eu entendi. Agora, a gente está desenvolvendo um controle remoto que vocês provavelmente já conhecem. Hum, queremos que ele seja original, algo que, uh, as pessoas ainda não pensaram, que não esteja nas lojas, hum, moderno, atraente pra um mercado amplo, mas, sabe, não um pedaço de metal, e fácil de usar, avós, crianças, talvez até cachorros deveriam conseguir usar. Ok, hum, primeiro vem o design funcional, hum, é onde cada um vai trabalhar individualmente, hum, quais necessidades o produto deve atender, hum, quais efeitos o produto tem que ter e como ele vai fazer isso. Hum, design conceitual, o que estamos pensando, como vai ser, e depois o design detalhado, como vamos colocar em prática e fazer funcionar.

#### R2 · Excesso de botões e símbolos

**[186] Paula:** É, o principal é isso mesmo, quer dizer

**[187] Marina:** Mm-hmm.

**[188] Paula:** e você não quer... eu odeio, eu odeio olhar pra um controle e ver um milhão de botõezinhos minúsculos com palavrinhas minúsculas dizendo o que cada um faz

**[189] Marina:** Mm.

**[190] Paula:** e ficar só sentado lá procurando o botão de teletexto ou algo assim.

**[191] Diego:** É.

**[192] Marina:** Mm. E símbolos que você não entende necessariamente,

**[193] Paula:** É.

**[194] Marina:** símbolos que você deveria entender mas não entende.

**[195] Ulisses:** Então simplificação de símbolos, algo que você poderia pensar.

#### R3 · Geração mais velha

**[213] Paula:** E a geração mais velha? E a vovó e os avôs?

**[214] Ulisses:** Você quer dizer reduzir o número.

**[215] Paula:** Hum, meu avô consegue atender o celular dele, mas ele não conseguiria nem sonhar em mandar mensagem ou algo assim.

**[216] Diego:** É.

**[217] Marina:** Mm-hmm. Mm-hmm. Ele pode programar o controle remoto dele ou isso também é básico?

**[218] Ulisses:** Certo.

**[219] Paula:** Eu não acho que eles gravam as coisas,

**[220] Diego:** É, meu avô na verdade é melhor que eu em usar teletexto, então

**[221] Paula:** Eu não acho que eles usem

**[222] Marina:** Certo. Certo. Então isso é um problema independentemente de quaisquer modificações de design que vocês venham a propor,

**[223] Diego:** É.

**[224] Marina:** isso vai ser um problema de qualquer forma com a geração mais velha, talvez,

**[225] Paula:** Mm, é, a diferença de idade.

**[226] Diego:** É, o que precisa ser é que seja meio que autoexplicativo e você consiga entender o que cada coisa faz, porque, tipo, os menus nos novos celulares agora têm todas essas imagens e coisas que deixam bem óbvio o que você quer fazer.

## Análise para o TCC

**Por ata e por trecho (pergunta A):**
- mediana e porcentagem de respostas 4 ou 5;
- porcentagem de "A ata não trata deste assunto", separada, sem entrar como nota.

**Por ata e por critério (pergunta 4):** mediana e distribuição das respostas em completude, fidelidade, organização, clareza e utilidade.

**Comparação entre LLMs (pergunta 5):** quantas vezes cada ata ficou em 1º, 2º e 3º e a posição média. Só depois de fechar esses números abra a chave. Com ao menos uns 10 respondentes, o teste de Friedman pode indicar se a diferença é maior do que o acaso; com menos, apresente só a estatística descritiva.

**Comentários:** agrupe por tipo (omissão, informação inventada, seção errada, atribuição errada) e confira cada caso na transcrição. Se alguém apontar uma invenção que está na transcrição, conte como erro do avaliador, não da ata.

**Tabelas sugeridas:**

| Trecho | Ata A (mediana, % 4 ou 5) | Ata B | Ata C | % "não trata" |
|---|---|---|---|---|
| T1 a T7 | | | | |

| Critério | Ata A | Ata B | Ata C |
|---|---|---|---|
| Completude, fidelidade, organização, clareza, utilidade | | | |

**Tempo de resposta:** mediana dos minutos registrados, sem os tempos absurdos de quem saiu e voltou depois.

**Limitações a declarar no TCC:**
- há uma só reunião e uma só execução por modelo, então o resultado não generaliza para outros tipos de reunião;
- o `qwen3.8-27b`, o melhor nos testes iniciais, ficou de fora porque não coube no limite gratuito do Groq com a reunião inteira;
- a reunião é traduzida e não passou pelo Whisper, então não mede erros de transcrição;
- os respondentes não estavam na reunião e avaliam o que está no trecho;
- os respondentes são uma amostra por conveniência;
- os trechos foram escolhidos por quem desenvolveu o sistema;
- o texto traduzido tem marcas como "L_C_D_", e a fala 14 diz "eu sou a Sarah", embora a falante esteja como Paula na transcrição. Se uma ata usar "Sarah", avalie isso à luz desse trecho.

## Chave da avaliação

O sorteio está em `chave_avaliacao.md`, fora do repositório e fora do que for compartilhado com o formulário. Só abra a chave depois de fechar os números da análise; aí copie a tabela abaixo para cá.

| Ata | Modelo | Status | Tempo (s) | Observação |
|---|---|---|---|---|
| A | | | | |
| B | | | | |
| C | | | | |

## Reunião completa (ES2004a)

- **Participantes:** Paula (Gerente de Projeto), Diego (Designer Industrial), Ulisses (Designer de Interface) e Marina (Marketing).
- **Cabeçalho da ata:** projeto Controle Remoto Universal, nº 001, 02/03/2026, 14:00 – 14:19 (fictício).
- **Fonte:** AMI Meeting Corpus via QMSum, traduzida para o português. Os tempos são estimados pelo número de palavras.
- **Arquivo usado na geração:** `datasets/reunioes/ES2004a/transcricao.json`. O resumo humano está em `datasets/reunioes/ES2004a/gabarito.md`.


`00:00` **[1] Ulisses:** Hmm hmm hmm.

`00:01` **[2] Paula:** Será que a gente não pode diminuir as luzes pra as pessoas verem isso um pouco melhor?

`00:08` **[3] Ulisses:** É.

`00:09` **[4] Paula:** Ok, tudo bem. Eu devo ficar em pé lá? Ok.

`00:14` **[5] Marina:** Então a gente tem os dois presos? Ela vai me responder ou não?

`00:20` **[6] Paula:** É, eu tenho

`00:21` **[7] Marina:** Certo, os dois, ok.

`00:23` **[8] Paula:** Sim.

`00:24` **[9] Marina:** Deus.

`00:25` **[10] Marina:** Jesus, vai cair.

`00:27` **[11] Ulisses:** Ok. Sim, sim. Ok. Tu tu tu tu

`00:31` **[12] Paula:** Ok. Olá pessoal.

`00:32` **[13] Ulisses:** Oi, bom dia.

`00:34` **[14] Paula:** Hum, eu sou a Sarah, a Gerente de Projeto, e essa é a nossa primeira reunião, surpreendentemente. Ok, essa é a nossa agenda, hum, vamos fazer algumas coisas, nos conhecer um pouco melhor pra ficar mais à vontade uns com os outros. Hum, depois vamos fazer treinamento de ferramenta, falar sobre o plano do projeto, discutir nossas próprias ideias e tudo mais, hum, e temos vinte e cinco minutos pra fazer isso, pelo que eu entendi. Agora, a gente está desenvolvendo um controle remoto que vocês provavelmente já conhecem. Hum, queremos que ele seja original, algo que, uh, as pessoas ainda não pensaram, que não esteja nas lojas, hum, moderno, atraente pra um mercado amplo, mas, sabe, não um pedaço de metal, e fácil de usar, avós, crianças, talvez até cachorros deveriam conseguir usar. Ok, hum, primeiro vem o design funcional, hum, é onde cada um vai trabalhar individualmente, hum, quais necessidades o produto deve atender, hum, quais efeitos o produto tem que ter e como ele vai fazer isso. Hum, design conceitual, o que estamos pensando, como vai ser, e depois o design detalhado, como vamos colocar em prática e fazer funcionar.

`01:54` **[15] Ulisses:** Tá.

`01:55` **[16] Paula:** Ok, certo. Vamos praticar com as canetas e desenhar nosso animal favorito no quadro branco, eu vou primeiro, e hum resumir as características desse animal.

`02:06` **[17] Paula:** Então

`02:07` **[18] Ulisses:** Ops.

`02:08` **[19] Paula:** Ok, vou deixar espaço pro resto. Hum, o que falta? Estamos sem azul. Ok. Não vou pedir pra vocês adivinharem, vou dizer que era pra ser um tigre.

`02:21` **[20] Ulisses:** Mm.

`02:22` **[21] Paula:** E eu vejo eles como majestosos, independentes e orgulhosos.

`02:26` **[22] Ulisses:** Ah, desculpa. Mm-hmm.

`02:28` **[23] Paula:** Agora, quem gostaria de ir em seguida?

`02:31` **[24] Ulisses:** É, eu.

`02:32` **[25] Paula:** Tá.

`02:33` **[26] Ulisses:** Gato. De onde isso veio?

`02:36` **[27] Paula:** É a sua lapela então?

`02:38` **[28] Ulisses:** Ah, sim.

`02:39` **[29] Paula:** Aí está.

`02:41` **[30] Ulisses:** Obrigado. Ah, talvez vocês possam adivinhar o que eu estou tentando fazer?

`02:46` **[31] Marina:** Um tipo de cachorro?

`02:48` **[32] Ulisses:** Sim. Na verdade está sentado, então

`02:50` **[33] Diego:** Está sentado.

`02:52` **[34] Marina:** Desculpa?

`02:52` **[35] Ulisses:** Está sentado, não está em pé.

`02:55` **[36] Marina:** Ah.

`02:55` **[37] Ulisses:** Ok, eu vejo isso como uma coisa só, muito apoiadora. É seu melhor amigo e você pode conversar com um cachorro, ele pode ser seu melhor amigo, não discrimina você, baseado no que você é. Segundo, ele é leal e, terceira coisa, tem intuição. Cães às vezes conseguem distinguir entre um ladrão e uma pessoa.

`03:19` **[38] Marina:** Mm-hmm.

`03:20` **[39] Ulisses:** Então, basicamente, essas são as três características únicas que eu acho que pertencem a um cachorro.

`03:25` **[40] Paula:** Ok, obrigado.

`03:27` **[41] Ulisses:** Obrigado.

`03:28` **[42] Diego:** É, eu vou tentar.

`03:31` **[43] Ulisses:** Ok. Desculpa.

`03:32` **[44] Diego:** Valeu.

`03:32` **[45] Marina:** Por favor, por favor me deixa um espaço na parte de baixo, eu sou baixinho,

`03:37` **[46] Diego:** Certo, ok.

`03:38` **[47] Marina:** você pode chegar ao topo, ficando em pé numa cadeira.

`03:43` **[48] Diego:** Bom, já que vocês escolheram os que eu queria fazer, eu vou ter que escolher algo meio aleatório.

`03:52` **[49] Ulisses:** Será que parece um cachorro, na verdade?

`03:55` **[50] Paula:** Ok.

`03:56` **[51] Diego:** E também, minha habilidade de desenhar não é tão boa, então, é.

`04:00` **[52] Paula:** Bom, como vocês podem ver, a qualidade do trabalho hoje é, hum

`04:06` **[53] Ulisses:** Hmm.

`04:06` **[54] Marina:** Eu acho que está extraordinariamente bom.

`04:09` **[55] Diego:** Ok, agora eu vou ter que mudar o que era pra ser originalmente

`04:14` **[56] Diego:** porque isso parece um bico agora, então. É, pode ser um crocodilo, pode ser um crocodilo.

`04:22` **[57] Marina:** Crocodilo?

`04:23` **[58] Paula:** Vai ser um pássaro. Vai ser

`04:26` **[59] Diego:** Bom, era, era um no começo

`04:30` **[60] Paula:** vai ser um pássaro.

`04:32` **[61] Diego:** Primeiro era uma tentativa de um T-Rex e depois meio que virou um pelicano

`04:39` **[62] Marina:** O

`04:40` **[63] Diego:** mas pode ser um crocodilo agora, na verdade.

`04:44` **[64] Paula:** Que lindo.

`04:45` **[65] Diego:** É, e, eu vou ter que pensar na hora nas coisas que ele é. Hum

`04:52` **[66] Marina:** Bonito, isso é

`04:53` **[67] Diego:** uh assustador, uh forte, é, é mais ou menos isso, eu acho.

`04:57` **[68] Paula:** Ok, tudo bem.

`04:59` **[69] Marina:** Ok. Hum, estou muito impressionada com suas habilidades artísticas,

`05:02` **[70] Diego:** Uh uh

`05:04` **[71] Marina:** as minhas são terríveis. Opa, isso está se desfazendo, deixa eu colocar a parte de cima.

`05:10` **[72] Diego:** Uó

`05:11` **[73] Marina:** Espero que encaixe, eu só vou segurar, ok.

`05:16` **[74] Marina:** Ops, ai meu, o que aconteceu aí?

`05:19` **[75] Paula:** Ajuda técnica.

`05:20` **[76] Diego:** Hmm.

`05:21` **[77] Marina:** Tomara que fique, versão de duas mãos.

`05:23` **[78] Diego:** Ok.

`05:24` **[79] Marina:** Ok, uh de novo, isso é meio que na hora, eu ia fazer um gato grande também, hum.

`05:32` **[80] Diego:** Uh

`05:33` **[81] Paula:** Hmm.

`05:34` **[82] Marina:** Oh, querido, não parece... tipo... o que eu quero que seja.

`05:39` **[83] Diego:** S Uh

`05:40` **[84] Marina:** Uh.

`05:41` **[85] Marina:** Não é um morcego vampiro, honestamente.

`05:44` **[86] Paula:** Ok, tá.

`05:45` **[87] Marina:** Uh, e em algum lugar tem um corpo atrás.

`05:48` **[88] Diego:** Ok, algum tipo de pássaro

`05:50` **[89] Marina:** Isso é... meu... terrível, é o pior até agora, quer dizer que é uma águia.

`05:56` **[90] Paula:** Um... gaivota

`05:57` **[91] Ulisses:** Águia, ok.

`05:59` **[92] Paula:** certo,

`05:59` **[93] Diego:** Ah, águia, certo, ok.

`06:01` **[94] Paula:** não é uma gaivota.

`06:03` **[95] Marina:** Você pode dizer que é um animal voador, poderia ter sido uma gaivota, nunca pensei numa gaivota. Uma águia, hum, de novo estou pensando nos meus pés, nossa. Acho que todas são tão independentes, eu colocaria essa de novo. Da dum um.

`06:20` **[96] Diego:** Eles são bons no golfe.

`06:22` **[97] Marina:** Independente, independente, né, você disse que eles são bons no golfe?

`06:26` **[98] Paula:** Águia.

`06:27` **[99] Diego:** É, não, é,

`06:28` **[100] Marina:** São?

`06:30` **[101] Diego:** uma águia.

`06:31` **[102] Marina:** Oh. Ah, certo, ok,

`06:33` **[103] Marina:** Eu não sou bom no golfe.

`06:35` **[104] Marina:** Eu diria que eles são bem livre-espírito, voando por aí, fazendo o que quiserem. E hum, aves de rapina não são?

`06:43` **[105] Paula:** Mm-hmm.

`06:43` **[106] Marina:** Oh querido, intrépido. Vou colocar isso, intrépido.

`06:47` **[107] Marina:** Aí vamos,

`06:48` **[108] Paula:** Isso é adorável.

`06:49` **[109] Marina:** espero que essa caneta vá ficar ok.

`06:52` **[110] Marina:** Ops.

`06:53` **[111] Paula:** Ok. Isso foi divertido, né. Hum, financeiramente, temos um preço de venda de vinte e cinco euros, que eu realmente não sei quanto isso dá em libras, de jeito nenhum. Alguma ideia?

`07:05` **[112] Diego:** É mais ou menos

`07:06` **[113] Ulisses:** Um ponto quatro ou algo assim.

`07:09` **[114] Diego:** mm, mm, yeah.

`07:10` **[115] Marina:** Dezessete.

`07:11` **[116] Ulisses:** Um ponto quatro euro seria uma libra ou algo assim.

`07:16` **[117] Diego:** É, é, algo assim,

`07:19` **[118] Ulisses:** É.

`07:19` **[119] Diego:** então isso

`07:21` **[120] Paula:** D quinze?

`07:22` **[121] Diego:** é, mais ou menos dezessete, dezessete libras, algo assim.

`07:25` **[122] Paula:** Dezessete.

`07:26` **[123] Marina:** Dezessete libras.

`07:27` **[124] Paula:** Ok, isso é caro.

`07:29` **[125] Marina:** A gente deveria anotar isso? Podemos só consultar depois, né?

`07:35` **[126] Paula:** Eu acho que sim, eu acho que sim,

`07:38` **[127] Diego:** Mas

`07:39` **[128] Paula:** Eu vou conseguir, hum, puxar isso,

`07:42` **[129] Marina:** É, ok.

`07:43` **[130] Paula:** ou eu poderia colocar na pasta compartilhada ou algo assim.

`07:48` **[131] Diego:** O Havi disse isso, mas se você quiser pegar um desses, os que estão no mercado agora custam, tipo, uns vinte libras, de qualquer forma.

`07:59` **[132] Marina:** Ok.

`08:00` **[133] Diego:** Então, ainda seria

`08:02` **[134] Paula:** Sério?

`08:03` **[135] Marina:** Certo.

`08:04` **[136] Diego:** é, a gente teve que comprar um.

`08:06` **[137] Marina:** Então

`08:07` **[138] Paula:** Mm. Eu acho

`08:09` **[139] Marina:** então eu suponho que depois vai depender se a gente quer baixar o preço, tipo, ou se isso vai fazer nosso produto parecer uma opção baratinha, baratinha?

`08:20` **[140] Paula:** É, hum, o custo de produção tá em doze e cinquenta, então

`08:23` **[141] Diego:** Hmm.

`08:24` **[142] Ulisses:** Ok, margem bem grande.

`08:26` **[143] Paula:** metade do preço de venda é consumida por construir isso.

`08:31` **[144] Diego:** É.

`08:31` **[145] Marina:** Mm.

`08:32` **[146] Paula:** Hum, e a meta de lucro é cinquenta milhões de euros,

`08:36` **[147] Marina:** Mm-hmm.

`08:36` **[148] Paula:** que é, uh

`08:38` **[149] Marina:** No nosso primeiro ano?

`08:40` **[150] Paula:** Sim, sim, hum, acho que sim. Hum

`08:43` **[151] Marina:** Mm-hmm.

`08:44` **[152] Ulisses:** Então então

`08:45` **[153] Marina:** Você tem alcance de mercado internacional e você disse antes que tem que ser, hum, acessível e utilizável por praticamente todas as faixas etárias

`08:55` **[154] Paula:** Mm-hmm.

`08:56` **[155] Marina:** Só que a gente não está focando no mercado empresarial, nada específico, é todo mundo

`09:02` **[156] Paula:** Não, é.

`09:03` **[157] Marina:** amigável para todo mundo. Ok.

`09:05` **[158] Paula:** Então

`09:05` **[159] Marina:** Grande grupo-alvo.

`09:07` **[160] Paula:** sim, sim, eu não acho que a gente precise, eu não acho que seja um caso de se preocupar com diferentes idiomas e coisas assim, hum, fazer disso um ponto chave,

`09:19` **[161] Marina:** Não.

`09:19` **[162] Paula:** só que vai estar no mercado internacional, tipo Austrália, América, coisas assim.

`09:26` **[163] Marina:** Mm.

`09:27` **[164] Paula:** Ok. Quais são as suas experiências com controles remotos? Quero dizer, eu... a gente... a gente tinha três vídeos, uma TV e um tipo de amplificador tudo configurado

`09:39` **[165] Ulisses:** Mm-hmm.

`09:39` **[166] Paula:** então a gente pegou um dos controles remotos universais, um que você programa cada um dos seus aparelhos nele,

`09:47` **[167] Diego:** É.

`09:47` **[168] Ulisses:** É,

`09:48` **[169] Diego:** É.

`09:49` **[170] Marina:** Certo.

`09:50` **[171] Ulisses:** that c

`09:51` **[172] Paula:** mas isso ficava perdendo o sinal, então a gente tinha que reprogramar de vez em quando. Acho que era bem barato também, então isso pode ter tido a ver com isso,

`10:05` **[173] Diego:** É, uh.

`10:06` **[174] Marina:** Mm-hmm.

`10:07` **[175] Paula:** mas isso era bem legal, o fato de que você podia... Você não precisava ter seis controles remotos na sua frente.

`10:15` **[176] Diego:** Usar todos ao mesmo tempo.

`10:19` **[177] Marina:** Certo.

`10:20` **[178] Ulisses:** Ok, você quer integrar tudo em um só, tipo

`10:23` **[179] Diego:** É,

`10:24` **[180] Ulisses:** Ok.

`10:25` **[181] Marina:** Mm-hmm.

`10:25` **[182] Diego:** porque você

`10:27` **[183] Marina:** Minha experiência tem sido só receber o controle remoto junto com o objeto que eu compro, sem mexer nele nem programar, usando pra programar a TV e, uh, vídeos e coisas assim. Mas basicamente ligar, desligar, subir e baixar volume, canal um, dois, essas funções básicas,

`10:46` **[184] Paula:** Mm.

`10:47` **[185] Marina:** Não acho que eu conseguiria ir além disso, então, suponho que tem que ser algo utilizável por alguém como eu também.

`10:57` **[186] Paula:** É, o principal é isso mesmo, quer dizer

`11:02` **[187] Marina:** Mm-hmm.

`11:02` **[188] Paula:** e você não quer... eu odeio, eu odeio olhar pra um controle e ver um milhão de botõezinhos minúsculos com palavrinhas minúsculas dizendo o que cada um faz

`11:14` **[189] Marina:** Mm.

`11:15` **[190] Paula:** e ficar só sentado lá procurando o botão de teletexto ou algo assim.

`11:20` **[191] Diego:** É.

`11:21` **[192] Marina:** Mm. E símbolos que você não entende necessariamente,

`11:24` **[193] Paula:** É.

`11:25` **[194] Marina:** símbolos que você deveria entender mas não entende.

`11:29` **[195] Ulisses:** Então simplificação de símbolos, algo que você poderia pensar.

`11:32` **[196] Paula:** Um. Quando você tem as coisas principais na frente e uma seção abre ou algo assim para as outras funções onde você pode ajustar som ou opções tipo gravação, coisas assim dentro dele.

`11:48` **[197] Marina:** Ah, é. Mm-hmm.

`11:49` **[198] Paula:** Porque não faz, quando você pega, não deixa tudo muito complicado de olhar,

`11:57` **[199] Marina:** Mm.

`11:58` **[200] Paula:** é óbvio o que você está fazendo, um.

`12:00` **[201] Marina:** Mm-hmm.

`12:01` **[202] Diego:** Mm.

`12:02` **[203] Marina:** Na verdade isso só levanta uma questão, eu me pergunto o que o pessoal de design pensa, mas sabe, num celular, você pode apertar uma tecla e ele te dá um menu, tem uma exibição de menu,

`12:16` **[204] Ulisses:** Mm-hmm. Menu, certo.

`12:18` **[205] Marina:** Eu me pergunto se incorporar isso no design de um controle remoto poderia ser útil,

`12:24` **[206] Diego:** É.

`12:25` **[207] Ulisses:** Uh uh

`12:26` **[208] Marina:** então você tem um display L_C_D_ pequeno.

`12:29` **[209] Ulisses:** Certo, eu estava pensando na mesma linha que você, ao invés de ter muitos botões e complicar pro usuário, talvez ter um display L_C_D_ ou algo assim, tipo um celular, sim, e com menus.

`12:45` **[210] Marina:** Com menus, sim, sim.

`12:47` **[211] Ulisses:** E se for meio que parecido com o que você tem no celular, as pessoas podem achar mais fácil navegar e explorar, talvez.

`12:57` **[212] Marina:** É.

`12:58` **[213] Paula:** E a geração mais velha? E a vovó e os avôs?

`13:02` **[214] Ulisses:** Você quer dizer reduzir o número.

`13:05` **[215] Paula:** Hum, meu avô consegue atender o celular dele, mas ele não conseguiria nem sonhar em mandar mensagem ou algo assim.

`13:13` **[216] Diego:** É.

`13:14` **[217] Marina:** Mm-hmm. Mm-hmm. Ele pode programar o controle remoto dele ou isso também é básico?

`13:20` **[218] Ulisses:** Certo.

`13:21` **[219] Paula:** Eu não acho que eles gravam as coisas,

`13:23` **[220] Diego:** É, meu avô na verdade é melhor que eu em usar teletexto, então

`13:28` **[221] Paula:** Eu não acho que eles usem

`13:30` **[222] Marina:** Certo. Certo. Então isso é um problema independentemente de quaisquer modificações de design que vocês venham a propor,

`13:37` **[223] Diego:** É.

`13:38` **[224] Marina:** isso vai ser um problema de qualquer forma com a geração mais velha, talvez,

`13:43` **[225] Paula:** Mm, é, a diferença de idade.

`13:45` **[226] Diego:** É, o que precisa ser é que seja meio que autoexplicativo e você consiga entender o que cada coisa faz, porque, tipo, os menus nos novos celulares agora têm todas essas imagens e coisas que deixam bem óbvio o que você quer fazer.

`14:05` **[227] Paula:** Mm.

`14:06` **[228] Ulisses:** Mm-hmm.

`14:07` **[229] Paula:** Eu não sei, eu...

`14:09` **[230] Diego:** Mas eu não sei como

`14:12` **[231] Paula:** Eu não gosto dos, sabe, novos celulares que têm um sistema baseado em Windows.

`14:19` **[232] Diego:** Ah, é.

`14:20` **[233] Marina:** Mm-hmm.

`14:21` **[234] Paula:** Eu acho isso muito confuso, eu ficava perdido no celular, eu... eu não tenho um novo, mas uh meu amigo comprou um novo

`14:32` **[235] Marina:** Certo.

`14:33` **[236] Paula:** e eu estava tentando fazer coisas com ele e ficava perdido, mas isso é só comigo.

`14:40` **[237] Diego:** É, eu não, eu não sei como, por vinte e cinco, ou doze euros e cinquenta, quanto de uma tela excelente você poderia ter,

`14:50` **[238] Paula:** É.

`14:50` **[239] Diego:** Você teria que manter isso como um display L_C_D_ preto e branco, de qualquer forma, eu imagino.

`14:58` **[240] Marina:** Mm-hmm. É possível que para a geração mais velha você possa ter um botão extra que você aperta para impressão grande, como nos livros em impressão grande?

`15:10` **[241] Ulisses:** Ok.

`15:11` **[242] Paula:** Teletext tem essa opção também.

`15:14` **[243] Marina:** Obviamente, ele exibe menos na tela, exibe menos na tela, mas enquanto eles conseguirem ler, isso é o principal.

`15:24` **[244] Paula:** É. Ou que tal meio que uma função dupla? Tipo, você tem os botões básicos só para reproduzir, volume, coisas de programa.

`15:33` **[245] Marina:** Mm-hmm.

`15:34` **[246] Paula:** e também, então um menu pra entrar com imagens óbvias, símbolos óbvios e é lá que você controla gravação e coisas assim.

`15:44` **[247] Marina:** É. Mm-hmm. Mm. A outra coisa é, só ch chucking nas características de design de celular de novo, poderia ter um controle remoto com tampa flip, então quando você abre a tampa, sua tela... você pode ter uma tela maior no flip.

`16:02` **[248] Paula:** Mm-hmm.

`16:03` **[249] Ulisses:** Mm, ok. S

`16:04` **[250] Paula:** Eu acho que isso é uma questão de custo, eu não, eu não sei quanto a gente vai saber sobre

`16:11` **[251] Diego:** Y

`16:12` **[252] Ulisses:** Pode ser

`16:13` **[253] Marina:** É?

`16:14` **[254] Ulisses:** pode economizar um pouquinho de espaço, é i ao invés de parecer volumoso, pode parecer pequeno.

`16:21` **[255] Marina:** Mm-hmm.

`16:22` **[256] Paula:** Sim, não, isso é importante.

`16:24` **[257] Ulisses:** Mas pode ter implicações de custo.

`16:27` **[258] Diego:** É.

`16:28` **[259] Marina:** É, tipo menor.

`16:30` **[260] Paula:** Ok.

`16:30` **[261] Marina:** E não há razão pra a gente fazer parecer tão fashion e estiloso quanto um celular, ainda pode ser plástico leve, sabe?

`16:41` **[262] Paula:** Mm.

`16:42` **[263] Ulisses:** Certo.

`16:42` **[264] Marina:** Algo que seja fácil de moldar e produzir.

`16:45` **[265] Paula:** É.

`16:46` **[266] Marina:** Desculpa, estou invadindo o território de vocês, gente.

`16:49` **[267] Paula:** Um, certo, ok

`16:51` **[268] Diego:** Não, uh uh

`16:52` **[269] Paula:** a gente tem meia hora antes da próxima reunião, então todo mundo vai se separar e fazer suas coisas individuais. Um, eu acho que é mais ou menos isso e depois a gente volta e se comunica de novo e eu faço outra apresentação fantástica no PowerPoint.

`17:09` **[270] Diego:** É. Só, só uma coisinha rápida sobre o, hum

`17:13` **[271] Paula:** Claro.

`17:14` **[272] Diego:** sobre o que você está dizendo sobre o, hum, precisa ser fashion? Tipo, eu dei uma olhada rápida no site da empresa e é tipo, hum, colocamos moda nos eletrônicos, então eu acho que a coisa toda de design pode ser qui

`17:34` **[273] Marina:** Ah, certo.

`17:35` **[274] Ulisses:** Ok.

`17:36` **[275] Paula:** Ok.

`17:36` **[276] Marina:** Ok.

`17:37` **[277] Diego:** Quero dizer, você não, você, ainda pode ter plástico

`17:41` **[278] Marina:** Claro b y yeah.

`17:43` **[279] Diego:** e ficaria bem legal mas

`17:46` **[280] Marina:** Mas é, quero dizer, não precisa ser isso, sabe, isso era meu ponto principal,

`17:53` **[281] Diego:** É.

`17:54` **[282] Marina:** a gente não precisa usar metal, eu não sei se usar plástico deixa mais barato,

`18:01` **[283] Paula:** Mm.

`18:02` **[284] Marina:** Eu presumo que seria.

`18:03` **[285] Paula:** Eu faria

`18:05` **[286] Diego:** É. É.

`18:06` **[287] Marina:** É, é, é.

`18:07` **[288] Paula:** provavelmente seria. Quero dizer, tem os controles remotos da Sky e tudo mais. Eles são meio moldados e parecem um pouco diferentes, e os controles remotos da Telewest são de plástico prata, que parece um pouco mais inteligente,

`18:20` **[289] Marina:** Certo.

`18:21` **[290] Paula:** então, sim, eu acho que isso são coisas que a gente pode pensar.

`18:26` **[291] Marina:** Ok.

`18:26` **[292] Paula:** Ok, então vamos parar por aí. Ok?

`18:30` **[293] Diego:** Ok.

`18:31` **[294] Marina:** Tá.

`18:31` **[295] Paula:** Então, a gente se vê em meia hora.

`18:34` **[296] Marina:** A gente volta pro nosso quarto? É?

`18:38` **[297] Ulisses:** Mm, é.

`18:39` **[298] Paula:** Eu acho que sim, né.
