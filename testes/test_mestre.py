"""Código mestre: libera o app completo sem pagar; trocar o código no servidor revoga; sem código configurado, nada libera."""
import os, sys, tempfile, time
os.environ["DATA_DIR"] = tempfile.mkdtemp(); os.environ["APP_TOKEN"] = ""
import mocks, server, armazem  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
c = TestClient(server.app)
falhas = []
def ok(cond, msg):
    print(("  ok   " if cond else "  FALHA ") + msg)
    if not cond: falhas.append(msg)
S = c.post("/api/conta/cadastrar", json={"nome": "Dono", "email": "dono@ex.com", "senha": "senhateste1"}).json()
H, uid = {"Authorization": "Bearer " + S["token"]}, S["usuario"]["id"]
d = armazem.ler("plano", uid); c.get("/api/plano", headers=H)
d = armazem.ler("plano", uid)["dados"]; d["teste_inicio"] = time.time() - 30 * 86400; armazem.gravar("plano", uid, d)
ok(c.get("/api/plano", headers=H).json()["plano"] == "gratis", "começa no grátis (teste acabou)")
os.environ.pop("CODIGO_MESTRE", None)
ok(c.post("/api/plano/acesso", headers=H, json={"codigo": "qualquer"}).status_code == 400, "sem CODIGO_MESTRE no servidor, nada libera")
os.environ["CODIGO_MESTRE"] = "curto"
ok(c.post("/api/plano/acesso", headers=H, json={"codigo": "curto"}).status_code == 400, "código com menos de 8 caracteres não vale")
os.environ["CODIGO_MESTRE"] = "Meu-Codigo-Secreto-2026"
ok(c.post("/api/plano/acesso", headers=H, json={"codigo": "errado123"}).status_code == 400, "código errado recusado")
p = c.post("/api/plano/acesso", headers=H, json={"codigo": " Meu-Codigo-Secreto-2026 "}).json()
ok(p["plano"] == "premium" and p["origem"] == "acesso_completo" and p["ate"] is None, "código certo: acesso completo, sem prazo")
pos = {t: {"qtd": 10, "pm": 20} for t in ["PETR4", "ITUB4", "BOVA11", "HGLG11", "VALE3", "WEGE3", "IVVB11"]}
pf = c.post("/api/portfolio", headers=H, json={"pos": pos, "perfil": "moderado", "objetivo": ""}).json()
ok(pf["premium"] and len(pf["ativos"]) == 7, "com o acesso completo, tudo liberado (7 ativos analisados)")
ok(c.post("/api/avisos/preco", headers=H, json={"ticker": "PETR4", "condicao": "acima", "valor": 50}).status_code == 200, "alertas de preço liberados")
os.environ["CODIGO_MESTRE"] = "Outro-Codigo-Novo-2027"
ok(c.get("/api/plano", headers=H).json()["plano"] == "gratis", "trocar o código no servidor revoga quem usou o antigo")
os.environ["CODIGO_MESTRE"] = "Meu-Codigo-Secreto-2026"
ok(c.get("/api/plano", headers=H).json()["origem"] == "acesso_completo", "voltar ao código antigo devolve o acesso")
print("TUDO OK" if not falhas else f"{len(falhas)} FALHA(S)")
