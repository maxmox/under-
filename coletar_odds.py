# -*- coding: utf-8 -*-
"""Odds pre-live do football-data.co.uk e casamento com os jogos do Understat.

   python coletar_odds.py E0 2425

Guarda match odds (1X2) e over/under 2.5, abertura e fechamento. Ambas sao
pre-live; o fechamento e o preco imediatamente antes da bola rolar, portanto
o balizador mais afiado de favoritismo e de jogo under/over.
"""
import csv, io, os, sqlite3, sys, unicodedata, urllib.request
from datetime import datetime

DIR = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(DIR, "futebol.db")
CACHE = os.path.join(DIR, "cache")

ESQUEMA = """
CREATE TABLE IF NOT EXISTS odds_pre (
  jogo_id INTEGER PRIMARY KEY,
  -- match odds (favoritismo); 'f' = fechamento
  oc REAL, oe REAL, o_f REAL, ocf REAL, oef REAL, off_ REAL,
  -- over/under 2.5 (perfil under/over do jogo)
  o25 REAL, u25 REAL, o25f REAL, u25f REAL,
  -- exchange (onde a comissao de 6,5% se aplica)
  bfe_o25 REAL, bfe_u25 REAL,
  -- lambda implicito derivado do par over/under 2.5 sem overround
  p_over25 REAL, lambda_jogo REAL,
  -- agregados finais que o Understat nao traz
  escanteios_casa INTEGER, escanteios_fora INTEGER,
  FOREIGN KEY (jogo_id) REFERENCES jogo(id)
);
"""

# Understat -> football-data. So os nomes que divergem; o resto casa sozinho.
APELIDOS = {
    "manchester united": "man united", "manchester city": "man city",
    "newcastle united": "newcastle", "tottenham": "tottenham",
    "wolverhampton wanderers": "wolves", "nottingham forest": "nott'm forest",
    "sheffield united": "sheffield united", "leeds": "leeds",
    "west bromwich albion": "west brom", "queens park rangers": "qpr",
    "huddersfield": "huddersfield", "cardiff": "cardiff",
    "brighton": "brighton", "leicester": "leicester",
    "west ham": "west ham", "bournemouth": "bournemouth",
    "ipswich": "ipswich", "luton": "luton",
}


def norm(s):
    s = unicodedata.normalize("NFKD", (s or "").lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return " ".join(s.replace(".", "").split())


def chave_time(nome):
    n = norm(nome)
    return norm(APELIDOS.get(n, n))


def baixa(div, temporada):
    os.makedirs(CACHE, exist_ok=True)
    arq = os.path.join(CACHE, f"fd_{div}_{temporada}.csv")
    if not os.path.exists(arq):
        url = f"https://www.football-data.co.uk/mmz4281/{temporada}/{div}.csv"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
        with urllib.request.urlopen(req, timeout=40) as r:
            dados = r.read()
        with open(arq, "wb") as f:
            f.write(dados)
    with open(arq, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def f(r, col):
    v = (r.get(col) or "").strip()
    try:
        return float(v)
    except ValueError:
        return None


def primeiro(r, *cols):
    for c in cols:
        v = f(r, c)
        if v:
            return v
    return None


def lambda_de_over25(odd_over, odd_under):
    """P(over 2.5) sem overround -> lambda que a reproduz num Poisson."""
    if not odd_over or not odd_under:
        return None, None
    po, pu = 1 / odd_over, 1 / odd_under
    p = po / (po + pu)
    # resolve P(X>=3)=p por bisseccao; X~Poisson(lam)
    import math
    def p_over(lam):
        return 1 - math.exp(-lam) * (1 + lam + lam * lam / 2)
    lo, hi = 0.05, 8.0
    for _ in range(60):
        mid = (lo + hi) / 2
        if p_over(mid) < p:
            lo = mid
        else:
            hi = mid
    return p, round((lo + hi) / 2, 4)


def casa(div, temporada):
    con = sqlite3.connect(DB)
    con.executescript(ESQUEMA)
    jogos = con.execute("SELECT id, data, casa, fora FROM jogo").fetchall()
    if not jogos:
        print("banco sem jogos — rode coletar_understat.py primeiro")
        return
    idx = {}
    for jid, data, c, fo in jogos:
        d = data[:10]
        idx[(d, chave_time(c), chave_time(fo))] = jid

    linhas = baixa(div, temporada)
    print(f"football-data {div} {temporada}: {len(linhas)} linhas")
    ok = falhou = 0
    nao_casou = []
    for r in linhas:
        try:
            d = datetime.strptime(r["Date"].strip(), "%d/%m/%Y").strftime("%Y-%m-%d")
        except ValueError:
            continue
        ch = (d, chave_time(r["HomeTeam"]), chave_time(r["AwayTeam"]))
        jid = idx.get(ch)
        if jid is None:  # jogo adiado/remarcado: tenta +-1 dia
            for delta in (-1, 1):
                from datetime import timedelta
                d2 = (datetime.strptime(d, "%Y-%m-%d") + timedelta(days=delta)).strftime("%Y-%m-%d")
                jid = idx.get((d2, ch[1], ch[2]))
                if jid:
                    break
        if jid is None:
            falhou += 1
            nao_casou.append(f"{d} {r['HomeTeam']} x {r['AwayTeam']}")
            continue
        o25f = primeiro(r, "B365C>2.5", "PC>2.5", "AvgC>2.5", "MaxC>2.5")
        u25f = primeiro(r, "B365C<2.5", "PC<2.5", "AvgC<2.5", "MaxC<2.5")
        p_over, lam = lambda_de_over25(o25f, u25f)
        con.execute(
            "INSERT OR REPLACE INTO odds_pre VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (jid,
             primeiro(r, "B365H", "PSH", "AvgH"), primeiro(r, "B365D", "PSD", "AvgD"),
             primeiro(r, "B365A", "PSA", "AvgA"),
             primeiro(r, "B365CH", "PSCH", "AvgCH"), primeiro(r, "B365CD", "PSCD", "AvgCD"),
             primeiro(r, "B365CA", "PSCA", "AvgCA"),
             primeiro(r, "B365>2.5", "P>2.5", "Avg>2.5"), primeiro(r, "B365<2.5", "P<2.5", "Avg<2.5"),
             o25f, u25f,
             f(r, "BFEC>2.5") or f(r, "BFE>2.5"), f(r, "BFEC<2.5") or f(r, "BFE<2.5"),
             p_over, lam,
             int(f(r, "HC") or 0) or None, int(f(r, "AC") or 0) or None),
        )
        ok += 1
    con.commit()
    print(f"casou {ok} | nao casou {falhou}")
    for n in nao_casou[:12]:
        print("   sem par:", n)
    con.close()


if __name__ == "__main__":
    casa(sys.argv[1] if len(sys.argv) > 1 else "E0",
         sys.argv[2] if len(sys.argv) > 2 else "2425")
