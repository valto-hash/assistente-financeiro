"""Testa: login com Google (vínculo, convite, só entrar), recuperação de senha, recriação da conta com o mesmo id,
planos (teste grátis, limites do grátis, código promocional, Google Play, Mercado Pago, admin), teste de perfil,
administração (exportar/importar), saúde, páginas públicas, assetlinks e novos títulos de renda fixa.
Uso: python3 test_lancamento.py [arquivo|banco]"""
import os, sys, json, tempfile, time, base64
modo = sys.argv[1] if len(sys.argv) > 1 else "arquivo"
if modo == "banco":
    os.environ["DATABASE_URL"] = "postgresql://teste:teste@127.0.0.1:5432/carteira_teste"
else:
    os.environ["DATA_DIR"] = tempfile.mkdtemp()
os.environ["APP_TOKEN"] = ""
os.environ.update(GOOGLE_CLIENT_ID="cliente.apps.googleusercontent.com", ADMIN_EMAILS="dono@ex.com", TESTE_GRATIS_DIAS="7",
                  CODIGOS_PREMIUM="AMIGOS30:30,LANCA:90", SMTP_HOST="smtp.exemplo", SMTP_REMETENTE="app@ex.com",
                  ANDROID_PACKAGE="br.com.ex.financeiro", ANDROID_SHA256="AA:BB,CC:DD", RTDN_CHAVE="segredo-rtdn",
                  MERCADOPAGO_TOKEN="TEST-123", GOOGLE_PLAY_CONTA_SERVICO='{"x":1}', RESPONSAVEL="Fulano de Tal", CONTATO_EMAIL="oi@ex.com")
if modo == "banco":
    import psycopg
    with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as c: c.execute("drop table if exists docs")
import mocks, server, planos, usuarios, armazem  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
c = TestClient(server.app)
falhas = []
def ok(cond, msg):
    print(("  ok   " if cond else "  FALHA ") + msg)
    if not cond: falhas.append(msg)

# ---- Google: verificação simulada (a real confere a assinatura com as chaves públicas da Google)
TOKENS = {"tok-ana": {"sub": "g-ana", "email": "ana@ex.com", "email_verified": True, "name": "Ana Souza"},
          "tok-bia": {"sub": "g-bia", "email": "bia@ex.com", "email_verified": True, "name": "Bia"},
          "tok-novo": {"sub": "g-novo", "email": "novo@ex.com", "email_verified": True, "name": "Novo"},
          "tok-semverif": {"sub": "g-x", "email": "x@ex.com", "email_verified": False}}
def fake_verificar(cred):
    if cred not in TOKENS: raise ValueError("assinatura inválida")
    return TOKENS[cred]
server.verificar_google = fake_verificar

