# Under Limite Lab — odd justa minuto a minuto

Projeto **independente** do dashboard de backtests. Objetivo: reconstruir o
estado de um jogo em qualquer minuto a partir de dados gratuitos e calcular a
**odd justa do under limite HT e FT** nesse momento.

Mercado modelado: *"nao sai mais nenhum gol ate o fim do periodo"* — a linha e
sempre `placar + 0,5`.

**Estado: piloto de 1 temporada concluido (EPL 2024).** A infraestrutura esta
validada ponta a ponta; o modelo **ainda nao** demonstrou ganho sobre o
baseline com esse volume. Ver *Resultado do piloto*.

## Como rodar

```bash
python coletar_understat.py EPL 2024   # jogos + chutes -> futebol.db
python coletar_odds.py E0 2425         # odds pre-live + casamento
python ajustar.py                      # busca em grade + ablacao
python avaliar.py                      # diagnostico, calibragem, exemplo
```

## Fontes

### Understat (minuto exato)

API JSON interna, nao documentada. Exige o header
`X-Requested-With: XMLHttpRequest` (sem ele devolve 404) e aceita gzip.

```
GET https://understat.com/main/getLeagueData/<LIGA>/<TEMPORADA>
GET https://understat.com/main/getMatchData/<ID_DO_JOGO>
```

`getMatchData` devolve `shots.h` / `shots.a`, cada chute com `minute`,
`result` (`Goal` / `SavedShot` / `BlockedShot` / `MissedShots` / `ShotOnPost`),
`xG`, `X`/`Y` na grama, `situation`, `shotType` e jogador.

Cobertura verificada: EPL, La_liga, Bundesliga, Serie_A, Ligue_1, RFPL —
temporadas **2014 a 2026** (~24 mil jogos concluidos). A coleta de uma
temporada da EPL (380 jogos) levou ~7 min a 1 request/s, sem nenhum erro.

### football-data.co.uk (odds pre-live)

CSV por divisao e temporada, sem autenticacao (segue redirect, use `-L`):

```
https://www.football-data.co.uk/mmz4281/<TEMPORADA>/<DIV>.csv
```

| Grupo | Abertura | Fechamento |
|---|---|---|
| Match odds (favoritismo) | `B365H/D/A`, `PSH/D/A` | `B365CH/CD/CA`, `PSCH/CD/CA` |
| Over/under 2.5 (perfil do jogo) | `B365>2.5`, `B365<2.5` | `B365C>2.5`, `B365C<2.5` |
| Betfair Exchange | `BFE>2.5`, `BFE<2.5` | `BFEC>2.5`, `BFEC<2.5` |

Ambas sao pre-live; o **fechamento** e o preco imediatamente antes da bola
rolar, portanto o balizador mais afiado. A Exchange importa porque e onde a
comissao de 6,5% se aplica.

O casamento com o Understat e por data (com tolerancia de +-1 dia para jogo
remarcado) e nome de time normalizado via tabela de apelidos em
`coletar_odds.py`. Na EPL 2024: **380 de 380 jogos casaram**.

## O que existe e o que nao existe minuto a minuto

| Dado | Minuto a minuto | Observacao |
|---|---|---|
| Gols / placar | **sim** | do `result == "Goal"` |
| Chutes | **sim** | |
| Chutes no alvo | **sim** | `Goal` + `SavedShot` |
| xG acumulado | **sim** | por chute |
| Escanteios | nao | so total final (`HC`/`AC`) |
| Ataques perigosos | **nao existe** em fonte gratuita | |
| Posse de bola | nao | so agregado final |
| **Odd ao vivo** | **nao existe** historicamente | so coletando daqui pra frente |

A ultima linha e a limitacao dura: o banco afere a **probabilidade** do modelo,
nao o ROI realizado. Para ROI e preciso o preco, e preco ao vivo historico nao
existe de graca.

### Nota de dado: a borda do 1o tempo

O minuto do Understat e **0-indexado** (minuto 0 = 1o minuto de jogo) e vai
ate 103.

O minuto 46 carrega uma **anomalia de 2,9x**: 30 gols contra 10,5 de media nos
vizinhos. A escolha do corte foi feita pela fatia de gols do 1o tempo, cujo
valor de livro e ~45%:

| corte | fatia do 1o tempo |
|---|---|
| 44 | 43,5% |
| **45** | **44,5%** |
| 46 | 47,3% |
| 47 | 48,3% |

Logo `LIMITE_HT = 45`. **O mecanismo da anomalia nao foi resolvido.** Se parte
dela for acrescimo do 1o tempo rotulado como 46, o under HT aparece ganhando um
pouco mais do que ganha de verdade — e o vies e otimista, que e a direcao ruim.
Resolver isso exige uma fonte com meia-tempo explicito.

## Arquivos

| Arquivo | O que faz |
|---|---|
| `coletar_understat.py` | jogos + chutes para `futebol.db`. Cache em `cache/`, resumivel, pula o que ja coletou. |
| `coletar_odds.py` | odds pre-live e casamento por data + apelido de time. |
| `motor.py` | reconstrucao de estado e calculo da odd justa. |
| `ajustar.py` | busca em grade dos parametros e ablacao de componentes. |
| `avaliar.py` | diagnostico, calibragem, bootstrap e exemplo de uso. |

