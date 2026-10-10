# -*- coding: utf-8 -*-
"""Motor 1 — empirico. Nao tem funcao nem suposicao: conta o que aconteceu.

Pergunta que responde: "jogos historicos que estavam EXATAMENTE nesta
situacao — mesmo minuto, mesmo placar em relacao ao favorito, favoritismo
parecido — em quantos % o placar NAO mudou ate o fim do periodo?"
Isso e a taxa de acerto do under limite (linha = placar + 0,5).

Implementacao de referencia. web/motor1.js espelha esta logica linha a
linha, e testes/test_paridade.py confere que as duas dao o mesmo numero.

CONVENCOES (precisam ser identicas nas duas implementacoes):

* Minuto. O Fut Odds mostra o minuto em andamento, 1-indexado ("28'" =
  entre 27:00 e 28:00 jogados). O Understat rotula 0-indexado. O instante da
  consulta e t = M - 1: so conta como passado o que tem rotulo < t, e o
  minuto em andamento conta como FUTURO. E conservador para o under: um gol
  que pode ter saido agora entra como risco, nao como fato.
* Tempo. M <= 45 e 1o tempo; M >= 46 e 2o tempo (t = M - 1, o 2o tempo
  do Understat comeca no rotulo 45); 'HT' e o inicio do 2o tempo (t = 45,
  tudo do 1o tempo e passado). Os gols de acrescimo do 1o tempo tem
  tempo = 1 mesmo rotulados 46+ (corrigido pelo placar oficial do intervalo).
* Favorito. O lado com maior probabilidade 1X2 SEM margem (empate -> casa).
  O placar e sempre lido como (gols do favorito, gols da zebra).

ESCADA DE RELAXAMENTO. Minuto e placar relativo sao sempre exatos. Os
demais filtros entram do mais especifico para o mais largo, e vale o
primeiro degrau com n >= N_MIN. A resposta diz qual degrau foi usado.
"""
import json
import math
import os

DIR = os.path.dirname(os.path.abspath(__file__))
JSON_PADRAO = os.path.join(DIR, "web", "linha_do_tempo.json")

N_MIN = 100
Z = 1.96

# (janela_fav, janela_over, usa_alvo, usa_chutes)
# janelas em probabilidade sem margem; None = filtro desligado. Degrau cujo
# filtro nao pode ser aplicado (o Scanner nao trouxe o dado) vira copia do
# seguinte e e pulado; o rotulo sai dos filtros EFETIVAMENTE aplicados.
ESCADA = [
    (0.03, 0.04, True, True),
    (0.03, 0.04, True, False),
    (0.03, 0.04, False, False),
    (0.05, 0.07, False, False),
    (0.05, None, False, False),
    (0.08, None, False, False),
    (0.12, None, False, False),
    (None, None, False, False),
]


def rotulo(jf, jo, usa_a, usa_c):
    partes = []
    if jf is not None:
        partes.append(("fav ±%.2f" % jf).replace(".", ","))
    if jo is not None:
        partes.append(("O/U ±%.2f" % jo).replace(".", ","))
    if usa_a:
        partes.append("no alvo")
    if usa_c:
        partes.append("chutes")
    return " · ".join(partes) or "só minuto e placar"

# campos do Scanner que existem no Fut Odds mas nao no historico
SEM_BASE = {
    "xg": "xG do Fut Odds e de outro modelo que o do historico",
    "xgs": "sem equivalente no historico",
    "pi1": "sem equivalente no historico", "pi2": "sem equivalente no historico",
    "pi3": "sem equivalente no historico",
    "appm": "sem equivalente no historico", "appm10": "sem equivalente no historico",
    "cg": "sem equivalente no historico", "cg10": "sem equivalente no historico",
    "canto": "historico so tem o total do jogo, sem minuto",
    "ataq": "sem equivalente no historico", "aper": "sem equivalente no historico",
    "poss": "historico so tem agregado final",
    "amar": "historico sem cartoes", "h2h": "sem equivalente no historico",
}


