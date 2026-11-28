"""Testa o que veio da comparação com os concorrentes: imposto de renda (apuração mensal, DARF, declaração), operações
registradas no app, lançamento rápido por frase, cartões com fatura e parcelas, agenda de proventos, comparador de renda
fixa, vencimentos, exportação em planilha, verificação em duas etapas e WhatsApp.
Uso: python3 testes/test_novidades.py"""
import os, sys, json, tempfile, time, hmac, hashlib
from datetime import date, timedelta
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))
os.environ["DATA_DIR"] = tempfile.mkdtemp()
os.environ.update(APP_TOKEN="", WHATSAPP_TOKEN="tok", WHATSAPP_PHONE_ID="123", WHATSAPP_VERIFY_TOKEN="verifica",
                  WHATSAPP_APP_SECRET="segredo-wa", WHATSAPP_NUMERO="5511900000000")
import mocks, server, usuarios, ir, rendafixa, gastos  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
c = TestClient(server.app)
falhas = []
def ok(cond, msg):
    print(("  ok   " if cond else "  FALHA ") + msg)
    if not cond: falhas.append(msg)

S = c.post("/api/conta/cadastrar", json={"nome": "Nova", "email": "nova@ex.com", "senha": "senhateste1"}).json()
H = {"Authorization": "Bearer " + S["token"]}
uid = S["usuario"]["id"]

print("== imposto de renda (regras da Receita)")
movs = [
    {"data": "2025-01-10", "ticker": "PETR4", "tipo": "compra", "qtd": 1000, "preco": 30.0},
    {"data": "2025-02-10", "ticker": "PETR4", "tipo": "venda", "qtd": 500, "preco": 36.0},     # vendas 18 mil: isento
    {"data": "2025-03-10", "ticker": "PETR4", "tipo": "venda", "qtd": 500, "preco": 50.0},     # vendas 25 mil: 15% de 10 mil
    {"data": "2025-04-01", "ticker": "HGLG11", "tipo": "compra", "qtd": 100, "preco": 160.0},
    {"data": "2025-05-05", "ticker": "HGLG11", "tipo": "venda", "qtd": 50, "preco": 150.0},    # FII: prejuízo de 500
    {"data": "2025-06-05", "ticker": "HGLG11", "tipo": "venda", "qtd": 50, "preco": 180.0},    # lucro 1000 - 500 = 500 * 20%
    {"data": "2025-07-01", "ticker": "BOVA11", "tipo": "compra", "qtd": 10, "preco": 100.0},
    {"data": "2025-07-20", "ticker": "BOVA11", "tipo": "venda", "qtd": 10, "preco": 105.0},    # ETF: 50 de lucro, 7,50 < 10
    {"data": "2025-08-04", "ticker": "BOVA11", "tipo": "compra", "qtd": 10, "preco": 100.0},
    {"data": "2025-08-29", "ticker": "BOVA11", "tipo": "venda", "qtd": 10, "preco": 110.0},    # 100 * 15% = 15 + 7,50 acumulado
]
ap = ir.apurar(movs)
M = {m["mes"]: m for m in ap["meses"]}
ok(M["2025-02"]["isento_acoes"] and M["2025-02"]["darf"] == 0 and M["2025-02"]["lucro_isento"] == 3000, f"fev: vendas de R$ 18 mil isentas, lucro isento {M['2025-02']['lucro_isento']}")
ok(abs(M["2025-03"]["darf"] - 1500) < 0.01 and M["2025-03"]["codigo"] == "6015", f"mar: 15% de R$ 10 mil = {M['2025-03']['darf']}")
ok(M["2025-03"]["vencimento"] == "2025-04-30", f"DARF vence no último dia útil do mês seguinte: {M['2025-03']['vencimento']}")
ok(M["2025-05"]["darf"] == 0 and M["2025-05"]["prejuizo_a_compensar"].get("fii") == 500, f"FII com prejuízo guarda R$ 500: {M['2025-05']['prejuizo_a_compensar']}")
ok(abs(M["2025-06"]["darf"] - 100) < 0.01, f"FII compensa o prejuízo: 20% de 500 = {M['2025-06']['darf']}")
ok(M["2025-07"]["darf"] == 0 and abs(M["2025-07"]["acumulado_proximo"] - 7.5) < 0.01, f"DARF abaixo de R$ 10 fica para o mês seguinte: {M['2025-07']['acumulado_proximo']}")
ok(abs(M["2025-08"]["darf"] - 22.5) < 0.01 and M["2025-08"]["vencimento"] == "2025-09-30", f"ago soma o acumulado: {M['2025-08']['darf']}")
dt = [{"data": "2025-09-02", "ticker": "VALE3", "tipo": "compra", "qtd": 100, "preco": 60.0},
      {"data": "2025-09-02", "ticker": "VALE3", "tipo": "venda", "qtd": 100, "preco": 62.0}]
