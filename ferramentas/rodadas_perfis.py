"""Rodadas de simulação para que a estratégia recomendada de cada perfil seja melhor que as outras que o app oferece.
Registrado antes de rodar (24/11/2026). Só dados reais: preços e proventos do Yahoo, Selic, IPCA, CDI e IMA-B 5+ do
Banco Central, nos dois testes do app (simulador mês a mês e corretora simulada dia a dia, com custos e imposto).

PERFIS REFORMULADOS (o limite vale para as três medidas, sem tolerância):
- Conservador: prioriza não perder. A carteira não pode ter caído mais de 8% em nenhum momento.
- Moderado: equilíbrio. Não pode ter caído mais de 18%.
- Arrojado: crescimento no longo prazo. Não pode ter caído mais de 30%.
Medidas: (1) maior queda dia a dia de 2013 até hoje, na corretora simulada; (2) maior queda no simulador mês a mês;
(3) pior crise real testada (2008, 2013, 2015, Joesley, caminhoneiros, Covid, 2022...), com os pesos da carteira.

CANDIDATOS (só ETFs e títulos; a escolha de ações e FIIs individuais é testada depois, na carteira escolhida):
- renda fixa: conservador 95/90/85/80/75/70%; moderado 70/65/60/55/50/45/40%; arrojado 50/45/40/35/30/25/20%;
- divisão da renda fixa: pós (Selic 70%, LCI 30%), padrão (Selic 30%, LCI 15%, IPCA+ 55%), inflação (Selic 15%, IPCA+ 85%);
- divisão da parte de risco (ações, FIIs, exterior, dólar e ouro): a do modelo atual do perfil, global (25/0/45/30),
  60/40 (50/0/50/0), terços (34/0/33/33), Brasil (45/20/25/10), proteção (20/0/30/50);
- dólar e ouro: metade cada, ou só ouro.
Ações: BOVA11 60% e DIVO11 40%; FIIs: KNCR11 e HGLG11; exterior: IVVB11.

REGRA DE ESCOLHA (rodada 1):
1. Elegível: as três medidas dentro do limite do perfil (os limites são de segurança: valem para o período inteiro).
2. Escolhida: o maior retorno ao ano na corretora simulada em 2013-2019 (só a 1ª metade decide o retorno).
CRITÉRIO DE SUCESSO (conferido depois):
(a) patrimônio final 2013-hoje maior que o de cada estratégia que o app oferece e cabe no perfil (planos consagrados e
    100% CDI), nos dois testes;
(b) retorno ao ano em 2020-hoje (fora da escolha) não menor que o do modelo atual do perfil, nos dois testes.
Se falhar, a próxima rodada muda uma coisa só, registrada aqui antes de rodar.

Uso, na raiz do repositório: python3 ferramentas/rodadas_perfis.py [rodada]  (precisa de internet)
"""
import itertools, json, os, sys, tempfile, time
os.environ["DATA_DIR"] = tempfile.mkdtemp(); os.environ["APP_TOKEN"] = ""
os.environ.pop("ANTHROPIC_API_KEY", None)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import multiprocessing as mp
import pandas as pd
import server, referencias, corretora as C, simulador as S  # noqa: E402

LIMITE = {"conservador": -8.0, "moderado": -18.0, "arrojado": -30.0}
RF_NIVEIS = {"conservador": [95, 90, 85, 80, 75, 70], "moderado": [70, 65, 60, 55, 50, 45, 40], "arrojado": [50, 45, 40, 35, 30, 25, 20]}
RF_DIV = {"pos": {"TESOURO_SELIC": .7, "LCI_LCA": .3}, "padrao": {"TESOURO_SELIC": .3, "LCI_LCA": .15, "TESOURO_IPCA": .55},
          "inflacao": {"TESOURO_SELIC": .15, "TESOURO_IPCA": .85}}
MIX = {"global": (.25, 0, .45, .30), "60_40": (.5, 0, .5, 0), "tercos": (.34, 0, .33, .33), "brasil": (.45, .2, .25, .10),
       "protecao": (.2, 0, .3, .5)}
CAMBIO = {"meio": {"DOLAR": .5, "GOLD11": .5}, "ouro": {"GOLD11": 1.0}}
NUC = {"acao": {"BOVA11": .6, "DIVO11": .4}, "fii": {"KNCR11": .5, "HGLG11": .5}, "exterior": {"IVVB11": 1.0}}
H1 = pd.Timestamp("2019-12-31")


def mix_atual(p):
    m = server.PERFIS[p]; r = 100 - m["renda_fixa"]
    return tuple(m[c] / r for c in ("acao", "fii", "exterior", "cambio"))


def pesos_cand(rf, div, mix, camb):
    w = {}
    for a, f in RF_DIV[div].items():
        w[a] = w.get(a, 0) + rf * f
    r = 100 - rf
    for c, x in zip(("acao", "fii", "exterior"), mix[:3]):
        for a, f in NUC[c].items():
            w[a] = w.get(a, 0) + r * x * f
    for a, f in CAMBIO[camb].items():
        w[a] = w.get(a, 0) + r * mix[3] * f
    return {a: round(v, 4) for a, v in w.items() if v > 0}


def classes_de(w):
    cl = {"renda_fixa": 0, "acao": 0, "fii": 0, "exterior": 0, "cambio": 0}
    for a, v in w.items():
        cl[server.UNIVERSO[a][0]] += v
    return {c: round(v, 1) for c, v in cl.items()}


