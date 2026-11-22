"""Regras de gestão de risco: dados limpos, liquidez, histórico mínimo, peso pelo risco, setor, armadilha de dividendos
e o teste da escolha de ações e FIIs. Uso: python3 test_trader.py"""
import os, sys, tempfile
os.environ["DATA_DIR"] = tempfile.mkdtemp(); os.environ["APP_TOKEN"] = ""
import numpy as np, pandas as pd
import mocks, server, regras, acertos, simulacao as sim  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
falhas = []
def ok(cond, msg):
    print(("  ok   " if cond else "  FALHA ") + msg)
    if not cond: falhas.append(msg)

# ---- 1) limpeza dos dados
idx = pd.bdate_range("2025-01-01", periods=300)
p = pd.Series(np.linspace(100, 110, 300), index=idx)
erro = p.copy(); erro.iloc[100:103] = 1.0                    # 3 dias de cotação errada (preço absurdo)
c = sim.limpar(erro)
ok(len(c) == 297 and c.max() <= 110 and c.min() >= 100, "cotação errada que se desfaz sai da série")
grup = p.copy(); grup.iloc[:200] = grup.iloc[:200] / 7.6     # desdobramento não ajustado (como o XPML11 em jan/2026)
c = sim.limpar(grup)
ok(abs(c.iloc[-1] / c.iloc[0] - 1.1) < 0.01, f"salto de 7,6x num dia é corrigido (retorno no período: {c.iloc[-1] / c.iloc[0] - 1:.1%})")
crash = p.copy(); crash.iloc[150:] = crash.iloc[150:] * 0.23 # queda real de 77% (como a Americanas em 2023)
c = sim.limpar(crash)
ok(len(c) == 300 and abs(c.iloc[-1] / c.iloc[0] - 0.253) < 0.01, "queda real de 77% fica (não é escondida)")
ok(sim.giro_diario(p, pd.Series(1e5, index=idx)) == round(float((p * 1e5).iloc[-63:].median()) / 1e6, 2), "giro diário em R$ milhões")
ok(sim.giro_diario(p, pd.Series(np.nan, index=idx)) is None, "sem volume, giro desconhecido")

# ---- 2) armadilha de dividendos, liquidez e setor
regras.CDI_REF[0] = 14.9
ok(regras.alerta_dividendos({"dy_12m": 14.8, "ret_12m": -41.5}, "acao") is not None, "ação com DY alto e preço despencando: alerta")
ok(regras.alerta_dividendos({"dy_12m": 8.6, "ret_12m": 42}, "acao") is None, "DY normal: sem alerta")
ok(regras.alerta_dividendos({"dy_12m": 20.1, "ret_12m": -39}, "fii") is not None, "FII com DY muito acima do CDI: alerta")
ok(regras.alerta_dividendos({"dy_12m": 13.4, "ret_12m": 1}, "fii") is None, "FII pagando perto do CDI: sem alerta")
ok(regras.pouca_liquidez({"giro_dia": 0.4}, "acao") and not regras.pouca_liquidez({"giro_dia": 50}, "acao")
   and not regras.pouca_liquidez({"giro_dia": None}, "acao") and not regras.pouca_liquidez({"giro_dia": 0.1}, "exterior"), "pouca liquidez só com dado e só para ação/FII")
ok(regras.escala_risco({"vol_aa": 60}, "acao") == 0.5 and regras.escala_risco({"vol_aa": 20}, "acao") == 1.0
   and regras.escala_risco({"vol_aa": 45}, "acao") == 0.67, "peso pelo risco: metade para quem oscila o dobro")
itens = [{"ticker": "ITUB4", "classe": "acao", "pct": 15}, {"ticker": "BBDC4", "classe": "acao", "pct": 14},
         {"ticker": "BOVA11", "classe": "acao", "pct": 40}, {"ticker": "WEGE3", "classe": "acao", "pct": 31}]
al = regras.concentracao_setor(itens, server.SETOR, server.ETF_ACAO)
ok(len(al) == 1 and "ITUB4, BBDC4" in al[0] and "29%" in al[0], f"setor acima de 25%: {al}")

