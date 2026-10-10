# -*- coding: utf-8 -*-
"""Odds pre-live do football-data.co.uk, casadas com os jogos do Understat.

   python coletar_odds.py            # todas as ligas/temporadas do banco
   python coletar_odds.py E0 2425    # so uma divisao/temporada

Guarda match odds (1X2) e over/under 2.5, abertura e fechamento. Ambas sao
pre-live; o fechamento e o preco imediatamente antes da bola rolar, portanto
o balizador mais afiado de favoritismo e de perfil under/over.

CASAMENTO DE NOMES: nao ha tabela de apelidos a manter. Dentro de uma
liga-temporada os dois lados tem o mesmo conjunto de ~20 times, entao o
mapeamento e resolvido por similaridade de nome (atribuicao gulosa) e depois
VERIFICADO pelo placar final: se FTHG/FTAG do football-data nao bate com os
gols do Understat, o jogo nao e gravado e entra no relatorio.
"""
import csv
import difflib
import os
import sqlite3
import sys
import unicodedata
import urllib.request
from collections import defaultdict
from datetime import datetime, timedelta

DIR = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(DIR, "futebol.db")
CACHE = os.path.join(DIR, "cache")

# liga do Understat -> divisao do football-data
DIVISAO = {
    "EPL": "E0", "La_liga": "SP1", "Bundesliga": "D1",
    "Serie_A": "I1", "Ligue_1": "F1",
    # RFPL (Russia) nao esta nos arquivos principais do football-data
}

ESQUEMA = """
CREATE TABLE IF NOT EXISTS odds_pre (
  jogo_id INTEGER PRIMARY KEY,
  oc REAL, oe REAL, o_f REAL, ocf REAL, oef REAL, off_ REAL,
  o25 REAL, u25 REAL, o25f REAL, u25f REAL,
  bfe_o25 REAL, bfe_u25 REAL,
  p_over25 REAL, lambda_jogo REAL,
  escanteios_casa INTEGER, escanteios_fora INTEGER,
  FOREIGN KEY (jogo_id) REFERENCES jogo(id)
);
"""

# ordem de preferencia por grupo; cobre mudanca de colunas ao longo dos anos
COLS = {
    "oc":   ("B365H", "PSH", "AvgH", "BbAvH", "WHH"),
    "oe":   ("B365D", "PSD", "AvgD", "BbAvD", "WHD"),
    "o_f":  ("B365A", "PSA", "AvgA", "BbAvA", "WHA"),
    "ocf":  ("B365CH", "PSCH", "AvgCH", "MaxCH"),
    "oef":  ("B365CD", "PSCD", "AvgCD", "MaxCD"),
    "off_": ("B365CA", "PSCA", "AvgCA", "MaxCA"),
    "o25":  ("B365>2.5", "P>2.5", "Avg>2.5", "BbAv>2.5", "GB>2.5"),
    "u25":  ("B365<2.5", "P<2.5", "Avg<2.5", "BbAv<2.5", "GB<2.5"),
    "o25f": ("B365C>2.5", "PC>2.5", "AvgC>2.5", "MaxC>2.5"),
    "u25f": ("B365C<2.5", "PC<2.5", "AvgC<2.5", "MaxC<2.5"),
    "bfe_o25": ("BFEC>2.5", "BFE>2.5"),
    "bfe_u25": ("BFEC<2.5", "BFE<2.5"),
}


