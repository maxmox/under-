# -*- coding: utf-8 -*-
"""Ajuste honesto dos parametros e ablacao de cada componente.

   python ajustar.py

Divide a temporada por data em treino/teste. Faz busca em grade de peso_xg e
prior_xg usando SO o treino (com validacao interna), e depois mede no teste
que nunca foi visto. Reporta cada componente ligado e desligado, contra dois
baselines. Componente que nao melhora o Brier fora da amostra nao fica.
"""
import sqlite3

import motor as M

MINUTOS_HT = (15, 25, 35, 42)
MINUTOS_FT = (60, 70, 80, 85)

GRADE_PESO = (0.0, 0.2, 0.35, 0.5, 0.7, 1.0)
GRADE_PRIOR = (0.3, 0.6, 1.2, 2.5)


def observacoes(jogos):
    for j in jogos:
        for periodo, minutos in (("ht", MINUTOS_HT), ("ft", MINUTOS_FT)):
            for t in minutos:
                y = M.under_bateu(j, t, periodo)
                if y is None:
                    continue
                yield j, t, periodo, M.estado_em(j, t), y


def brier(mt, jogos, **kw):
    s = n = 0
    for j, t, periodo, e, y in observacoes(jogos):
        p = mt.p_under(j, t, periodo, e, **kw)
        s += (p - y) ** 2
        n += 1
    return s / n if n else float("nan")


def brier_plano(mt, jogos):
    """Baseline: Poisson com o lambda medio da amostra, sem odds do jogo."""
    plano = M.Motor(mt.perfis, mt.lambda_medio, peso_xg=0.0)
    s = n = 0
    for j, t, periodo, e, y in observacoes(jogos):
        jsem = dict(j, lambda_jogo=None)
        p = plano.p_under(jsem, t, periodo, e, usar_placar=False)
        s += (p - y) ** 2
        n += 1
    return s / n if n else float("nan")


def divide(jogos, frac=0.7):
    o = sorted(jogos, key=lambda j: j["data"])
    c = int(len(o) * frac)
    return o[:c], o[c:]


def main():
    con = sqlite3.connect(M.DB)
    jogos = M.carrega(con)
    con.close()
    treino, teste = divide(jogos)
    # validacao interna: nao toca no teste para escolher parametro
    tr_a, tr_b = divide(treino, 0.75)

    print(f"jogos: {len(jogos)}  |  treino {len(treino)}  teste {len(teste)}")
    print(f"busca em grade com validacao interna ({len(tr_a)}/{len(tr_b)})\n")
    print("  peso_xg  prior_xg   Brier validacao")
    melhor = None
    for peso in GRADE_PESO:
        for prior in GRADE_PRIOR:
            mt, _ = M.treina(tr_a, MINUTOS_HT, MINUTOS_FT, peso, prior)
            b = brier(mt, tr_b)
            marca = ""
            if melhor is None or b < melhor[0]:
                melhor = (b, peso, prior)
                marca = "  <-"
            print(f"  {peso:7.2f}  {prior:8.2f}   {b:.5f}{marca}")
            if peso == 0.0:
                break  # prior nao tem efeito quando o peso e zero
    _b, peso, prior = melhor
    print(f"\nescolhido no treino: peso_xg={peso}  prior_xg={prior}")

    # reajusta no treino inteiro e afere no teste intocado
    mt, info = M.treina(treino, MINUTOS_HT, MINUTOS_FT, peso, prior)

    print("\n" + "=" * 68)
    print("EFEITO DE PLACAR CALIBRADO EM P(zero gols)   (>1 = sai mais gol)")
    print("=" * 68)
    for k in sorted(info["efeito_placar"]):
        n = info["n_por_estado"].get(k, 0)
        print(f"  {k[0]:3s} {k[1]:16s} : x{info['efeito_placar'][k]:.3f}  (n={n})")
    faltou = [k for k in info["n_por_estado"] if k not in info["efeito_placar"]]
    for k in sorted(faltou):
        print(f"  {k[0]:3s} {k[1]:16s} : sem n suficiente "
              f"(n={info['n_por_estado'][k]}) -> usa x1,000")

    print("\n" + "=" * 68)
    print("ABLACAO FORA DA AMOSTRA  (Brier; menor e melhor)")
    print("=" * 68)
    bp = brier_plano(mt, teste)
    linhas = [
        ("Poisson plano (lambda medio, sem odds)", bp),
        ("lambda pre-live, sem ajuste", brier(mt, teste, usar_xg=False, usar_placar=False)),
        ("lambda + xG", brier(mt, teste, usar_xg=True, usar_placar=False)),
        ("lambda + placar", brier(mt, teste, usar_xg=False, usar_placar=True)),
        ("lambda + xG + placar (completo)", brier(mt, teste, usar_xg=True, usar_placar=True)),
    ]
    for nome, b in linhas:
        g = (bp - b) / bp * 100
        print(f"  {nome:40s} {b:.5f}   {g:+6.2f}% vs plano")

    vencedor = min(linhas, key=lambda x: x[1])
    print(f"\n  melhor fora da amostra: {vencedor[0]}")
    print("\n  n de observacoes no teste:", sum(1 for _ in observacoes(teste)))


if __name__ == "__main__":
    main()
