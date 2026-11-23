"""Revisão dos modelos dos três perfis, com validação fora da amostra (registrado antes de rodar, 23/11/2026).
Uso, na raiz do repositório: python3 ferramentas/revisar_modelos.py (precisa de internet; leva uns 15 minutos).
Os candidatos abaixo são os da revisão de nov/2026 ("atual" era o modelo de antes dela; hoje é o novo).

Candidatos: o modelo atual de cada perfil, os planos consagrados (referencias.PLANOS) levados para as cinco classes do
app, e uma variação "global" do atual (menos FIIs, mais exterior, dólar e ouro: a lição da revisão do conservador).
Atenção: os resultados dos planos no período inteiro já tinham aparecido no simulador antes desta revisão. Por isso a
escolha usa só 2013-2019 e a confirmação, 2020-2026; e a prova que vale continua sendo a ao vivo.

Regra (fixada antes de rodar):
1. Elegível: pior crise real testada >= limite do perfil - 2 (o mesmo critério da auditoria) e maior queda na
   simulação de 2013-2019 dentro do limite do perfil.
2. Escolha: maior retorno ao ano (TIR) em 2013-2019 entre os elegíveis.
3. Adota só se, em 2020-2026 (fora da escolha), render mais que o modelo atual e a maior queda ficar dentro do limite.
   Senão, fica o atual.
Todos rodam com as regras do app (escolha de ativos, faixas, custos), como no simulador.
"""
import os, sys, tempfile, json
os.environ["DATA_DIR"] = tempfile.mkdtemp(); os.environ["APP_TOKEN"] = ""
os.environ.pop("ANTHROPIC_API_KEY", None)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import multiprocessing as mp
import pandas as pd
import server, simulador as S

C = ("renda_fixa", "acao", "fii", "exterior", "cambio")
m = lambda *v: dict(zip(C, v))
CAND = {
    "conservador": {"atual": m(70, 7, 3, 10, 10),
                    "All Weather": m(55, 15, 0, 15, 15), "Renda e crescimento 35/65": m(65, 20, 0, 15, 0),
                    "Permanente": m(50, 25, 0, 0, 25)},
    "moderado": {"atual": m(45, 20, 15, 15, 5), "global": m(45, 17, 8, 20, 10),
                 "All Weather": m(55, 15, 0, 15, 15), "60/40": m(40, 30, 0, 30, 0), "Três fundos": m(40, 40, 0, 20, 0),
                 "Swensen": m(30, 30, 20, 20, 0), "Permanente": m(50, 25, 0, 0, 25), "Coffeehouse": m(40, 40, 10, 10, 0),
                 "Golden Butterfly": m(40, 40, 0, 0, 20)},
    "arrojado": {"atual": m(25, 32, 15, 22, 6), "global": m(25, 30, 7, 28, 10),
                 "60/40": m(40, 30, 0, 30, 0), "Core Four": m(20, 48, 8, 24, 0), "Três fundos": m(40, 40, 0, 20, 0),
                 "Swensen": m(30, 30, 20, 20, 0), "100% bolsa": m(0, 100, 0, 0, 0)},
}
PER = {"2013-19": ("2013-01-01", "2019-12-31"), "2020-26": ("2019-12-31", "2026-12-31"), "tudo": ("2013-01-01", "2026-12-31")}
d = S.preparar()


def periodo(ini, fim):
    return {**d, "meses": d["meses"][(d["meses"] >= pd.Timestamp(ini)) & (d["meses"] <= pd.Timestamp(fim))]}


def rodar(args):
    perfil, nome, per = args
    ini, fim = PER[per]
    x = S._resumo(nome, S._rodar(periodo(ini, fim), S.decisor(d, CAND[perfil][nome]), S.INICIAL, S.MENSAL))
    return args, {k: x[k] for k in ("final", "tir_aa", "maior_queda", "pior_12m", "investido")}


def crise(modelo):
    pesos = {a: modelo[c] * w for c, ws in S.NUCLEO.items() for a, w in ws.items() if modelo.get(c)}
    return server._pior_crise(pesos, server._specs(pesos, {}))


if __name__ == "__main__":
    print(json.dumps(CAND, ensure_ascii=False))
    tarefas = [(p, n, per) for p in CAND for n in CAND[p] for per in PER]
    with mp.get_context("fork").Pool(4) as pool:
        res = dict(pool.map(rodar, tarefas))
    final = {}
    for p, cands in CAND.items():
        lim = server.PIOR_CRISE[p]
        print(f"\n===== {p} (aceita até {lim:.0f}%)")
        linhas = {}
        for n, mod in cands.items():
            r = {per: res[(p, n, per)] for per in PER}
            r["crise"] = crise(mod)
            linhas[n] = r
            cr = r["crise"] or ("?", 0)
            print(f"  {n:26s} 2013-19: {r['2013-19']['tir_aa']:5.1f}% queda {r['2013-19']['maior_queda']:6.1f} | "
                  f"2020-26: {r['2020-26']['tir_aa']:5.1f}% queda {r['2020-26']['maior_queda']:6.1f} | "
                  f"tudo: R$ {r['tudo']['final']:>9,.0f} {r['tudo']['tir_aa']:5.1f}% queda {r['tudo']['maior_queda']:6.1f} | "
                  f"pior crise: {cr[0]} {cr[1]:+.1f}%")
        eleg = {n: r for n, r in linhas.items() if r["crise"] and r["crise"][1] >= lim - 2 and r["2013-19"]["maior_queda"] >= lim}
        esc = max(eleg, key=lambda n: eleg[n]["2013-19"]["tir_aa"])
        e, a = linhas[esc], linhas["atual"]
        adota = esc != "atual" and e["2020-26"]["tir_aa"] > a["2020-26"]["tir_aa"] and e["2020-26"]["maior_queda"] >= lim
        print(f"  elegíveis: {list(eleg)}")
        print(f"  escolhido com 2013-19: {esc} | 2020-26: {e['2020-26']['tir_aa']}% (atual {a['2020-26']['tir_aa']}%), "
              f"queda {e['2020-26']['maior_queda']} -> {'ADOTAR' if adota else 'FICA O ATUAL'}")
        final[p] = {"escolhido": esc, "adota": adota, "modelo": cands[esc]}
    print("\nresultado:", json.dumps(final, ensure_ascii=False))
