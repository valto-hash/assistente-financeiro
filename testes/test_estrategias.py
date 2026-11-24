"""Escolha de estratégia: lista com o teste de cada uma, só as que cabem no perfil podem ser seguidas, a carteira segue a
estratégia escolhida (sem IA) e passa pela auditoria, e a escolha fica salva e na memória.
Uso: python3 testes/test_estrategias.py"""
import json, os, tempfile
os.environ["DATA_DIR"] = tempfile.mkdtemp(); os.environ["APP_TOKEN"] = ""
import mocks, server, armazem, estrategias, memoria, referencias, simulador as S  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
falhas = []
def ok(cond, msg):
    print(("  ok   " if cond else "  FALHA ") + msg)
    if not cond: falhas.append(msg)

c = TestClient(server.app)
T = c.post("/api/conta/cadastrar", json={"nome": "Teste", "email": "e@ex.com", "senha": "senhateste1"}).json()
H, uid = {"Authorization": "Bearer " + T["token"]}, T["usuario"]["id"]

# ---- 1) a lista de estratégias
ok(c.get("/api/estrategias").status_code == 401, "precisa estar logado")
j = c.get("/api/estrategias?perfil=moderado", headers=H).json()
E = {e["id"]: e for e in j["estrategias"]}
print("   ", [(e["id"], e["ret_aa"], e["maior_queda"], e["pior_crise"], e["cabe"]) for e in j["estrategias"]])
ok(list(E)[0] == "app" and "modelo_fixo" not in E and set(p["id"] for p in referencias.PLANOS) <= set(E) and not E["app"]["satelites"],
   "moderado: a recomendada (que já é só com ETFs e títulos) e os 11 planos consagrados, sem a opção repetida")
for pf in server.PERFIS:  # o "modelo só com ETFs" só aparece à parte onde o app escolhe ações (hoje, em nenhum perfil)
    Ea = {e["id"]: e for e in c.get(f"/api/estrategias?perfil={pf}", headers=H).json()["estrategias"]}
    ok(("modelo_fixo" in Ea) == server.ESCOLHE_ATIVOS[pf] and Ea["app"]["satelites"] == server.ESCOLHE_ATIVOS[pf]
       and Ea["app"].get("crise_sem_cambio"), f"{pf}: opções sem repetição, e a crise se o real não se desvalorizar aparece")
ok(all(abs(sum(e["classes"].values()) - 100) < 0.6 and abs(sum(e["ativos"].values()) - 100) < 0.6 for e in E.values()),
   "cada estratégia tem a divisão por classe e por ativo somando 100%")
ok(E["app"]["classes"] == server.PERFIS["moderado"] and E["app"]["cabe"],
   "a recomendada parte do modelo do perfil e sempre cabe nele")
lim = j["limite"]
regra = all(e["cabe"] == (e["maior_queda"] >= lim and (e["pior_crise"] is None or e["pior_crise"][1] >= lim)
                          and (e["queda_dia"] is None or e["queda_dia"] >= lim) and e["classes"]["renda_fixa"] >= j["rf_min"] - 0.5)
            and bool(e["motivo_nao_cabe"]) == (not e["cabe"]) for e in E.values() if e["tipo"] == "plano")
ok(regra, "um plano só cabe se a maior queda e a pior crise real ficarem dentro do limite do perfil, e o motivo aparece quando não cabe")
ok(all(e["pior_crise"] for e in E.values()), "todas passaram pelo teste das crises reais")
ok("motivos" not in E["all_weather"], "a lista não manda os textos internos")

# ---- 2) seguir uma estratégia que cabe no perfil
cabe = next(e for e in E.values() if e["tipo"] == "plano" and e["cabe"] and e["id"] != "cdi")
pos = {"PETR4": {"qtd": 100, "pm": 30}, "TESOURO_SELIC": {"saldo": 20000, "pct": 100}}
mocks.CALLS.clear()
p = c.post("/api/portfolio", headers=H, json={"pos": pos, "perfil": "moderado", "objetivo": "", "estrategia": cabe["id"]}).json()
pesos = {s["ticker"]: s["peso"] for s in p["sugerida"]}
print(f"   seguindo {cabe['nome']}:", p["estrategia"], pesos)
ok(p["fonte"] == "estrategia" and p["estrategia"]["seguida"] and p["estrategia"]["id"] == cabe["id"],
   f"a carteira segue a estratégia escolhida ({cabe['nome']})")
ok(not any("planejador" in k["system"] for k in mocks.CALLS), "estratégia de divisão fixa não usa a IA (nem gasta com ela)")
ok(abs(sum(pesos.values()) - 100) < 0.6 and all(abs(p["alvo"][cl] - v) < 0.6 for cl, v in cabe["classes"].items()),
   "a divisão por classe é a da estratégia")