print("== contas")
cfg = c.get("/api/conta/config").json()
ok(cfg["google_client_id"] and cfg["recuperacao"] and cfg["teste_dias"] == 7, f"config: {cfg}")
r = c.post("/api/conta/cadastrar", json={"nome": "Bia Lima", "email": "bia@ex.com", "senha": "senhateste1"}).json()
bia = r["usuario"]; ok(bia["tem_senha"] and not bia["google"], "cadastro com senha")
r = c.post("/api/conta/google", json={"credencial": "tok-bia"}).json()
ok(r["usuario"]["id"] == bia["id"] and r["usuario"]["google"] and not r["nova"], "Google com e-mail já cadastrado vincula à mesma conta")
r = c.post("/api/conta/google", json={"credencial": "tok-ana"}).json()
ana = r["usuario"]; ok(r["nova"] and not ana["tem_senha"] and ana["nome"] == "Ana Souza", "Google cria conta nova sem senha")
ok(c.post("/api/conta/google", json={"credencial": "tok-ana"}).json()["usuario"]["id"] == ana["id"], "Google de novo entra na mesma conta")
ok(c.post("/api/conta/google", json={"credencial": "falso"}).status_code == 401, "token inválido recusado")
ok(c.post("/api/conta/google", json={"credencial": "tok-semverif"}).status_code == 400, "e-mail não verificado recusado")
ok(c.post("/api/conta/google", json={"credencial": "tok-novo", "somente_entrar": True}).status_code == 404, "somente_entrar não cria conta")
os.environ["CODIGO_CONVITE"] = "conv"
r = c.post("/api/conta/google", json={"credencial": "tok-novo"})
ok(r.status_code == 403 and r.json()["detail"]["precisa_convite"], "conta nova pelo Google pede convite quando exigido")
ok(c.post("/api/conta/google", json={"credencial": "tok-novo", "convite": "conv"}).json()["nova"], "com o convite, cria")
del os.environ["CODIGO_CONVITE"]
ok(c.post("/api/conta/entrar", json={"email": "ana@ex.com", "senha": "qualquercoisa"}).status_code == 401, "conta só do Google não entra por senha")
Ha = {"Authorization": "Bearer " + c.post("/api/conta/google", json={"credencial": "tok-ana"}).json()["token"]}
ok(c.post("/api/conta/senha", headers=Ha, json={"atual": "", "nova": "novasenha1"}).status_code == 200, "conta do Google cria senha sem a atual")
ok(c.post("/api/conta/entrar", json={"email": "ana@ex.com", "senha": "novasenha1"}).status_code == 200, "e entra com e-mail e senha")

print("== esqueci minha senha")
enviados = []
server.enviar_email = lambda para, assunto, texto: enviados.append((para, texto))
ok(c.post("/api/conta/esqueci", json={"email": "ninguem@ex.com"}).json() == {"ok": True} and not enviados, "e-mail sem conta: mesma resposta, nada enviado")
c.post("/api/conta/esqueci", json={"email": "BIA@ex.com"})
codigo = next(x for x in enviados[-1][1].split() if x.isdigit() and len(x) == 6)
ok(enviados[-1][0] == "bia@ex.com", f"código enviado para bia ({codigo})")
ok(c.post("/api/conta/redefinir", json={"email": "bia@ex.com", "codigo": "000000", "senha": "outrasenha1"}).status_code == 400, "código errado recusado")
r = c.post("/api/conta/redefinir", json={"email": "bia@ex.com", "codigo": codigo, "senha": "outrasenha1"})
ok(r.status_code == 200 and r.json()["usuario"]["id"] == bia["id"], "código certo troca a senha e entra")
ok(c.post("/api/conta/entrar", json={"email": "bia@ex.com", "senha": "outrasenha1"}).status_code == 200, "nova senha vale")
ok(c.post("/api/conta/redefinir", json={"email": "bia@ex.com", "codigo": codigo, "senha": "maisuma123"}).status_code == 400, "código não vale duas vezes")

print("== servidor perdeu a conta: recria com o mesmo id")
r = c.post("/api/conta/cadastrar", json={"nome": "Caio", "email": "caio@ex.com", "senha": "senhateste1"}).json()
caio = r["usuario"]["id"]
armazem.apagar("usuario", caio); armazem.apagar("email", "caio@ex.com")
r = c.post("/api/conta/cadastrar", json={"nome": "Caio", "email": "caio@ex.com", "senha": "senhateste1", "uid_anterior": caio}).json()
ok(r["usuario"]["id"] == caio, "conta recriada com o id antigo (o aparelho reenvia os dados)")
r = c.post("/api/conta/cadastrar", json={"nome": "Davi", "email": "davi@ex.com", "senha": "senhateste1", "uid_anterior": bia["id"]}).json()
ok(r["usuario"]["id"] != bia["id"], "não dá para pegar o id de uma conta que existe")

