"""Testa: modelo das decisões (Opus + streaming + fallback de modelo), consenso IA x regras, checagem dos números,
registro e avaliação dos sinais, teste com o passado e avisos só com consenso. Uso: python3 test_confiab.py"""
import os, sys, json, tempfile, time
from datetime import date, timedelta
os.environ["DATA_DIR"] = tempfile.mkdtemp()
import mocks, server  # noqa: E402
import acertos, checagem, regras  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
import httpx2, anthropic  # noqa: E402

c = TestClient(server.app)
S = c.post("/api/conta/cadastrar", json={"nome": "Teste", "email": "t@ex.com", "senha": "senhateste1", "convite": "teste"}).json()
H, uid = {"Authorization": "Bearer " + S["token"]}, S["usuario"]["id"]
print("modelos:", c.get("/api/watchlist", headers=H).json()["modelos"])

# ---- 1) consenso IA x regras na análise de um ativo
for t in ("PETR4", "ITUB4", "BOVA11", "VOO"):
    a = c.post("/api/analyze", headers=H, json={"ticker": t, "pos": {"qtd": 10, "pm": 20}}).json()
    esperado = "concordam" if a["regras"]["decisao"] == a["decisao"] else "divergem"
    print(f"{t}: IA={a['decisao']} regras={a['regras']['decisao']} consenso={a['consenso']} (ok={a['consenso'] == esperado})"
          f" conf={a['confianca']} conf_ia={a['confianca_ia']} | {a['sugestao']} | checagem={a['checagem']}")
    assert a["consenso"] == esperado
    if esperado == "divergem": assert a["confianca"] <= 40 and ("discordam" in a["sugestao"] or "atingido" in a["sugestao"])

# ---- 2) checagem dos números: um resumo de ativo com número inventado vira o texto das regras
orig = server.client.messages.create
def inventa(**kw):
    msg = orig(**kw)
    if kw["system"].startswith("Você é um trader"):
        d = json.loads(msg.content[1].text); d["resumo"] = "Subiu 87,3% no ano e deve ir a 150."; d["riscos"] = ["Risco sem número", "Pode cair 66,6%"]
        msg.content[1].text = json.dumps(d)
    return msg
server.client.messages.create = inventa
server.cache.pop("m:ITUB4", None)
a = c.post("/api/analyze", headers=H, json={"ticker": "ITUB4", "pos": {"qtd": 0, "pm": 0}}).json()
print("resumo trocado:", a["resumo"][:90], "| riscos:", a["riscos"], "| checagem:", a["checagem"])
assert a["resumo"] == regras.analise_ativo(a["metricas"])["resumo"] and a["riscos"] == ["Risco sem número"] and {d["onde"] for d in a["checagem"]["detalhes"]} >= {"resumo", "riscos"}
server.client.messages.create = orig

# ---- 3) carteira: Opus 5.5 com effort alto e streaming; checagem do "porque" inventado
mocks.CALLS.clear()
pos = {"PETR4": {"qtd": 300, "pm": 30}, "ITUB4": {"qtd": 50, "pm": 25}, "PORQUINHO": {"saldo": 5000, "pct": 100}}
p = c.post("/api/portfolio", headers=H, json={"pos": pos, "perfil": "moderado", "objetivo": ""}).json()
kw = next(k for k in mocks.CALLS if "planejador" in k["system"])
print("carteira:", p["fonte"], "| modelo:", kw["model"], "| effort:", kw["output_config"]["effort"], "| max_tokens:", kw["max_tokens"],
      "| modelo na resposta:", p["modelo"])
assert kw["model"] == "claude-opus-5-5" and kw["output_config"]["effort"] == "high" and kw["max_tokens"] == 32000
bova = next(s for s in p["sugerida"] if s["ticker"] == "BOVA11")
print("BOVA11 porque:", bova["porque"][:110], "| contra:", bova["contra"])
print("checagem carteira:", p["checagem"])
assert "38,4" not in bova["porque"] and bova["contra"] == "Oscila com a bolsa." and any("BOVA11" in d["onde"] for d in p["checagem"]["detalhes"])
assert "Cite apenas números" in kw["system"]