# ---- 3) escolha: só entra ativo novo líquido, com 3 anos, e quem oscila mais entra menor
bom = {"ret_3a_aa": 25, "vol_aa": 25, "queda_max_12m": -10, "dy_12m": 5, "giro_dia": 100, "anos_hist": 10, "ret_12m": 20}
cand = {"BOVA11": {"classe": "acao", "m": {}}, "DIVO11": {"classe": "acao", "m": {}},
        "AAAA3": {"classe": "acao", "m": {**bom, "giro_dia": 2}},           # ótimo, mas negocia pouco
        "BBBB3": {"classe": "acao", "m": {**bom, "anos_hist": 1.5, "ret_3a_aa": None}},  # IPO recente
        "CCCC3": {"classe": "acao", "m": {**bom, "ret_3a_aa": 60, "vol_aa": 60}},       # bom, mas oscila muito
        "DDDD3": {"classe": "acao", "m": {**bom, "ret_3a_aa": 22}},
        "EEEE3": {"classe": "acao", "m": {**bom, "ret_3a_aa": 21, "giro_dia": None}},   # sem dado de volume: não é barrado
        "FFFF3": {"classe": "acao", "m": {**bom, "giro_dia": 0.5}}}                     # já tenho, negocia pouco
setores = {"AAAA3": "A", "BBBB3": "B", "CCCC3": "C", "DDDD3": "D", "EEEE3": "E", "FFFF3": "F"}
pesos, mot = regras.escolher_ativos({"acao": 40, "renda_fixa": 60}, cand, {"FFFF3": 3000, "TESOURO_SELIC": 7000}, {}, None,
                                    {"BOVA11", "DIVO11"}, 12.0, setores)
print("   pesos:", pesos)
ok("AAAA3" not in pesos and "BBBB3" not in pesos, "ativo novo que negocia pouco ou sem 3 anos de histórico não entra")
ok("FFFF3" in pesos, "o que você já tem não é vendido só por negociar pouco")
ok("CCCC3" in pesos and "DDDD3" in pesos and pesos["CCCC3"] < pesos["DDDD3"], "quem oscila mais entra com peso menor")
ok("oscila mais" in mot["CCCC3"], "o motivo explica o peso menor")
ok(max(w for a, w in pesos.items() if a in setores) <= 10, "nenhum papel individual passa de 10%")

# ---- 4) API: alertas na carteira, lista da IA sem ativos ilíquidos novos e teste da escolha
c = TestClient(server.app)
S = c.post("/api/conta/cadastrar", json={"nome": "Teste", "email": "t@ex.com", "senha": "senhateste1"}).json()
print("   cadastro:", S) if "token" not in S else None
H = {"Authorization": "Bearer " + S["token"]}
pos = {"ITUB4": {"qtd": 400, "pm": 20}, "BBDC4": {"qtd": 400, "pm": 15}, "BOVA11": {"qtd": 10, "pm": 100}, "OIBR3": {"qtd": 300, "pm": 2}}
mocks.CALLS.clear()
pf = c.post("/api/portfolio", headers=H, json={"pos": pos, "perfil": "moderado", "objetivo": ""}).json()
print("   alertas:", pf["alertas"])
ok(any("um só setor" in a for a in pf["alertas"]), "alerta de setor concentrado (bancos)")
ok(any(a.startswith("OIBR3 negocia pouco") for a in pf["alertas"]), "alerta de papel que negocia pouco")
kw = next((k for k in mocks.CALLS if "planejador" in k["system"]), None)
if kw:
    import json
    dados = json.loads(kw["messages"][0]["content"] if isinstance(kw["messages"][0]["content"], str) else kw["messages"][0]["content"][-1]["text"])
    lista = {x["ativo"] for x in dados["ativos_permitidos"]}
    ok("BRCR11" not in lista and "SLCE3" not in lista and "HGLG11" in lista, "a IA não recebe ativos novos que negociam pouco")
    ok("Gestão de risco" in kw["system"] and "Nunca sugira" not in kw["system"], "princípios no prompt da carteira")
an = c.post("/api/analyze", headers=H, json={"ticker": "OIBR3", "pos": {"qtd": 300, "pm": 2}}).json()
ok(an["metricas"].get("giro_dia") == 0.3, f"giro diário calculado na análise do ativo ({an['metricas'].get('giro_dia')})")
ac = c.get("/api/acertos", headers=H).json()
e = (ac.get("escolha") or {}).get("classes", {})
print("   escolha:", {k: {kk: v[kk] for kk in ("meses", "bate_media", "vantagem_media", "veredito")} for k, v in e.items()})
ok("acao" in e and e["acao"]["meses"] >= 24 and e["acao"]["veredito"] in ("ajudou", "pouco", "nao"), "teste da escolha de ações volta no /api/acertos")
print("TUDO OK" if not falhas else f"{len(falhas)} FALHA(S)")
