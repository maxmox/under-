# -*- coding: utf-8 -*-
"""Coleta o Understat inteiro: 6 ligas x temporadas 2014..2026.

   python coletar_tudo.py              # tudo
   python coletar_tudo.py 2020 2026    # so essas temporadas
   PAUSA=1.0 python coletar_tudo.py    # mais devagar

Resumivel: cada resposta fica em cache/ e cada jogo ja gravado e pulado,
entao interromper e rodar de novo retoma de onde parou sem repetir request.
"""
import os
import sqlite3
import sys
import time

from coletar_understat import DB, coleta

LIGAS = ["EPL", "La_liga", "Bundesliga", "Serie_A", "Ligue_1", "RFPL"]
TEMPORADAS = list(range(2014, 2027))


def total_no_banco():
    if not os.path.exists(DB):
        return 0, 0
    con = sqlite3.connect(DB)
    try:
        j = con.execute("SELECT COUNT(*) FROM jogo").fetchone()[0]
        c = con.execute("SELECT COUNT(*) FROM chute").fetchone()[0]
        return j, c
    except sqlite3.OperationalError:
        return 0, 0
    finally:
        con.close()


def main():
    temporadas = TEMPORADAS
    if len(sys.argv) > 2:
        temporadas = list(range(int(sys.argv[1]), int(sys.argv[2]) + 1))

    alvos = [(l, t) for t in temporadas for l in LIGAS]
    print(f"{len(alvos)} liga-temporadas | pausa {os.environ.get('PAUSA','0.7')}s")
    j0, c0 = total_no_banco()
    print(f"banco antes: {j0} jogos, {c0} chutes\n")

    t_ini = time.time()
    falhas = []
    for i, (liga, temp) in enumerate(alvos, 1):
        print(f"[{i}/{len(alvos)}] {liga} {temp}")
        try:
            coleta(liga, str(temp))
        except Exception as e:
            print(f"  FALHOU: {type(e).__name__}: {e}")
            falhas.append((liga, temp, str(e)))
        j, c = total_no_banco()
        dec = time.time() - t_ini
        print(f"  acumulado: {j} jogos, {c} chutes | {dec/60:.1f} min\n")

    j1, c1 = total_no_banco()
    print("=" * 60)
    print(f"FIM em {(time.time()-t_ini)/60:.1f} min")
    print(f"banco: {j1} jogos (+{j1-j0}), {c1} chutes (+{c1-c0})")
    if falhas:
        print(f"\n{len(falhas)} liga-temporadas falharam (rode de novo para retomar):")
        for liga, temp, e in falhas:
            print(f"  {liga} {temp}: {e}")


if __name__ == "__main__":
    main()
