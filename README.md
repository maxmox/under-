# Under Limite Lab

Banco de dados de jogos com **minuto exato de cada chute e gol**, odds
pre-live, e dois motores de precificacao do under limite (linha = placar + 0,5,
mercado "nao sai mais gol ate o fim do periodo"):

- **Motor 1 — empirico.** Conta o que aconteceu. "Jogos que estavam nesta
  situacao — mesmo minuto, mesmo placar em relacao ao favorito, favoritismo
  parecido — em quantos % o placar nao mudou ate o fim do periodo?"
  **Integrado ao Scanner do site Futebol.**
- **Motor 2 — funcao calibrada.** Modelo suave que reproduz o Motor 1 onde
  ha amostra e estima onde nao ha. *A ser refeito* (`motor.py` e o piloto
  antigo, ver *Motor 2* abaixo).

## Pipeline

```bash
python baixar.py          # Understat -> cache/ (paralelo, resumivel, ~2 h do zero)
python carregar.py        # cache/ -> futebol.db (sem rede)
python coletar_odds.py    # football-data.co.uk -> odds pre-live + placar do intervalo
python consolidar.py      # corrige o tempo dos gols pelo placar oficial do intervalo
python exportar_web.py --publicar ../Futebol   # JSON do Motor 1 -> site
python dataset.py exportar                     # futebol.db -> dados/futebol.db.gz
```

Para so usar o banco, sem coletar: `python dataset.py restaurar`.

## Fontes

**Understat** (minuto exato). API JSON interna, nao documentada; exige o header
`X-Requested-With: XMLHttpRequest` (sem ele, 404):

```
GET https://understat.com/main/getLeagueData/<LIGA>/<TEMPORADA>
GET https://understat.com/main/getMatchData/<ID>
```

Cada chute traz `id`, `minute`, `result`, `xG`, `X`/`Y`, `situation`,
`shotType`, jogador. Cobertura: EPL, La_liga, Bundesliga, Serie_A, Ligue_1,
RFPL, temporadas 2014–2026.

**football-data.co.uk** (pre-live). CSV por divisao/temporada:
`https://www.football-data.co.uk/mmz4281/<1415>/<E0>.csv`. Uso: 1X2 e O/U 2.5
(abertura e fechamento), Betfair Exchange, placar do intervalo (`HTHG/HTAG`),
escanteios e vermelhos **finais** (sem minuto). Nao cobre a RFPL.

O casamento entre as duas fontes nao usa tabela de apelidos: os nomes sao
casados por similaridade **dentro de cada liga-temporada** e cada par e
**confirmado pelo placar final**. Divergencia de placar = jogo fora (pegou,
por exemplo, um Sassuolo 2-1 em campo que virou 0-3 no tribunal).

## Correcoes sobre o dado cru — todas medidas

| Problema | Medida | Correcao |
|---|---|---|
| **Gol contra** (`OwnGoal`) fica no lado de quem fez o contra | contando so `Goal`, o placar batia em 92,3% dos jogos | `gol_para` = adversario; placar bate em **99,83%** |
| **Acrescimo do 1o tempo transborda**: 45+3 vira "48", igual ao 4o min do 2o tempo | o corte fixo em 45 erra o tempo de **2,34% dos gols do 1o tempo** — 3 jogos a cada 100 | o `id` do chute e cronologico (validado: **zero conflitos em 11.428 jogos**); os primeiros `HTHG+HTAG` gols sao do 1o tempo |
| Placar reconstruido nao confere | 24 jogos (W.O. 3-0 sem chutes; chutes faltando) | `placar_confere = 0`, fora de toda contagem |

`corte_ht` de cada jogo diz como o intervalo foi fixado: `placar_ht` (exato,
87% do banco), `detectado` (virada do minuto visivel na ordem de `id`),
`inferido` (corte em 45 — basicamente a RFPL, que nao entra no Motor 1).

Valor medido de gols no 1o tempo nessas ligas, com o corte exato: **43,7%**.

## O que existe minuto a minuto

| Dado | Minuto a minuto | Motor 1 |
|---|---|---|
| Placar | **sim** | estado base |
| Chutes, chutes no alvo | **sim** | filtro de ritmo |
| xG | sim, mas **outro modelo que o do Fut Odds** | nao usado (escalas diferentes) |
| Escanteios, vermelhos | so total do jogo | nao usado — filtrar por eles seria usar o futuro |
| Ataques perigosos, posse, PI, APPM, CG | **nao existe** | declarado como "sem base" |
| Odd ao vivo | **nao existe** historicamente | — |