ok(abs(ir.apurar(dt)["meses"][0]["darf"] - 40) < 0.01, "day trade: 20% de R$ 200 mesmo com vendas pequenas")
dc = ir.declaracao(movs + [{"data": "2025-10-01", "ticker": "ITSA4", "tipo": "compra", "qtd": 100, "preco": 10.0}],
                   [{"data": "2025-11-10", "ticker": "ITSA4", "tipo": "Dividendo", "valor": 12.0},
                    {"data": "2025-11-10", "ticker": "ITSA4", "tipo": "JCP", "valor": 8.0}], 2025, {"TESOURO_SELIC": 5000})
bens = {b["ticker"]: b for b in dc["bens"]}
ok(bens["ITSA4"]["custo_31_12"] == 1000 and bens["ITSA4"]["grupo"] == "03" and "PETR4" not in bens, "bens e direitos pelo custo, só o que sobrou")
ok(dc["isentos"]["Dividendos"] == 12 and dc["tributacao_exclusiva"]["Juros sobre capital próprio"] == 8, "dividendos isentos e JCP exclusivo")
ok("TESOURO_SELIC" in bens, "renda fixa entra nos bens")

print("== operações pelo app e rota /api/ir")
ok(c.post("/api/operacoes", headers=H, json={"data": "2099-01-01", "ticker": "PETR4", "tipo": "compra", "qtd": 1, "preco": 1}).status_code == 400, "data no futuro recusada")
for m in movs[:3]:
    ok(c.post("/api/operacoes", headers=H, json=m).status_code == 200, f"registrou {m['tipo']} de {m['ticker']}")
r = c.get("/api/ir?ano=2025", headers=H).json()
ok(any(m["mes"] == "2025-03" and abs(m["darf"] - 1500) < .01 for m in r["meses"]) and "contador" in r["aviso"], "rota /api/ir apura as operações registradas")
ops = c.get("/api/operacoes", headers=H).json()["itens"]
ok(c.delete("/api/operacoes/" + ops[0]["id"], headers=H).status_code == 200 and len(c.get("/api/operacoes", headers=H).json()["itens"]) == 2, "apaga operação")

print("== lançamento rápido e cartões")
hoje = date(2026, 11, 28)
x = gastos.interpretar("gastei 52,90 no mercado ontem", hoje)
ok(x["valor"] == -52.9 and x["data"] == "2026-11-27" and x["descricao"].lower().startswith("mercado"), f"frase simples: {x}")
x = gastos.interpretar("recebi 1.500 de salário dia 05/11", hoje)
ok(x["valor"] == 1500 and x["data"] == "2026-11-05" and "Salário" in x["descricao"], f"receita com data e acento: {x}")
car = c.post("/api/cartoes", headers=H, json={"nome": "Nubank", "fecha": 3, "vence": 10, "limite": 5000}).json()
ok(car.get("id") and c.post("/api/cartoes", headers=H, json={"nome": "", "fecha": 40, "vence": 1}).status_code == 400, "cadastra cartão e recusa inválido")
ok(gastos.fatura_de(car, date(2026, 11, 2)) == ("2026-11", date(2026, 11, 10)) and gastos.fatura_de(car, date(2026, 11, 3))[0] == "2026-12",
   "compra antes do fechamento cai na fatura do mês; no dia do fechamento, na seguinte")