ok(set(pesos) - set(cabe["ativos"]) <= {"TESOURO_SELIC"}, "os ativos são os da estratégia (mais a reserva de emergência, se faltar)")
ok(p["auditoria"]["aprovada"] and any(x["id"] == "crise" and x["ok"] for x in p["auditoria"]["checagens"]),
   "a carteira da estratégia passa pela auditoria completa")
petr = next((a for a in p["acoes"] if a["ativo"] == "PETR4"), None)
ok(petr and petr["acao"] in ("VENDER", "REDUZIR"), f"o que a pessoa tem fora da estratégia aparece para vender ou reduzir ({petr and petr['acao']})")

# ---- 3) estratégia que não cabe no perfil: vale a recomendada, com o motivo
server.cache.clear()
lim_orig = dict(server.PIOR_CRISE)
server.PIOR_CRISE["conservador"] = -0.5  # nenhum plano com risco cabe
p = c.post("/api/portfolio", headers=H, json={"pos": pos, "perfil": "conservador", "objetivo": "", "estrategia": "bolsa"}).json()
server.PIOR_CRISE.update(lim_orig); server.cache.clear()
print("   não cabe:", p["estrategia"])
ok(p["fonte"] != "estrategia" and not p["estrategia"]["seguida"] and "não cabe no seu perfil" in p["estrategia"]["motivo"]
   and "recomendada pelo app" in p["estrategia"]["motivo"], "estratégia fora do perfil não é seguida, e a tela diz por quê")

# ---- 4) dinheiro de curto prazo: estratégia com pouca renda fixa é barrada pela auditoria
arr = c.get("/api/estrategias?perfil=arrojado", headers=H).json()
risco = next((e for e in arr["estrategias"] if e["tipo"] == "plano" and e["cabe"] and e["classes"]["renda_fixa"] < 85), None)
if risco:
    p = c.post("/api/portfolio", headers=H, json={"pos": pos, "perfil": "arrojado", "objetivo": "Comprar um carro daqui a 1 ano",
                                                  "estrategia": risco["id"]}).json()
    print("   curto prazo:", p["estrategia"])
    ok(not p["estrategia"]["seguida"] and "curto prazo" in p["estrategia"]["motivo"].lower() and p["auditoria"]["aprovada"],
       f"{risco['nome']} não é seguida para dinheiro de curto prazo; vale a recomendada, que passa na auditoria")
else:
    ok(False, "deveria haver um plano com menos de 85% em renda fixa que cabe no arrojado")

# ---- 5) id desconhecido vira a recomendada; trocar de estratégia fica na memória
p = c.post("/api/portfolio", headers=H, json={"pos": pos, "perfil": "moderado", "objetivo": "", "estrategia": "inventada"}).json()
ok(p["estrategia"]["id"] == "app" and p["estrategia"]["seguida"], "estratégia desconhecida: vale a recomendada")
mocks.CALLS.clear(); server.cache.clear()
p = c.post("/api/portfolio", headers=H, json={"pos": pos, "perfil": "moderado", "objetivo": "", "estrategia": cabe["id"]}).json()
p2 = c.post("/api/portfolio", headers=H, json={"pos": pos, "perfil": "moderado", "objetivo": ""}).json()
kw = next(k for k in mocks.CALLS if "planejador" in k["system"])
hist = json.loads(kw["messages"][0]["content"]).get("historico_do_investidor") or {}
print("   memória:", hist.get("o_que_mudou_desde_entao"))
ok(any("a estratégia seguida mudou de " + cabe["nome"] in x for x in hist.get("o_que_mudou_desde_entao", [])),
   "voltar para a recomendada: a IA fica sabendo que a estratégia mudou")
ok(not any(x["id"] == "consistencia" and not x["ok"] for x in p2["auditoria"]["checagens"]),
   "mudar de estratégia não vira aviso de incoerência")
ent = memoria.entrada("moderado", "", [], {"reserva_meses": 6, "contas_mensais": 0})
ok("estrategia" not in ent, "quem segue a recomendada não ganha campo novo na memória (sem falsa mudança para quem já usava o app)")

# ---- 6) a escolha fica salva com a carteira (só quando não é a recomendada)
for est, esperado in (("all_weather", "all_weather"), ("app", None), ("inventada", None)):
    v = c.get("/api/carteira", headers=H).json()["versao"]
    c.put("/api/carteira", headers=H, json={"dados": {"pos": {}, "perfil": "moderado", "estrategia": est}, "base": v})
    ok(c.get("/api/carteira", headers=H).json()["dados"].get("estrategia") == esperado, f"estratégia '{est}' salva como {esperado}")

