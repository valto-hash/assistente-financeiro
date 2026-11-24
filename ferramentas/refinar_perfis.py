"""Rodada 3: refinar a carteira de cada perfil até ela ficar "quase perfeita". Registrado antes de rodar (24/11/2026).
Só dados reais, nos dois testes do app (simulador mês a mês e corretora simulada dia a dia, com custos e imposto).

O QUE É "QUASE PERFEITA" (as quatro condições ao mesmo tempo):
(1) respeita o limite de queda do perfil nas três medidas (dia a dia, mês a mês e pior crise real);
(2) termina com mais dinheiro que todas as estratégias do app que cabem no perfil, nos dois testes;
(3) nenhuma carteira vizinha é claramente melhor. "Claramente melhor" = também respeita o limite e, ao mesmo tempo:
    retorno na corretora em 2013-2019 maior por 0,3 ponto ou mais; retorno em 2020-hoje não menor, nos dois testes;
    patrimônio final maior, nos dois testes;
(4) é robusta: em janelas de 5 anos começando a cada 3 meses de 2013 a 2021 (simulador mês a mês, R$ 10 mil + R$ 1.000
    por mês), rende mais que o CDI em pelo menos 2 de cada 3 janelas e não passa do limite de queda em nenhuma.

PROCESSO: parte da carteira atual de cada perfil (a versão só com ETFs e títulos). Se alguma vizinha for claramente
melhor (3), a de maior retorno em 2013-2019 vira a atual e a busca recomeça em volta dela (no máximo 4 voltas). Quando
nenhuma for, confere (1), (2) e (4). Depois, a escolha de ações individuais é refeita com a regra da etapa 2, versão 2.

VIZINHAS: renda fixa da atual ±5 e ±10 pontos (entre 15% e 95%); divisão da renda fixa: pós (Selic 70%, LCI 30%),
padrão (Selic 30%, LCI 15%, IPCA+ 55%), inflação (Selic 15%, IPCA+ 85%), meio a meio (Selic 50%, IPCA+ 50%); parte de
risco (ações, FIIs, exterior, dólar e ouro): global (25/0/45/30), mais exterior (20/0/55/25), mais Brasil (35/0/40/25),
mais proteção (25/0/40/35), com FIIs (20/10/40/30), menos câmbio (30/0/50/20); dólar e ouro: metade cada, só ouro, ou um
terço dólar e dois terços ouro.

RODADA 3 (24/11/2026, ferramentas/rodada3_resultado.txt): sem a faixa de renda fixa da rodada 1, a busca levou moderado
e arrojado à MESMA carteira (15% de renda fixa, 85% em risco, quase metade no S&P 500) e o conservador a 60% de renda
fixa. Isso é o teste "ganhando no passado": de 2013 a 2026 o dólar e o ouro subiram justamente nas crises brasileiras e
seguraram as quedas; numa crise em que o real não se desvalorize, 85% em risco cairia bem mais do que o moderado aceita.
E dois perfis não podem ter a mesma carteira. Não foi aplicada.

RODADA 4 (registrada antes de rodar): cada perfil passa a ter também uma renda fixa mínima, que entra na definição do
perfil: conservador 70%, moderado 40%, arrojado 15% (as faixas da rodada 1 para conservador e moderado; o piso da rodada 3
para o arrojado). Mesmo processo e mesmos critérios da rodada 3, partindo das carteiras de 24/11. Como informação, mostra
também a pior crise real se o real não tivesse se desvalorizado (S&P 500 e ouro em dólar, dólar parado).

Uso, na raiz do repositório: python3 ferramentas/refinar_perfis.py [3|4]  (precisa de internet)
"""
import itertools, json, os, sys, tempfile, time
os.environ["DATA_DIR"] = tempfile.mkdtemp(); os.environ["APP_TOKEN"] = ""
os.environ.pop("ANTHROPIC_API_KEY", None)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import multiprocessing as mp
import numpy as np
import pandas as pd
import server, referencias, corretora as C, simulador as S, simulacao as sim  # noqa: E402

