# -*- coding: utf-8 -*-
"""Integridade do banco: o que o Motor 1 conta bate com o placar oficial?

Precisa de futebol.db (baixar.py -> carregar.py -> coletar_odds.py ->
consolidar.py) e de web/linha_do_tempo.json (exportar_web.py).
"""
import json
import os
import sqlite3
import sys

import pytest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
import motor1 as M  # noqa: E402

DB = os.path.join(RAIZ, "futebol.db")
JSON = os.path.join(RAIZ, "web", "linha_do_tempo.json")

pytestmark = pytest.mark.skipif(not os.path.exists(DB), reason="sem futebol.db")


@pytest.fixture(scope="module")
def con():
    c = sqlite3.connect(DB)
    yield c
    c.close()


def test_placar_reconstruido_bate_com_o_oficial(con):
    ruins = con.execute(
        """SELECT j.id FROM jogo j
           LEFT JOIN (SELECT jogo_id, SUM(gol_para='h') h, SUM(gol_para='a') a
                      FROM chute GROUP BY jogo_id) g ON g.jogo_id = j.id
           WHERE j.placar_confere = 1
             AND (COALESCE(g.h,0) != j.gols_casa OR COALESCE(g.a,0) != j.gols_fora)"""
    ).fetchall()
    assert not ruins, f"{len(ruins)} jogos marcados como conferidos nao conferem"


def test_tempo_dos_gols_reproduz_o_placar_oficial_do_intervalo(con):
    ruins = con.execute(
        """SELECT j.id FROM jogo j
           LEFT JOIN (SELECT jogo_id, SUM(gol_para='h' AND tempo=1) h,
                             SUM(gol_para='a' AND tempo=1) a
                      FROM chute GROUP BY jogo_id) g ON g.jogo_id = j.id
           WHERE j.corte_ht = 'placar_ht'
             AND (COALESCE(g.h,0) != j.ht_casa OR COALESCE(g.a,0) != j.ht_fora)"""
    ).fetchall()
    assert not ruins, f"{len(ruins)} jogos com intervalo divergente"


def test_nenhum_conflito_de_intervalo(con):
    n = con.execute("SELECT COUNT(*) FROM jogo WHERE corte_ht='conflito'").fetchone()[0]
    assert n == 0


def test_tempo_nao_volta_na_ordem_cronologica(con):
    """Depois do primeiro chute do 2o tempo, nenhum chute volta a ser do 1o."""
    ruins = con.execute(
        """SELECT COUNT(DISTINCT a.jogo_id) FROM chute a JOIN chute b
             ON a.jogo_id = b.jogo_id AND b.ordem > a.ordem
           WHERE a.tempo = 2 AND b.tempo = 1"""
    ).fetchone()[0]
    assert ruins == 0


@pytest.mark.skipif(not os.path.exists(JSON), reason="sem linha_do_tempo.json")
def test_json_do_site_reproduz_o_placar_final_e_do_intervalo(con):
    with open(JSON, encoding="utf-8") as f:
        doc = json.load(f)
    exportados = len(doc["jogos"])
    esperados = con.execute(
        """SELECT COUNT(*) FROM jogo j JOIN odds_pre o ON o.jogo_id = j.id
           WHERE j.placar_confere = 1 AND j.corte_ht != 'conflito'
             AND COALESCE(o.ocf, o.oc) IS NOT NULL""").fetchone()[0]
    assert exportados == esperados
    # a soma de gols no JSON, por tempo, tem de bater com o banco
    g1 = g2 = 0
    for *_cab, evs in doc["jogos"]:
        for c in evs:
            tempo, _m, tipo, _l = M.decodifica(c)
            if tipo in (0, 3):
                g1 += tempo == 1
                g2 += tempo == 2
    b1, b2 = con.execute(
        """SELECT SUM(c.tempo=1), SUM(c.tempo=2) FROM chute c
           JOIN jogo j ON j.id = c.jogo_id JOIN odds_pre o ON o.jogo_id = j.id
           WHERE c.gol_para IS NOT NULL AND j.placar_confere = 1
             AND j.corte_ht != 'conflito' AND COALESCE(o.ocf, o.oc) IS NOT NULL"""
    ).fetchone()
    assert (g1, g2) == (b1, b2)