## Motor 1

`motor1.py` e a referencia; `web/motor1.js` espelha linha a linha e e o que
roda no site. `testes/test_paridade.py` confere que os dois dao o mesmo numero.

### Estado consultado

- **Instante.** O Fut Odds mostra o minuto em andamento, 1-indexado; o Understat
  rotula 0-indexado. O instante e `t = M - 1` e **o minuto em andamento conta
  como futuro** — conservador para o under.
- **Tempo.** `M <= 45` e 1o tempo; `M >= 46` e 2o; `HT` e o inicio do 2o.
- **Favorito.** Maior probabilidade 1X2 **sem margem** (empate -> casa). O
  placar e sempre lido como *gols do favorito x gols da zebra*: favorito
  vencendo 1x0 e zebra vencendo 0x1 sao estados diferentes.

### Escada de relaxamento

Minuto e placar relativo sao **sempre exatos**. Os outros filtros entram do
mais especifico para o mais largo; vale o primeiro degrau com `n >= 100`:

| degrau | favorito (prob.) | O/U 2.5 (prob.) | no alvo | chutes |
|---|---|---|---|---|
| 0 | ±0,03 | ±0,04 | ±25% | ±25% |
| 1 | ±0,03 | ±0,04 | ±25% | |
| 2 | ±0,03 | ±0,04 | | |
| 3 | ±0,05 | ±0,07 | | |
| 4 | ±0,05 | | | |
| 5 | ±0,08 | | | |
| 6 | ±0,12 | | | |
| 7 | | | | |

Degrau cujo filtro o Scanner nao trouxe vira copia do seguinte e e pulado; o
rotulo exibido sai dos filtros **efetivamente aplicados**.

### Saida

`p` (taxa de green), `n`, `green`, `ic95` (Wilson), `justa = 1/p`, degrau e
filtros usados, distribuicao de gols a mais (0 / 1 / 2+), e dois avisos que
nunca sao omitidos: **expulsao** (o historico nao tem cartoes, a taxa nao a
considera) e **amostra fina**. Todo campo do Scanner sem equivalente
historico e listado em `ignorados`.

### No Scanner

O site Futebol carrega `motor1/motor1.js` e `motor1/linha_do_tempo.json`. Um
gancho de uma linha no fim do `scanRodar` acrescenta duas colunas:

- **Motor 1** — odd justa empirica, diferenca % contra a justa atual, n e taxa
- **M1 base** — filtros usados, IC95 em odd, ⚠ com os avisos

Passar o mouse na linha mostra o placar relativo, a odd justa do favorito, a
distribuicao de gols a mais e os campos sem base.

## Testes

```bash
python -m venv .venv && .venv/Scripts/python -m pip install mini-racer pytest
.venv/Scripts/python -m pytest testes
```

| Arquivo | Cobre |
|---|---|
| `test_motor1.py` | regras em jogos sinteticos com resposta conhecida: convencao de minuto, gol de acrescimo do 1o tempo, gol contra, placar relativo ao favorito, escada, avisos |
| `test_paridade.py` | o `motor1.js` real num V8 embutido contra o Python, 150 consultas no banco real, campo a campo |
| `test_dados.py` | placar reconstruido = oficial; tempo dos gols = placar oficial do intervalo; o JSON do site = o banco |
| `test_integracao_scanner.py` | o `scanParse` **extraido do index.html publicado** le uma Tabela Live e entrega ao Motor 1 sem traducao; colunas entram na tabela; o gancho esta no HTML e no gerador |

O `mini-racer` segura o processo vivo na saida se o contexto V8 nao for
fechado; os fixtures fecham com `ctx.close()`.

## Motor 2

`motor.py`, `ajustar.py` e `avaliar.py` sao o piloto de 1 temporada (EPL 2024)
e **precisam ser refeitos**: contam so `Goal` (ignoram gol contra), usam o
corte fixo em 45 e descrevem o placar sem referencia ao favorito. No piloto,
o ganho sobre um Poisson plano nao se distinguiu de zero (IC95 do bootstrap
por jogo cruzou zero) e o ajuste por xG acumulado foi rejeitado pela busca em
grade. O papel dele daqui em diante e reproduzir o Motor 1 onde ha amostra.