RF_DIV = {"pos": {"TESOURO_SELIC": .7, "LCI_LCA": .3}, "padrao": {"TESOURO_SELIC": .3, "LCI_LCA": .15, "TESOURO_IPCA": .55},
          "inflacao": {"TESOURO_SELIC": .15, "TESOURO_IPCA": .85}, "meio": {"TESOURO_SELIC": .5, "TESOURO_IPCA": .5}}
MIX = {"global": (.25, 0, .45, .30), "mais_exterior": (.20, 0, .55, .25), "mais_brasil": (.35, 0, .40, .25),
       "mais_protecao": (.25, 0, .40, .35), "com_fiis": (.20, .10, .40, .30), "menos_cambio": (.30, 0, .50, .20)}
CAMBIO = {"meio": {"DOLAR": .5, "GOLD11": .5}, "ouro": {"GOLD11": 1.0}, "dois_tercos_ouro": {"DOLAR": 1 / 3, "GOLD11": 2 / 3}}
NUC = {"acao": {"BOVA11": .6, "DIVO11": .4}, "fii": {"KNCR11": .5, "HGLG11": .5}, "exterior": {"IVVB11": 1.0}}
INICIO = {"conservador": (70, "pos", "global", "meio"), "moderado": (40, "inflacao", "global", "meio"),
          "arrojado": (20, "inflacao", "global", "meio")}   # as carteiras de 24/11 (rodada 1)
MARGEM, VOLTAS = 0.3, 4
RF_MIN = {3: {"conservador": 15, "moderado": 15, "arrojado": 15}, 4: {"conservador": 70, "moderado": 40, "arrojado": 15}}
RODADA = 4
D = PM = DM = None


def pesos(rf, div, mix, camb):
    w = {}
    for a, f in RF_DIV[div].items():
        w[a] = w.get(a, 0) + rf * f
    r, mx = 100 - rf, MIX[mix]
    for c, x in zip(("acao", "fii", "exterior"), mx[:3]):
        for a, f in NUC[c].items():
            w[a] = w.get(a, 0) + r * x * f
    for a, f in CAMBIO[camb].items():
        w[a] = w.get(a, 0) + r * mx[3] * f
    return {a: round(v, 4) for a, v in w.items() if v > 1e-9}


def classes(w):
    cl = dict.fromkeys(("renda_fixa", "acao", "fii", "exterior", "cambio"), 0.0)
    for a, v in w.items():
        cl[server.UNIVERSO[a][0]] += v
    return {c: round(v, 2) for c, v in cl.items()}


def preparar():
    global D, PM, DM
    D = S.preparar()
    planos = {p["id"]: S.pesos_plano(p["pesos"]) for p in referencias.PLANOS}
    ativos = sorted(set(server.UNIVERSO) | {a for w in planos.values() for a in w} | {"LCI_LCA", "DOLAR", "GOLD11"})
    PM, DM = C.precos([a for a in ativos if a == "DOLAR" or a in server.RF or a in D["ret"]], D["meses"][0])
    return planos


def avaliar(args):
    k, w = args
    cor = C.rodar(D, PM, DM, lambda t, h, w=w: w)
    sim = S._resumo(k, S._rodar(D, lambda t, h, w=w: w, S.INICIAL, S.MENSAL))
    return k, {"corretora": {x: cor[x] for x in ("final", "metade1_aa", "metade2_aa", "maior_queda")},
               "simulador": {x: sim[x] for x in ("final", "metade1_aa", "metade2_aa", "maior_queda")}}


def vizinhas(p, atual):
    rf0 = atual[0]
    niveis = sorted({min(max(rf0 + d, RF_MIN[RODADA][p]), 95) for d in (-10, -5, 0, 5, 10)})
    return [(rf, div, mix, camb) for rf, div, mix, camb in itertools.product(niveis, RF_DIV, MIX, CAMBIO)
            if not (MIX[mix][3] == 0 and camb != "meio")]