r = c.post("/api/gastos/rapido", headers=H, json={"texto": "comprei TV 2400 em 10x no cartão nubank", "confirmar": False}).json()
ok(r["entendido"]["parcelas"] == 10 and r["entendido"]["cartao"] == car["id"] and r["criados"] == [], "prévia não lança nada")
r = c.post("/api/gastos/rapido", headers=H, json={"texto": "comprei TV 2400 em 10x no cartão nubank"}).json()
ok(len(r["criados"]) == 10 and all(i["valor"] == -240 for i in r["criados"]) and r["criados"][9]["parcela"] == "10/10", "10 parcelas de R$ 240")
fat = c.get("/api/cartoes", headers=H).json()["cartoes"][0]
ok(fat["limite_usado"] >= 2400 - 240 and len(fat["faturas"]) >= 9, f"faturas abertas: {len(fat['faturas'])}, limite usado {fat['limite_usado']}")
r = c.post("/api/gastos", headers=H, json=[{"data": "2026-11-20", "descricao": "Sapato", "valor": -300, "cartao": car["id"], "parcelas": 3}])
ok(r.status_code == 200 and len(r.json()["criados"]) == 3, "compra parcelada pelo formulário")
ok(c.post("/api/gastos/rapido", headers=H, json={"texto": "almoço"}).status_code == 400, "sem valor: pede o valor")
ok(c.delete("/api/cartoes/" + car["id"], headers=H).status_code == 200, "apaga cartão")

print("== renda fixa e agenda")
a = rendafixa.simular({"tipo": "lci", "taxa": 90}, 10000, 365, 10, 4)
b = rendafixa.simular({"tipo": "cdb", "taxa": 100}, 10000, 365, 10, 4)
ok(a["ir"] == 0 and abs(b["ir"] - (b["bruto"] - 10000) * 0.175) < 0.01, "LCI isenta; CDB de 1 ano paga 17,5%")
ok(rendafixa.aliquota_ir(180) == .225 and rendafixa.aliquota_ir(181) == .2 and rendafixa.aliquota_ir(721) == .15, "tabela regressiva")
cp = c.post("/api/rendafixa/comparar", json={"valor": 10000, "dias": 365, "opcoes": [{"tipo": "lci", "taxa": 90}, {"tipo": "cdb", "taxa": 100}]}).json()
lci = next(o for o in cp["opcoes"] if o["tipo"] == "lci")
ok(lci["equivale_cdb_pct_cdi"] > 100 and cp["melhor"] in ("lci", "cdb") and "promessa" in cp["aviso"], f"LCI 90% equivale a CDB de {lci['equivale_cdb_pct_cdi']}% do CDI")
c.put("/api/carteira", headers=H, json={"dados": {"pos": {"TESOURO_IPCA": {"saldo": 1000, "venc": (date.today() + timedelta(days=20)).isoformat()},
                                                         "PETR4": {"qtd": 100, "pm": 30}}}, "base": 0})
v = c.get("/api/rendafixa/vencimentos", headers=H).json()["itens"]
ok(len(v) == 1 and v[0]["situacao"] == "vence em até 30 dias", f"vencimento guardado e avisado: {v}")
ag = c.post("/api/agenda_proventos", headers=H, json={"pos": {"HGLG11": {"qtd": 100}, "BOVA11": {"qtd": 10}}}).json()
h = next((x for x in ag.get("ativos", []) if x["ticker"] == "HGLG11"), None)
ok(h and h["frequencia"] == "mensal" and h["proxima_estimada"] > date.today().isoformat() and len(h["pagamentos_12m"]) >= 11
   and all(x["ticker"] != "BOVA11" for x in ag["ativos"]) and "estimadas" in ag["aviso"] and ag["proximos_meses"],
   f"agenda: FII mensal, próxima data-com estimada {h and h['proxima_estimada']}, sem ETFs")

print("== exportar")
for t in ("carteira", "operacoes", "ir", "gastos"):
    e = c.get("/api/exportar/" + t, headers=H)
    ok(e.status_code == 200 and "text/csv" in e.headers["content-type"] and e.text.count("\n") >= 2, f"planilha de {t}: {e.text.count(chr(10))} linhas")
