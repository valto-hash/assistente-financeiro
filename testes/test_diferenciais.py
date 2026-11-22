"""Gastos (Mobills), rentabilidade/proventos/B3 (Kinvo) e fundamentos/ranking (Investidor10). Uso: python3 test_diferenciais.py"""
import io, os, sys, tempfile, time
from datetime import date, timedelta
os.environ["DATA_DIR"] = tempfile.mkdtemp(); os.environ["APP_TOKEN"] = ""
import openpyxl
import mocks, server, armazem, gastos as G, investimentos as I  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
falhas = []
def ok(cond, msg):
    print(("  ok   " if cond else "  FALHA ") + msg)
    if not cond: falhas.append(msg)
c = TestClient(server.app)
def conta(email):
    S = c.post("/api/conta/cadastrar", json={"nome": "Teste", "email": email, "senha": "senhateste1"}).json()
    return {"Authorization": "Bearer " + S["token"]}, S["usuario"]["id"]
H, uid = conta("g@ex.com")
hoje = date.today(); ym = hoje.strftime("%Y-%m")
d = lambda n: (hoje - timedelta(days=n)).isoformat()

# ---------------- gastos
print("== gastos")
r = c.post("/api/gastos", headers=H, json=[
    {"data": d(0), "descricao": "IFOOD *RESTAURANTE", "valor": -58.9}, {"data": d(0), "descricao": "UBER TRIP", "valor": -23.5},
    {"data": d(0), "descricao": "NETFLIX.COM", "valor": -55.9}, {"data": d(0), "descricao": "SUPERMERCADO DIA", "valor": -312.4},
    {"data": d(0), "descricao": "SALARIO EMPRESA X", "valor": 6500}, {"data": d(0), "descricao": "Loja do Zé", "valor": -100}]).json()
cats = {x["descricao"]: x["categoria"] for x in r["criados"]}
print("   ", cats)
ok(cats["IFOOD *RESTAURANTE"] == "Alimentação fora" and cats["UBER TRIP"] == "Transporte" and cats["NETFLIX.COM"] == "Assinaturas"
   and cats["SUPERMERCADO DIA"] == "Mercado" and cats["SALARIO EMPRESA X"] == "Salário" and cats["Loja do Zé"] == "Outros", "categoria automática")
ze = next(x for x in r["criados"] if x["descricao"] == "Loja do Zé")
c.post("/api/gastos", headers=H, json=[{"data": d(1), "descricao": "Loja do Zé", "valor": -40}])
e = c.put(f"/api/gastos/{ze['id']}", headers=H, json={"categoria": "Pets", "semelhantes": True}).json()
ok(e["alterados"] == 2, f"corrigir a categoria aplica às semelhantes ({e['alterados']})")
novo = c.post("/api/gastos", headers=H, json=[{"data": d(0), "descricao": "LOJA DO ZE", "valor": -15}]).json()["criados"][0]
ok(novo["categoria"] == "Pets", "o app aprende: a mesma descrição já entra na categoria corrigida")
ok(c.put(f"/api/gastos/{ze['id']}", headers=H, json={"categoria": "Salário"}).status_code == 400, "categoria de receita num gasto é recusada")
ok(c.post("/api/gastos", headers=H, json=[{"data": "2026-13-01", "descricao": "x", "valor": -1}]).status_code == 400, "data inválida recusada")
c.put("/api/gastos-limites", headers=H, json={"Alimentação fora": 50, "Mercado": 1000, "Inexistente": 10})
R = c.get("/api/gastos", headers=H).json()
lim = {l["categoria"]: l for l in R["categorias"]}
ok(R["limites"] == {"Alimentação fora": 50, "Mercado": 1000}, "limites só de categorias válidas")
ok(lim["Alimentação fora"]["usado"] > 100 and any("passou do limite" in o["texto"] for o in R["observacoes"]), "passou do limite aparece no resumo")
ok(R["receitas"] == 6500 and abs(R["gastos"] - (58.9 + 23.5 + 55.9 + 312.4 + 100 + 15 + (40 if d(1)[:7] == ym else 0))) < 0.01, f"totais do mês ({R['gastos']})")
n = c.post("/api/avisos/verificar", headers=H).json()["novos"]
av = c.get("/api/avisos", headers=H).json()
titulos = [a["titulo"] for a in av.get("itens", av if isinstance(av, list) else [])]
ok(any("Alimentação fora: passou do limite" in t for t in titulos), f"aviso de limite ({titulos[:3]})")
ofx = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "extrato.ofx"), "rb").read()
i1 = c.post("/api/gastos/importar", headers=H, files={"arquivo": ("extrato.ofx", ofx)}).json()
i2 = c.post("/api/gastos/importar", headers=H, files={"arquivo": ("extrato.ofx", ofx)}).json()
print("   importação:", {k: i1[k] for k in ("novos", "repetidos", "meses")}, list(i1["por_categoria"].items())[:4])
ok(i1["novos"] > 0 and i2["novos"] == 0 and i2["repetidos"] == i1["novos"], "importar o mesmo extrato duas vezes não duplica")
mes_ext = i1["meses"][-1]
R2 = c.get(f"/api/gastos?mes={mes_ext}", headers=H).json()
ok(R2["gastos"] > 0 and len(R2["historico"]) >= 1, f"resumo de um mês do extrato ({mes_ext}: R$ {R2['gastos']})")
ok(c.delete(f"/api/gastos/{novo['id']}", headers=H).json()["ok"] and c.delete(f"/api/gastos/{novo['id']}", headers=H).status_code == 404, "apagar")
# plano grátis não importa
H2, uid2 = conta("free@ex.com")
p = armazem.ler("plano", uid2) or {"dados": {}}; c.get("/api/plano", headers=H2)
dd = armazem.ler("plano", uid2)["dados"]; dd["teste_inicio"] = time.time() - 30 * 86400; armazem.gravar("plano", uid2, dd)
ok(c.post("/api/gastos/importar", headers=H2, files={"arquivo": ("extrato.ofx", ofx)}).status_code == 402, "importar extrato é do Premium")
ok(c.post("/api/gastos", headers=H2, json=[{"data": d(0), "descricao": "Padaria", "valor": -12}]).status_code == 200, "lançar à mão é grátis")

