# -*- coding: utf-8 -*-
"""Diagnostico do banco e afericao do motor fora da amostra.

   python avaliar.py

1. o que o dado tem (gols por minuto, borda do 1o tempo)
2. efeito de placar calibrado
3. calibragem, Brier e intervalo de confianca por bootstrap de jogos
4. exemplo de uso: odd justa num jogo concreto

Os parametros vem de ajustar.py, que os escolhe por busca em grade com
validacao interna. peso_xg=0 significa que o ajuste por xG foi REJEITADO
pelos dados nesta amostra.
"""
import random
import sqlite3
from collections import defaultdict

import motor as M
from ajustar import MINUTOS_FT, MINUTOS_HT, divide, observacoes

PESO_XG = 0.0    # escolhido por ajustar.py
PRIOR_XG = 0.3


def linha(t=""):
    print("\n" + "=" * 70)
    if t:
        print(t)
        print("=" * 70)


def diagnostico(jogos):
    linha("O QUE O BANCO TEM")
    n_chutes = sum(len(j["chutes"]) for j in jogos)
    n_gols = sum(1 for j in jogos for _m, _l, r, _x in j["chutes"] if r == "Goal")
    n_odds = sum(1 for j in jogos if j["lambda_jogo"])
    ligas = sorted({(j["liga"], j["temporada"]) for j in jogos})
    print(f"  ligas/temporadas      : {', '.join(f'{l} {t}' for l, t in ligas)}")
    print(f"  jogos                 : {len(jogos)}")
    print(f"  chutes                : {n_chutes}  ({n_chutes/len(jogos):.1f}/jogo)")
    print(f"  gols                  : {n_gols}  ({n_gols/len(jogos):.2f}/jogo)")
    print(f"  jogos com odds pre    : {n_odds}  ({n_odds/len(jogos)*100:.0f}%)")
    if n_odds:
        lams = sorted(j["lambda_jogo"] for j in jogos if j["lambda_jogo"])
        print(f"  lambda pre-live       : min {lams[0]:.2f} | mediana "
              f"{lams[len(lams)//2]:.2f} | max {lams[-1]:.2f}")

    pm = defaultdict(int)
    for j in jogos:
        for m, _l, r, _x in j["chutes"]:
            if r == "Goal":
                pm[m] += 1
    tot = sum(pm.values())
    print("\n  borda do 1o tempo — fatia dos gols no 1o tempo por corte")
    print("  (o valor de livro e ~45%; LIMITE_HT escolhido = "
          f"{M.LIMITE_HT})")
    for corte in (44, 45, 46, 47):
        pri = sum(v for m, v in pm.items() if m <= corte)
        print(f"    corte {corte}: {pri/tot*100:5.1f}%")
    viz = sum(pm.get(m, 0) for m in (44, 45, 47, 48)) / 4
    print(f"    ANOMALIA: minuto 46 tem {pm.get(46,0)} gols contra "
          f"{viz:.1f} de media nos vizinhos ({pm.get(46,0)/viz:.1f}x)")


def calibragem(mt, jogos, rotulo):
    por_faixa = defaultdict(lambda: [0, 0.0, 0])
    por_celula = defaultdict(lambda: [0, 0.0, 0])
    for j, t, periodo, e, y in observacoes(jogos):
        p = mt.p_under(j, t, periodo, e)
        c = por_faixa[min(int(p * 10), 9)]
        c[0] += 1
        c[1] += p
        c[2] += y
        c2 = por_celula[(periodo, t, mt.chave_placar(e))]
        c2[0] += 1
        c2[1] += p
        c2[2] += y

    linha(f"CALIBRAGEM — {rotulo}")
    print("  faixa de P      n   P media   freq real     erro   odd justa media")
    for fx in sorted(por_faixa):
        n, sp, sy = por_faixa[fx]
        pm_, fr = sp / n, sy / n
        print(f"  {fx/10:.1f}-{fx/10+0.1:.1f}  {n:7d}   {pm_:6.3f}    {fr:6.3f}   "
              f"{fr-pm_:+6.3f}          {1/pm_ if pm_ else 0:6.2f}")

    print("\n  por celula (periodo, minuto, placar) — n>=40")
    print("  per  min  placar             n   P prev   freq real     erro")
    for k in sorted(por_celula):
        n, sp, sy = por_celula[k]
        if n < 40:
            continue
        pm_, fr = sp / n, sy / n
        print(f"  {k[0]:3s} {k[1]:4d}  {k[2]:16s} {n:5d}   {pm_:6.3f}   "
              f"{fr:6.3f}   {fr-pm_:+6.3f}")


