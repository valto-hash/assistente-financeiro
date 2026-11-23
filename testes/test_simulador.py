"""Simulador do passado: não olha o futuro, opera como o app manda, compara com o modelo fixo e guarda a prova ao vivo.
Uso: python3 testes/test_simulador.py"""
import os, sys, tempfile
os.environ["DATA_DIR"] = tempfile.mkdtemp(); os.environ["APP_TOKEN"] = ""
import numpy as np, pandas as pd
import mocks, server, armazem, regras, simulador as S, simulacao as sim  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
falhas = []
def ok(cond, msg):
    print(("  ok   " if cond else "  FALHA ") + msg)
    if not cond: falhas.append(msg)

# ---- 1) sem olhar o futuro: as métricas do mês t são as mesmas com ou sem os dados depois de t
sim.baixar(["WEGE3"])
_, c, dv, _ = sim._hist["WEGE3"]
meses = pd.date_range("2016-01-31", "2020-12-31", freq="ME")
todas = S._metricas_mes(c, dv, meses)
t = pd.Timestamp("2018-06-30")
cortada = S._metricas_mes(c[c.index <= t], dv[dv.index <= t], [t])
# (o dividend yield fica fora desta conta: o Yahoo ajusta os preços antigos pelos dividendos pagos depois, então cortar a
#  série não desfaz o ajuste; o simulador reconstrói o preço de tela da época, conferido com o preço sem ajuste do Yahoo)
ok(t in todas and all(abs((todas[t][k] or 0) - (cortada[t][k] or 0)) < 1e-6 for k in ("ret_12m", "ret_3a_aa", "vol_aa", "queda_max_12m", "anos_hist")),
   "as métricas de jun/2018 não mudam quando os preços de depois são apagados (o app não vê o futuro)")
orig_bcb = S._bcb
S._bcb = lambda serie, desde=2005: pd.Series({pd.Timestamp("2018-05-15"): 2.0 if serie == 13522 else 6.5,
                                              pd.Timestamp("2018-06-15"): 4.0 if serie == 13522 else 6.5})
sel, ip, aprox = S._taxas(pd.DatetimeIndex([pd.Timestamp("2018-06-30")]), None)
ok(float(ip.iloc[0]) == 2.0 and float(sel.iloc[0]) == 6.5 and not aprox, "no fim de junho vale o IPCA de maio (o de junho só é divulgado em julho)")
def _falha(serie, desde=2005): raise IOError("Banco Central fora do ar")
S._bcb = _falha
R0 = pd.DataFrame({"CDI": [0.01] * 14}, index=pd.date_range("2017-05-31", periods=14, freq="ME"))
sel, ip, aprox = S._taxas(R0.index, R0)
S._bcb = orig_bcb
ok(aprox == ["Selic", "IPCA"] and float(ip.iloc[-1]) == 4.5, "sem o Banco Central, a Selic e o IPCA são aproximados e isso fica marcado")
import requests as _rq
chamadas, orig_get = [], _rq.get
class _Resp:
    def __init__(self, ok): self.ok = ok
    def raise_for_status(self):
        if not self.ok: raise IOError("503")
    def json(self): return [{"data": "15/06/2018", "valor": "6,5"}]
def _get(url, **kw):
    chamadas.append(url); return _Resp(len(chamadas) > 1)  # a primeira tentativa falha
_rq.get = _get; S._bcb_cache.clear(); orig_sleep = S.time.sleep; S.time.sleep = lambda s: None
s1 = S._bcb(432, desde=2016); n = len(chamadas); s2 = S._bcb(432, desde=2016)
_rq.get = orig_get; S.time.sleep = orig_sleep; S._bcb_cache.clear()
ok(float(s1.iloc[0]) == 6.5 and n == 3 and len(chamadas) == n and s2.equals(s1),
   "a API do Banco Central é tentada de novo quando falha, e a série fica guardada (duas rodadas seguidas dão o mesmo resultado)")
idx = pd.Series(np.linspace(100, 200, 40), index=pd.date_range("2015-01-31", periods=40, freq="ME"))
ok(S._indicador(idx, idx.index[20])["ret_12m"] == S._indicador(idx[:21], idx.index[20])["ret_12m"], "o panorama da época também só usa o passado")

# ---- 2) operar como o app manda
hold, base = {"A": 5000.0, "B": 5000.0, "VELHO": 1000.0}, {"A": 4000.0, "B": 5000.0, "VELHO": 500.0}
custos, ir, ops = S.operar(hold, base, {"A": 50, "B": 50}, 1000, 1000)
ok("VELHO" not in hold, "vende o que saiu da carteira recomendada")
ok(abs(sum(hold.values()) - (12000 - custos)) < 1, f"custo de {S.CUSTO * 100:.1f}% em cada operação ({custos:.0f})")
hold, base = {"A": 6500.0, "B": 3500.0}, {"A": 6500.0, "B": 3500.0}
S.operar(hold, base, {"A": 50, "B": 50}, 1000, 1000)
ok(hold["A"] >= 6490, "excesso pequeno que os próximos aportes resolvem não é vendido (evita IR e custo)")
hold, base = {"A": 9500.0, "B": 500.0}, {"A": 5000.0, "B": 500.0}
_, ir, _ = S.operar(hold, base, {"A": 50, "B": 50}, 0, 0)
ok(hold["A"] < 6000, "excesso grande, sem aportes para corrigir, é vendido")

