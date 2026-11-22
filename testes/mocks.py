"""Mocks para rodar o app sem rede: preços sintéticos, BCB, Focus, notícias e Claude."""
import json, os, sys, types, zlib
import numpy as np, pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # a raiz do repositório
import os
os.environ.setdefault("APP_TOKEN", "teste")
os.environ.setdefault("ANTHROPIC_API_KEY", "x")
import yfinance as yf, requests

PARAMS = {"^BVSP": (0.08, 0.25, 30000), "^GSPC": (0.09, 0.17, 1200), "USDBRL=X": (0.04, 0.15, 2.2), "GC=F": (0.08, 0.16, 550),
          "VOO": (0.11, 0.17, 100)}
def serie(sym, idx):
    seed = zlib.crc32(sym.encode())
    rng = np.random.default_rng(seed)
    mu, vol, p0 = PARAMS.get(sym, (0.06 + (seed % 7) / 100, 0.2 + (seed % 5) / 50, 10 + seed % 90))
    start = 0 if sym in PARAMS else int(rng.integers(0, len(idx) // 2))
    r = rng.normal(mu / 252, vol / np.sqrt(252), len(idx))
    if sym in ("^BVSP",):  # crash sintético em 2008 e 2020
        for a, b in (("2008-05-20", "2008-10-27"), ("2020-01-23", "2020-03-23")):
            m = (idx >= a) & (idx <= b); r[m] -= 0.45 / m.sum()
    p = p0 * np.exp(np.cumsum(r))
    p[:start] = np.nan
    return pd.Series(p, index=idx)

IDX = pd.bdate_range("2004-01-02", pd.Timestamp.today().normalize())
def fake_download(tickers, **kw):
    if isinstance(tickers, str): tickers = [tickers]
    close = pd.DataFrame({t: serie(t, IDX) for t in tickers})
    div = pd.DataFrame({t: np.where((IDX.day < 3) & t.endswith("11.SA"), 0.8, 0.0) for t in tickers}, index=IDX)
    vol = pd.DataFrame({t: GIRO.get(t, 5e6 if t.endswith("11.SA") else 80e6) / close[t] for t in tickers})
    return pd.concat({"Close": close, "Dividends": div, "Volume": vol}, axis=1)
GIRO = {"BRCR11.SA": 0.5e6, "SLCE3.SA": 3e6, "OIBR3.SA": 0.3e6}  # R$ por dia: papéis que negociam pouco
yf.download = fake_download

class FakeTicker:
    def __init__(self, s): self.s = s
    def history(self, period="1y"):
        s = serie(self.s, IDX).dropna()
        n = {"1y": 252, "5d": 5}.get(period, 252)
        return pd.DataFrame({"Close": s.iloc[-n:], "Volume": GIRO.get(self.s, 80e6) / s.iloc[-n:]})
    @property
    def dividends(self): return pd.Series([0.5, 0.5], index=IDX[-200:-100:50])
    @property
    def info(self):  # balanço sintético, estável por ativo
        seed = zlib.crc32(self.s.encode())
        if self.s.endswith("11.SA") and self.s[:4] in ("HGLG", "KNRI", "XPML", "MXRF", "KNCR", "BTLG", "VISC", "HGRU", "BRCR"):
            return {"longName": self.s[:-3] + " Fundo Imobiliário", "bookValue": 80 + seed % 40, "marketCap": 2e9 + seed % 10 * 1e8}
        return {"longName": self.s[:-3] + " S.A.", "marketCap": 1e10 + seed % 50 * 1e9, "netIncomeToCommon": 1e9 + seed % 9 * 1e8,
                "bookValue": 10 + seed % 20, "returnOnEquity": 0.08 + seed % 15 / 100, "profitMargins": 0.05 + seed % 20 / 100,
                "payoutRatio": 0.3 + seed % 6 / 10, "revenueGrowth": -0.05 + seed % 20 / 100, "ebitda": 3e9, "totalDebt": 6e9,
                "totalCash": 1e9, "ebitdaMargins": 0.2 + seed % 10 / 100}
yf.Ticker = FakeTicker

class R:
    def __init__(self, j=None, content=b""): self._j, self.content = j, content
    def json(self): return self._j
RSS = b"""<rss><channel><item><title>Copom mantem Selic e sinaliza cautela</title><link>https://ex.com/a</link><source>Valor</source><pubDate>Thu, 19 Nov 2026 10:00:00 GMT</pubDate></item>
<item><title>Ibovespa sobe com exterior positivo</title><link>https://ex.com/b</link><source>InfoMoney</source></item></channel></rss>"""
def fake_get(url, params=None, timeout=None, **kw):
    if "sgs.432" in url: return R([{"valor": "13,75"}])
    if "sgs.4389" in url: return R([{"valor": "13,65"}])
    if "sgs.13522" in url: return R([{"valor": "4,62"}])
    if "olinda" in url:
        return R({"value": [{"Indicador": "Selic", "Data": "2026-11-14", "DataReferencia": "2026", "Mediana": 13.75},
                            {"Indicador": "Selic", "Data": "2026-11-14", "DataReferencia": "2027", "Mediana": 12.0},
                            {"Indicador": "Selic", "Data": "2026-11-14", "DataReferencia": "2028", "Mediana": 10.5},
                            {"Indicador": "IPCA", "Data": "2026-11-14", "DataReferencia": "2026", "Mediana": 4.5},
                            {"Indicador": "IPCA", "Data": "2026-11-14", "DataReferencia": "2027", "Mediana": 4.0},
                            {"Indicador": "IPCA", "Data": "2026-11-14", "DataReferencia": "2028", "Mediana": 3.6}]})
    if "sgs.433/" in url:  # IPCA mensal (% a.m.)
        a0, a1 = int(params["dataInicial"][-4:]), int(params["dataFinal"][-4:])
        hoje = pd.Timestamp.today()
        return R([{"data": f"01/{m:02d}/{a}", "valor": "0,40"} for a in range(a0, a1 + 1) for m in range(1, 13) if pd.Timestamp(a, m, 1) < hoje - pd.offsets.MonthBegin(1)])
    if "news.google" in url: return R(content=RSS)
    if "sgs.4391" in url:  # CDI mensal (% a.m.) entre as datas pedidas
        a0, a1 = int(params["dataInicial"][-4:]), int(params["dataFinal"][-4:])
        hoje = pd.Timestamp.today()
        return R([{"data": f"01/{m:02d}/{a}", "valor": f"{0.75 + 0.35 * ((a * 12 + m) % 7) / 6:.2f}".replace(".", ",")}
                  for a in range(a0, a1 + 1) for m in range(1, 13) if pd.Timestamp(a, m, 1) <= hoje])
    raise RuntimeError("rede bloqueada no teste: " + url)
requests.get = fake_get

import server
class Blk:
    def __init__(self, t, text=""): self.type, self.text = t, text
class Msg:
    def __init__(self, txt): self.content, self.stop_reason = [Blk("thinking"), Blk("text", txt)], "end_turn"
CALLS = []
def fake_create(**kw):
    CALLS.append(kw)
    sysp = kw["system"]
    if sysp.startswith("Você é um trader"):
        return Msg(json.dumps({"decisao": "COMPRAR", "confianca": 62, "alvo": 99.5, "stop": 70.1, "resumo": "Tendência de alta.", "riscos": ["Risco A", "Risco B"]}))
    if "estrategista" in sysp:
        return Msg(json.dumps({"resumo": "Juros altos favorecem renda fixa; bolsa barata.",
            "classes": {c: {"visao": "POSITIVA" if c == "renda_fixa" else "NEUTRA", "ajuste": 1 if c == "renda_fixa" else 0, "motivo": "Motivo " + c} for c in server.CORE},
            "cenarios": [{"nome": "Base", "prob": 55, "descricao": "Base desc.", "ajustes": {c: 0 for c in server.CORE}},
                         {"nome": "Otimista", "prob": 20, "descricao": "Otim desc.", "ajustes": {"renda_fixa": -1, "acao": 6, "fii": 4, "exterior": 0, "cambio": -3}},
                         {"nome": "Pessimista", "prob": 25, "descricao": "Pess desc.", "ajustes": {"renda_fixa": 1, "acao": -8, "fii": -5, "exterior": 2, "cambio": 6}}],
            "fatores": ["Fator 1", "Fator 2", "Fator 3"]}))
    if "planejador" in sysp:
        enum = kw["output_config"]["format"]["schema"]["properties"]["carteira"]["items"]["properties"]["ativo"]["enum"]
        cart = [("TESOURO_SELIC", 20), ("TESOURO_IPCA", 25), ("BOVA11", 10), ("ITUB4", 5), ("HGLG11", 8), ("KNCR11", 7), ("IVVB11", 15), ("GOLD11", 5), ("INVENTADO3", 5)]
        payload = json.loads(kw["messages"][0]["content"])
        if "objetivo" in payload:  # objetivo de prazo médio: a IA deixa a carteira bem mais conservadora
            return Msg(json.dumps({"objetivo_analise": {"resumo": "Você quer juntar R$ 150 mil para a entrada de um apartamento em 5 anos, investindo R$ 2.000 por mês.",
                "metas": [{"descricao": "Entrada do apartamento", "prazo_anos": 5, "valor_alvo": 150000}, {"descricao": "Reserva de emergência", "prazo_anos": 0, "valor_alvo": 0}],
                "aporte_mensal": 2000, "liquidez": "MEDIA", "influencia": "Como o dinheiro tem data para ser usado, reduzi ações e reforcei Tesouro IPCA+ com vencimento próximo do prazo.",
                "atencao": ["Confirme se você já tem reserva de emergência separada."]},
                "resumo": "Carteira focada na entrada do apartamento.", "alvo": {"renda_fixa": 80, "acao": 10, "fii": 5, "exterior": 5, "cambio": 0},
                "alvo_motivo": "Prazo de 5 anos pede mais renda fixa.", "carteira": [{"ativo": a, "peso": w, "motivo": "Serve à meta: " + a} for a, w in
                [("TESOURO_IPCA", 45), ("TESOURO_SELIC", 35), ("BOVA11", 10), ("KNCR11", 5), ("IVVB11", 5)]],
                "acoes": [{"ativo": "PETR4", "acao": "REDUZIR", "motivo": "Risco alto para o prazo."}], "alertas": []}))
        return Msg(json.dumps({"resumo": "Carteira concentrada em ações.", "alvo": {"renda_fixa": 50, "acao": 18, "fii": 15, "exterior": 12, "cambio": 5},
            "alvo_motivo": "Selic alta.", "carteira": [{"ativo": a, "peso": w, "motivo": "Porque " + a,
                **({"porque": "Rendeu 38,4% em 12 meses, bem acima do CDI.", "contra": "Oscila com a bolsa."} if a == "BOVA11" else {})}
                for a, w in cart if a in enum or a == "INVENTADO3"],
            "acoes": [{"ativo": "PETR4", "acao": "REDUZIR", "motivo": "Concentração."}], "alertas": ["Sem reserva de emergência"]}))
    return Msg("{}")
class FakeStream:
    def __init__(self, kw): self.kw = kw
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def get_final_message(self): return server.client.messages.create(**self.kw)  # busca na hora: os testes podem trocar o create
sem_beta = lambda kw: {k: v for k, v in kw.items() if k not in ("betas", "fallbacks")}
server.client = types.SimpleNamespace(messages=types.SimpleNamespace(create=fake_create, stream=lambda **kw: FakeStream(kw)),
                                      beta=types.SimpleNamespace(messages=types.SimpleNamespace(create=lambda **kw: server.client.messages.create(**sem_beta(kw)),
                                                                                                stream=lambda **kw: FakeStream(sem_beta(kw)))))
