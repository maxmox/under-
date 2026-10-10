# -*- coding: utf-8 -*-
"""Empacota e restaura o banco, para versiona-lo no repositorio.

   python dataset.py exportar    # futebol.db -> dados/futebol.db.gz (+ resumo)
   python dataset.py restaurar   # dados/futebol.db.gz -> futebol.db
   python dataset.py resumo      # o que tem no banco atual

O banco cru passa de 70 MB com as 6 ligas; gzipado fica perto de 30 MB, que
cabe no GitHub sem LFS. Como e um blob binario, cada commit dele guarda uma
copia inteira — versione em marcos, nao a cada coleta incremental. Se a serie
crescer muito, migre para Releases ou LFS.
"""
import gzip
import os
import shutil
import sqlite3
import sys

DIR = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(DIR, "futebol.db")
PASTA = os.path.join(DIR, "dados")
GZ = os.path.join(PASTA, "futebol.db.gz")
RESUMO = os.path.join(PASTA, "RESUMO.md")


def _con():
    if not os.path.exists(DB):
        raise SystemExit("futebol.db nao existe — rode coletar_tudo.py "
                         "ou python dataset.py restaurar")
    return sqlite3.connect(DB)


def resumo(escreve=False):
    con = _con()
    jogos = con.execute("SELECT COUNT(*) FROM jogo").fetchone()[0]
    chutes = con.execute("SELECT COUNT(*) FROM chute").fetchone()[0]
    gols = con.execute("SELECT COUNT(*) FROM chute WHERE resultado='Goal'").fetchone()[0]
    try:
        odds = con.execute("SELECT COUNT(*) FROM odds_pre").fetchone()[0]
    except sqlite3.OperationalError:
        odds = 0
    linhas = con.execute(
        "SELECT liga, temporada, COUNT(*) FROM jogo "
        "GROUP BY liga, temporada ORDER BY liga, temporada").fetchall()
    por_liga = con.execute(
        "SELECT liga, COUNT(*), MIN(temporada), MAX(temporada) FROM jogo "
        "GROUP BY liga ORDER BY liga").fetchall()

    out = []
    out.append("# Resumo do banco\n")
    out.append(f"- jogos: **{jogos}**")
    out.append(f"- chutes: **{chutes}** ({chutes/jogos:.1f}/jogo)")
    out.append(f"- gols: **{gols}** ({gols/jogos:.2f}/jogo)")
    out.append(f"- jogos com odds pre-live: **{odds}** "
               f"({odds/jogos*100:.1f}%)\n")
    out.append("| liga | jogos | temporadas |")
    out.append("|---|---|---|")
    for liga, n, t0, t1 in por_liga:
        out.append(f"| {liga} | {n} | {t0}–{t1} |")
    out.append("\n<details><summary>por liga-temporada</summary>\n")
    out.append("| liga | temporada | jogos |")
    out.append("|---|---|---|")
    for liga, temp, n in linhas:
        out.append(f"| {liga} | {temp} | {n} |")
    out.append("\n</details>")
    texto = "\n".join(out) + "\n"
    con.close()

    print(texto)
    if escreve:
        os.makedirs(PASTA, exist_ok=True)
        with open(RESUMO, "w", encoding="utf-8") as f:
            f.write(texto)
    return texto


def exportar():
    con = _con()
    print("otimizando o banco (VACUUM + ANALYZE)...")
    con.execute("ANALYZE")
    con.execute("VACUUM")
    con.close()
    os.makedirs(PASTA, exist_ok=True)
    cru = os.path.getsize(DB)
    print(f"compactando {cru/1e6:.1f} MB...")
    with open(DB, "rb") as e, gzip.open(GZ, "wb", compresslevel=9) as s:
        shutil.copyfileobj(e, s, length=1 << 20)
    comp = os.path.getsize(GZ)
    print(f"dados/futebol.db.gz: {comp/1e6:.1f} MB "
          f"({comp/cru*100:.0f}% do original)")
    if comp > 90e6:
        print("AVISO: passou de 90 MB — o limite por arquivo do GitHub e "
              "100 MB. Use Releases ou LFS.")
    elif comp > 45e6:
        print("AVISO: passou de 45 MB — o GitHub avisa acima de 50 MB.")
    resumo(escreve=True)


def restaurar():
    if not os.path.exists(GZ):
        raise SystemExit(f"{GZ} nao existe")
    if os.path.exists(DB):
        resp = os.environ.get("SOBRESCREVER", "")
        if resp != "1":
            raise SystemExit(
                "futebol.db ja existe. Para sobrescrever: "
                "SOBRESCREVER=1 python dataset.py restaurar")
    with gzip.open(GZ, "rb") as e, open(DB, "wb") as s:
        shutil.copyfileobj(e, s, length=1 << 20)
    print(f"futebol.db restaurado ({os.path.getsize(DB)/1e6:.1f} MB)")
    resumo()


if __name__ == "__main__":
    acao = sys.argv[1] if len(sys.argv) > 1 else "resumo"
    {"exportar": exportar, "restaurar": restaurar,
     "resumo": resumo}.get(acao, resumo)()
