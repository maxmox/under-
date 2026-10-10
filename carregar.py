# -*- coding: utf-8 -*-
"""Carrega o cache/ no futebol.db. Sem rede.

   python carregar.py              # tudo o que estiver no cache
   python carregar.py 2018 2020    # so essas temporadas
   python carregar.py --refazer    # apaga as tabelas e recarrega do zero

Idempotente: pode rodar com o baixar.py ainda em andamento.

TRES CORRECOES SOBRE O DADO CRU DO UNDERSTAT, todas medidas:

1. Gol contra. O resultado 'OwnGoal' fica registrado no lado de QUEM FEZ o
   contra e soma para o adversario. Contando so 'Goal', o placar reconstruido
   batia com o oficial em 92,3% dos jogos; com a regra certa, 99,83%.
   `gol_para` guarda a quem o gol conta ('h'/'a'), ou NULL se nao e gol.

2. Tempo de cada chute. O minuto e 0-indexado e o acrescimo do 1o tempo
   transborda: um gol aos 45+3 aparece como '48', igual a um gol no 4o minuto
   do 2o tempo. Mas o `id` do chute e cronologico, entao na virada do
   intervalo o minuto VOLTA (ex.: 47 -> 45). Quando ha virada, ela separa os
   tempos exatamente (`corte_ht = 'detectado'`). Sem virada, cai no corte em
   45 (`corte_ht = 'inferido'`).

3. Jogos cujo placar reconstruido nao bate com o oficial (W.O. 3-0 sem
   nenhum chute, ou chutes faltando) ficam com placar_confere = 0 e devem ser
   excluidos de qualquer contagem.
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
  xg_casa REAL, xg_fora REAL, p_casa REAL, p_empate REAL, p_fora REAL,
  ht_casa INTEGER, ht_fora INTEGER,
  corte_ht TEXT,            -- 'detectado' | 'inferido'
  placar_confere INTEGER    -- 1 se os chutes reconstroem o placar oficial
);
CREATE TABLE IF NOT EXISTS chute (
  jogo_id INTEGER, ordem INTEGER, minuto INTEGER, tempo INTEGER,
  lado TEXT, resultado TEXT, gol_para TEXT, xg REAL,
  situacao TEXT, tipo TEXT, jogador TEXT, x REAL, y REAL,
  FOREIGN KEY (jogo_id) REFERENCES jogo(id)
);
CREATE INDEX IF NOT EXISTS ix_chute_jogo ON chute(jogo_id, ordem);
CREATE INDEX IF NOT EXISTS ix_jogo_liga  ON jogo(liga, temporada);
"""

NO_ALVO = {"Goal", "SavedShot"}


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


def acha_intervalo(minutos):
    """Indice do primeiro chute do 2o tempo, pela volta do minuto na ordem de
    id. So aceita a volta na faixa da virada (antes 45..55, depois 44..50),
    para nao confundir com ruido no meio do jogo. None se nao ha virada."""
    for i in range(1, len(minutos)):
        antes, depois = minutos[i - 1], minutos[i]
        if depois < antes and 45 <= antes <= 55 and 44 <= depois <= 50:
            return i
    return None


def processa_chutes(md):
    """Lista de chutes enriquecida (ordem, tempo, gol_para) + corte usado."""
    brutos = []
    for lado in ("h", "a"):
        outro = "a" if lado == "h" else "h"
        for s in md.get("shots", {}).get(lado, []):
            res = s["result"]
            gol_para = lado if res == "Goal" else (outro if res == "OwnGoal" else None)
            brutos.append((int(s["id"]), int(s["minute"]), lado, res, gol_para, s))
    brutos.sort(key=lambda b: b[0])
    corte = acha_intervalo([b[1] for b in brutos])
    saida = []
    for i, (sid, minuto, lado, res, gol_para, s) in enumerate(brutos):
        if corte is not None:
            tempo = 1 if i < corte else 2
        else:
            tempo = 1 if minuto <= 45 else 2
        saida.append((sid, minuto, tempo, lado, res, gol_para, s))
    return saida, ("detectado" if corte is not None else "inferido")


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    temporadas = TEMPORADAS
    if len(args) >= 2:
        temporadas = list(range(int(args[0]), int(args[1]) + 1))

    con = sqlite3.connect(DB)
    if "--refazer" in sys.argv:
        con.executescript("DROP TABLE IF EXISTS chute; DROP TABLE IF EXISTS jogo;")
    con.executescript(ESQUEMA)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=NORMAL")

    ja = {r[0] for r in con.execute("SELECT id FROM jogo")}
    novos = sem_cache = corrompidos = nao_confere = detectados = 0

    for temp in temporadas:
        for liga in LIGAS:
            d = le(f"liga_{liga}_{temp}.json")
            if not d:
                continue
            n0 = novos
            lote = []
            for j in (x for x in d.get("dates", []) if x.get("isResult")):
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
                chutes, corte = processa_chutes(md)
                gh, ga = int(j["goals"]["h"]), int(j["goals"]["a"])
                rec_h = sum(1 for c in chutes if c[5] == "h")
                rec_a = sum(1 for c in chutes if c[5] == "a")
                confere = int((rec_h, rec_a) == (gh, ga))
                ht_h = sum(1 for c in chutes if c[5] == "h" and c[2] == 1)
                ht_a = sum(1 for c in chutes if c[5] == "a" and c[2] == 1)
                prev = j.get("forecast") or {}
                con.execute(
                    "INSERT OR REPLACE INTO jogo VALUES "
                    "(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (jid, liga, int(temp), j["datetime"],
                     j["h"]["title"], j["a"]["title"], gh, ga,
                     f(j["xG"]["h"]), f(j["xG"]["a"]),
                     f(prev.get("w")), f(prev.get("d")), f(prev.get("l")),
                     ht_h if confere else None, ht_a if confere else None,
                     corte, confere))
                con.execute("DELETE FROM chute WHERE jogo_id=?", (jid,))
                for sid, minuto, tempo, lado, res, gol_para, s in chutes:
                    lote.append((jid, sid, minuto, tempo, lado, res, gol_para,
                                 f(s.get("xG")), s.get("situation"),
                                 s.get("shotType"), s.get("player"),
                                 f(s.get("X")), f(s.get("Y"))))
                ja.add(jid)
                novos += 1
                nao_confere += 1 - confere
                detectados += corte == "detectado"
            if lote:
                con.executemany(
                    "INSERT INTO chute VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", lote)
            con.commit()
            if novos > n0:
                print(f"  {liga:11s} {temp}: +{novos-n0} jogos")

    n_j = con.execute("SELECT COUNT(*) FROM jogo").fetchone()[0]
    n_c = con.execute("SELECT COUNT(*) FROM chute").fetchone()[0]
    con.close()
    print(f"\n+{novos} jogos carregados | banco: {n_j} jogos, {n_c} chutes")
    if novos:
        print(f"intervalo detectado pela ordem de id: {detectados} "
              f"({detectados/novos*100:.1f}%) | inferido pelo corte em 45: "
              f"{novos-detectados}")
        print(f"placar reconstruido NAO confere: {nao_confere} "
              f"(excluidos das contagens)")
    if sem_cache:
        print(f"{sem_cache} jogos ainda sem cache (rode baixar.py)")
    if corrompidos:
        print(f"{corrompidos} arquivos de cache sem 'shots' — apague e rebaixe")


if __name__ == "__main__":
    main()