# com objetivo: números do texto da pessoa são aceitos ("R$ 150 mil", "5 anos", "R$ 2.000")
p2 = c.post("/api/portfolio", headers=H, json={"pos": pos, "perfil": "moderado",
            "objetivo": "Entrada de um apartamento em 5 anos, preciso de R$ 150 mil e guardo R$ 2.000 por mês"}).json()
print("objetivo:", p2["objetivo_analise"]["resumo"][:100], "| checagem:", p2["checagem"])
assert "150 mil" in p2["objetivo_analise"]["resumo"]

# modelo das decisões indisponível na conta: usa o modelo padrão
def sem_opus(**kw):
    if kw["model"] == "claude-opus-5-5":
        raise anthropic.NotFoundError("model not found", response=httpx2.Response(404, request=httpx2.Request("POST", "https://x")), body=None)
    return orig(**kw)
server.client.messages.create = sem_opus
mocks.CALLS.clear(); server.cache.clear()
p3 = c.post("/api/portfolio", headers=H, json={"pos": pos, "perfil": "arrojado", "objetivo": ""}).json()
print("sem Opus na conta ->", p3["fonte"], [k["model"] for k in mocks.CALLS if "planejador" in k["system"]])
assert p3["fonte"] == "ia" and [k["model"] for k in mocks.CALLS if "planejador" in k["system"]] == [server.MODEL]
server.client.messages.create = orig

# ---- 4) sinais registrados e avaliação depois de 3, 6 e 12 meses
regs = acertos.todos_registros()
print("sinais registrados:", len(regs), sorted({(r["ticker"], r["fonte"], r["decisao"]) for r in regs})[:6])
antes = len(regs)
c.post("/api/analyze", headers=H, json={"ticker": "PETR4", "pos": {"qtd": 10, "pm": 20}})
assert len(acertos.todos_registros()) == antes, "não repete o mesmo sinal no mesmo mês"
velho = (date.today() - timedelta(days=400))
for t, d, f, cons in (("PETR4", "COMPRAR", "ia", "concordam"), ("ITUB4", "VENDER", "regras", None), ("BOVA11", "COMPRAR", "ia", "divergem")):
    acertos.registrar(t, d, 10.0, f, 60, cons, hoje=velho)
acertos.registrar("VOO", "COMPRAR", 500.0, "regras", 55, None, hoje=date.today() - timedelta(days=120))
av = acertos.avaliar(10.0)
print("avaliação:", json.dumps(av["fontes"], ensure_ascii=False))
print("total:", av["total"], "| pendentes 3m:", av["pendentes"], "| desde:", av["desde"])
assert set(av["fontes"]) >= {"ia", "regras", "consenso"} and av["fontes"]["ia"]["12m"]["n"] == 2 and av["fontes"]["consenso"]["12m"]["n"] == 1
assert av["fontes"]["regras"]["3m"]["n"] == 2 and av["fontes"]["regras"]["6m"]["n"] == 1
print("último:", {k: av["ultimos"][0][k] for k in ("ticker", "data", "decisao", "avaliacao", "pendente")})

