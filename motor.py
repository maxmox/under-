# -*- coding: utf-8 -*-
"""Motor de odd justa do under limite (HT e FT) minuto a minuto.

Mercado: "nao sai mais nenhum gol ate o fim do periodo".

Poisson nao-homogeneo:
    P(sem mais gol) = exp(-Lambda_resto)
    Lambda_resto = lambda_jogo * fracao_do_perfil(t, fim) * aj_xg * aj_placar

Perfil, perfil de xG e efeito de placar sao ESTIMADOS da amostra.

NOTAS DE DADO (medidas em EPL 2024, ver avaliar.py):
  * o minuto do Understat e 0-indexado: o minuto 0 e o 1o minuto de jogo,
    e o maximo observado e 103.
  * o minuto 46 carrega uma anomalia de 3x (30 gols contra ~10 nos vizinhos).
    Cortando o 1o tempo em 45 a fatia de gols do 1o tempo da 44,5%; cortando
    em 46 da 47,3%. O valor de livro e ~45%, logo o 46 pertence ao 2o tempo
    e LIMITE_HT = 45. O mecanismo da anomalia nao foi resolvido: se parte dela
    for acrescimo do 1o tempo rotulado como 46, o under HT parece ganhar um
    pouco mais do que ganha na realidade.
"""
import math
import os
import sqlite3
from collections import defaultdict

DIR = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(DIR, "futebol.db")

LIMITE_HT = 45
MAX_FT = 103
NO_ALVO = {"Goal", "SavedShot"}


# ---------------------------------------------------------------- estado

def carrega(con):
    """Jogos com seus chutes ordenados por minuto."""
    jogos = {}
    q = """SELECT j.id, j.data, j.casa, j.fora, j.liga, j.temporada,
                  j.gols_casa, j.gols_fora,
                  o.lambda_jogo, o.ocf, o.oef, o.off_, o.o25f, o.u25f
           FROM jogo j LEFT JOIN odds_pre o ON o.jogo_id = j.id"""
    for r in con.execute(q):
        jogos[r[0]] = {
            "id": r[0], "data": r[1], "casa": r[2], "fora": r[3],
            "liga": r[4], "temporada": r[5],
            "gols_casa": r[6], "gols_fora": r[7],
            "lambda_jogo": r[8],
            "odds_1x2": (r[9], r[10], r[11]), "odds_25": (r[12], r[13]),
            "chutes": [],
        }
    for jid, minuto, lado, res, xg in con.execute(
            "SELECT jogo_id, minuto, lado, resultado, xg FROM chute "
            "ORDER BY jogo_id, minuto"):
        if jid in jogos:
            jogos[jid]["chutes"].append((minuto, lado, res, xg or 0.0))
    return list(jogos.values())


def estado_em(jogo, t):
    """Tudo o que se sabe do jogo ao fim do minuto t, e nada depois."""
    e = {"gols_c": 0, "gols_f": 0, "chutes_c": 0, "chutes_f": 0,
         "alvo_c": 0, "alvo_f": 0, "xg_c": 0.0, "xg_f": 0.0}
    for minuto, lado, res, xg in jogo["chutes"]:
        if minuto > t:
            break
        s = "c" if lado == "h" else "f"
        e["chutes_" + s] += 1
        e["xg_" + s] += xg
        if res in NO_ALVO:
            e["alvo_" + s] += 1
        if res == "Goal":
            e["gols_" + s] += 1
    e["placar"] = (e["gols_c"], e["gols_f"])
    e["xg_total"] = e["xg_c"] + e["xg_f"]
    e["chutes_total"] = e["chutes_c"] + e["chutes_f"]
    e["alvo_total"] = e["alvo_c"] + e["alvo_f"]
    e["dif"] = e["gols_c"] - e["gols_f"]
    return e


def fim_do_periodo(periodo):
    return LIMITE_HT if periodo == "ht" else MAX_FT


def gols_no_resto(jogo, t, periodo):
    fim = fim_do_periodo(periodo)
    return sum(1 for m, _l, r, _x in jogo["chutes"]
               if r == "Goal" and t < m <= fim)


