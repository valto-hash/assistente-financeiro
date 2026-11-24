"""Camada de garantia: dados parados, planos de referência, auditoria que barra a IA, memória e coerência.
Uso: python3 test_garantias.py"""
import json, os, sys, tempfile, time
from datetime import date, timedelta
os.environ["DATA_DIR"] = tempfile.mkdtemp(); os.environ["APP_TOKEN"] = ""
import numpy as np, pandas as pd
import mocks, server, armazem, memoria, referencias, simulacao as sim  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
falhas = []
def ok(cond, msg):
    print(("  ok   " if cond else "  FALHA ") + msg)
    if not cond: falhas.append(msg)

# ---- 1) dados parados e série IPCA+ longo
idx = pd.bdate_range("2023-01-02", periods=400)
viva = pd.Series(100 * np.exp(np.cumsum(np.random.default_rng(1).normal(0, 0.01, 400))), index=idx)
parada = viva.copy(); parada.iloc[100:200] = parada.iloc[100]
ok(not sim.parado(viva) and sim.parado(parada), "preço parado por 100 pregões é detectado; série viva, não")
s = sim.fechamentos_brl(["IPCA_LONGO"])
ok("IPCA_LONGO" in s and len(s["IPCA_LONGO"]) > 500, "série IPCA+ longo disponível mesmo sem o Banco Central (usa o IB5M11)")
ok(sim.PROXY_ATIVO["TESOURO_IPCA"] == "IPCA_LONGO" and "IMAB11" not in sim.BASE, "Tesouro IPCA+ simulado pelo IMA-B 5+, não pelo IMAB11")

# ---- 2) planos de referência
ref = referencias.planos_ref()
ids = [p["id"] for p in ref["planos"]]
print("   planos:", [(p["nome"], p["ret_aa"], p["maior_queda"]) for p in ref["planos"]], ref["desde"], ref["ate"])
ok(len(ids) == 11 and ids[:5] == ["cdi", "permanente", "all_weather", "60_40", "tres_fundos"]
   and {"wellesley", "golden_butterfly", "coffeehouse", "swensen", "core_four", "bolsa"} <= set(ids), "11 planos consagrados testados")
ok(all(p["metade1"]["ret_aa"] is not None and p["metade2"]["ret_aa"] is not None for p in ref["planos"]), "cada plano tem o resultado das duas metades do período")
# comparação com TODOS os planos que cabem no perfil
falso = {"planos": [
    {"id": "cdi", "nome": "CDI", "ret_aa": 10, "maior_queda": 0, "vol_aa": 1, "metade1": {"ret_aa": 10}, "metade2": {"ret_aa": 10}},
    {"id": "a", "nome": "Plano A", "ret_aa": 14, "maior_queda": -6, "vol_aa": 5, "metade1": {"ret_aa": 14}, "metade2": {"ret_aa": 14}},
    {"id": "b", "nome": "Plano B", "ret_aa": 13, "maior_queda": -7, "vol_aa": 6, "metade1": {"ret_aa": 13}, "metade2": {"ret_aa": 13}},
    {"id": "c", "nome": "Plano C", "ret_aa": 9, "maior_queda": -12, "vol_aa": 9, "metade1": {"ret_aa": 9}, "metade2": {"ret_aa": 9}},
    {"id": "d", "nome": "Plano D", "ret_aa": 20, "maior_queda": -40, "vol_aa": 20, "metade1": {"ret_aa": 20}, "metade2": {"ret_aa": 20}}]}
rp = referencias.para_perfil(falso, -18)
cart = {"ret_aa": 11, "maior_queda": -9, "vol_aa": 7, "metade1": {"ate": "01/2019", "ret_aa": 8}, "metade2": {"desde": "02/2019", "ret_aa": 14}}
chs, dom = referencias.comparar(cart, rp, "moderado")
chs = {c["id"]: c for c in chs}
print("   dominam:", dom, "|", chs["ranking"]["detalhe"])
ok(dom == ["a", "b"] and "Plano A" in chs["dominada"]["detalhe"] and "Plano B" in chs["dominada"]["detalhe"],
   "lista TODOS os planos que foram melhores e menos arriscados, não só um")
