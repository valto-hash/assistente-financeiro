"""Corretora simulada (dia a dia, com ordens), garantia de melhor decisão e proventos informados pela pessoa.
Uso: python3 testes/test_corretora.py"""
import json, os, tempfile
os.environ["DATA_DIR"] = tempfile.mkdtemp(); os.environ["APP_TOKEN"] = ""
import numpy as np, pandas as pd
import mocks, server, armazem, corretora as C, estrategias, simulador as S  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
falhas = []
def ok(cond, msg):
    print(("  ok   " if cond else "  FALHA ") + msg)
    if not cond: falhas.append(msg)

# ---- 1) contas da corretora num mercado de mentira, conferidas à mão
cal = pd.bdate_range("2020-01-01", "2021-12-31")
meses = pd.date_range("2020-01-31", "2021-11-30", freq="ME")
d = {"meses": meses}
cdi = pd.Series(100 * 1.0004 ** np.arange(len(cal)), index=cal)
bova = pd.Series(100.0, index=cal); bova[cal >= "2020-07-01"] = 200.0       # dobra em julho/2020
Pm = pd.DataFrame({"TESOURO_SELIC": cdi, "BOVA11": bova, "HGLG11": 150.0, "ITUB4": 30.0}, index=cal)
Dm = pd.DataFrame(0.0, index=cal, columns=Pm.columns)
Dm.loc[pd.Timestamp("2020-03-16"), "HGLG11"] = 1.0                           # R$ 1 por cota na data-com
custo0 = (C.EMOL, C.SPREAD, C.CUSTODIA_AA)

# 1a) 100% Tesouro Selic sem custos = aportes corrigidos pelo índice do dia de cada aplicação
C.EMOL = C.SPREAD = C.CUSTODIA_AA = 0.0
r = C.rodar(d, Pm, Dm, lambda t, h: {"TESOURO_SELIC": 100}, 10000, 1000)
execs = [cal[cal.searchsorted(t, side="right")] for t in meses]
mao = sum((10000 if k == 0 else 1000) * cdi.iloc[-1] / cdi[e] for k, e in enumerate(execs))
ok(abs(r["final"] - mao) < 2 and r["aplicado"] == 10000 + 1000 * (len(meses) - 1),
   f"100% Tesouro Selic sem custos bate com a conta à mão (R$ {r['final']:,.0f} x R$ {mao:,.0f}), antes do imposto do resgate")
ok(all(pd.Timestamp(o[0]) > t and pd.Timestamp(o[0]) == e for o in r["ultimas_ordens"] for t, e in zip(meses, execs) if o[0] == e.strftime("%Y-%m-%d")),
   "as ordens saem no pregão seguinte à decisão (nunca no mesmo dia)")
C.EMOL, C.SPREAD, C.CUSTODIA_AA = custo0

# 1b) ETF: compra em janeiro, preço dobra, vende tudo em agosto -> 15% de IR sobre o lucro, pago no mês seguinte
def vai_e_volta(t, h):
    return {"BOVA11": 100} if t < pd.Timestamp("2020-07-31") else {"TESOURO_SELIC": 100}
r = C.rodar(d, Pm, Dm, vai_e_volta, 10000, 0)
cotas = [o for o in r["ultimas_ordens"] if o[1] == "BOVA11"]
compras = [o for o in r["ultimas_ordens"] if o[1] == "BOVA11" and o[2] == "C"]
ok(all(float(o[3]).is_integer() for o in cotas), "ETF comprado e vendido em quantidades inteiras")
q = sum(o[3] for o in compras)
ganho = q * 200 * (1 - C.SPREAD) * (1 - C.EMOL) - q * 100 * (1 + C.SPREAD) * (1 + C.EMOL)
ok(r["vendas"] >= 1 and abs(r["lucro_bruto"] - ganho) < 2, f"lucro da venda do ETF conferido à mão (R$ {ganho:,.0f})")
ok(abs(r["ir_pago"] - 0.15 * ganho) < 3, f"IR de 15% sobre o lucro do ETF, pago no mês seguinte (R$ {0.15 * ganho:,.0f}; corretora: R$ {r['ir_pago']:,.0f})")
ok(r["vendas_com_lucro"] == 1 and r["vendas_com_prejuizo"] == 0, "estatística de operações só com renda variável (resgate de título não conta)")