# ---- 7) simulador: os planos mostrados são os que podem ser escolhidos; a prova ao vivo guarda os planos
d = S.preparar()
x = S.simular(d, "moderado", server.PERFIS["moderado"], server.PIOR_CRISE["moderado"], cabem={cabe["id"]})
ok({l["id"] for l in x["linhas"] if l.get("plano")} == {cabe["id"]}, "no simulador, só os planos que cabem no perfil (queda e crises)")
reg = S.registrar_vivo(d, server.PERFIS)
k = list(reg["meses"])[-1]
ok(set(reg["meses"][k]["planos"]) == {p["id"] for p in referencias.PLANOS}, "a prova ao vivo guarda a carteira de cada plano antes do mês")
reg["meses"][(d["meses"][-2]).strftime("%Y-%m")] = reg["meses"][k]
v = S.resultado_vivo(d, reg, server.PERFIS)
ok(len(v["planos_meses"]) == 1 and set(v["planos"]) == {p["id"] for p in referencias.PLANOS}, "e mostra o resultado real de cada plano")
# ---- 8) perfis reformulados: a mesma definição em todo lugar
import re, perfil as teste_perfil
html = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "index.html")).read()
for k, dd in teste_perfil.DEFINICOES.items():
    ok(f"{k}: [{dd['nome']!r}, {dd['curto']!r}, {dd['para_quem']!r}]" in html and server.PIOR_CRISE[k] == -dd["limite"]
       and str(dd["limite"]) + "%" in dd["curto"], f"{k}: a tela, o limite de queda do app e a definição dizem a mesma coisa")
ok(all(abs(sum(m.values()) - 100) < 0.01 for m in server.PERFIS.values()), "cada modelo soma 100%")
ok(all(abs(sum(n.values()) - 1) < 1e-9 for p in server.NUCLEOS.values() for n in p.values()), "cada divisão dentro de uma classe soma 100%")
r = teste_perfil.avaliar({"queda": "vende_tudo", "frase": "seguranca", "impacto": "muito"})
ok(r["perfil"] == "conservador" and r["definicao"]["limite"] == 8, "o teste de perfil devolve a definição do perfil")
p = c.post("/api/portfolio", headers=H, json={"pos": pos, "perfil": "conservador", "objetivo": ""}).json()
pesos = {s_["ticker"]: s_["peso"] for s_ in p["sugerida"]}
print("   conservador:", p["fonte"], pesos)
nucleo = {a for n in {**server.regras.NUCLEO_PADRAO, **server.NUCLEOS["conservador"]}.values() for a in n}
ok(not any(server._individual(a) and a not in pos and a not in nucleo for a in pesos),
   "conservador: nenhuma ação ou FII individual novo fora dos núcleos (escolher ativos não melhorou este perfil)")
# ---- 9) teste pessoal: depois da descrição da pessoa, a carteira dela testada com os números dela
ok(c.post("/api/teste_pessoal", json={}).status_code == 401, "teste pessoal: precisa estar logado")
t = c.post("/api/teste_pessoal", headers=H, json={"perfil": "moderado", "estrategia": "app", "inicial": 20000, "mensal": 1500,
                                                    "anos": 5, "meta": 150000}).json()
print("   teste pessoal:", t["texto"][:220])
ok(t["anos"] == 5 and t["periodos"] >= 10 and t["inicial"] == 20000 and t["mensal"] == 1500 and not t["exemplo"]
   and t["aplicado"] == 20000 + 1500 * 60, "usa o valor, o aporte e o prazo da pessoa, em vários períodos reais")
ids = {x["id"] for x in t["estrategias"]}
cabem = {e["id"] for e in server.estrategias_perfil("moderado")["estrategias"] if e["cabe"]}
ok(ids == cabem and sum(x["sua"] for x in t["estrategias"]) == 1 and next(x for x in t["estrategias"] if x["sua"])["id"] == "app",
   "compara a estratégia da pessoa com todas as que cabem no perfil")
ok(all(x["pior"] <= x["mediana"] <= x["melhor"] and 0 <= x["chance_meta"] <= 100 for x in t["estrategias"]) and "meta" in t["texto"],
   "pior, mediana e melhor caso coerentes, e a chance de chegar à meta")
t2 = c.post("/api/teste_pessoal", headers=H, json={"perfil": "conservador", "estrategia": "app", "anos": 40}).json()
ok(t2["exemplo"] and t2["anos"] < 40 and "até" in t2["texto"], "sem valores informados usa exemplo e avisa; prazo maior que o histórico é limitado e avisado")
t3 = c.post("/api/teste_pessoal", headers=H, json={"perfil": "moderado", "estrategia": "all_weather", "inicial": 20000, "mensal": 1500,
                                                     "anos": 5, "meta": 150000}).json()
ok(next(x for x in t3["estrategias"] if x["sua"])["id"] == "all_weather", "quem escolheu outra estratégia vê o teste dela")
print("TUDO OK" if not falhas else f"{len(falhas)} FALHA(S)")