# ---- 3) o ajuste pelo momento do mercado ficou desligado (o simulador mostrou que piorava)
mod = server.PERFIS["moderado"]
pan = {"renda_fixa": {"visao": "POSITIVA"}, "acao": {"visao": "NEGATIVA"}}
ok(regras.alvo_classes(mod, pan, None)[0] == {k: float(v) for k, v in mod.items()}, "sem objetivo, a alocação é a do perfil (sem adivinhar o momento)")
ok(regras.alvo_classes(mod, pan, None, momento=True)[0]["renda_fixa"] > mod["renda_fixa"], "a versão antiga (com ajuste) continua disponível para comparação")

# ---- 4) conferências independentes: conta à mão e o outro motor de testes do app
d = S.preparar()
meses = list(d["meses"])
for ativo in ("TESOURO_SELIC", "BOVA11"):
    v = 0.0
    for i in range(len(meses) - 1):
        v = (v + (S.INICIAL if i == 0 else S.MENSAL) * (1 - S.CUSTO)) * (1 + float(d["ret"].at[meses[i + 1], ativo]))
    x = S._rodar(d, lambda t, h, a=ativo: {a: 100}, S.INICIAL, S.MENSAL)
    ok(abs(x["valores"][-1] - v) < 0.01, f"100% {ativo}: o simulador bate com a conta feita à mão (R$ {v:,.2f})")
import referencias
# plano sem ouro: nos dados simulados dos testes, o GOLD11 é uma série aleatória que não acompanha o ouro
perm = next(p for p in referencias.PLANOS if p["id"] == "tres_fundos")
pp = {}
for k, w in perm["pesos"].items():
    for a, f in S.COMP_ATIVO[k].items():
        pp[a] = pp.get(a, 0) + w * f
x = S._rodar(d, lambda t, h: pp, S.INICIAL, 0.0)
c1 = (np.prod(1 + np.array(x["rets"])) ** (12 / len(x["rets"])) - 1) * 100
rr = referencias.rodar(perm["pesos"], d["R"][d["R"].index > meses[0]])
c2 = (float((1 + rr).prod()) ** (12 / len(rr)) - 1) * 100
ok(abs(c1 - c2) < 1.0, f"Três fundos: simulador {c1:.2f}% x outro motor {c2:.2f}% ao ano (só muda o rebalanceamento)")

# ---- 5) simulação completa nos três perfis
r = S.tudo(server.PERFIS, server.PIOR_CRISE, anteriores=server.PERFIS_ANTERIOR)
for p, x in r["perfis"].items():
    ids = [l["id"] for l in x["linhas"]]
    app = next(l for l in x["linhas"] if l["id"] == "app")
    print(f"   {p}: app {app['final']:,.0f} (TIR {app['tir_aa']}%), vs fixo {x['vs_fixo']:+,.0f}, vs CDI {x['vs_cdi']:+,.0f}, {x['posicao']}º de {x['total']}")
    ok({"app", "app_antigo", "fixo", "cdi"} <= set(ids) and len(app["serie"]) == len(x["datas"]) and app["investido"] > 0 and app["final"] > 0,
       f"{p}: app, versão antiga, modelo fixo e CDI com o mesmo dinheiro nas mesmas datas")
xm = r["perfis"]["moderado"]
ok(all(x["total"] == len(x["linhas"]) - 2 and 1 <= x["posicao"] <= x["total"] for x in r["perfis"].values()),
   "a versão antiga do app e o modelo antigo não entram na contagem de posição")
ok(all(any(l["id"] == "fixo_antigo" for l in x["linhas"]) and x["modelo_anterior"] == server.PERFIS_ANTERIOR[p]
       for p, x in r["perfis"].items()), "o modelo antigo de cada perfil aparece para comparação")
cdi = next(l for l in r["perfis"]["moderado"]["linhas"] if l["id"] == "cdi")
ok(cdi["maior_queda"] == 0 and cdi["ir_estimado"] == 0, "CDI sem queda e sem IR de vendas (sanidade)")

# ---- 6) prova ao vivo: guarda uma carteira por mês, antes de o mês acontecer
reg = armazem.ler("simulador_vivo", "todos")["dados"]
k = list(reg["meses"])[0]
ok(len(reg["meses"]) == 1 and set(reg["meses"][k]["app"]) == set(server.PERFIS), "carteira do mês guardada para os três perfis")
S.tudo(server.PERFIS, server.PIOR_CRISE)
ok(len(armazem.ler("simulador_vivo", "todos")["dados"]["meses"]) == 1, "rodar de novo no mesmo mês não duplica o registro")
d = S.preparar()
ant = (pd.Timestamp(k + "-01") - pd.offsets.MonthEnd(1)).strftime("%Y-%m")  # finge um registro do mês anterior
reg["meses"][ant] = reg["meses"][k]
v = S.resultado_vivo(d, reg, server.PERFIS)
ok(len(v["meses"]) == 1 and v["perfis"]["moderado"]["cdi"] > 0, f"o resultado ao vivo usa só os meses que já aconteceram ({v['meses']})")

# ---- 7) API
c = TestClient(server.app)
T = c.post("/api/conta/cadastrar", json={"nome": "Teste", "email": "s@ex.com", "senha": "senhateste1"}).json()["token"]
j = c.get("/api/simulador", headers={"Authorization": "Bearer " + T}).json()
ok(set(j["perfis"]) == {"conservador", "moderado", "arrojado"} and armazem.ler("cache", "simulador") and not j["aproximado"],
   "API do simulador, com o resultado guardado no banco")
ok(c.get("/api/simulador").status_code == 401, "precisa estar logado")
print("TUDO OK" if not falhas else f"{len(falhas)} FALHA(S)")