def janelas(w, anos=5, passo=3, decidir=None):
    """Janelas de `anos` anos, começando a cada `passo` meses: retorno ao ano (tempo) e maior queda de cada uma."""
    meses = list(D["meses"])
    out = []
    for i in range(0, len(meses) - anos * 12, passo):
        dd = {**D, "meses": pd.DatetimeIndex(meses[i:i + anos * 12 + 1])}
        x = S._rodar(dd, decidir or (lambda t, h, w=w: w), S.INICIAL, S.MENSAL)
        r = np.array(x["rets"]); idx = np.cumprod(1 + r)
        out.append({"inicio": meses[i].strftime("%m/%Y"), "aa": (float(idx[-1]) ** (12 / len(r)) - 1) * 100,
                    "queda": float((idx / np.maximum.accumulate(np.concatenate([[1.0], idx]))[1:] - 1).min()) * 100})
    return out


def crise_sem_cambio(w):
    """A pior crise real se o real não tivesse se desvalorizado: exterior e ouro pela variação em dólar, dólar parado."""
    sim.baixar(["IBOV", "SP500", "OURO", "IPCA_LONGO", *sim.FII_CESTA])
    serie = lambda c: sim._hist[c][1]
    def var(c, ini, fim):
        s_ = serie(c)
        a, b = s_.asof(pd.Timestamp(ini)), s_.asof(pd.Timestamp(fim))
        return float(b / a - 1) if a == a and b == b and a > 0 else None
    pior = None
    for nome, ini, fim, cdi in sim.CRISES:
        dias = (pd.Timestamp(fim) - pd.Timestamp(ini)).days
        rf = (1 + cdi / 100) ** (dias / 365) - 1
        fii = np.nanmean([x for x in (var(c, ini, fim) for c in sim.FII_CESTA) if x is not None] or [np.nan])
        r_ = {"acao": var("IBOV", ini, fim), "exterior": var("SP500", ini, fim), "ouro": var("OURO", ini, fim), "ipca": var("IPCA_LONGO", ini, fim)}
        tot = 0.0
        for a, p_ in w.items():
            c = server.UNIVERSO[a][0]
            x = (rf if a in ("TESOURO_SELIC", "LCI_LCA", "CDB_CDI") else r_["ipca"] if a == "TESOURO_IPCA" else 0.0 if a == "DOLAR"
                 else r_["ouro"] if a == "GOLD11" else r_["exterior"] if c == "exterior" else fii if c == "fii" else r_["acao"])
            tot += p_ / 100 * (x if x is not None and x == x else 0.0)
        if pior is None or tot < pior[1]:
            pior = (nome, round(float(tot) * 100, 1))
    return pior


