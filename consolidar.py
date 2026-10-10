# -*- coding: utf-8 -*-
"""Corrige o tempo (1o/2o) de cada chute usando o placar oficial do intervalo.

   python consolidar.py

Roda depois de carregar.py e coletar_odds.py.

Os gols em ordem de `id` sao cronologicos. Se o football-data diz que o
intervalo terminou HTHG x HTAG, os primeiros k = HTHG+HTAG gols do jogo sao do
1o tempo e o resto e do 2o — sem depender do minuto rotulado, que transborda
no acrescimo. O lado de cada gol confere a regra: os k primeiros precisam
somar exatamente HTHG para a casa e HTAG para a fora.

Os chutes que nao sao gol herdam a fronteira: tudo antes do k-esimo gol e 1o
tempo, tudo a partir do (k+1)-esimo e 2o. Entre os dois, vale a virada do
minuto se houver, senao o corte em 45.

corte_ht resultante:
  'placar_ht'  fronteira fixada pelo placar oficial do intervalo (exato p/ gols)
  'detectado'  sem placar oficial, mas a virada do minuto aparece
  'inferido'   nem um nem outro: corte em 45 (RFPL, basicamente)
  'conflito'   placar oficial nao casa com a ordem dos gols — fica como estava
"""
import os
import sqlite3
from collections import Counter

DIR = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(DIR, "futebol.db")


def fronteira(chutes, k):
    """chutes: [(ordem, minuto, gol_para)] em ordem de id. Devolve o indice do
    primeiro chute do 2o tempo, sabendo que ha k gols no 1o tempo."""
    idx_gols = [i for i, c in enumerate(chutes) if c[2] is not None]
    lo = idx_gols[k - 1] + 1 if k > 0 else 0              # depois do k-esimo gol
    hi = idx_gols[k] if k < len(idx_gols) else len(chutes)  # no (k+1)-esimo gol
    mins = [c[1] for c in chutes]
    # virada do minuto dentro da janela permitida
    for i in range(max(lo, 1), hi + 1):
        if i < len(mins) and mins[i] < mins[i - 1] and 45 <= mins[i - 1] <= 55 \
                and 44 <= mins[i] <= 50:
            return i
    # senao, primeiro chute rotulado depois de 45 dentro da janela
    for i in range(lo, hi):
        if mins[i] > 45:
            return i
    return hi


def main():
    con = sqlite3.connect(DB)
    linhas = con.execute(
        """SELECT j.id, o.ht_casa_fd, o.ht_fora_fd, j.corte_ht
           FROM jogo j LEFT JOIN odds_pre o ON o.jogo_id = j.id
           WHERE j.placar_confere = 1""").fetchall()
    resultado = Counter()
    for jid, hth, hta, corte_atual in linhas:
        if hth is None or hta is None:
            resultado[corte_atual] += 1
            continue
        chutes = con.execute(
            "SELECT ordem, minuto, gol_para FROM chute WHERE jogo_id=? ORDER BY ordem",
            (jid,)).fetchall()
        gols = [c[2] for c in chutes if c[2] is not None]
        k = hth + hta
        primeiros = gols[:k]
        if (k > len(gols) or primeiros.count("h") != hth
                or primeiros.count("a") != hta):
            # a ordem dos gols nao reproduz o placar do intervalo
            con.execute("UPDATE jogo SET corte_ht='conflito' WHERE id=?", (jid,))
            resultado["conflito"] += 1
            continue
        b = fronteira(chutes, k)
        con.executemany(
            "UPDATE chute SET tempo=? WHERE jogo_id=? AND ordem=?",
            [(1 if i < b else 2, jid, c[0]) for i, c in enumerate(chutes)])
        con.execute(
            "UPDATE jogo SET corte_ht='placar_ht', ht_casa=?, ht_fora=? WHERE id=?",
            (hth, hta, jid))
        resultado["placar_ht"] += 1
    con.commit()

    tot = sum(resultado.values())
    print(f"{tot} jogos com placar conferido")
    for k in ("placar_ht", "detectado", "inferido", "conflito"):
        print(f"  {k:10s}: {resultado[k]:6d} ({resultado[k]/tot*100:5.1f}%)")

    print("\nfatia de gols no 1o tempo por tipo de corte (livro ~45-46%):")
    for corte, n_g, pri in con.execute(
            """SELECT j.corte_ht, COUNT(*), SUM(c.tempo=1) FROM chute c
               JOIN jogo j ON j.id=c.jogo_id
               WHERE c.gol_para IS NOT NULL AND j.placar_confere=1
               GROUP BY j.corte_ht ORDER BY 2 DESC"""):
        print(f"  {corte:10s}: {pri/n_g*100:5.2f}% de {n_g} gols")
    con.close()


if __name__ == "__main__":
    main()
