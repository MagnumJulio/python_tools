# Calendário — atualizar os books pelo calendário Bloomberg

A aba **📅 Calendário** lê os releases do dia na tabela `OPT_Macro_Calendar` (a mesma que
alimenta o calendário semanal do site do escritório) e atualiza os books que dependem
deles, sem precisar escolher relatório por relatório.

## Como funciona

1. **Carregar calendário** roda a mesma query do site para a data escolhida (mesmos países
   excluídos; "Só High / Very High" liga o mesmo filtro de relevância).
2. Cada linha tem um **indicador** (coluna `indicator`, ou o nome do evento quando ela está
   vazia). O arquivo `calendar_books.csv` diz qual book cada indicador atualiza.
3. A lista **Books a atualizar** junta os indicadores por book. Exemplo: Change in Nonfarm
   Payrolls, Change in Manuf. Payrolls e Unemployment Rate viram uma linha só, `US Payroll`,
   no horário do primeiro release.
4. Daí:
   - **▶ Atualizar agora** roda os books marcados (igual ao Run Once).
   - **⏰ Agendar** cria agendamentos na aba *Schedule Runs*, um por horário
     (1º release do book + os minutos de atraso). Books com o mesmo horário rodam juntos.
     O engine já tenta de novo até o Haver/Bloomberg trazer o dado novo, então 1 minuto de
     atraso basta.
   - **Agendar sozinho todo dia às 07:00**: com o app aberto, todo dia nesse horário ele
     lê o calendário e agenda tudo, sem ninguém clicar. Se o app abrir depois das 07:00, ele
     agenda na hora (releases que já passaram ficam no log, para rodar com *Atualizar agora*).

O book `UK - Employment and Earnings` usa o mês da divulgação nas URLs do ONS
(ex.: `a01nov2026.xls`), então pelo calendário ele não pergunta o mês.

## Cores da coluna Book

| Cor | Significa | O que fazer |
|---|---|---|
| verde | o book vai ser atualizado | nada |
| laranja `? não mapeado` | indicador novo, ninguém disse qual é o book | selecionar a linha → **🔗 Vincular a book…** |
| cinza `— sem book` | marcado como "não temos book" | nada |
| vermelho `✗ … (não existe)` | o CSV aponta para um nome de book que não está no banco | corrigir o nome no CSV |

## O arquivo `calendar_books.csv`

Fica ao lado do exe (ou do `main.py`). Se não existir, o app cria um com os indicadores
de payroll e Michigan. Abre no Excel ou no Bloco de Notas (botão **📄 Abrir mapeamento**):

```
pais;indicador;book
United States;Change in Nonfarm Payrolls;US Payroll
United States;Change in Manuf. Payrolls;US Payroll
United States;Unemployment Rate;US Payroll
United States;U. of Mich. Sentiment;University of Michigan Sentiment
Czech Republic;Industrial Output YoY;-
```

- `pais` = país como aparece no calendário. `*` vale para qualquer país.
- `indicador` = nome do dado como aparece na coluna Indicador da aba.
- `book` = nome exato do relatório. `-` = "não tem book" (para de aparecer como pendente).
- Maiúsculas/minúsculas não importam. Linhas com `#` no começo são comentários.
- O jeito mais fácil de manter: quando aparecer um laranja, selecione e use **Vincular a book…**;
  o app escreve a linha no CSV. Se o nome de um indicador mudar no calendário, ele volta a
  aparecer em laranja: vincule de novo.

## Modo dev (PC pessoal)

`dev_mocks/seed_db.py` cria `OPT_Macro_Calendar` com releases de hoje (horários relativos a
agora: um que já passou, payroll daqui a 2 minutos, Michigan daqui a 5) e os books
`US Payroll` / `University of Michigan Sentiment`. Para testar sem GUI:

```
python run_dev.py --reset-db --calendar            # mostra indicador -> book
python run_dev.py --calendar 2026-11-06 --all      # outra data, sem filtro de relevância
python run_dev.py --calendar --run                 # e roda os books
```

`MACRO_CALENDAR_BOOKS=caminho.csv` usa outro arquivo de mapeamento.
