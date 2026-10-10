# -*- coding: utf-8 -*-
"""Regras do Motor 1 em jogos sinteticos, com resposta conhecida a mao."""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import motor1 as M  # noqa: E402

GOL, ALVO, FORA, CONTRA = 0, 1, 2, 3
CASA, VIS = 0, 1


def ev(tempo, minuto, tipo, lado):
    """Mesmo codigo do exportar_web.py."""
    return tempo * 10000 + minuto * 10 + tipo * 2 + lado


def doc(*jogos):
    return {"ligas": ["TESTE"], "jogos": list(jogos)}


def jogo(eventos, pc=600, pe=250, pf=150, po=550):
    return [0, 2020, pc, pe, pf, po, eventos]


def vivo(**kw):
    base = {"golsC": 0, "golsF": 0, "minuto": 26, "noIntervalo": False,
            "ocasa": 1.55, "oempa": 4.0, "ofora": 6.5, "ov25": 1.8, "un25": 2.0}
    base.update(kw)
    return base


# ---------------------------------------------------------------- convencoes

@pytest.mark.parametrize("entrada,esperado", [
    ({"minuto": 1}, (1, 0)),
    ({"minuto": 26}, (1, 25)),
    ({"minuto": 45}, (1, 44)),
    ({"minuto": 46}, (2, 45)),
    ({"minuto": 80}, (2, 79)),
    ({"minuto": 45, "noIntervalo": True}, (2, 45)),
])
def test_instante(entrada, esperado):
    assert M.instante(entrada) == esperado


def test_codificacao_ida_e_volta():
    for t, m, tp, l in [(1, 0, 0, 0), (1, 48, 3, 1), (2, 45, 1, 0), (2, 103, 2, 1)]:
        assert M.decodifica(ev(t, m, tp, l)) == (t, m, tp, l)


@pytest.mark.parametrize("x,tol", [(0, 1), (2, 1), (4, 1), (6, 2), (10, 3), (14, 4)])
def test_tolerancia_arredonda_para_cima_no_meio(x, tol):
    # 10 * 0,25 = 2,5 -> 3 (o round() bancario do Python daria 2)
    assert M.tolerancia(x) == tol


# ------------------------------------------------------------------- estado

def test_minuto_em_andamento_conta_como_futuro():
    # gol rotulado 25 com o vivo mostrando 26' (t=25): ainda e risco
    g, *_r, fut_ht, fut_ft = M.Motor1.estado([M.decodifica(ev(1, 25, GOL, CASA))], 1, 25)
    assert g == [0, 0] and fut_ht == 1 and fut_ft == 1
    g, *_r, fut_ht, _ = M.Motor1.estado([M.decodifica(ev(1, 24, GOL, CASA))], 1, 25)
    assert g == [1, 0] and fut_ht == 0


def test_gol_de_acrescimo_do_1o_tempo_derruba_o_under_ht():
    # gol aos 45+3: rotulo 48 mas tempo 1. Consulta HT aos 42'.
    evs = [M.decodifica(ev(1, 48, GOL, VIS))]
    _g, _a, _c, fut_ht, fut_ft = M.Motor1.estado(evs, 1, 41)
    assert fut_ht == 1 and fut_ft == 1
    # e no 2o tempo ele ja e passado, mesmo rotulado 48 > t
    g, *_r, fut_ft2 = M.Motor1.estado(evs, 2, 49)
    assert g == [0, 1] and fut_ft2 == 0


def test_gol_do_2o_tempo_rotulado_45_nao_e_do_1o():
    evs = [M.decodifica(ev(2, 45, GOL, CASA))]
    _g, _a, _c, fut_ht, fut_ft = M.Motor1.estado(evs, 1, 30)
    assert fut_ht == 0 and fut_ft == 1


def test_gol_contra_conta_placar_mas_nao_e_chute():
    evs = [M.decodifica(ev(1, 10, CONTRA, VIS)), M.decodifica(ev(1, 12, ALVO, CASA)),
           M.decodifica(ev(1, 13, FORA, VIS)), M.decodifica(ev(1, 14, GOL, CASA))]
    g, alvo, chutes, _h, _f = M.Motor1.estado(evs, 1, 30)
    assert g == [1, 1]
    assert alvo == 2      # defendido + gol normal; o contra nao
    assert chutes == 3    # defendido + fora + gol normal


# ------------------------------------------------------------ placar relativo