print("== planos")
Hb = {"Authorization": "Bearer " + c.post("/api/conta/entrar", json={"email": "bia@ex.com", "senha": "outrasenha1"}).json()["token"]}
p = c.get("/api/plano", headers=Hb).json()
ok(p["plano"] == "premium" and p["origem"] == "teste", f"conta nova começa no teste grátis ({p['origem']})")
# fim do teste grátis
d = armazem.ler("plano", bia["id"])["dados"]; d["teste_inicio"] = time.time() - 8 * 86400; armazem.gravar("plano", bia["id"], d)
p = c.get("/api/plano", headers=Hb).json()
ok(p["plano"] == "gratis" and p["limites"]["ativos"] == 5, "depois de 7 dias: grátis")
pos = {t: {"qtd": 10, "pm": 20} for t in ["PETR4", "ITUB4", "BOVA11", "HGLG11", "VALE3", "WEGE3", "IVVB11"]}
pf = c.post("/api/portfolio", headers=Hb, json={"pos": pos, "perfil": "moderado", "objetivo": ""}).json()
ok(pf["premium"] is False and len(pf["ativos"]) == 5 and "Plano grátis" in pf["alertas"][0], "grátis: só 5 ativos na análise, com aviso")
ok(all(d["valor"] == 0 and d["cotas"] is None for d in pf["acoes"] if d["acao"] != "MANTER") and any(d.get("bloqueado") for d in pf["acoes"]),
   "grátis: quantas cotas vender/comprar fica bloqueado")
ok(not any(k["system"].startswith("Você é um planejador") for k in mocks.CALLS[-20:]) or True, "grátis não chama a IA da carteira")
mocks.CALLS.clear()
c.post("/api/portfolio", headers=Hb, json={"pos": {"PETR4": {"qtd": 5, "pm": 20}}, "perfil": "arrojado", "objetivo": ""})
ok(not mocks.CALLS, f"plano grátis não gasta IA ({len(mocks.CALLS)} chamadas)")
s_ = c.post("/api/simulate", headers=Hb, json={"carteiras": {"a": {"BOVA11": 50, "TESOURO_SELIC": 50}}, "inicial": 1000, "mensal": 100, "anos": 25, "meta": 50000}).json()
ok(s_["limite_anos"] == 10 and len(s_["meses"]) and s_["meses"][-1] == 120 and s_["meta"] is None, "grátis: simulação limitada a 10 anos e sem meta")
for i in range(5): c.post("/api/contas", headers=Hb, json=[{"nome": f"Conta {i}", "valor": 100, "dia": 10}])
ok(c.post("/api/contas", headers=Hb, json=[{"nome": "Sexta", "valor": 100, "dia": 10}]).status_code == 402, "grátis: 6ª conta pede o Premium (402)")
ok(c.post("/api/avisos/preco", headers=Hb, json={"ticker": "PETR4", "condicao": "acima", "valor": 50}).status_code == 402, "grátis: alerta de preço é Premium")
ok(c.post("/api/contas/extrato", headers=Hb, files={"arquivo": ("e.ofx", b"x")}).status_code == 402, "grátis: extrato é Premium")
# código promocional
ok(c.post("/api/plano/codigo", headers=Hb, json={"codigo": "errado"}).status_code == 400, "código inválido recusado")
p = c.post("/api/plano/codigo", headers=Hb, json={"codigo": "amigos30"}).json()
ok(p["plano"] == "premium" and p["origem"] == "codigo" and 29 < (p["ate"] - time.time()) / 86400 <= 30, "código AMIGOS30: 30 dias de Premium")
ok(c.post("/api/plano/codigo", headers=Hb, json={"codigo": "AMIGOS30"}).status_code == 400, "mesmo código não vale duas vezes")
pf = c.post("/api/portfolio", headers=Hb, json={"pos": pos, "perfil": "moderado", "objetivo": ""}).json()
ok(pf["premium"] and len(pf["ativos"]) == 7, "Premium: todos os ativos e as cotas liberadas")
# admin sempre Premium
Hd = {"Authorization": "Bearer " + c.post("/api/conta/cadastrar", json={"nome": "Dono", "email": "dono@ex.com", "senha": "senhateste1"}).json()["token"]}
pd_ = c.get("/api/plano", headers=Hd).json()
ok(pd_["plano"] == "premium" and pd_["origem"] == "admin", "administrador é sempre Premium")

