# -*- coding: utf-8 -*-
"""Integracao com o Scanner do site Futebol.

Extrai o scanParse DE VERDADE do index.html publicado, roda num V8 junto com
o motor1.js, cola uma Tabela Live no formato do Fut Odds e confere que o
Motor 1 recebe os campos certos. E aqui que um nome de campo trocado entre os
dois projetos apareceria.

Repo Futebol em ../Futebol, ou em FUTEBOL_DIR.
"""
import json
import os
import sys

import pytest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
import motor1 as M  # noqa: E402

FUTEBOL = os.environ.get("FUTEBOL_DIR", os.path.join(os.path.dirname(RAIZ), "Futebol"))
INDEX = os.path.join(FUTEBOL, "index.html")
GERADOR = os.path.join(FUTEBOL, "analisar_backtests.py")
JSON = os.path.join(RAIZ, "web", "linha_do_tempo.json")
JS = os.path.join(RAIZ, "web", "motor1.js")

py_mini_racer = pytest.importorskip("py_mini_racer")
pytestmark = [
    pytest.mark.skipif(not os.path.exists(INDEX), reason=f"sem {INDEX}"),
    pytest.mark.skipif(not os.path.exists(JSON), reason="rode exportar_web.py"),
]

CABECALHO = ["Jogo", "H2H", "PI1", "PI2", "PI3", "APPM", "APPM10", "CG", "CG10",
             "xG", "xGS", "Chut", "CAG", "CFG", "Canto", "Ataq", "A/Per", "Poss",
             "Amar", "Verm", "OCASA", "OEMPA", "OFORA", "OV25", "UN25"]


def bloco_jogo(casa, placar_c, fora, placar_f, minuto, pares, odds):
    """Um jogo como o Fut Odds cola: times + caixas de placar, o token de
    minuto, e os 43 valores (19 pares casa/fora + 5 odds)."""
    linhas = [casa, *placar_c, fora, *placar_f, minuto]
    for a, b in pares:
        linhas += [str(a), str(b)]
    linhas += [str(o) for o in odds]
    return linhas


def pares(**kw):
    base = dict(h2h=(50, 30), pi1=(40, 20), pi2=(6, 3), pi3=(2, 1), appm=(1.1, 0.6),
                appm10=(1.4, 0.5), cg=(5, 2), cg10=(2, 1), xg=(0.9, 0.3), xgs=(1.2, 0.4),
                chut=(7, 3), cag=(3, 1), cfg=(4, 2), canto=(4, 1), ataq=(30, 15),
                aper=(20, 8), poss=("62%", "38%"), amar=(1, 0), verm=(0, 0))
    base.update(kw)
    ordem = ["h2h", "pi1", "pi2", "pi3", "appm", "appm10", "cg", "cg10", "xg", "xgs",
             "chut", "cag", "cfg", "canto", "ataq", "aper", "poss", "amar", "verm"]
    return [base[k] for k in ordem]


COLAGEM = "\n".join(
    CABECALHO
    # favorito da casa a 1,50, 1x1 aos 26' -> o exemplo do usuario
    + bloco_jogo("Arsenal", ["0", "1"], "Luton", ["0", "1"], "26'",
                 pares(), [1.50, 4.20, 6.50, 1.65, 2.25])
    # favorito VISITANTE vencendo 0x1 aos 63', com expulsao
    + bloco_jogo("Ceara", ["0"], "Palmeiras", ["1"], "63'",
                 pares(verm=(1, 0), chut=(5, 11), cag=(1, 5)),
                 [5.50, 3.90, 1.62, 2.10, 1.72])
    # no intervalo
    + bloco_jogo("Lazio", ["1", "0"], "Roma", ["1", "0"], "HT",
                 pares(), [2.40, 3.30, 3.00, 1.90, 1.90])
    # nao comecou -> o Scanner ignora
    + bloco_jogo("Time A", ["0"], "Time B", ["0"], "-'", pares(), [2, 3, 4, 1.9, 1.9])
)


def trecho(html, ini, fim):
    a = html.index(ini)
    return html[a:html.index(fim, a)]


@pytest.fixture(scope="module")
def ctx():
    with open(INDEX, encoding="utf-8") as f:
        html = f.read()
    parser = trecho(html, "const SCAN_PARES", "const scSoma")
    c = py_mini_racer.MiniRacer()
    c.eval(parser)
    with open(JS, encoding="utf-8") as f:
        c.eval(f.read())
    with open(JSON, encoding="utf-8") as f:
        c.eval(f"Motor1.carregarDoc(JSON.parse({json.dumps(f.read())}))")
    yield c
    if hasattr(c, "close"):
        c.close()