ok("d" not in dom and not next(p for p in rp["planos"] if p["id"] == "d")["cabe"], "plano que cai mais do que o perfil aceita não entra na comparação")
ok(not chs["ranking"]["ok"] and "1 dos 3" in chs["ranking"]["detalhe"], "posição entre os planos que cabem no perfil")
ok(not chs["periodos"]["ok"], "resultado que dependeu de uma metade do período vira aviso")
cdi = ref["planos"][0]
ok(cdi["maior_queda"] == 0 and cdi["vol_aa"] < 2, "CDI não tem queda (sanidade do teste)")
r = referencias.rodar({"A": 50, "B": 50}, pd.DataFrame({"A": [0.1, 0.0], "B": [-0.1, 0.0]}, index=pd.to_datetime(["2020-01-31", "2020-02-29"])))
ok(abs(r.iloc[0]) < 1e-12, "rebalanceamento: 50/50 entre +10% e -10% dá zero")

# ---- 3) auditoria objetiva (direto)
held = set()
chk = referencias.checar({"PETR4": 30, "TESOURO_SELIC": 70}, {"renda_fixa": 70, "acao": 30, "fii": 0, "exterior": 0, "cambio": 0},
                         server.PERFIS["conservador"], "conservador", "ALTA", held, server._individual, lambda a: True, -8, ("Covid", -12.0), True)
fal = {c["id"] for c in chk if not c["ok"]}
print("   reprovou:", sorted(fal))
ok({"perfil", "prazo", "concentracao", "crise"} <= fal and all(c["bloqueia"] for c in chk if not c["ok"]), "carteira arriscada demais para conservador de curto prazo: 4 bloqueios")
ok(not [c for c in referencias.checar({"TESOURO_SELIC": 100}, {"renda_fixa": 100, "acao": 0, "fii": 0, "exterior": 0, "cambio": 0},
        server.PERFIS["arrojado"], "arrojado", None, held, server._individual, lambda a: True, -30, ("Covid", 0.1), False) if not c["ok"]],
   "mais prudente que o perfil não é bloqueado")
cons = referencias.consistencia({"renda_fixa": 30, "acao": 40}, {"renda_fixa": 60, "acao": 10}, False, 5)
ok(cons and not cons[0]["ok"] and not cons[0]["bloqueia"], "mudança brusca sem motivo vira aviso de coerência")
ok(not referencias.consistencia({"renda_fixa": 30}, {"renda_fixa": 60}, True, 5), "se o perfil ou o objetivo mudou, mudar a carteira é coerente")

# ---- 4) API: IA reprovada pela auditoria vira carteira das regras
c = TestClient(server.app)
S = c.post("/api/conta/cadastrar", json={"nome": "Teste", "email": "g@ex.com", "senha": "senhateste1"}).json()
H, uid = {"Authorization": "Bearer " + S["token"]}, S["usuario"]["id"]
pos = {"PETR4": {"qtd": 100, "pm": 30}, "TESOURO_SELIC": {"saldo": 20000, "pct": 100}}
orig = server.client.messages.create
def ia_ruim(**kw):
    msg = orig(**kw)
    if "planejador" in kw["system"]:
        d = json.loads(msg.content[1].text)
        d["alvo"] = {"renda_fixa": 5, "acao": 85, "fii": 5, "exterior": 5, "cambio": 0}
        d["carteira"] = [{"ativo": "ITUB4", "peso": 85, "motivo": "x"},
                         {"ativo": "TESOURO_SELIC", "peso": 5, "motivo": "x"}, {"ativo": "HGLG11", "peso": 5, "motivo": "x"}, {"ativo": "IVVB11", "peso": 5, "motivo": "x"}]
        msg.content[1].text = json.dumps(d)
    return msg
