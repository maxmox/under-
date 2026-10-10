# -*- coding: utf-8 -*-
"""Carrega o cache/ no futebol.db. Sem rede.

   python carregar.py              # tudo o que estiver no cache
   python carregar.py 2018 2020    # so essas temporadas

Idempotente: pode rodar quantas vezes quiser, inclusive com o baixar.py ainda
em andamento, que carrega o que ja chegou.
"""
import json
import os
import sqlite3
import sys

DIR = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(DIR, "cache")
DB = os.path.join(DIR, "futebol.db")

LIGAS = ["EPL", "La_liga", "Bundesliga", "Serie_A", "Ligue_1", "RFPL"]
TEMPORADAS = list(range(2014, 2027))

ESQUEMA = """
CREATE TABLE IF NOT EXISTS jogo (
  id INTEGER PRIMARY KEY, liga TEXT, temporada INTEGER, data TEXT,
  casa TEXT, fora TEXT, gols_casa INTEGER, gols_fora INTEGER,
  xg_casa REAL, xg_fora REAL, p_casa REAL, p_empate REAL, p_fora REAL
);
CREATE TABLE IF NOT EXISTS chute (
  jogo_id INTEGER, minuto INTEGER, lado TEXT, resultado TEXT, xg REAL,
  situacao TEXT, tipo TEXT, jogador TEXT, x REAL, y REAL,
  FOREIGN KEY (jogo_id) REFERENCES jogo(id)
);
CREATE INDEX IF NOT EXISTS ix_chute_jogo ON chute(jogo_id);
CREATE INDEX IF NOT EXISTS ix_chute_min  ON chute(jogo_id, minuto);
CREATE INDEX IF NOT EXISTS ix_jogo_liga  ON jogo(liga, temporada);
"""


def f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def le(nome):
    arq = os.path.join(CACHE, nome)
    if not os.path.exists(arq):
        return None
    try:
        with open(arq, encoding="utf-8") as fh:
            return json.load(fh)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None


def main():
    temporadas = TEMPORADAS
    if len(sys.argv) > 2:
        temporadas = list(range(int(sys.argv[1]), int(sys.argv[2]) + 1))

    con = sqlite3.connect(DB)
    con.executescript(ESQUEMA)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=NORMAL")

    ja = {r[0] for r in con.execute("SELECT id FROM jogo")}
    novos = sem_cache = corrompidos = 0

    for temp in temporadas:
        for liga in LIGAS:
            d = le(f"liga_{liga}_{temp}.json")
            if not d:
                continue
            jogos = [j for j in d.get("dates", []) if j.get("isResult")]
            n0 = novos
            lote = []
            for j in jogos:
                jid = int(j["id"])
                if jid in ja:
                    continue
                md = le(f"jogo_{jid}.json")
                if md is None:
                    sem_cache += 1
                    continue
                if "shots" not in md:
                    corrompidos += 1
                    continue
                prev = j.get("forecast") or {}
                con.execute(
                    "INSERT OR REPLACE INTO jogo VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (jid, liga, int(temp), j["datetime"],
                     j["h"]["title"], j["a"]["title"],
                     int(j["goals"]["h"]), int(j["goals"]["a"]),
                     f(j["xG"]["h"]), f(j["xG"]["a"]),
                     f(prev.get("w")), f(prev.get("d")), f(prev.get("l"))))
                con.execute("DELETE FROM chute WHERE jogo_id=?", (jid,))
                for lado in ("h", "a"):
                    for s in md["shots"].get(lado, []):
                        lote.append((jid, int(s["minute"]), lado, s["result"],
                                     f(s["xG"]), s.get("situation"),
                                     s.get("shotType"), s.get("player"),
                                     f(s.get("X")), f(s.get("Y"))))
                ja.add(jid)
                novos += 1
            if lote:
                con.executemany(
                    "INSERT INTO chute VALUES (?,?,?,?,?,?,?,?,?,?)", lote)
            con.commit()
            if novos > n0:
                print(f"  {liga:11s} {temp}: +{novos-n0} jogos")

    n_j = con.execute("SELECT COUNT(*) FROM jogo").fetchone()[0]
    n_c = con.execute("SELECT COUNT(*) FROM chute").fetchone()[0]
    con.close()
    print(f"\n+{novos} jogos carregados | banco: {n_j} jogos, {n_c} chutes")
    if sem_cache:
        print(f"{sem_cache} jogos ainda sem cache (rode baixar.py)")
    if corrompidos:
        print(f"{corrompidos} arquivos de cache sem 'shots' — apague e rebaixe")


if __name__ == "__main__":
    main()