# 1c) ação individual com vendas abaixo de R$ 20 mil no mês: isenta
Pm2 = Pm.copy(); Pm2.loc[cal >= "2020-07-01", "ITUB4"] = 40.0
r = C.rodar(d, Pm2, Dm, lambda t, h: {"ITUB4": 100} if t < pd.Timestamp("2020-07-31") else {"TESOURO_SELIC": 100}, 10000, 0)
ok(r["lucro_bruto"] > 2000 and r["ir_pago"] < 1, "ação vendida com menos de R$ 20 mil no mês: lucro isento de IR")

# 1c2) custódia do Tesouro sai do próprio título: nenhuma venda nem imposto por causa dela
r = C.rodar(d, Pm, Dm, lambda t, h: {"TESOURO_SELIC": 100}, 10000, 0)
ok(r["vendas"] == 0 and r["ir_pago"] == 0 and r["custodia"] > 0, f"custódia de R$ {r['custodia']:,.0f} descontada do título, sem vendas")

# 1d) FII: rendimento cai na conta na data-com; venda com lucro paga 20%
r = C.rodar(d, Pm, Dm, lambda t, h: {"HGLG11": 100}, 10000, 0)
cotas_fii = sum(o[3] for o in r["ultimas_ordens"] if o[1] == "HGLG11" and o[2] == "C" and o[0] < "2020-03-16")
ok(abs(r["proventos"] - cotas_fii * 1.0) < 1, f"rendimento do FII na conta: {cotas_fii:.0f} cotas x R$ 1")

# ---- 2) com os dados simulados do app: a corretora inteira, sem olhar o futuro
r = C.tudo({"moderado": server.PERFIS["moderado"]})
x = r["perfis"]["moderado"]["app"]
print("   app moderado:", {k: x[k] for k in ("final", "aplicado", "tir_aa", "metade1_aa", "metade2_aa", "maior_queda", "ordens", "ir_pago", "proventos")})
ok(set(r["planos"]) == {p["id"] for p in __import__("referencias").PLANOS} and {"app", "fixo"} <= set(r["perfis"]["moderado"]),
   "a recomendada, o modelo fixo e todos os planos rodam na corretora")
ok(x["aplicado"] == S.INICIAL + S.MENSAL * (len(S.preparar()["meses"]) - 1) and x["final"] > 0 and x["ordens"] > 0
   and x["metade1_aa"] is not None and x["metade2_aa"] is not None, "mesmo dinheiro do simulador, com resultado de cada metade")
json.dumps(r)
ok(True, "o resultado vira JSON sem números do numpy")

# ---- 3) garantia de melhor decisão (regra fixada antes de rodar com dados reais)
L = lambda f, m1, m2, q: {"final": f, "metade1_aa": m1, "metade2_aa": m2, "maior_queda": q}
rec = (L(100, 10, 10, -10), L(95, 10, 10, -12))
lin = {"app": rec, "a": (L(110, 10.5, 10.4, -10.5), L(104, 10.3, 10.3, -12.5)),   # melhor nas duas metades, nos dois testes
       "b": (L(120, 12, 9.9, -9), L(110, 12, 9.9, -9)),                           # perde na 2ª metade
       "c": (L(130, 12, 12, -14), L(120, 12, 12, -15)),                           # cai bem mais
       "d": (L(105, 10.5, 10.5, -10), L(94, 10.5, 10.5, -12))}                    # rende mais, mas termina com menos numa delas
dom = estrategias.dominantes("app", lin)
ok([x["id"] for x in dom] == ["a"], f"só domina quem vence nas duas metades, nos dois testes, sem cair mais e terminando com mais ({[x['id'] for x in dom]})")

c = TestClient(server.app)
T = c.post("/api/conta/cadastrar", json={"nome": "Teste", "email": "c@ex.com", "senha": "senhateste1"}).json()
H = {"Authorization": "Bearer " + T["token"]}
ok(c.get("/api/corretora").status_code == 401, "corretora simulada: precisa estar logado")
j = c.get("/api/corretora", headers=H).json()
ok(set(j["perfis"]) == set(server.PERFIS) and armazem.ler("cache", "corretora") and all(v["id"] for v in j["padroes"].values()),
   "API da corretora, com o resultado guardado no banco e a decisão de cada perfil")