def decodifica(cod):
    """-> (tempo, minuto, tipo, lado)"""
    tempo = cod // 10000
    resto = cod % 10000
    return tempo, resto // 10, (resto % 10) // 2, resto % 2


def tolerancia(x):
    # arredondamento explicito: o round() do Python e bancario (2,5 -> 2) e o
    # Math.round do JS nao (2,5 -> 3); as duas versoes precisam bater
    return max(1, int(math.floor(0.25 * x + 0.5)))


def wilson(v, n):
    if n == 0:
        return (0.0, 1.0)
    p = v / n
    den = 1 + Z * Z / n
    centro = (p + Z * Z / (2 * n)) / den
    meia = Z * math.sqrt(p * (1 - p) / n + Z * Z / (4 * n * n)) / den
    return (max(0.0, centro - meia), min(1.0, centro + meia))


def sem_margem(*odds):
    inv = [1 / o for o in odds]
    s = sum(inv)
    return [x / s for x in inv]


def soma(par):
    if not par:
        return None
    a, b = par
    if a is None and b is None:
        return None
    return (a or 0) + (b or 0)


def preenchido(v):
    """Campo do Scanner com algum valor (par casa/fora ou escalar)."""
    if isinstance(v, (list, tuple)):
        return soma(v) is not None
    return v is not None


def instante(jogo):
    """(tempo_atual, t) a partir do que o Scanner leu."""
    if jogo.get("noIntervalo"):
        return 2, 45
    m = int(jogo.get("minuto") or 0)
    if m <= 45:
        return 1, max(0, m - 1)
    return 2, m - 1


