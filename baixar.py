# -*- coding: utf-8 -*-
"""Enche o cache/ com as respostas do Understat, em paralelo.

   python baixar.py                 # todas as ligas, 2014..2026
   python baixar.py 2018 2020       # so essas temporadas
   TRABALHADORES=6 python baixar.py

Separado do banco de proposito: a rede e o gargalho (~0,9 s de latencia por
request), entao baixar em paralelo derruba o tempo total de ~11 h para ~2 h.
O SQLite nao e tocado aqui — carregar.py le o cache depois, sem rede e sem
contencao de escrita.

Resumivel: arquivo que ja esta no cache nao e baixado de novo.
"""
import gzip
import io
import json
import os
import random
import sys
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

BASE = "https://understat.com"
DIR = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(DIR, "cache")

LIGAS = ["EPL", "La_liga", "Bundesliga", "Serie_A", "Ligue_1", "RFPL"]
TEMPORADAS = list(range(2014, 2027))

TRABALHADORES = int(os.environ.get("TRABALHADORES", "4"))
PAUSA = float(os.environ.get("PAUSA", "0.25"))   # por trabalhador
TENTATIVAS = 4

_trava = threading.Lock()
_contagem = {"ok": 0, "cache": 0, "erro": 0}


def pega(caminho, nome_cache):
    """GET com cache em disco e backoff. Devolve (dados, veio_do_cache)."""
    arq = os.path.join(CACHE, nome_cache)
    if os.path.exists(arq) and os.path.getsize(arq) > 2:
        with open(arq, encoding="utf-8") as f:
            return json.load(f), True

    ultimo = None
    for tentativa in range(TENTATIVAS):
        req = urllib.request.Request(
            f"{BASE}/main/{caminho}",
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
                "X-Requested-With": "XMLHttpRequest",
                "Accept-Encoding": "gzip",
                "Referer": BASE + "/",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=40) as r:
                bruto = r.read()
                if r.headers.get("Content-Encoding") == "gzip":
                    bruto = gzip.GzipFile(fileobj=io.BytesIO(bruto)).read()
            dados = json.loads(bruto.decode("utf-8"))
            tmp = arq + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(dados, f, ensure_ascii=False)
            os.replace(tmp, arq)   # escrita atomica: cache nunca fica parcial
            time.sleep(PAUSA)
            return dados, False
        except urllib.error.HTTPError as e:
            ultimo = e
            if e.code == 429:       # pedindo para desacelerar
                time.sleep(10 * (tentativa + 1))
            elif 400 <= e.code < 500:
                raise               # 404 nao melhora com retry
            else:
                time.sleep(2 ** tentativa + random.random())
        except Exception as e:
            ultimo = e
            time.sleep(2 ** tentativa + random.random())
    raise RuntimeError(f"{caminho}: {type(ultimo).__name__}: {ultimo}")


def baixa_jogo(jid):
    try:
        _d, do_cache = pega(f"getMatchData/{jid}", f"jogo_{jid}.json")
        with _trava:
            _contagem["cache" if do_cache else "ok"] += 1
        return None
    except Exception as e:
        with _trava:
            _contagem["erro"] += 1
        return (jid, str(e))


def main():
    os.makedirs(CACHE, exist_ok=True)
    temporadas = TEMPORADAS
    if len(sys.argv) > 2:
        temporadas = list(range(int(sys.argv[1]), int(sys.argv[2]) + 1))

    print(f"ligas: {', '.join(LIGAS)}")
    print(f"temporadas: {temporadas[0]}..{temporadas[-1]}")
    print(f"{TRABALHADORES} trabalhadores, pausa {PAUSA}s cada\n")

    # 1) indices das liga-temporadas (serial, sao poucos)
    ids = []
    for temp in temporadas:
        for liga in LIGAS:
            try:
                d, _c = pega(f"getLeagueData/{liga}/{temp}",
                             f"liga_{liga}_{temp}.json")
            except Exception as e:
                print(f"  INDICE FALHOU {liga} {temp}: {e}")
                continue
            jogos = [int(j["id"]) for j in d.get("dates", []) if j.get("isResult")]
            ids.extend(jogos)
            print(f"  {liga:11s} {temp}: {len(jogos):4d} jogos concluidos")
    ids = sorted(set(ids))

    pendentes = [i for i in ids
                 if not os.path.exists(os.path.join(CACHE, f"jogo_{i}.json"))]
    print(f"\n{len(ids)} jogos no total | {len(ids)-len(pendentes)} ja no cache "
          f"| {len(pendentes)} a baixar")
    if not pendentes:
        print("nada a fazer")
        return

    t0 = time.time()
    erros = []
    with ThreadPoolExecutor(max_workers=TRABALHADORES) as ex:
        futuros = {ex.submit(baixa_jogo, i): i for i in pendentes}
        feitos = 0
        for fut in as_completed(futuros):
            r = fut.result()
            if r:
                erros.append(r)
            feitos += 1
            if feitos % 200 == 0 or feitos == len(pendentes):
                dec = time.time() - t0
                taxa = feitos / dec
                resta = (len(pendentes) - feitos) / taxa if taxa else 0
                print(f"  {feitos}/{len(pendentes)}  {taxa:.1f}/s  "
                      f"faltam {resta/60:.0f} min  (erros {len(erros)})",
                      flush=True)

    print(f"\nFIM em {(time.time()-t0)/60:.1f} min")
    print(f"baixados {_contagem['ok']} | ja em cache {_contagem['cache']} "
          f"| erros {_contagem['erro']}")
    if erros:
        print(f"\n{len(erros)} jogos falharam (rode de novo para retomar):")
        for jid, e in erros[:15]:
            print(f"  {jid}: {e}")


if __name__ == "__main__":
    main()