# ---- 5) teste com o passado (20 anos) pelo endpoint
t0 = time.time()
r = c.get("/api/acertos", headers=H).json()
g = r["teste"]["geral"]
print(f"teste com o passado ({time.time() - t0:.1f}s): {r['teste']['ativos']} ativos desde {r['teste']['desde']} | cdi real: {r['teste']['cdi_real']}")
for h in ("3m", "6m", "12m"): print("  ", h, g[h])
print("   PETR4:", r["teste"]["por_ativo"].get("PETR4", {}).get("12m"))
print("   histórico:", r["historico"]["total"], "sinais | fontes:", list(r["historico"]["fontes"]))
assert r["teste"]["ativos"] >= 10 and g["12m"]["base"]["n"] > 1000 and r["teste"]["cdi_real"] and "PETR4" in r["teste"]["por_ativo"]
assert all(g[h]["COMPRAR"]["n"] + g[h]["VENDER"]["n"] <= g[h]["base"]["n"] for h in g)
# o sinal vetorizado do teste é o mesmo que o app calcula no dia
serie = server.sim.fechamentos_brl(["PETR4"])["PETR4"]
m = server.metrics("PETR4")
print("   sinal de hoje (teste x app):", acertos.sinais_serie(serie).iloc[-1], regras.analise_ativo(m)["decisao"])

# ---- 6) avisos de compra/venda só quando IA e regras concordam
c.put("/api/carteira", headers=H, json={"dados": {"pos": pos}, "base": 0})
an_orig = server.regras.analise_ativo
server.regras.analise_ativo = lambda m, *a: {**an_orig(m, *a), "decisao": "COMPRAR"}
c.post("/api/avisos/verificar", headers=H)  # 1ª: só registra
est = server.armazem.ler("avisos_estado", uid)["dados"]; est["sinal"]["PETR4"] = "MANTER"; server.armazem.gravar("avisos_estado", uid, est)
def ia_diz(dec):
    def f(**kw):
        msg = orig(**kw)
        if kw["system"].startswith("Você é um trader"):
            d = json.loads(msg.content[1].text); d["decisao"] = dec; msg.content[1].text = json.dumps(d)
        return msg
    return f
server.client.messages.create = ia_diz("VENDER"); server.cache.pop("m:PETR4", None)
n1 = c.post("/api/avisos/verificar", headers=H).json()
pend = server.armazem.ler("avisos_estado", uid)["dados"]["pendente"]
titulos = [x["titulo"] for x in c.get("/api/avisos", headers=H).json()["itens"]]
print("IA discorda -> avisos:", n1, "| pendente:", {k: (v["dec"], v.get("ia")) for k, v in pend.items()}, "| títulos:", titulos)
assert not any("PETR4: sinal" in x for x in titulos) and pend["PETR4"]["ia"] == "VENDER"
n2 = c.post("/api/avisos/verificar", headers=H).json()
print("logo depois (não pergunta de novo à IA antes de 6h):", n2)
est = server.armazem.ler("avisos_estado", uid)["dados"]; est["pendente"]["PETR4"]["checado"] = 0; server.armazem.gravar("avisos_estado", uid, est)
server.client.messages.create = ia_diz("COMPRAR"); server.cache.pop("m:PETR4", None)
n3 = c.post("/api/avisos/verificar", headers=H).json()
itens = c.get("/api/avisos", headers=H).json()["itens"]
x = next(i for i in itens if i["titulo"].startswith("PETR4: sinal"))
print("IA concorda ->", n3, "|", x["titulo"], "—", x["texto"])
assert "concordam" in x["texto"] and "PETR4" not in server.armazem.ler("avisos_estado", uid)["dados"]["pendente"]
# sem IA configurada: as regras avisam sozinhas
server.IA_ATIVA = False
est = server.armazem.ler("avisos_estado", uid)["dados"]; est["sinal"]["ITUB4"] = "MANTER"; server.armazem.gravar("avisos_estado", uid, est)
n4 = c.post("/api/avisos/verificar", headers=H).json()
x = next((i for i in c.get("/api/avisos", headers=H).json()["itens"] if i["titulo"].startswith("ITUB4: sinal")), None)
print("sem IA ->", n4, "|", x and x["texto"])
assert x and "concordam" not in x["texto"]
server.IA_ATIVA = True
server.regras.analise_ativo = an_orig
server.client.messages.create = orig

# ---- 7) panorama: checagem
o = c.get("/api/outlook", headers=H).json()
print("panorama checagem:", o["checagem"])
print("TUDO OK")