ok(c.get("/api/exportar/xyz", headers=H).status_code == 404 and c.get("/api/exportar/gastos").status_code == 401, "tipo desconhecido e sem login recusados")

print("== verificação em duas etapas")
ini = c.post("/api/conta/2fa/iniciar", headers=H).json()
ok(ini["uri"].startswith("otpauth://totp/") and len(ini["segredo"]) >= 26, "gera o segredo para o app autenticador")
ok(c.post("/api/conta/2fa/ativar", headers=H, json={"codigo": "000000"}).status_code == 400, "código errado não liga")
ok(c.post("/api/conta/2fa/ativar", headers=H, json={"codigo": usuarios.totp(ini["segredo"])}).status_code == 200, "liga com o código certo")
r = c.post("/api/conta/entrar", json={"email": "nova@ex.com", "senha": "senhateste1"})
ok(r.status_code == 401 and r.json()["detail"]["precisa_2fa"], "senha certa sem código: pede o código")
r = c.post("/api/conta/entrar", json={"email": "nova@ex.com", "senha": "senhateste1", "codigo": usuarios.totp(ini["segredo"])})
ok(r.status_code == 200 and r.json()["usuario"]["dois_fatores"], "entra com senha e código")
ok(c.post("/api/conta/2fa/desativar", headers=H, json={"codigo": "123"}).status_code == 400, "desligar exige o código")
ok(c.post("/api/conta/2fa/desativar", headers=H, json={"codigo": usuarios.totp(ini["segredo"])}).status_code == 200
   and c.post("/api/conta/entrar", json={"email": "nova@ex.com", "senha": "senhateste1"}).status_code == 200, "desligado, volta a entrar só com a senha")

print("== WhatsApp")
ok(c.get("/api/whatsapp/webhook", params={"hub.mode": "subscribe", "hub.verify_token": "verifica", "hub.challenge": "42"}).text == "42", "verificação da Meta")
ok(c.get("/api/whatsapp/webhook", params={"hub.mode": "subscribe", "hub.verify_token": "errado", "hub.challenge": "42"}).status_code == 403, "token errado recusado")
cod = c.post("/api/whatsapp/codigo", headers=H).json()["codigo"]
ok("não está ligado" in server.wa_mensagem("5511988887777", "gastei 10 no café"), "número desconhecido não lança")
ok("Pronto" in server.wa_mensagem("5511988887777", f"vincular {cod}") and "inválido" in server.wa_mensagem("5511900001111", f"vincular {cod}"),
   "vincula com o código, que só vale uma vez")
antes = len(gastos.ler(uid)["itens"])
resp = server.wa_mensagem("5511988887777", "gastei 35,50 no uber hoje")
ok("Anotado" in resp and "35,50" in resp and len(gastos.ler(uid)["itens"]) == antes + 1, f"lança pela mensagem: {resp}")
ok(c.get("/api/whatsapp", headers=H).json()["vinculado"] == "final 7777", "tela mostra o final do número")
enviados = []
server.wa_enviar = lambda para, txt: enviados.append((para, txt))
corpo = json.dumps({"entry": [{"changes": [{"value": {"messages": [{"from": "5511988887777", "type": "text", "text": {"body": "paguei 20 de pão"}}]}}]}]}).encode()
ok(c.post("/api/whatsapp/webhook", content=corpo, headers={"x-hub-signature-256": "sha256=errada"}).status_code == 403, "assinatura errada recusada")
sig = "sha256=" + hmac.new(b"segredo-wa", corpo, hashlib.sha256).hexdigest()
ok(c.post("/api/whatsapp/webhook", content=corpo, headers={"x-hub-signature-256": sig, "content-type": "application/json"}).status_code == 200, "assinatura certa aceita")
time.sleep(0.5)
ok(enviados and "Anotado" in enviados[0][1], f"responde no WhatsApp: {enviados[:1]}")
ok("desligado" in server.wa_mensagem("5511988887777", "desvincular") and c.get("/api/whatsapp", headers=H).json()["vinculado"] is None, "desvincula")

print("\n" + ("TUDO OK" if not falhas else f"{len(falhas)} FALHA(S): " + "; ".join(falhas)))