# ---------------- B3: planilhas sintéticas no formato da Área do Investidor
print("== B3")
wb = openpyxl.Workbook(); ws = wb.active; ws.title = "Acoes"
ws.append(["Produto", "Instituição", "Conta", "Código de Negociação", "CNPJ da Empresa", "Código ISIN / Distribuição", "Tipo", "Escriturador",
           "Quantidade", "Quantidade Disponível", "Quantidade Indisponível", "Motivo", "Preço de Fechamento", "Valor Atualizado"])
ws.append(["PETR4 - PETROLEO BRASILEIRO S.A. PETROBRAS", "XP", "1", "PETR4", "", "", "PN", "", 300, 300, 0, "", 38.5, 11550])
ws.append(["PETR4 - PETROLEO BRASILEIRO S.A. PETROBRAS", "NU", "2", "PETR4", "", "", "PN", "", 100, 100, 0, "", 38.5, 3850])
ws.append(["ITUB4 - ITAU UNIBANCO HOLDING S.A.", "XP", "1", "ITUB4", "", "", "PN", "", 200, 200, 0, "", 35, 7000])
ws.append(["Total", None, None, None, None, None, None, None, None, None, None, None, None, 22400])
ws2 = wb.create_sheet("Fundo de Investimento")
ws2.append(["Produto", "Instituição", "Conta", "Código de Negociação", "CNPJ do Fundo", "Código ISIN / Distribuição", "Tipo", "Administrador",
            "Quantidade", "Quantidade Disponível", "Quantidade Indisponível", "Motivo", "Preço de Fechamento", "Valor Atualizado"])
ws2.append(["HGLG11 - CSHG LOGISTICA FII", "XP", "1", "HGLG11", "", "", "Cotas", "", 50, 50, 0, "", 160, 8000])
ws3 = wb.create_sheet("Tesouro Direto")
ws3.append(["Produto", "Instituição", "Código ISIN", "Indexador", "Vencimento", "Quantidade", "Valor Aplicado", "Valor bruto", "Valor líquido", "Valor Atualizado"])
ws3.append(["Tesouro Selic 2029", "XP", "", "SELIC", "01/03/2029", 1.5, 20000, 21000, 20800, 21000])
ws3.append(["Tesouro IPCA+ 2035", "XP", "", "IPCA", "15/05/2035", 2, 6000, 6500, 6400, 6500])
b = io.BytesIO(); wb.save(b); posicao = b.getvalue()
wb = openpyxl.Workbook(); ws = wb.active; ws.title = "Negociação"
ws.append(["Data do Negócio", "Tipo de Movimentação", "Mercado", "Prazo/Vencimento", "Instituição", "Código de Negociação", "Quantidade", "Preço", "Valor"])
for row in [(d(700), "Compra", "Mercado à Vista", "-", "XP", "PETR4", 200, 30.0, 6000), (d(500), "Compra", "Mercado à Vista", "-", "NU", "PETR4F", 200, 25.0, 5000),
            (d(400), "Venda", "Mercado à Vista", "-", "XP", "PETR4", 100, 33.0, 3300), (d(300), "Compra", "Mercado à Vista", "-", "XP", "ITUB4", 200, 28.0, 5600),
            (d(200), "Compra", "Mercado à Vista", "-", "XP", "HGLG11", 50, 150.0, 7500)]:
    ws.append([__import__("datetime").datetime.fromisoformat(row[0]), *row[1:]])