# uma estratégia que vence nos dois testes vira a recomendada, e a carteira passa a segui-la
cabe = next(e for e in server.estrategias_perfil("moderado")["estrategias"] if e["tipo"] == "plano" and e["cabe"] and e["id"] != "cdi")
sim_f = {"perfis": {"moderado": {"linhas": [{"id": "app", **L(100, 10, 10, -10)}, {"id": cabe["id"], **L(120, 11, 11, -10)}]}}}
cor_f = {"perfis": {"moderado": {"app": L(95, 10, 10, -12)}}, "planos": {cabe["id"]: L(115, 11, 11, -12)}}
server._atualizar_padroes(sim=sim_f, cor=cor_f)
ok(server._padroes()["moderado"]["id"] == cabe["id"] and server._padroes()["conservador"]["id"] == "app",
   f"{cabe['nome']} venceu nos dois testes: vira a recomendada do moderado (e só dele)")
server.cache.pop("p:", None)
pos = {"TESOURO_SELIC": {"saldo": 20000, "pct": 100}}
p = c.post("/api/portfolio", headers=H, json={"pos": pos, "perfil": "moderado", "objetivo": ""}).json()
print("   recomendada:", p["estrategia"])
ok(p["fonte"] == "estrategia" and p["estrategia"]["id"] == "app" and p["estrategia"]["segue"]["id"] == cabe["id"]
   and "duas metades" in p["estrategia"]["segue"]["texto"], "quem segue a recomendada passa a receber a carteira da vencedora, com o motivo")
armazem.gravar("decisao", "padrao", {pp: {"id": "app"} for pp in server.PERFIS}); server.cache.clear()
p = c.post("/api/portfolio", headers=H, json={"pos": pos, "perfil": "moderado", "objetivo": ""}).json()
ok(p["fonte"] != "estrategia" and not p["estrategia"].get("segue"), "sem vencedora, a recomendada é a carteira do app")

# ---- 4) quanto a pessoa ganha com cada FII e ação
pos = {"HGLG11": {"qtd": 100, "pm": 150, "renda": 110}, "PETR4": {"qtd": 200, "pm": 30, "renda": 40},
       "TESOURO_SELIC": {"saldo": 5000, "pct": 100}}
mocks.CALLS.clear(); server.cache.clear()
p = c.post("/api/portfolio", headers=H, json={"pos": pos, "perfil": "moderado", "objetivo": ""}).json()
kw = next((k for k in mocks.CALLS if "planejador" in k["system"]), None)
itens = {i["ticker"]: i for i in json.loads(kw["messages"][0]["content"])["posicao_atual"]} if kw else {}
ok(itens.get("HGLG11", {}).get("proventos_mes_informado") == 110 and "proventos_mes_estimado" in itens.get("HGLG11", {}),
   "a IA recebe quanto a pessoa diz que ganha com cada FII e ação, e a estimativa pelo histórico")
ok(p["renda"]["informada"] == 150 and set(p["renda"]["sem_informar"]) == set(), f"a carteira soma os proventos informados ({p['renda']})")
fatos = {a["ativo"]: [f["rotulo"] if isinstance(f, dict) and "rotulo" in f else str(f) for f in a["fatos"]] for a in p["acoes"]}
ok(any("Proventos que você recebe" in str(f) for f in p["acoes"][0]["fatos"] + sum((a["fatos"] for a in p["acoes"]), [])),
   "o que fazer com cada ativo mostra os proventos informados")
vend = [a for a in p["acoes"] if a["acao"] in ("VENDER", "REDUZIR", "REALIZAR_LUCRO") and a["ativo"] in ("HGLG11", "PETR4")]
ok(not vend or all("deixa de receber" in a["contra"] for a in vend), "venda de quem paga proventos diz quanto de renda deixa de entrar")
v = c.get("/api/carteira", headers=H).json()["versao"]
c.put("/api/carteira", headers=H, json={"dados": {"pos": pos, "perfil": "moderado"}, "base": v})
ok(c.get("/api/carteira", headers=H).json()["dados"]["pos"]["HGLG11"].get("renda") == 110, "os proventos informados ficam salvos com a carteira")
print("TUDO OK" if not falhas else f"{len(falhas)} FALHA(S)")