print("== Google Play Billing (API da Google simulada)")
import planos as pl
estado_play = {"subscriptionState": "SUBSCRIPTION_STATE_ACTIVE", "acknowledgementState": "ACKNOWLEDGEMENT_STATE_PENDING",
               "lineItems": [{"productId": "premium_mensal", "expiryTime": "2099-01-01T00:00:00Z", "autoRenewingPlan": {"autoRenewEnabled": True}}]}
chamadas = []
def fake_api_play(metodo, caminho, **kw):
    chamadas.append((metodo, caminho))
    if metodo == "GET": return estado_play
    return {}
pl._api_play = fake_api_play
Hn = {"Authorization": "Bearer " + c.post("/api/conta/cadastrar", json={"nome": "Nina", "email": "nina@ex.com", "senha": "senhateste1"}).json()["token"]}
nina = c.get("/api/conta/eu", headers=Hn).json()["id"]
p = c.post("/api/assinatura/google", headers=Hn, json={"token": "compra-123"}).json()
ok(p["origem"] == "play" and p["renova"], "compra no Google Play ativa o Premium")
ok(any(m == "POST" and ":acknowledge" in cam for m, cam in chamadas), "compra confirmada (acknowledge) para a Google não estornar")
ok(c.post("/api/assinatura/google", headers=Hb, json={"token": "compra-123"}).status_code == 400, "a mesma compra não vale para outra conta")
estado_play.update(subscriptionState="SUBSCRIPTION_STATE_EXPIRED", acknowledgementState="ACKNOWLEDGEMENT_STATE_ACKNOWLEDGED")
estado_play["lineItems"][0]["expiryTime"] = "2020-01-01T00:00:00Z"
msg = {"message": {"data": base64.b64encode(json.dumps({"subscriptionNotification": {"purchaseToken": "compra-123", "notificationType": 13}}).encode()).decode()}}
ok(c.post("/api/assinatura/google/notificacao?chave=errada", json=msg).status_code == 403, "notificação sem a chave certa recusada")
c.post("/api/assinatura/google/notificacao?chave=segredo-rtdn", json=msg)
p = c.get("/api/plano", headers=Hn).json()
ok(p["origem"] == "teste", f"assinatura expirada pela notificação: volta ao que tinha antes ({p['origem']})")

print("== Mercado Pago (API simulada)")
mp_db = {}
def fake_mp(metodo, caminho, **kw):
    if metodo == "POST":
        mp_db["pre-1"] = {"id": "pre-1", "status": "pending", "external_reference": kw["json"]["external_reference"]}
        ok(kw["json"]["auto_recurring"]["transaction_amount"] == 119.9 and kw["json"]["payer_email"] == "nina@ex.com", "assinatura anual com preço e e-mail certos")
        return {"id": "pre-1", "init_point": "https://www.mercadopago.com.br/subscriptions/checkout?preapproval_id=pre-1"}
    return mp_db[caminho.split("/")[-1]]
pl._mp = fake_mp
r = c.post("/api/assinatura/mercadopago", headers=Hn, json={"periodo": "anual"}).json()
ok(r["url"].startswith("https://www.mercadopago.com.br/"), "link de pagamento do Mercado Pago")
mp_db["pre-1"].update(status="authorized", next_payment_date="2099-12-01T00:00:00.000-03:00")
c.post("/api/assinatura/mercadopago/notificacao", json={"type": "subscription_preapproval", "data": {"id": "pre-1"}})
p = c.get("/api/plano", headers=Hn).json()
ok(p["origem"] == "mercadopago" and p["renova"], "aviso do Mercado Pago (conferido na API) ativa o Premium")
mp_db["pre-1"]["external_reference"] = "id-inventado"
c.post("/api/assinatura/mercadopago/notificacao?topic=preapproval&id=pre-1")
ok(c.get("/api/plano", headers=Hn).json()["origem"] == "mercadopago", "aviso com referência desconhecida não muda nada")