b = io.BytesIO(); wb.save(b); negoc = b.getvalue()
mov_csv = ("Entrada/Saída;Data;Movimentação;Produto;Instituição;Quantidade;Preço unitário;Valor da Operação\n"
           f"Credito;{(hoje - timedelta(days=60)).strftime('%d/%m/%Y')};Dividendo;PETR4 - PETROLEO BRASILEIRO S.A. PETROBRAS;XP;300;0,90;270,00\n"
           f"Credito;{(hoje - timedelta(days=30)).strftime('%d/%m/%Y')};Juros Sobre Capital Próprio;ITUB4 - ITAU UNIBANCO;XP;200;0,25;42,50\n"
           f"Credito;{(hoje - timedelta(days=15)).strftime('%d/%m/%Y')};Rendimento;HGLG11 - CSHG LOGISTICA FII;XP;50;1,10;55,00\n"
           f"Credito;{(hoje - timedelta(days=10)).strftime('%d/%m/%Y')};Direito de Subscrição;HGLG11 - CSHG LOGISTICA FII;XP;5;-;-\n").encode("utf-8")
r1 = c.post("/api/b3/importar", headers=H, files={"arquivo": ("posicao.xlsx", posicao)}).json()
print("   posição:", r1["posicoes"], r1["avisos"])
ok(r1["tipos"] == ["posicao", "posicao", "tesouro"] and r1["posicoes"]["PETR4"]["qtd"] == 400 and r1["posicoes"]["ITUB4"]["qtd"] == 200
   and r1["posicoes"]["HGLG11"]["qtd"] == 50 and r1["posicoes"]["TESOURO_SELIC"] == {"saldo": 21000} and r1["posicoes"]["TESOURO_IPCA"] == {"saldo": 6500},
   "Posição: soma corretoras, FIIs e Tesouro")
ok(any("Sem o preço médio" in a for a in r1["avisos"]), "Posição sozinha avisa que falta o preço médio")
r2 = c.post("/api/b3/importar", headers=H, files={"arquivo": ("negociacao.xlsx", negoc)}).json()
print("   negociação:", r2["posicoes"], r2["avisos"])
ok(r2["tipos"] == ["negociacao"] and r2["posicoes"]["PETR4"] == {"qtd": 300, "pm": 27.5} and r2["posicoes"]["ITUB4"]["pm"] == 28.0, "Negociação: preço médio (venda não muda o PM)")
r3 = c.post("/api/b3/importar", headers=H, files={"arquivo": ("movimentacao.csv", mov_csv)}).json()
ok(r3["proventos"] == 3 and r3["total_movs"] == 5, f"Movimentação: proventos e sem duplicar negociações ({r3['proventos']}, {r3['total_movs']})")
r4 = c.post("/api/b3/importar", headers=H, files={"arquivo": ("negociacao.xlsx", negoc)}).json()
ok(r4["total_movs"] == 5, "importar de novo não duplica")
ok(c.post("/api/b3/importar", headers=H, files={"arquivo": ("x.csv", b"a;b\n1;2\n")}).status_code == 422, "planilha desconhecida: mensagem clara")
ok(c.post("/api/b3/importar", headers=H2, files={"arquivo": ("posicao.xlsx", posicao)}).status_code == 402, "importar da B3 é do Premium")