def main():
    t0 = time.time()
    planos = preparar()
    crises_cache = {}
    atual = dict(INICIO)
    historico = {p: [] for p in atual}
    with mp.get_context("fork").Pool(4) as pool:
        for volta in range(1, VOLTAS + 1):
            cands = {}
            for p, a in atual.items():
                for v in vizinhas(p, a):
                    cands[(p, v)] = pesos(*v)
            novas = {k: w for k, w in cands.items() if k not in crises_cache}
            if novas:
                cr = server._crises({f"{k[0]}|{'|'.join(map(str, k[1]))}": w for k, w in novas.items()})
                res = dict(pool.map(avaliar, [(f"{k[0]}|{'|'.join(map(str, k[1]))}", w) for k, w in novas.items()], chunksize=8))
                for k in novas:
                    nome = f"{k[0]}|{'|'.join(map(str, k[1]))}"
                    crises_cache[k] = {**res[nome], "crise": list(cr[nome]) if nome in cr else None, "pesos": novas[k]}
            mudou = False
            for p in list(atual):
                lim = server.PIOR_CRISE[p]
                cabe = lambda r: (r["corretora"]["maior_queda"] >= lim and r["simulador"]["maior_queda"] >= lim
                                  and r["crise"] is not None and r["crise"][1] >= lim)
                ref = crises_cache[(p, atual[p])]
                melhores = []
                for v in vizinhas(p, atual[p]):
                    r = crises_cache[(p, v)]
                    if v == atual[p] or not cabe(r):
                        continue
                    if (r["corretora"]["metade1_aa"] >= ref["corretora"]["metade1_aa"] + MARGEM
                            and all(r[t]["metade2_aa"] >= ref[t]["metade2_aa"] and r[t]["final"] > ref[t]["final"] for t in ("corretora", "simulador"))):
                        melhores.append((r["corretora"]["metade1_aa"], v))
                print(f"volta {volta} | {p}: atual {atual[p]} (cor 1ª {ref['corretora']['metade1_aa']} 2ª {ref['corretora']['metade2_aa']}"
                      f" R$ {ref['corretora']['final']:,.0f}; queda dia {ref['corretora']['maior_queda']}) -> "
                      f"{len(melhores)} vizinhas claramente melhores" + (f"; nova: {max(melhores)[1]}" if melhores else ""), flush=True)
                historico[p].append({"volta": volta, "atual": atual[p], "melhores": len(melhores)})
                if melhores:
                    atual[p] = max(melhores)[1]
                    mudou = True
            if not mudou:
                break
    print(f"\n===== RESULTADO DA RODADA {RODADA}")
    final = {}
    for p, v in atual.items():
        lim = server.PIOR_CRISE[p]
        r = crises_cache[(p, v)]
        w = pesos(*v)
        jan = janelas(w)
        cdi = janelas({"TESOURO_SELIC": 100})
        alts = {k: janelas(wp) for k, wp in planos.items() if k != "cdi"}
        vence_cdi = sum(a["aa"] > b["aa"] for a, b in zip(jan, cdi)) / len(jan)
        pior_queda = min(j["queda"] for j in jan)
        print(f"\n{p.upper()} (limite {lim:.0f}%): {v} -> classes {classes(w)}")
        print(f"  corretora R$ {r['corretora']['final']:,.0f} ({r['corretora']['metade1_aa']}% | {r['corretora']['metade2_aa']}%), queda dia"
              f" {r['corretora']['maior_queda']}%; simulador R$ {r['simulador']['final']:,.0f}, queda {r['simulador']['maior_queda']}%;"
              f" pior crise {r['crise']}")
        print(f"  janelas de 5 anos ({len(jan)}): vence o CDI em {vence_cdi:.0%}; pior janela {min(j['aa'] for j in jan):.1f}% ao ano;"
              f" mediana {np.median([j['aa'] for j in jan]):.1f}% ao ano; maior queda numa janela {pior_queda:.1f}%")
        for k, a in alts.items():
            print(f"    contra {k:16s}: vence em {sum(x['aa'] > y['aa'] for x, y in zip(jan, a)) / len(jan):.0%} das janelas")
        ok4 = vence_cdi >= 2 / 3 and pior_queda >= lim
        final[p] = {"carteira": v, "classes": classes(w), "pesos": w, "robusta": ok4, "voltas": historico[p],
                    "vence_cdi_janelas": round(vence_cdi, 3), "pior_queda_janelas": round(pior_queda, 1)}
        print(f"  (4) robusta: {'SIM' if ok4 else 'NÃO'} | informação: pior crise se o real não tivesse se desvalorizado: {crise_sem_cambio(w)}")
    print("\nresultado:", json.dumps(final, ensure_ascii=False))
    print(f"({time.time() - t0:.0f}s)")


if __name__ == "__main__":
    RODADA = int(sys.argv[1]) if len(sys.argv) > 1 else 4
    main()