def norm(s):
    s = unicodedata.normalize("NFKD", (s or "").lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    for lixo in ("fc ", " fc", "cf ", " cf", "ac ", " ac", "ss ", " calcio",
                 "1. ", "sv ", "vfl ", "vfb ", "tsg ", "bsc ", " 04", " 05",
                 " 1900", " 1899", "sc ", " sc", "as ", "ca ", "rc ", "us "):
        s = s.replace(lixo, " ")
    return " ".join(s.replace(".", " ").replace("-", " ").split())


def temporada_fd(ano):
    """Understat 2014 (= 2014/15) -> '1415' do football-data."""
    return f"{ano % 100:02d}{(ano + 1) % 100:02d}"


def baixa(div, temp_fd):
    os.makedirs(CACHE, exist_ok=True)
    arq = os.path.join(CACHE, f"fd_{div}_{temp_fd}.csv")
    if not os.path.exists(arq):
        url = f"https://www.football-data.co.uk/mmz4281/{temp_fd}/{div}.csv"
        req = urllib.request.Request(
            url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
        with urllib.request.urlopen(req, timeout=40) as r:
            if r.geturl() != url and not r.geturl().endswith(".csv"):
                raise RuntimeError(f"redirecionou para {r.geturl()}")
            dados = r.read()
        with open(arq, "wb") as f:
            f.write(dados)
    with open(arq, encoding="utf-8-sig", errors="replace", newline="") as f:
        return [r for r in csv.DictReader(f) if (r.get("Date") or "").strip()]


def val(r, grupo):
    for c in COLS[grupo]:
        v = (r.get(c) or "").strip()
        try:
            x = float(v)
        except ValueError:
            continue
        if x > 1.0:
            return x
    return None


def inteiro(r, col):
    try:
        return int(float((r.get(col) or "").strip()))
    except ValueError:
        return None


def lambda_de_over25(odd_over, odd_under):
    """P(over 2.5) sem overround -> lambda Poisson que a reproduz."""
    import math
    if not odd_over or not odd_under:
        return None, None
    po, pu = 1 / odd_over, 1 / odd_under
    p = po / (po + pu)

    def p_over(lam):
        return 1 - math.exp(-lam) * (1 + lam + lam * lam / 2)

    lo, hi = 0.05, 8.0
    for _ in range(60):
        mid = (lo + hi) / 2
        if p_over(mid) < p:
            lo = mid
        else:
            hi = mid
    return round(p, 4), round((lo + hi) / 2, 4)


def mapeia_times(nomes_us, nomes_fd):
    """Atribuicao gulosa por similaridade de nome, dentro da liga-temporada."""
    pares = []
    for u in nomes_us:
        for f in nomes_fd:
            pares.append((difflib.SequenceMatcher(None, norm(u), norm(f)).ratio(), u, f))
    pares.sort(reverse=True)
    de_us, usados_fd = {}, set()
    for s, u, f in pares:
        if u in de_us or f in usados_fd:
            continue
        de_us[u] = (f, s)
        usados_fd.add(f)
    return de_us


def processa(con, liga, temporada, div=None, temp_fd=None):
    div = div or DIVISAO.get(liga)
    if not div:
        return {"liga": liga, "temporada": temporada, "status": "sem divisao no football-data"}
    temp_fd = temp_fd or temporada_fd(temporada)

    jogos = con.execute(
        "SELECT id, data, casa, fora, gols_casa, gols_fora FROM jogo "
        "WHERE liga=? AND temporada=?", (liga, temporada)).fetchall()
    if not jogos:
        return {"liga": liga, "temporada": temporada, "status": "sem jogos no banco"}

    try:
        linhas = baixa(div, temp_fd)
    except Exception as e:
        return {"liga": liga, "temporada": temporada,
                "status": f"download falhou: {type(e).__name__}: {e}"}
    if not linhas:
        return {"liga": liga, "temporada": temporada, "status": "csv vazio"}

    nomes_us = sorted({j[2] for j in jogos} | {j[3] for j in jogos})
    nomes_fd = sorted({r["HomeTeam"] for r in linhas} | {r["AwayTeam"] for r in linhas})
    mapa = mapeia_times(nomes_us, nomes_fd)
    pior = min((s for _f, s in mapa.values()), default=1.0)

    # indice do football-data por (data, casa_fd, fora_fd)
    idx = {}
    for r in linhas:
        try:
            d = datetime.strptime(r["Date"].strip(), "%d/%m/%Y")
        except ValueError:
            try:
                d = datetime.strptime(r["Date"].strip(), "%d/%m/%y")
            except ValueError:
                continue
        idx[(d.date(), r["HomeTeam"], r["AwayTeam"])] = r

    ok = divergente = sem_par = 0
    exemplos = []
    for jid, data, casa, fora, gc, gf in jogos:
        d0 = datetime.strptime(data[:10], "%Y-%m-%d").date()
        c_fd = mapa.get(casa, (None, 0))[0]
        f_fd = mapa.get(fora, (None, 0))[0]
        r = None
        for delta in (0, -1, 1, -2, 2):
            r = idx.get((d0 + timedelta(days=delta), c_fd, f_fd))
            if r:
                break
        if not r:
            sem_par += 1
            if len(exemplos) < 4:
                exemplos.append(f"sem par: {d0} {casa} x {fora}")
            continue
        # verificacao: o placar final tem de bater
        if inteiro(r, "FTHG") != gc or inteiro(r, "FTAG") != gf:
            divergente += 1
            if len(exemplos) < 4:
                exemplos.append(
                    f"placar divergente: {d0} {casa} {gc}-{gf} vs "
                    f"{r['HomeTeam']} {r.get('FTHG')}-{r.get('FTAG')}")
            continue
        o25f = val(r, "o25f") or val(r, "o25")
        u25f = val(r, "u25f") or val(r, "u25")
        p_over, lam = lambda_de_over25(o25f, u25f)
        con.execute(
            "INSERT OR REPLACE INTO odds_pre VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (jid, val(r, "oc"), val(r, "oe"), val(r, "o_f"),
             val(r, "ocf"), val(r, "oef"), val(r, "off_"),
             val(r, "o25"), val(r, "u25"), o25f, u25f,
             val(r, "bfe_o25"), val(r, "bfe_u25"), p_over, lam,
             inteiro(r, "HC"), inteiro(r, "AC")))
        ok += 1
    con.commit()
    return {"liga": liga, "temporada": temporada, "div": div, "temp_fd": temp_fd,
            "status": "ok", "casou": ok, "divergente": divergente,
            "sem_par": sem_par, "n_jogos": len(jogos),
            "pior_similaridade": round(pior, 3), "exemplos": exemplos}


def main():
    con = sqlite3.connect(DB)
    con.executescript(ESQUEMA)
    if len(sys.argv) > 2:  # modo manual: divisao + temporada do football-data
        div, temp_fd = sys.argv[1], sys.argv[2]
        liga = next((l for l, d in DIVISAO.items() if d == div), None)
        ano = 2000 + int(temp_fd[:2])
        print(processa(con, liga, ano, div, temp_fd))
        con.close()
        return

    alvos = con.execute(
        "SELECT liga, temporada, COUNT(*) FROM jogo GROUP BY liga, temporada "
        "ORDER BY liga, temporada").fetchall()
    print(f"{len(alvos)} liga-temporadas no banco\n")
    tot_ok = tot_div = tot_sem = 0
    problemas = []
    for liga, temporada, _n in alvos:
        r = processa(con, liga, temporada)
        if r["status"] != "ok":
            print(f"  {liga:11s} {temporada}  -> {r['status']}")
            problemas.append(r)
            continue
        tot_ok += r["casou"]
        tot_div += r["divergente"]
        tot_sem += r["sem_par"]
        aviso = ""
        if r["divergente"] or r["sem_par"]:
            aviso = f"   <-- {r['divergente']} div, {r['sem_par']} sem par"
            problemas.append(r)
        print(f"  {liga:11s} {temporada}  {r['casou']:3d}/{r['n_jogos']:3d}  "
              f"sim.min {r['pior_similaridade']:.2f}{aviso}")

    print(f"\ncasou {tot_ok} | placar divergente {tot_div} | sem par {tot_sem}")
    com = con.execute("SELECT COUNT(*) FROM odds_pre").fetchone()[0]
    jog = con.execute("SELECT COUNT(*) FROM jogo").fetchone()[0]
    print(f"banco: {com}/{jog} jogos com odds ({com/jog*100:.1f}%)")
    if problemas:
        print("\ndetalhe dos problemas:")
        for p in problemas:
            if p.get("exemplos"):
                print(f"  {p['liga']} {p['temporada']}:")
                for e in p["exemplos"]:
                    print(f"     {e}")
    con.close()


if __name__ == "__main__":
    main()