server.client.messages.create = ia_ruim
mocks.CALLS.clear()
p = c.post("/api/portfolio", headers=H, json={"pos": pos, "perfil": "arrojado", "objetivo": ""}).json()  # perfil que escolhe ações
a = p["auditoria"]
print("   IA reprovada:", a["ia_reprovada"], "| fonte:", p["fonte"])
ok(p["fonte"] == "regras" and a["ia_reprovada"] and any("ITUB4" in m for m in a["ia_reprovada"]["motivos"]),
   "carteira absurda da IA (todas as ações numa empresa só) é descartada e as regras assumem")
# perfil sem ações individuais (conservador): a ação nova que a IA sugerir vira o ETF da classe
_, pesos_s, _, _ = server.montar_carteira({"alvo": dict(server.PERFIS["conservador"]), "carteira": [
    {"ativo": "ITUB4", "peso": 7.5, "motivo": "x"}, {"ativo": "TESOURO_SELIC", "peso": 70, "motivo": "x"},
    {"ativo": "IVVB11", "peso": 13.5, "motivo": "x"}, {"ativo": "GOLD11", "peso": 9, "motivo": "x"}]}, "conservador", {}, {}, False)
ok("ITUB4" not in pesos_s and pesos_s.get("BOVA11", 0) > 0, f"no perfil sem ações individuais, a IA não consegue incluir uma ação nova ({pesos_s})")
alvo_c, pesos_c, _, _ = server.montar_carteira({"alvo": {"renda_fixa": 5, "acao": 85, "fii": 5, "exterior": 5, "cambio": 0}, "carteira": []},
                                               "conservador", {}, {}, False)
mod = server.PERFIS["conservador"]
ok(all(mod[c] - 10.1 <= v <= mod[c] + 10.1 for c, v in alvo_c.items()) and abs(sum(alvo_c.values()) - 100) < 0.5,
   f"a IA não consegue tirar a alocação da faixa do perfil: {alvo_c}")
ok(a["aprovada"] and all(c_["ok"] for c_ in a["checagens"] if c_["bloqueia"] or c_["id"] in ("soma", "perfil")), "a carteira das regras passa na auditoria")
kw = next(k for k in mocks.CALLS if "planejador" in k["system"])
dados = json.loads(kw["messages"][0]["content"])
ok("PLANOS DE REFERÊNCIA" in kw["system"] and "TODOS os planos" in kw["system"] and len(dados["planos_de_referencia"]["planos"]) == 11
   and all("cabe_no_perfil" in p and "retorno_ao_ano_2a_metade" in p for p in dados["planos_de_referencia"]["planos"])
   and "comparacao_planos" in kw["output_config"]["format"]["schema"]["required"], "a IA recebe os planos consagrados e precisa se comparar com eles")
ok(a["carteira"] and a["carteira"]["cobertura"] >= 0 and a["referencia"]["planos"], "teste com o passado da carteira recomendada")
server.client.messages.create = orig

# ---- 5) memória: segunda recomendação sabe da primeira e das compras
mem = memoria.ler(uid)
ok(len(mem["recomendacoes"]) == 1 and mem["recomendacoes"][0]["entrada"]["perfil"] == "arrojado", "recomendação guardada na memória")
c.put("/api/carteira", headers=H, json={"dados": {"pos": pos}, "base": 0})
pos2 = {**pos, "BOVA11": {"qtd": 30, "pm": 110}}
c.put("/api/carteira", headers=H, json={"dados": {"pos": pos2}, "base": 1})
ev = memoria.ler(uid)["eventos"]
print("   eventos:", [e["texto"] for e in ev])
ok(any("comprou 30 de BOVA11" in e["texto"] for e in ev), "compra registrada vai para a memória")
mocks.CALLS.clear(); server.cache.clear()
p2 = c.post("/api/portfolio", headers=H, json={"pos": pos2, "perfil": "conservador", "objetivo": ""}).json()
kw = next(k for k in mocks.CALLS if "planejador" in k["system"])
dados = json.loads(kw["messages"][0]["content"])
hist = dados.get("historico_do_investidor") or {}
print("   contexto da IA:", json.dumps(hist, ensure_ascii=False)[:300])
ok(hist.get("ultima_recomendacao") and any("BOVA11" in x for x in hist.get("o_que_mudou_desde_entao", [])) and
   any("comprou 30 de BOVA11" in x for x in hist.get("acoes_registradas_pelo_investidor", [])), "a IA recebe a última recomendação, o que mudou e as compras")