# ---------------- rentabilidade e proventos
print("== rentabilidade")
pos = {"PETR4": {"qtd": 300, "pm": 27.5}, "ITUB4": {"qtd": 200, "pm": 28}, "HGLG11": {"qtd": 50, "pm": 150}, "TESOURO_SELIC": {"saldo": 21000, "pct": 100}}
t0 = time.time(); R = c.post("/api/rentabilidade", headers=H, json={"pos": pos}).json(); print(f"   {time.time() - t0:.1f}s")
at, hi, pv = R["atual"], R["historico"], R["proventos"]
print("   atual:", [(p["chave"], p["carteira"], p["cdi"], p.get("ibov"), p["ipca"], p["pct_cdi"]) for p in at["periodos"]])
print("   histórico:", hi and [(p["chave"], p["carteira"], p["cdi"]) for p in hi["periodos"]], hi and hi["desde"])
ok([p["chave"] for p in at["periodos"]] == ["1m", "3m", "6m", "12m", "24m"] and all(p["cdi"] > 0 and p["ipca"] is not None for p in at["periodos"]), "janelas com CDI e IPCA")
ok(len(at["serie"]["datas"]) >= 50 and at["serie"]["carteira"][0] == 100, "série semanal de 12 meses para o gráfico")
ok(hi and hi["periodos"][-1]["chave"] == "inicio" and hi["desde"] == d(700) and len(hi["serie"]["datas"]) > 20, "rentabilidade real desde a primeira compra")
ok(pv["fonte"] == "b3" and pv["total_12m"] == 367.5 and len(pv["por_ativo"]) == 3 and pv["por_mes"][-1]["mes"] == ym, f"proventos da B3 ({pv['total_12m']})")
R3 = c.post("/api/rentabilidade", headers=H2, json={"pos": {"HGLG11": {"qtd": 10, "pm": 100}}}).json()
ok(R3["proventos"]["fonte"] == "estimado" and R3["proventos"]["total_12m"] > 0 and R3["historico"] is None, f"sem B3: proventos estimados ({R3['proventos']['total_12m']})")
ok(c.post("/api/rentabilidade", headers=H2, json={"pos": {}}).json() == {"vazio": True}, "carteira vazia")
# Dietz: sem fluxo, a rentabilidade do histórico é a da cota
m = I.custo_medio([{"data": "2020-01-02", "ticker": "X", "tipo": "compra", "qtd": 10, "preco": 10}, {"data": "2020-02-02", "ticker": "X", "tipo": "evento", "qtd": 10, "preco": None}])
ok(m["X"] == {"qtd": 20, "pm": 5.0}, "desdobramento dobra a quantidade e divide o preço médio")

# ---------------- fundamentos e ranking
print("== fundamentos")
f = c.get("/api/fundamentos/PETR4", headers=H).json()
print("   ", f["nome"], f["comparado_com"], [(x["chave"], x["valor"], x["referencia"]) for x in f["indicadores"]][:6], f["proventos"]["anos"][-2:])
ok({"dy", "pl", "pvp", "roe"} <= {x["chave"] for x in f["indicadores"]} and all(x["ajuda"] for x in f["indicadores"]), "indicadores com explicação")
ok(any(x["referencia"] is not None for x in f["indicadores"]), "comparação com o setor ou a classe")
ok(len(f["proventos"]["anos"]) >= 10, "proventos por ano (10 anos)")
ff = c.get("/api/fundamentos/HGLG11", headers=H).json()
ok({x["chave"] for x in ff["indicadores"]} >= {"dy", "pvp"} and "pl" not in {x["chave"] for x in ff["indicadores"]}, "FII: P/VP e DY, sem P/L")
ok(c.get("/api/fundamentos/BOVA11", headers=H).status_code == 404 and c.get("/api/fundamentos/TESOURO_SELIC", headers=H).status_code == 400, "ETF e título: sem balanço")
rk = c.get("/api/ranking?tipo=acao", headers=H).json()
ok(rk["premium"] and len(rk["linhas"]) == rk["total"] > 20 and "pl" in rk["colunas"], f"ranking completo no Premium ({rk['total']})")
rk2 = c.get("/api/ranking?tipo=fii", headers=H2).json()
ok(not rk2["premium"] and len(rk2["linhas"]) == 5 and rk2["total"] > 5, "ranking no grátis: só 5 linhas")
# exclusão de conta leva gastos e B3
ok(c.request("DELETE", "/api/conta", headers=H, json={"email": "g@ex.com", "senha": "senhateste1"}).status_code == 200
   and armazem.ler("gastos", uid) is None and armazem.ler("b3", uid) is None, "excluir a conta apaga gastos e histórico da B3")
print("TUDO OK" if not falhas else f"{len(falhas)} FALHA(S)")
