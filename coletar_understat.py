# -*- coding: utf-8 -*-
"""Coleta jogos e chutes (com minuto exato) da API interna do Understat.

   python coletar_understat.py EPL 2024

Guarda cada resposta em cache/ para nunca repetir request, e grava em
futebol.db. Pode ser interrompido e retomado: jogo ja coletado e pulado.
"""
import json, os, re, sqlite3, sys, time, urllib.request, gzip, io

BASE = "https://understat.com"
CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache")
DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "futebol.db")
PAUSA = float(os.environ.get("PAUSA", "0.7"))  # segundos entre requests

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
"""


def pega(caminho, nome_cache):
    """GET na API interna, com cache em disco. Exige X-Requested-With."""
    arq = os.path.join(CACHE, nome_cache)
    if os.path.exists(arq):
        with open(arq, encoding="utf-8") as f:
            return json.load(f)
    req = urllib.request.Request(
        f"{BASE}/main/{caminho}",
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            "X-Requested-With": "XMLHttpRequest",
            "Accept-Encoding": "gzip",
            "Referer": BASE + "/",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        bruto = r.read()
        if r.headers.get("Content-Encoding") == "gzip":
            bruto = gzip.GzipFile(fileobj=io.BytesIO(bruto)).read()
    dados = json.loads(bruto.decode("utf-8"))
    with open(arq, "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False)
    time.sleep(PAUSA)
    return dados


def coleta(liga, temporada):
    os.makedirs(CACHE, exist_ok=True)
    con = sqlite3.connect(DB)
    con.executescript(ESQUEMA)

    liga_dados = pega(f"getLeagueData/{liga}/{temporada}", f"liga_{liga}_{temporada}.json")
    jogos = [j for j in liga_dados["dates"] if j.get("isResult")]
    print(f"{liga} {temporada}: {len(jogos)} jogos concluidos")

    ja = {r[0] for r in con.execute("SELECT id FROM jogo WHERE liga=? AND temporada=?", (liga, temporada))}
    novos = erros = 0
    for i, j in enumerate(jogos, 1):
        jid = int(j["id"])
        if jid in ja:
            continue
        try:
            d = pega(f"getMatchData/{jid}", f"jogo_{jid}.json")
        except Exception as e:
            print(f"  ERRO jogo {jid}: {e}")
            erros += 1
            continue
        prev = j.get("forecast") or {}
        con.execute(
            "INSERT OR REPLACE INTO jogo VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (jid, liga, int(temporada), j["datetime"], j["h"]["title"], j["a"]["title"],
             int(j["goals"]["h"]), int(j["goals"]["a"]),
             float(j["xG"]["h"]), float(j["xG"]["a"]),
             _f(prev.get("w")), _f(prev.get("d")), _f(prev.get("l"))),
        )
        con.execute("DELETE FROM chute WHERE jogo_id=?", (jid,))
        for lado in ("h", "a"):
            for s in d.get("shots", {}).get(lado, []):
                con.execute(
                    "INSERT INTO chute VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (jid, int(s["minute"]), lado, s["result"], _f(s["xG"]),
                     s.get("situation"), s.get("shotType"), s.get("player"),
                     _f(s.get("X")), _f(s.get("Y"))),
                )
        novos += 1
        if novos % 20 == 0:
            con.commit()
            print(f"  {i}/{len(jogos)} ({novos} novos)")
    con.commit()
    n_j = con.execute("SELECT COUNT(*) FROM jogo").fetchone()[0]
    n_c = con.execute("SELECT COUNT(*) FROM chute").fetchone()[0]
    con.close()
    print(f"pronto: +{novos} jogos, {erros} erros | banco: {n_j} jogos, {n_c} chutes")


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


if __name__ == "__main__":
    liga = sys.argv[1] if len(sys.argv) > 1 else "EPL"
    temp = sys.argv[2] if len(sys.argv) > 2 else "2024"
    coleta(liga, temp)