def under_bateu(jogo, t, periodo):
    """1 = nao saiu mais gol (win do under). None = fora do horizonte."""
    if t >= fim_do_periodo(periodo):
        return None
    return 1 if gols_no_resto(jogo, t, periodo) == 0 else 0


# ---------------------------------------------------------------- perfis

def _suaviza_acumula(bruto, janela=4):
    suave = []
    for m in range(len(bruto)):
        lo, hi = max(0, m - janela), min(len(bruto) - 1, m + janela)
        jan = bruto[lo:hi + 1]
        suave.append(sum(jan) / len(jan))
    s = sum(suave) or 1.0
    perfil = [x / s for x in suave]
    acum, c = [], 0.0
    for p in perfil:
        c += p
        acum.append(c)
    return perfil, acum


def ajusta_perfis(jogos):
    """Dois perfis medidos na amostra, ambos normalizados para somar 1:
       - gols: fracao dos gols do jogo que cai em cada minuto
       - xg:   fracao do xG do jogo que cai em cada minuto
    Mais as duas escalas medias, necessarias para o ajuste de xG nao ter
    descasamento de escala (o xG medio do Understat, 3,25/jogo, nao e o mesmo
    numero que o lambda implicito nas odds, 3,06/jogo)."""
    g = [0] * (MAX_FT + 1)
    x = [0.0] * (MAX_FT + 1)
    n_gols = 0
    for j in jogos:
        for minuto, _l, res, xg in j["chutes"]:
            m = min(max(int(minuto), 0), MAX_FT)
            x[m] += xg
            if res == "Goal":
                g[m] += 1
                n_gols += 1
    if not n_gols:
        raise SystemExit("sem gols na amostra")
    perfil_g, acum_g = _suaviza_acumula(g)
    _perfil_x, acum_x = _suaviza_acumula(x)
    xg_medio = sum(x) / len(jogos)
    return {"acum_gols": acum_g, "perfil_gols": perfil_g,
            "acum_xg": acum_x, "xg_medio": xg_medio, "n_gols": n_gols}


def fracao_janela(acum, t, periodo):
    fim = fim_do_periodo(periodo)
    if t >= fim:
        return 0.0
    return max(acum[fim] - acum[min(t, MAX_FT)], 1e-9)


# ------------------------------------------------------------- o modelo

class Motor:
    def __init__(self, perfis, lambda_medio, efeito_placar=None,
                 peso_xg=0.5, prior_xg=1.2, comissao=0.065):
        self.perfis = perfis
        self.acum = perfis["acum_gols"]
        self.acum_xg = perfis["acum_xg"]
        self.xg_medio = perfis["xg_medio"]
        self.lambda_medio = lambda_medio
        self.efeito_placar = efeito_placar or {}
        self.peso_xg = peso_xg
        self.prior_xg = prior_xg
        self.comissao = comissao

    @staticmethod
    def chave_placar(e):
        """Estados de placar que importam: total de gols e diferenca."""
        tot = e["gols_c"] + e["gols_f"]
        if tot == 0:
            return "0x0"
        d = abs(e["dif"])
        if d == 0:
            return "empate_com_gol"
        if d == 1:
            return "dif1"
        return "dif2+"

    def razao_xg(self, jogo, t, e):
        """Quanto perigo o jogo gerou ate t, contra o que se esperava dele.
        A referencia e a escala do PROPRIO xG da amostra, escalada pelo
        favoritismo/perfil do jogo (lambda_jogo / lambda_medio)."""
        lam_jogo = jogo.get("lambda_jogo") or self.lambda_medio
        esperado = (self.xg_medio * (lam_jogo / self.lambda_medio)
                    * self.acum_xg[min(t, MAX_FT)])
        return (e["xg_total"] + self.prior_xg) / (esperado + self.prior_xg)

    def lambda_resto(self, jogo, t, periodo, estado=None,
                     usar_xg=True, usar_placar=True):
        e = estado if estado is not None else estado_em(jogo, t)
        lam_jogo = jogo.get("lambda_jogo") or self.lambda_medio
        base = lam_jogo * fracao_janela(self.acum, t, periodo)
        if usar_xg and self.peso_xg:
            base *= self.razao_xg(jogo, t, e) ** self.peso_xg
        if usar_placar:
            base *= self.efeito_placar.get((periodo, self.chave_placar(e)), 1.0)
        return max(base, 1e-9)

    def p_under(self, jogo, t, periodo, estado=None, **kw):
        return math.exp(-self.lambda_resto(jogo, t, periodo, estado, **kw))

    def odd_justa(self, jogo, t, periodo, **kw):
        p = self.p_under(jogo, t, periodo, **kw)
        return 1 / p if p > 0 else float("inf")

    def odd_minima(self, jogo, t, periodo, **kw):
        """Odd que zera o EV com a comissao da exchange descontada."""
        p = self.p_under(jogo, t, periodo, **kw)
        if p <= 0:
            return float("inf")
        return 1 + (1 - p) / (p * (1 - self.comissao))