D = PM = DM = None


def preparar():
    global D, PM, DM
    D = S.preparar()
    planos = {p["id"]: S.pesos_plano(p["pesos"]) for p in referencias.PLANOS}
    ativos = sorted({a for w in planos.values() for a in w} | set(RF_DIV["padrao"]) | {"LCI_LCA"} | {a for n in NUC.values() for a in n} | {"DOLAR", "GOLD11"})
    PM, DM = C.precos(ativos, D["meses"][0])
    return planos


def avaliar(args):
    nome, w = args
    cor = C.rodar(D, PM, DM, lambda t, h, w=w: w)
    sim = S._resumo(nome, S._rodar(D, lambda t, h, w=w: w, S.INICIAL, S.MENSAL))
    return nome, {"corretora": {k: cor[k] for k in ("final", "metade1_aa", "metade2_aa", "maior_queda", "ir_pago", "custos", "custodia")},
                  "simulador": {k: sim[k] for k in ("final", "metade1_aa", "metade2_aa", "maior_queda")}}


def main(rodada=1):
    t0 = time.time()
    planos = preparar()
    cands = {}
    for p in server.PERFIS:
        mixes = {"atual": mix_atual(p), **MIX}
        for rf, div, (mn, mx), camb in itertools.product(RF_NIVEIS[p], RF_DIV, mixes.items(), CAMBIO):
            if mx[3] == 0 and camb == "ouro":
                continue
            cands[f"{p}|rf{rf}|{div}|{mn}|{camb}"] = pesos_cand(rf, div, mx, camb)
    atuais = {f"atual|{p}": pesos_cand(server.PERFIS[p]["renda_fixa"], "padrao", mix_atual(p), "meio") for p in server.PERFIS}
    todos = {**cands, **atuais, **{f"plano|{k}": w for k, w in planos.items()}}
    print(f"{len(cands)} candidatos + {len(atuais)} modelos atuais + {len(planos)} planos", flush=True)
    crises = server._crises(todos)
    with mp.get_context("fork").Pool(4) as pool:
        res = dict(pool.map(avaliar, list(todos.items()), chunksize=8))
    for k in res:
        res[k]["crise"] = list(crises[k]) if k in crises else None
        res[k]["pesos"] = todos[k]
    json.dump(res, open(os.path.join(tempfile.gettempdir(), f"rodada{rodada}.json"), "w"))
    final = {}
    for p, lim in LIMITE.items():
        cabe = lambda r: (r["corretora"]["maior_queda"] >= lim and r["simulador"]["maior_queda"] >= lim
                          and r["crise"] is not None and r["crise"][1] >= lim)
        eleg = {k: r for k, r in res.items() if k.startswith(p + "|") and cabe(r)}
        alt = {k: r for k, r in res.items() if k.startswith("plano|") and cabe(r)}
        atual = res[f"atual|{p}"]
        print(f"\n===== {p} (limite {lim:.0f}%): {len(eleg)} candidatos elegíveis; planos que cabem: {[k[6:] for k in alt]}")
        if not eleg:
            print("  nenhum candidato elegível"); continue
        esc = max(eleg, key=lambda k: (eleg[k]["corretora"]["metade1_aa"], eleg[k]["corretora"]["maior_queda"]))
        e = res[esc]
        ok_a = all(e[t]["final"] > a[t]["final"] for a in alt.values() for t in ("corretora", "simulador"))
        ok_b = all(e[t]["metade2_aa"] >= atual[t]["metade2_aa"] for t in ("corretora", "simulador"))
        def linha(nome, r):
            return (f"  {nome:42s} cor R$ {r['corretora']['final']:>9,.0f} {r['corretora']['metade1_aa']:5.1f}|{r['corretora']['metade2_aa']:5.1f}"
                    f" queda {r['corretora']['maior_queda']:6.1f} | sim R$ {r['simulador']['final']:>9,.0f} {r['simulador']['metade1_aa']:5.1f}|"
                    f"{r['simulador']['metade2_aa']:5.1f} queda {r['simulador']['maior_queda']:6.1f} | crise {r['crise'][1] if r['crise'] else '?'}")
        print(linha("ESCOLHIDA " + esc.split("|", 1)[1], e))
        print(linha("modelo atual (" + ("cabe" if cabe(atual) else "NÃO cabe") + ")", atual))
        for k, a in sorted(alt.items(), key=lambda kv: -kv[1]["corretora"]["final"]):
            print(linha(k, a))
        top = sorted(eleg, key=lambda k: -eleg[k]["corretora"]["metade1_aa"])[:5]
        print("  5 melhores na 1ª metade:", [(k.split("|", 1)[1], eleg[k]["corretora"]["metade1_aa"]) for k in top])
        print(f"  classes: {classes_de(e['pesos'])} | pesos: {e['pesos']}")
        print(f"  (a) vence todas as que cabem, nos dois testes: {'SIM' if ok_a else 'NÃO'} | (b) 2ª metade não pior que o atual: {'SIM' if ok_b else 'NÃO'}")
        final[p] = {"escolhida": esc, "ok": ok_a and ok_b, "classes": classes_de(e["pesos"]), "pesos": e["pesos"]}
    print("\nresultado:", json.dumps(final, ensure_ascii=False))
    print(f"({time.time() - t0:.0f}s)")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 1)