def test_placar_lido_em_relacao_ao_favorito():
    # historico: favorito da CASA (pc>pf) vencendo 1x0 aos 20, sem mais gols
    h = jogo([ev(1, 10, GOL, CASA)], pc=600, pf=150)
    m = M.Motor1(doc=doc(h))
    # vivo: favorito VISITANTE vencendo 0x1 -> tambem "favorito 1 x 0 zebra"
    r = m.consulta(vivo(golsC=0, golsF=1, ocasa=6.5, ofora=1.55), "ht", n_min=1)
    assert r["placar_rel"] == [1, 0] and r["fav"]["lado"] == "fora"
    assert r["n"] == 1 and r["green"] == 1
    # zebra vencendo nao casa com favorito vencendo
    r2 = m.consulta(vivo(golsC=1, golsF=0, ocasa=6.5, ofora=1.55), "ht", n_min=1)
    assert r2["n"] == 0


def test_taxa_conta_green_e_red():
    jogos = [jogo([]), jogo([]), jogo([ev(1, 30, GOL, VIS)]), jogo([ev(2, 70, GOL, CASA)])]
    m = M.Motor1(doc=doc(*jogos))
    r = m.consulta(vivo(minuto=26), "ht", n_min=1)
    assert (r["n"], r["green"]) == (4, 3)
    assert r["dist"] == {"0": 3, "1": 1, "2+": 0}
    r = m.consulta(vivo(minuto=26), "ft", n_min=1)
    assert (r["n"], r["green"]) == (4, 2)


# ---------------------------------------------------------------- relaxamento

def test_escolhe_o_degrau_mais_especifico_com_amostra():
    perto = [jogo([], pc=640, pf=150) for _ in range(5)]
    longe = [jogo([ev(1, 30, GOL, CASA)], pc=800, pf=60) for _ in range(5)]
    m = M.Motor1(doc=doc(*(perto + longe)))
    v = vivo(ocasa=1.50, oempa=4.2, ofora=7.0, ov25=None, un25=None)
    r = m.consulta(v, "ht", n_min=5)
    assert r["n"] == 5 and r["green"] == 5        # so os parecidos
    r = m.consulta(v, "ht", n_min=10)
    assert r["n"] == 10 and r["nivel"] == len(M.ESCADA) - 1   # relaxou tudo
    assert any("amostra fina" in a for a in r["avisos"]) is False


def test_amostra_fina_e_avisada():
    m = M.Motor1(doc=doc(jogo([])))
    r = m.consulta(vivo(), "ht", n_min=50)
    assert r["n"] == 1 and any("amostra fina" in a for a in r["avisos"])


def test_filtro_de_chutes_no_alvo():
    poucos = [jogo([ev(1, 5, ALVO, CASA)]) for _ in range(3)]
    muitos = [jogo([ev(1, m, ALVO, CASA) for m in range(1, 9)]) for _ in range(3)]
    m = M.Motor1(doc=doc(*(poucos + muitos)))
    r = m.consulta(vivo(cag=[1, 0], chut=[None, None]), "ht", n_min=3)
    assert r["n"] == 3
    # o Scanner nao trouxe chutes: o degrau 0 aplica so o no alvo, e o rotulo
    # diz isso (nao promete um filtro de chutes que nao rodou)
    assert r["nivel"] == 0
    assert r["filtros"] == "fav ±0,03 · O/U ±0,04 · no alvo"


def test_degrau_repetido_e_pulado():
    m = M.Motor1(doc=doc(jogo([])))
    v = vivo(ov25=None, un25=None)          # sem O/U: degraus 2 e 4 viram iguais
    r = m.consulta(v, "ht", n_min=1)
    assert r["nivel"] == 0 and r["filtros"] == "fav ±0,03"


# ------------------------------------------------------------------ avisos

def test_ht_no_segundo_tempo_nao_se_aplica():
    m = M.Motor1(doc=doc(jogo([])))
    assert m.consulta(vivo(minuto=60), "ht")["ok"] is False
    assert m.consulta(vivo(minuto=45, noIntervalo=True), "ht")["ok"] is False


def test_expulsao_e_campos_sem_base_sao_declarados():
    m = M.Motor1(doc=doc(jogo([])))
    r = m.consulta(vivo(verm=[0, 1], aper=[30, 12], poss=[60, 40], xg=[1.2, 0.3]),
                   "ft", n_min=1)
    assert any("expulsao" in a for a in r["avisos"])
    nomes = {s.split(":")[0] for s in r["ignorados"]}
    assert {"aper", "poss", "xg"} <= nomes


def test_sem_odds_1x2_cai_para_casa_x_fora():
    m = M.Motor1(doc=doc(jogo([ev(1, 10, GOL, CASA)])))
    r = m.consulta(vivo(golsC=1, ocasa=None, oempa=None, ofora=None), "ht", n_min=1)
    assert r["fav"] is None and r["n"] == 1
    assert r["nivel"] == len(M.ESCADA) - 1


def test_wilson_contem_a_taxa():
    lo, hi = M.wilson(73, 131)
    assert lo < 73 / 131 < hi
    assert M.wilson(0, 0) == (0.0, 1.0)