class Motor1:
    def __init__(self, caminho=JSON_PADRAO, doc=None):
        if doc is None:
            with open(caminho, encoding="utf-8") as f:
                doc = json.load(f)
        self.ligas = doc["ligas"]
        self.jogos = []
        for liga, temp, pc, pe, pf, po, evs in doc["jogos"]:
            fav = 0 if pc >= pf else 1
            self.jogos.append({
                "liga": liga, "temporada": temp,
                "fav": fav, "pfav": max(pc, pf) / 1000,
                "po": po / 1000 if po >= 0 else None,
                "ev": [decodifica(c) for c in evs],
            })

    # ------------------------------------------------------------------
    @staticmethod
    def estado(ev, tempo_atual, t):
        """Placar, chutes e gols futuros de um jogo historico no instante."""
        gols = [0, 0]
        alvo = chutes = 0
        fut_ht = fut_ft = 0
        for tempo, minuto, tipo, lado in ev:
            passado = tempo < tempo_atual or (tempo == tempo_atual and minuto < t)
            eh_gol = tipo == 0 or tipo == 3
            if passado:
                if eh_gol:
                    gols[lado] += 1
                if tipo <= 1:
                    alvo += 1
                if tipo <= 2:
                    chutes += 1
            elif eh_gol:
                fut_ft += 1
                if tempo == 1:
                    fut_ht += 1
        return gols, alvo, chutes, fut_ht, fut_ft

    # ------------------------------------------------------------------
    def consulta(self, jogo, periodo, n_min=N_MIN):
        """jogo: dict no formato do scanParse do site (golsC, golsF, minuto,
        noIntervalo, ocasa/oempa/ofora, ov25/un25, cag/chut/verm como pares).
        periodo: 'ht' | 'ft'."""
        tempo_atual, t = instante(jogo)
        if periodo == "ht" and tempo_atual != 1:
            return {"ok": False, "motivo": "1o tempo ja terminou"}

        avisos, ignorados = [], []
        oc, oe, of_ = jogo.get("ocasa"), jogo.get("oempa"), jogo.get("ofora")
        if oc and oe and of_ and min(oc, oe, of_) > 1:
            pc, _pe, pf = sem_margem(oc, oe, of_)
            fav_vivo = 0 if pc >= pf else 1
            pfav_vivo = max(pc, pf)
        else:
            fav_vivo, pfav_vivo = 0, None
            avisos.append("sem odds 1X2: placar lido como casa x fora e "
                          "sem filtro de favoritismo")

        ov, un = jogo.get("ov25"), jogo.get("un25")
        po_vivo = sem_margem(ov, un)[0] if (ov and un and ov > 1 and un > 1) else None

        gols_vivo = [int(jogo.get("golsC") or 0), int(jogo.get("golsF") or 0)]
        gf_vivo, gz_vivo = gols_vivo[fav_vivo], gols_vivo[1 - fav_vivo]
        alvo_vivo = soma(jogo.get("cag"))
        chutes_vivo = soma(jogo.get("chut"))

        verm = soma(jogo.get("verm"))
        if verm:
            avisos.append("expulsao no jogo: o historico nao tem cartoes, a "
                          "taxa NAO considera a expulsao")
        for campo, motivo in SEM_BASE.items():
            if preenchido(jogo.get(campo)):
                ignorados.append(f"{campo}: {motivo}")

        # uma passada: so os jogos com o mesmo placar relativo no instante
        cands = []
        for jh in self.jogos:
            gols, alvo, chutes, fut_ht, fut_ft = self.estado(jh["ev"], tempo_atual, t)
            fav = jh["fav"] if pfav_vivo is not None else 0
            if gols[fav] != gf_vivo or gols[1 - fav] != gz_vivo:
                continue
            futuro = fut_ht if periodo == "ht" else fut_ft
            cands.append((jh["pfav"], jh["po"], alvo, chutes, futuro))

        escolha = None
        vistos = set()
        for nivel, (jf, jo, ua, uc) in enumerate(ESCADA):
            if pfav_vivo is None and jf is not None:
                continue
            jo_ef = jo if (jo is not None and po_vivo is not None) else None
            usa_a = ua and alvo_vivo is not None
            usa_c = uc and chutes_vivo is not None
            assin = (jf, jo_ef, usa_a, usa_c)
            if assin in vistos:
                continue
            vistos.add(assin)
            rot = rotulo(*assin)
            sel = []
            for pfav, po, alvo, chutes, futuro in cands:
                if jf is not None and abs(pfav - pfav_vivo) > jf + 1e-9:
                    continue
                if jo_ef is not None and (po is None or abs(po - po_vivo) > jo_ef + 1e-9):
                    continue
                if usa_a and abs(alvo - alvo_vivo) > tolerancia(alvo_vivo):
                    continue
                if usa_c and abs(chutes - chutes_vivo) > tolerancia(chutes_vivo):
                    continue
                sel.append(futuro)
            escolha = (nivel, rot, sel)
            if len(sel) >= n_min:
                break

        nivel, rot, sel = escolha
        n = len(sel)
        v = sum(1 for x in sel if x == 0)
        p = v / n if n else None
        if n < n_min:
            avisos.append(f"amostra fina: n={n} mesmo no degrau mais largo")
        return {
            "ok": n > 0,
            "periodo": periodo,
            "instante": [tempo_atual, t],
            "placar_rel": [gf_vivo, gz_vivo],
            "fav": None if pfav_vivo is None else
                   {"lado": "casa" if fav_vivo == 0 else "fora",
                    "p": round(pfav_vivo, 4), "odd_justa": round(1 / pfav_vivo, 3)},
            "p": p, "n": n, "green": v,
            "ic95": list(wilson(v, n)) if n else None,
            "justa": (1 / p) if p else None,
            "nivel": nivel, "filtros": rot,
            "dist": {"0": v, "1": sum(1 for x in sel if x == 1),
                     "2+": sum(1 for x in sel if x >= 2)},
            "avisos": avisos, "ignorados": ignorados,
        }


if __name__ == "__main__":
    import sys
    m = Motor1()
    exemplo = {"golsC": 1, "golsF": 1, "minuto": 26, "noIntervalo": False,
               "ocasa": 1.50, "oempa": 4.20, "ofora": 6.50,
               "ov25": 1.65, "un25": 2.25}
    r = m.consulta(exemplo, sys.argv[1] if len(sys.argv) > 1 else "ht")
    print(json.dumps(r, ensure_ascii=False, indent=1))