def parse(c):
    return json.loads(c.eval(f"JSON.stringify(scanParse({json.dumps(COLAGEM)}))"))


def test_o_parser_do_site_le_a_colagem(ctx):
    r = parse(ctx)
    assert [j["casa"] for j in r["jogos"]] == ["Arsenal", "Ceara", "Lazio"]
    assert [i["por"] for i in r["ignorados"]] == ["não começou"]
    a = r["jogos"][0]
    assert (a["golsC"], a["golsF"], a["minuto"]) == (1, 1, 26)
    assert a["cag"] == [3, 1] and a["ocasa"] == 1.5


def test_motor1_recebe_o_jogo_do_scanner_sem_traducao(ctx):
    jogos = parse(ctx)["jogos"]
    arsenal, ceara, lazio = jogos

    r = json.loads(ctx.eval(f"JSON.stringify(Motor1.consulta({json.dumps(arsenal)}, 'ht'))"))
    assert r["ok"] and r["instante"] == [1, 25] and r["placar_rel"] == [1, 1]
    assert r["fav"]["lado"] == "casa"
    # tudo que o historico nao tem e declarado, nao usado em silencio
    sem_base = {s.split(":")[0] for s in r["ignorados"]}
    assert {"aper", "poss", "canto", "pi1", "xg"} <= sem_base

    r = json.loads(ctx.eval(f"JSON.stringify(Motor1.consulta({json.dumps(ceara)}, 'ft'))"))
    assert r["fav"]["lado"] == "fora" and r["placar_rel"] == [1, 0]
    assert r["instante"] == [2, 62]
    assert any("expulsao" in a for a in r["avisos"])

    r = json.loads(ctx.eval(f"JSON.stringify(Motor1.consulta({json.dumps(lazio)}, 'ht'))"))
    assert r["ok"] is False
    r = json.loads(ctx.eval(f"JSON.stringify(Motor1.consulta({json.dumps(lazio)}, 'ft'))"))
    assert r["ok"] and r["instante"] == [2, 45]


def test_js_e_python_concordam_nos_jogos_colados(ctx):
    py = M.Motor1(JSON)
    for j in parse(ctx)["jogos"]:
        for per in ("ht", "ft"):
            a = py.consulta(j, per)
            b = json.loads(ctx.eval(f"JSON.stringify(Motor1.consulta({json.dumps(j)}, '{per}'))"))
            assert (a["ok"], a.get("n"), a.get("green"), a.get("nivel")) == \
                   (b["ok"], b.get("n"), b.get("green"), b.get("nivel"))


def test_colunas_entram_na_tabela_do_scanner(ctx):
    """Motor1.scanner sobre uma tabela falsa com a mesma forma da do site."""
    saida = json.loads(ctx.eval("""(function () {
      function Tr() { this.html = ''; this.title = ''; }
      Tr.prototype.querySelector = function () { return this.html.indexOf('m1h') >= 0 ? {} : null; };
      Tr.prototype.querySelectorAll = function () { return []; };
      Tr.prototype.insertAdjacentHTML = function (_p, h) { this.html += h; };
      const linhas = scanParse(%s).jogos.map(j => ({ j, r: { periodo: 'ft', justa: 2.0 } }));
      const trs = [new Tr()].concat(linhas.map(() => new Tr()));
      Motor1.scanner(linhas, { querySelectorAll: () => trs });
      return JSON.stringify(trs.map(t => ({ html: t.html, title: t.title })));
    })()""" % json.dumps(COLAGEM)))
    cab, *linhas = saida
    assert "Motor 1" in cab["html"] and "M1 base" in cab["html"]
    assert len(linhas) == 3
    for ln in linhas:
        assert ln["html"].count('class="m1c"') == 2
        assert "n=" in ln["html"] and "IC" in ln["html"]
    assert "⚠" in linhas[1]["html"]           # Ceara x Palmeiras: expulsao
    assert "placar 1x0 (fav x zebra)" in linhas[1]["title"]


@pytest.mark.parametrize("arq", [INDEX, GERADOR])
def test_gancho_esta_no_html_e_no_gerador(arq):
    """Se o index.html for regerado pelo analisar_backtests.py, o gancho
    precisa continuar la."""
    with open(arq, encoding="utf-8") as f:
        s = f.read()
    assert "Motor1.scanner(scLinhas, $('scTabela'))" in s
    assert '<script src="motor1/motor1.js"></script>' in s
