# -*- coding: utf-8 -*-
"""Gera a linha do tempo compacta que o Motor 1 consulta (Python e navegador).

   python exportar_web.py                 # -> web/linha_do_tempo.json
   python exportar_web.py --publicar DIR  # e copia web/ para DIR/motor1/

So entram jogos com placar conferido, tempo dos chutes sem conflito e odds
1X2 (sem odds nao existe favorito, e o Motor 1 descreve o placar em relacao
ao favorito).

FORMATO de cada jogo:  [liga, temporada, pc, pe, pf, po, eventos]
  pc/pe/pf  probabilidades 1X2 SEM margem, em milesimos (fechamento)
  po        P(over 2.5) sem margem em milesimos, ou -1 se ausente
  eventos   inteiros em ordem cronologica:
              codigo = tempo*10000 + minuto*10 + tipo*2 + lado
            tempo  1|2 (corrigido pelo placar oficial do intervalo)
            minuto rotulo 0-indexado do Understat
            tipo   0 gol | 1 no alvo (defendido) | 2 chute fora/bloqueado/trave
                   | 3 gol contra (conta para `lado`, nao e chute de ninguem)
            lado   0 casa | 1 fora  (para gol: a quem o gol conta)
"""
import json
import os
import shutil
import sqlite3
import sys
from datetime import date

DIR = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(DIR, "futebol.db")
WEB = os.path.join(DIR, "web")
SAIDA = os.path.join(WEB, "linha_do_tempo.json")

TIPO = {"Goal": 0, "SavedShot": 1, "MissedShots": 2, "BlockedShot": 2,
        "ShotOnPost": 2, "OwnGoal": 3}


def sem_margem(*odds):
    inv = [1 / o for o in odds]
    s = sum(inv)
    return [x / s for x in inv]


def main():
    con = sqlite3.connect(DB)
    ligas = [r[0] for r in con.execute("SELECT DISTINCT liga FROM jogo ORDER BY liga")]
    ix_liga = {l: i for i, l in enumerate(ligas)}

    jogos_sql = con.execute(
        """SELECT j.id, j.liga, j.temporada,
                  COALESCE(o.ocf, o.oc), COALESCE(o.oef, o.oe), COALESCE(o.off_, o.o_f),
                  o.o25f, o.u25f, o.o25, o.u25
           FROM jogo j JOIN odds_pre o ON o.jogo_id = j.id
           WHERE j.placar_confere = 1 AND j.corte_ht != 'conflito'
           ORDER BY j.data, j.id""").fetchall()

    eventos = {}
    for jid, ordem, minuto, tempo, lado, res, gol_para in con.execute(
            """SELECT c.jogo_id, c.ordem, c.minuto, c.tempo, c.lado, c.resultado,
                      c.gol_para
               FROM chute c JOIN jogo j ON j.id = c.jogo_id
               WHERE j.placar_confere = 1 ORDER BY c.jogo_id, c.ordem"""):
        tipo = TIPO.get(res, 2)
        quem = gol_para if tipo in (0, 3) else lado
        cod = tempo * 10000 + max(0, minuto) * 10 + tipo * 2 + (1 if quem == "a" else 0)
        eventos.setdefault(jid, []).append(cod)

    saida, sem_1x2 = [], 0
    for jid, liga, temp, oc, oe, of_, o25f, u25f, o25, u25 in jogos_sql:
        if not (oc and oe and of_):
            sem_1x2 += 1
            continue
        pc, pe, pf = sem_margem(oc, oe, of_)
        ov, un = (o25f, u25f) if (o25f and u25f) else (o25, u25)
        po = round(sem_margem(ov, un)[0] * 1000) if (ov and un) else -1
        saida.append([ix_liga[liga], temp, round(pc * 1000), round(pe * 1000),
                      round(pf * 1000), po, eventos.get(jid, [])])
    con.close()

    doc = {
        "versao": 1,
        "gerado": date.today().isoformat(),
        "ligas": ligas,
        "formato": "[liga, temporada, pc, pe, pf, po, eventos]; "
                   "evento = tempo*10000 + minuto*10 + tipo*2 + lado",
        "jogos": saida,
    }
    os.makedirs(WEB, exist_ok=True)
    with open(SAIDA, "w", encoding="utf-8") as f:
        json.dump(doc, f, separators=(",", ":"))
    tam = os.path.getsize(SAIDA)
    print(f"{len(saida)} jogos -> web/linha_do_tempo.json ({tam/1e6:.1f} MB)"
          f"{f' | {sem_1x2} sem odds 1X2 ignorados' if sem_1x2 else ''}")

    if "--publicar" in sys.argv:
        destino = sys.argv[sys.argv.index("--publicar") + 1]
        alvo = os.path.join(destino, "motor1")
        os.makedirs(alvo, exist_ok=True)
        for nome in ("motor1.js", "linha_do_tempo.json"):
            shutil.copy2(os.path.join(WEB, nome), os.path.join(alvo, nome))
        print(f"publicado em {alvo}")


if __name__ == "__main__":
    main()