def significancia(mt, teste, n_amostras=4000, semente=7):
    """O ganho sobre o baseline se distingue de zero? Bootstrap POR JOGO,
    porque minutos do mesmo jogo sao correlacionados."""
    plano = M.Motor(mt.perfis, mt.lambda_medio, peso_xg=0.0)
    por_jogo = defaultdict(list)
    for j, t, periodo, e, y in observacoes(teste):
        a = (mt.p_under(j, t, periodo, e) - y) ** 2
        b = (plano.p_under(dict(j, lambda_jogo=None), t, periodo, e,
                           usar_placar=False) - y) ** 2
        por_jogo[j["id"]].append(a - b)

    ids = list(por_jogo)

    def media(sel):
        v = [d for i in sel for d in por_jogo[i]]
        return sum(v) / len(v)

    obs = media(ids)
    random.seed(semente)
    bs = sorted(media([random.choice(ids) for _ in ids]) for _ in range(n_amostras))
    lo, hi = bs[int(0.025 * len(bs))], bs[int(0.975 * len(bs))]

    linha("O GANHO SOBRE O BASELINE SE DISTINGUE DE ZERO?")
    n_obs = sum(len(v) for v in por_jogo.values())
    print(f"  teste: {len(ids)} jogos, {n_obs} observacoes")
    print(f"  diferenca media de Brier (modelo - Poisson plano): {obs:+.5f}")
    print(f"  IC95% bootstrap por jogo: [{lo:+.5f}, {hi:+.5f}]")
    if hi < 0:
        print("  -> o modelo e melhor, e a diferenca e distinguivel de zero")
    elif lo > 0:
        print("  -> o modelo e PIOR, e a diferenca e distinguivel de zero")
    else:
        print("  -> NAO distinguivel de zero: esta amostra nao sustenta a "
              "afirmacao\n     de que o condicionamento por estado bate o "
              "baseline.")


def exemplo(mt, jogos):
    linha("EXEMPLO DE USO — odd justa num jogo concreto")
    j = max(jogos, key=lambda x: len(x["chutes"]))
    print(f"  {j['data'][:10]}  {j['casa']} x {j['fora']}   final "
          f"{j['gols_casa']}-{j['gols_fora']}   lambda pre-live "
          f"{j['lambda_jogo']:.2f}")
    print("\n  per  min  placar  chutes  alvo     xG   odd justa   odd minima"
          "   saiu gol?")
    for periodo, minutos in (("ht", MINUTOS_HT), ("ft", MINUTOS_FT)):
        for t in minutos:
            y = M.under_bateu(j, t, periodo)
            if y is None:
                continue
            e = M.estado_em(j, t)
            print(f"  {periodo:3s} {t:4d}   {e['gols_c']}-{e['gols_f']}   "
                  f"{e['chutes_total']:5d}  {e['alvo_total']:4d}  "
                  f"{e['xg_total']:6.2f}      "
                  f"{mt.odd_justa(j,t,periodo,estado=e):6.2f}       "
                  f"{mt.odd_minima(j,t,periodo,estado=e):6.2f}      "
                  f"{'nao' if y else 'SIM'}")


def main():
    con = sqlite3.connect(M.DB)
    jogos = M.carrega(con)
    con.close()
    if not jogos:
        raise SystemExit("banco vazio — rode coletar_understat.py")

    diagnostico(jogos)

    treino, teste = divide(jogos)
    mt, info = M.treina(treino, MINUTOS_HT, MINUTOS_FT, PESO_XG, PRIOR_XG)

    linha("EFEITO DE PLACAR CALIBRADO EM P(zero gols)   (>1 = sai mais gol)")
    for k in sorted(info["efeito_placar"]):
        print(f"  {k[0]:3s} {k[1]:16s} : x{info['efeito_placar'][k]:.3f}  "
              f"(n={info['n_por_estado'].get(k,0)})")
    for k in sorted(k for k in info["n_por_estado"]
                    if k not in info["efeito_placar"]):
        print(f"  {k[0]:3s} {k[1]:16s} : n insuficiente "
              f"({info['n_por_estado'][k]}) -> x1,000")

    calibragem(mt, teste, f"FORA da amostra (treino {len(treino)}, "
                          f"teste {len(teste)})")
    significancia(mt, teste)
    exemplo(mt, jogos)


if __name__ == "__main__":
    main()
