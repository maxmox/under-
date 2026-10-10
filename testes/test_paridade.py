# -*- coding: utf-8 -*-
"""O motor1.js (o que vai para o site) da EXATAMENTE o mesmo resultado que o
motor1.py (a referencia), consulta a consulta, sobre o banco real?

Roda o arquivo JS de verdade num V8 embutido (mini-racer). Precisa de
web/linha_do_tempo.json (python exportar_web.py).
"""
import json
import os
import random
import sys

import pytest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
import motor1 as M  # noqa: E402

JSON = os.path.join(RAIZ, "web", "linha_do_tempo.json")
JS = os.path.join(RAIZ, "web", "motor1.js")

py_mini_racer = pytest.importorskip("py_mini_racer")
pytestmark = pytest.mark.skipif(not os.path.exists(JSON),
                                reason="rode exportar_web.py antes")

ODDS_1X2 = [(1.25, 6.0, 11.0), (1.50, 4.2, 6.5), (1.80, 3.6, 4.5), (2.30, 3.3, 3.1),
            (2.70, 3.4, 2.6), (4.50, 3.8, 1.75), (8.0, 5.0, 1.35), None]
ODDS_OU = [(1.45, 2.75), (1.80, 2.00), (2.30, 1.62), None]


def consultas(n, semente=20261010):
    rnd = random.Random(semente)
    out = []
    for _ in range(n):
        periodo = rnd.choice(["ht", "ft"])
        intervalo = rnd.random() < 0.08
        if intervalo:
            minuto = 45
        elif periodo == "ht" and rnd.random() < 0.1:
            minuto = rnd.randint(46, 70)     # HT pedido no 2o tempo: nao se aplica
        else:
            minuto = rnd.randint(1, 45) if periodo == "ht" else rnd.randint(1, 93)
        o = rnd.choice(ODDS_1X2)
        ou = rnd.choice(ODDS_OU)
        j = {"golsC": rnd.choice([0, 0, 1, 1, 2, 3]), "golsF": rnd.choice([0, 0, 1, 2]),
             "minuto": minuto, "noIntervalo": intervalo,
             "ocasa": o[0] if o else None, "oempa": o[1] if o else None,
             "ofora": o[2] if o else None,
             "ov25": ou[0] if ou else None, "un25": ou[1] if ou else None}
        if rnd.random() < 0.6:
            j["cag"] = [rnd.randint(0, 6), rnd.randint(0, 4)]
        if rnd.random() < 0.4:
            j["chut"] = [rnd.randint(0, 14), rnd.randint(0, 10)]
        if rnd.random() < 0.1:
            j["verm"] = [0, 1]
        if rnd.random() < 0.3:
            j["aper"] = [rnd.randint(5, 40), rnd.randint(5, 40)]
        out.append((j, periodo, rnd.choice([30, 100, 100, 200])))
    return out


@pytest.fixture(scope="module")
def motores():
    with open(JSON, encoding="utf-8") as f:
        texto = f.read()
    py = M.Motor1(doc=json.loads(texto))
    ctx = py_mini_racer.MiniRacer()
    with open(JS, encoding="utf-8") as f:
        ctx.eval(f.read())
    n_js = ctx.eval(f"Motor1.carregarDoc(JSON.parse({json.dumps(texto)}))")
    assert n_js == len(py.jogos)
    yield py, ctx
    # sem fechar, o V8 do mini-racer segura o processo vivo na saida
    if hasattr(ctx, "close"):
        ctx.close()


def js_consulta(ctx, jogo, periodo, n_min):
    return json.loads(ctx.eval(
        f"JSON.stringify(Motor1.consulta({json.dumps(jogo)}, "
        f"{json.dumps(periodo)}, {n_min}))"))


EXATOS = ["ok", "motivo", "n", "green", "nivel", "filtros", "placar_rel",
          "instante", "dist", "avisos", "ignorados"]


def test_mesmo_resultado_em_150_consultas(motores):
    py, ctx = motores
    divergencias = []
    for jogo, periodo, n_min in consultas(150):
        a = py.consulta(jogo, periodo, n_min=n_min)
        b = js_consulta(ctx, jogo, periodo, n_min)
        for k in EXATOS:
            if a.get(k) != b.get(k):
                divergencias.append((jogo, periodo, k, a.get(k), b.get(k)))
        for k in ("p", "justa"):
            if (a.get(k) is None) != (b.get(k) is None) or (
                    a.get(k) is not None and abs(a[k] - b[k]) > 1e-12):
                divergencias.append((jogo, periodo, k, a.get(k), b.get(k)))
        if a.get("ic95"):
            if any(abs(x - y) > 1e-12 for x, y in zip(a["ic95"], b["ic95"])):
                divergencias.append((jogo, periodo, "ic95", a["ic95"], b["ic95"]))
        if a.get("fav") != b.get("fav"):
            divergencias.append((jogo, periodo, "fav", a.get("fav"), b.get("fav")))
    assert not divergencias, f"{len(divergencias)} divergencias, ex.: {divergencias[:3]}"


def test_consultas_cobrem_os_casos(motores):
    """Garante que a amostra de consultas exercitou o que importa."""
    py, _ctx = motores
    vistos = {"ht": 0, "ft": 0, "intervalo": 0, "relaxou": 0, "fina": 0,
              "sem_1x2": 0, "nao_se_aplica": 0}
    for jogo, periodo, n_min in consultas(150):
        r = py.consulta(jogo, periodo, n_min=n_min)
        vistos[periodo] += 1
        vistos["intervalo"] += bool(jogo["noIntervalo"])
        if not r["ok"] and r.get("motivo"):
            vistos["nao_se_aplica"] += 1
            continue
        vistos["relaxou"] += r["nivel"] > 0
        vistos["fina"] += any("amostra fina" in a for a in r["avisos"])
        vistos["sem_1x2"] += r["fav"] is None
    assert all(v > 0 for v in vistos.values()), vistos