# -------------------------------------------------- calibragem do placar

def calibra_placar(jogos, motor, minutos_ht, minutos_ft, min_n=100):
    """Multiplicador por estado de placar que faz a MEDIA DE P(zero gols)
    bater com a frequencia observada de under.

    Calibrar pela media de gols (obs/previsto) seria errado: a grandeza de
    interesse e exp(-lambda), e exp e convexa, entao acertar a media de
    lambda deixa a media de P alta demais. Resolve-se por bisseccao em m:
        media_i exp(-m * lambda_i) = taxa_observada
    """
    grupos = defaultdict(lambda: {"lams": [], "y": []})
    for j in jogos:
        for periodo, minutos in (("ht", minutos_ht), ("ft", minutos_ft)):
            fim = fim_do_periodo(periodo)
            for t in minutos:
                if t >= fim:
                    continue
                e = estado_em(j, t)
                k = (periodo, motor.chave_placar(e))
                g = grupos[k]
                g["lams"].append(
                    motor.lambda_resto(j, t, periodo, e, usar_placar=False))
                g["y"].append(1 if gols_no_resto(j, t, periodo) == 0 else 0)

    efeito, enes = {}, {}
    for k, g in grupos.items():
        n = len(g["y"])
        enes[k] = n
        if n < min_n:
            continue
        alvo = sum(g["y"]) / n
        lams = g["lams"]

        def media_p(m):
            return sum(math.exp(-m * l) for l in lams) / n

        # media_p e decrescente em m; procura m com media_p(m) = alvo
        lo, hi = 1e-4, 20.0
        if media_p(hi) > alvo:
            efeito[k] = round(hi, 4)
            continue
        if media_p(lo) < alvo:
            efeito[k] = round(lo, 4)
            continue
        for _ in range(80):
            mid = (lo + hi) / 2
            if media_p(mid) > alvo:
                lo = mid
            else:
                hi = mid
        efeito[k] = round((lo + hi) / 2, 4)
    return efeito, enes


def treina(jogos, minutos_ht=(15, 25, 35, 42), minutos_ft=(60, 70, 80, 85),
           peso_xg=0.5, prior_xg=1.2, iteracoes=3):
    """Ajusta perfis e efeito de placar SO nos jogos passados."""
    perfis = ajusta_perfis(jogos)
    lams = [j["lambda_jogo"] for j in jogos if j["lambda_jogo"]]
    if lams:
        lam_medio = sum(lams) / len(lams)
    else:
        lam_medio = sum(j["gols_casa"] + j["gols_fora"] for j in jogos) / len(jogos)
    mt = Motor(perfis, lam_medio, peso_xg=peso_xg, prior_xg=prior_xg)
    ef, enes = {}, {}
    for _ in range(iteracoes):
        ef, enes = calibra_placar(jogos, mt, minutos_ht, minutos_ft)
        mt = Motor(perfis, lam_medio, ef, peso_xg=peso_xg, prior_xg=prior_xg)
    return mt, {"lambda_medio": lam_medio, "efeito_placar": ef,
                "n_por_estado": enes, "n_gols": perfis["n_gols"],
                "xg_medio": perfis["xg_medio"]}


def constroi(con=None, **kw):
    fechar = con is None
    con = con or sqlite3.connect(DB)
    jogos = carrega(con)
    mt, info = treina(jogos, **kw)
    if fechar:
        con.close()
    return jogos, mt, info