`cache/`, `*.db` e `*.csv` estao no `.gitignore` — o banco se reconstroi dos
scripts.

## O modelo

```
P(sem mais gol) = exp(-Lambda_resto)
Lambda_resto = lambda_jogo * fracao_do_perfil(t, fim) * aj_xg * aj_placar
```

1. **`lambda_jogo`** — gols totais esperados, extraidos do par over/under 2.5
   de fechamento: tira o overround, acha `P(over 2.5)` e resolve por bisseccao
   o `lambda` que a reproduz num Poisson. Sem odds, cai na media da amostra.
2. **`fracao_do_perfil(t, fim)`** — o perfil `r(s)` de intensidade ao longo do
   jogo e **medido nos gols reais da amostra** (suavizado em janela de 9 min),
   nao postulado como reta.
3. **`aj_xg`** — razao entre o xG acumulado ate `t` e o que se esperava do
   jogo, amortecida por um prior. A referencia usa a escala do **proprio xG da
   amostra** (3,25/jogo) e nao o lambda das odds (3,06/jogo): sao numeros
   diferentes, e compara-los diretamente introduzia vies.
   **Peso ajustado: 0 — rejeitado pelos dados.** Ver abaixo.
4. **`aj_placar`** — efeito do placar por estado (`0x0`, `empate_com_gol`,
   `dif1`, `dif2+`), calibrado para que a **media de `P(zero gols)`** bata com
   a frequencia observada de under.

Odd minima, com a comissao da exchange descontada:
`1 + (1-p) / (p * (1 - comissao))`.

### Por que calibrar em P e nao em gols

A primeira versao calibrava o efeito de placar pela razao
`gols observados / gols previstos`, o que acerta a media de `lambda`. Isso esta
errado: a grandeza de interesse e `exp(-lambda)`, e **`exp` e convexa**, logo
`E[exp(-lambda)] != exp(-E[lambda])`. Acertar a media de `lambda` deixava a
media de `P` alta demais, e a calibragem mostrava o modelo super-estimando o
under em 3 a 4 pontos em quase toda faixa. A calibragem agora resolve por
bisseccao o multiplicador `m` tal que
`media_i exp(-m * lambda_i) = taxa observada`, e o vies sistematico desapareceu.

## Resultado do piloto (EPL 2024, 380 jogos)

Banco: 380 jogos, 9.878 chutes, 1.081 gols (2,84/jogo), 100% com odds pre-live.
`lambda` pre-live: mediana 3,04, faixa 2,15 a 4,36.

**Ablacao fora da amostra** (treino 266 jogos / teste 114, divididos por data;
parametros escolhidos por validacao interna que nunca viu o teste):

| Modelo | Brier | vs plano |
|---|---|---|
| Poisson plano (lambda medio, sem odds) | 0,20081 | — |
| lambda pre-live, sem ajuste | 0,20039 | +0,21% |
| lambda + xG | 0,20039 | +0,21% |
| lambda + placar | **0,19963** | **+0,59%** |
| lambda + xG + placar | 0,19963 | +0,59% |

**Duas conclusoes honestas:**

1. **O ajuste por xG foi rejeitado.** Na busca em grade o Brier de validacao
   piora monotonicamente com o peso (0,2135 em peso 0 contra 0,2194 em peso 1),
   para todo prior testado. Como especificado, o xG acumulado nao agrega
   informacao sobre o placar e o `lambda` pre-live.
2. **O ganho total nao se distingue de zero.** Bootstrap de 4.000 reamostragens
   **por jogo** (minutos do mesmo jogo sao correlacionados, reamostrar
   observacoes infla a precisao): diferenca media de Brier `-0,00118`, IC95%
   `[-0,00620, +0,00406]`. O intervalo cruza zero.

Ou seja: uma temporada **nao sustenta** a afirmacao de que o condicionamento
por estado bate um Poisson plano. O que o piloto estabelece e que a
infraestrutura funciona, que a calibragem esta sem vies sistematico fora da
amostra, e que os efeitos de placar medidos tem a direcao plausivel
(`ft empate_com_gol` x0,76 — jogo empatado 1x1 sai menos gol que o modelo
preve, igual ao que o projeto antigo achou nos backtests).

## Proximos passos, em ordem de retorno

1. **Volume.** 380 jogos -> ~24 mil (6 ligas x 12 temporadas) e ~65x mais
   amostra. E o unico caminho para sair do "nao distinguivel de zero". Crawl de
   ~7 h a 1 req/s, resumivel. So depois disso faz sentido julgar o modelo.
2. **Refazer o xG como taxa recente, nao nivel acumulado.** A especificacao
   atual compara niveis, que e redundante com o placar. xG nos ultimos 10-15
   minutos mede pressao corrente, que e o que o acumulado nao captura.
3. **Chutes no alvo como sinal separado.** Esta no banco e nao foi usado.
4. **Resolver a anomalia do minuto 46**, porque o vies que ela gera e otimista
   no HT.
5. **Coletor ao vivo**, se ROI medido importar. Unica fonte possivel de preco
   ao vivo, e so acumula para frente.

Observacoes do mesmo jogo em minutos diferentes sao correlacionadas, entao os
`n` das tabelas de calibragem sao maiores que o numero de jogos independentes;
leia-os como volume, nao como precisao estatistica.