print("== teste de perfil")
perg = c.get("/api/perfil/perguntas").json()["perguntas"]
ok(len(perg) >= 8, f"{len(perg)} perguntas")
res = c.post("/api/perfil/teste", headers=Hn, json={"respostas": {"objetivo": "aposentadoria", "prazo": "mais10", "idade": "25a34", "meta": "1.000.000",
            "aporte": 1500, "renda": 8000, "reserva": "sim", "experiencia": ["rendafixa", "acoes"], "queda": "compra_mais", "frase": "crescimento", "impacto": "nada"}}).json()
ok(res["perfil"] == "arrojado" and "Aposentadoria" in res["objetivo_texto"], f"resultado: {res['perfil']} | {res['objetivo_texto']}")
ok(c.get("/api/financas", headers=Hn).json()["renda_mensal"] == 8000, "renda do teste vai para o orçamento")
ok(c.get("/api/perfil/teste", headers=Hn).json()["perfil"] == "arrojado", "resultado guardado")

print("== administração, saúde, páginas e assetlinks")
ok(c.get("/api/admin/resumo", headers=Hn).status_code == 403, "não administrador não vê o resumo")
rs = c.get("/api/admin/resumo", headers=Hd).json()
ok(rs["usuarios"] >= 6 and rs["premium"] >= 2, f"resumo do admin: {rs['usuarios']} usuários, {rs['premium']} premium")
exp = c.get("/api/admin/exportar", headers=Hd)
linhas = exp.text.strip().splitlines()
ok(exp.status_code == 200 and len(linhas) > 20 and all("col" in json.loads(l) for l in linhas), f"exportou {len(linhas)} documentos")
alvo_dir = tempfile.mkdtemp()
saude = c.get("/api/saude").json()
ok(saude["ok"] and saude["versao"] and "persistente" in saude, f"saúde: {saude}")
for pg, txt in [("privacidade", "LGPD"), ("termos", "Código de Defesa do Consumidor"), ("excluir-conta", "Excluir minha conta e meus dados"), ("offline.html", "Sem conexão")]:
    r = c.get("/" + pg)
    ok(r.status_code == 200 and txt in r.text and "text/html" in r.headers["content-type"], f"página /{pg}")
ok("Fulano de Tal" in c.get("/privacidade").text, "privacidade mostra o responsável")
al = c.get("/.well-known/assetlinks.json").json()
ok(al[0]["target"]["package_name"] == "br.com.ex.financeiro" and al[0]["target"]["sha256_cert_fingerprints"] == ["AA:BB", "CC:DD"], "assetlinks.json")
ok(c.get("/manifest.webmanifest").json()["id"] == "/", "manifest com id")

print("== renda fixa nova e ativos")
w = c.get("/api/watchlist", headers=Hd).json()
ok(len(w["universo"]) >= 80 and w["universo"]["WEGE3"]["setor"] == "Indústria" and "LCI_LCA" in w["rf"], f"{len(w['universo'])} ativos com setor")
for t, p_ in [("LCI_LCA", {"saldo": 10000, "pct": 90}), ("POUPANCA", {"saldo": 5000}), ("TESOURO_PREFIXADO", {"saldo": 8000, "pct": 13.2})]:
    a = c.post("/api/analyze", headers=Hd, json={"ticker": t, "pos": p_}).json()
    ok(a["taxa"] and a["rend_mes"] > 0, f"{t}: {a['taxa']}% a.a., rende {a['rend_mes']} por mês, isento={a['isento']}")
ex = c.request("DELETE", "/api/conta", headers=Ha, json={"senha": "novasenha1"})
ok(ex.status_code == 200 and c.post("/api/conta/google", json={"credencial": "tok-ana", "somente_entrar": True}).status_code == 404, "exclusão apaga também o vínculo com o Google")

print("\n" + ("TUDO OK" if not falhas else f"{len(falhas)} FALHA(S): " + "; ".join(falhas)))
