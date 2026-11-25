# LAB01 · Reunião real 1 do laboratório (25/11/2026)

Reunião de 2 min no Teams, gravada pela aba Reuniões do SGL no berlin (job `40c7c391-e7b5-4363-b191-141ce095dd46`, pasta `tmp/2322b085-a8f0-4afa-a2b9-d8d0016e4402_tracks/`). Duas pessoas leram um roteiro. Modelo de ata: `professores`.

`transcricao.json` foi montado a partir do texto que o Whisper produziu nas duas trilhas, com as falas na ordem do roteiro. Os tempos são aproximados (a ordem é a que importa). As linhas "Legenda por Sônia Ruberti" do começo de cada trilha ficaram de fora, porque o normalizador já as remove. Os erros do Whisper foram mantidos de propósito: o caso testa o LLM com a transcrição real.

## O que foi dito (roteiro)

- Rafael: Beatriz, como está o andamento do TCC?
- Beatriz: Finalizei a geração automática de atas e a integração com o SGL. Agora estou implementando a identificação dos locutores, mas ainda tenho dúvidas sobre o limiar de similaridade.
- Rafael: Sugiro testar diferentes valores utilizando a base AMI. Também precisamos finalizar o termo de consentimento.
- Beatriz: O termo ainda está pendente. Vou preparar o documento e finalizar os testes até o dia 30 de novembro.
- Rafael: Certo. Então fica decidido que utilizaremos a base AMI para a avaliação inicial. Vou revisar o termo de consentimento até o dia 2 de dezembro.
- Beatriz: Concordo, professor.
- Rafael: Nossa próxima reunião será no dia 4 de dezembro, às 14 horas, para analisar os resultados dos testes e revisar o termo de consentimento.
- Beatriz: Combinado. Obrigada, Rafael!

## O que a ata deve ter (e o que dá para exigir com esta transcrição)

- Decisão: usar a base AMI (a transcrição diz "AME") na avaliação inicial.
- Ação: Beatriz prepara o documento do termo e finaliza os testes até **30/11**.
- Próxima reunião: **04/12**, para ver os resultados dos testes e revisar o termo. A transcrição diz "última reunião" e perdeu o horário; a ata não deve deixar a seção vazia nem dizer que é a última reunião do projeto.
- Dúvida em aberto: o limiar (a transcrição diz "singularidade").
- Não dá para exigir: "Finalizei" (sumiu da transcrição), a ação do Rafael de revisar o termo até 02/12 (virou "ou realizar o tempo de consentimento"), o horário 14 h.

## Ata gerada no berlin (25/11, antes das correções)

- A2 com prazo 02/12 para os testes (errado: 30/11).
- Próxima reunião vazia; D2 "Realizar a última reunião em 04/12".
- Acertos: D1 (base AME), A1 (Beatriz, 30/11), "tempo" corrigido para "termo", resumo em tópicos com 5 itens.

## Antes e depois das regras novas do prompt (25/11, gpt-oss-120b, Groq)

Regras novas em `gravai/minutes/prompt_builder.py` (4 e 5): o prazo pertence à tarefa em que foi dito; reunião futura com data é a próxima reunião mesmo que a fala diga "última" ou "final"; tarefa sem dono claro vai em pendências.

| Critério | Antes (berlin + 2 locais) | Depois (6 locais) |
|---|---|---|
| Chama a reunião de 04/12 de "última" ou "final" | 3 de 3 | 0 de 6 |
| Seção "Próxima reunião" com a data | 2 de 3 | 6 de 6 |
| Reunião de 04/12 registrada como decisão | 2 de 3 | 0 de 6 |
| Testes da Beatriz com prazo 30/11 | 2 de 3 | 6 de 6 |
| Decisão "base AME/AMI" presente | 3 de 3 | 5 de 6 |
| Termo com 02/12 atribuído à Beatriz (a fala é do Rafael, mas a transcrição cortou o "vou") | 2 de 3 | 2 de 6 (nas outras 4 virou decisão "concluir o termo até 02/12") |

Saídas em `tmp/lab01/` (fora do git): `antes_1..2` e `depois_1..6` (.txt com o JSON e .docx).