ok("HISTÓRICO DO INVESTIDOR" in kw["system"] and "mudancas" in kw["output_config"]["format"]["schema"]["required"], "a IA precisa explicar as mudanças")
ok(p2["mudancas"], f"a tela mostra o que mudou: {p2['mudancas'][:120]}")
# coerência: memória com uma recomendação muito diferente, mesma entrada, há 3 dias
d = armazem.ler("memoria", uid)["dados"]
ult = d["recomendacoes"][-1]
ult["data"] = (date.today() - timedelta(days=3)).isoformat()
ult["alvo"] = {"renda_fixa": 40, "acao": 40, "fii": 10, "exterior": 10, "cambio": 0}
armazem.gravar("memoria", uid, d)
server.cache.clear()
p3 = c.post("/api/portfolio", headers=H, json={"pos": pos2, "perfil": "conservador", "objetivo": ""}).json()
co = next((x for x in p3["auditoria"]["checagens"] if x["id"] == "consistencia"), None)
print("   coerência:", co)
ok(co and not co["ok"], "mudança brusca desde a última recomendação aparece como aviso")
# revisão do modelo do perfil: a recomendação anterior feita com o modelo antigo não vira aviso de incoerência
# (modelo antigo fictício, bem diferente, para a revisão sozinha passar do limite de 10 p.p. do aviso)
velho = {"renda_fixa": 85, "acao": 4, "fii": 3, "exterior": 5, "cambio": 3}
novo = server.PERFIS["conservador"]
d = armazem.ler("memoria", uid)["dados"]
d["recomendacoes"][-1].update(data=(date.today() - timedelta(days=3)).isoformat(),
                              alvo={c: v + velho[c] - novo[c] for c, v in p3["alvo"].items()})
armazem.gravar("memoria", uid, d)
orig = server.REVISAO_MODELO["conservador"], server.PERFIS_ANTERIOR["conservador"]
server.REVISAO_MODELO["conservador"] = ((date.today() - timedelta(days=1)).isoformat(), orig[0][1])
server.PERFIS_ANTERIOR["conservador"] = velho
mocks.CALLS.clear(); server.cache.clear()
p4 = c.post("/api/portfolio", headers=H, json={"pos": pos2, "perfil": "conservador", "objetivo": ""}).json()
server.REVISAO_MODELO["conservador"], server.PERFIS_ANTERIOR["conservador"] = orig
kw = next(k for k in mocks.CALLS if "planejador" in k["system"])
hist = json.loads(kw["messages"][0]["content"]).get("historico_do_investidor") or {}
co = next((x for x in p4["auditoria"]["checagens"] if x["id"] == "consistencia"), None)
print("   revisão do modelo:", co)
ok(p4["alvo"] == p3["alvo"] and any("reformulado" in x for x in hist.get("o_que_mudou_desde_entao", [])) and co and co["ok"],
   "a IA fica sabendo que o modelo do perfil foi revisto, e a mudança que vem da revisão não vira aviso")
ok(memoria.ler(uid) and c.request("DELETE", "/api/conta", headers=H, json={"email": "g@ex.com", "senha": "senhateste1"}).status_code == 200
   and armazem.ler("memoria", uid) is None, "excluir a conta apaga a memória")
print("TUDO OK" if not falhas else f"{len(falhas)} FALHA(S)")
