"""Histórico de preços, premissas de retorno, simulação Monte Carlo e testes de estresse.

Como a simulação funciona (resumo):
1. Padrões históricos: baixamos até 20 anos de preços (ajustados por proventos) e calculamos os retornos
   mensais de cada ativo. Meses sem dado do ativo são preenchidos com um índice da mesma classe (proxy).
2. Os retornos históricos são "centralizados" (tiramos a média) e sorteados em blocos de 6 meses seguidos
   (block bootstrap). Isso preserva volatilidade, correlação entre ativos, caudas gordas e sequências de crise.
3. A média de cada ativo é uma premissa prospectiva: mistura do retorno histórico (limitado) com uma premissa
   de equilíbrio para a classe (CDI esperado + prêmio de risco, inflação, câmbio), mais o ajuste das notícias.
4. As notícias geram cenários (base, otimista, pessimista) com probabilidades; o efeito delas é integral no
   primeiro ano e some aos poucos até o terceiro ano, quando voltam a valer só as premissas de longo prazo.
"""
import threading, time
from datetime import date

import numpy as np
import pandas as pd
import requests
import yfinance as yf

ANOS_HIST = 20          # janela de histórico usada no sorteio
BLOCO = 6               # meses por bloco no bootstrap
N_CAMINHOS = 2000
TTL_HIST = 12 * 3600

SIMB = {"DOLAR": "USDBRL=X", "VOO": "VOO", "IBOV": "^BVSP", "SP500": "^GSPC", "OURO": "GC=F"}
EM_USD = {"VOO", "SP500", "OURO"}
FII_CESTA = ["HGLG11", "KNRI11", "XPML11", "MXRF11", "KNCR11"]
PROXY_CLASSE = {"acao": "IBOV", "fii": "FII_IDX", "exterior": "SP500", "cambio": "DOLAR", "renda_fixa": "IPCA_LONGO"}
PROXY_ATIVO = {"GOLD11": "OURO", "TESOURO_IPCA": "IPCA_LONGO", "IVVB11": "SP500", "VOO": "SP500", "NASD11": "SP500",
               "IMAB11": "IPCA_LONGO", "B5P211": "IPCA_LONGO"}
# Séries montadas pelo app. IPCA_LONGO = IMA-B 5+ (títulos públicos IPCA+ com mais de 5 anos): índice da ANBIMA
# publicado pelo Banco Central (série 12468, 2005 a mai/2023) emendado com o ETF IB5M11, que segue o mesmo índice.
# Os ETFs de renda fixa no Yahoo (IMAB11, B5P211, IRFM11, FIXA11) ficaram com o preço parado de 2023 a 2025 e depois
# "saltaram" ~50% num dia: não servem para medir risco nem retorno.
SINTETICOS = {"IPCA_LONGO"}
BASE = sorted({"IBOV", "SP500", "DOLAR", "OURO", "IPCA_LONGO", *FII_CESTA})

CRISES = [  # (nome, início, fim, CDI médio aproximado no período, % a.a.)
    ("Crise financeira global", "2008-05-20", "2008-10-27", 13.0),
    ("Recessão e crise política", "2015-05-05", "2016-01-26", 14.0),
    ("Joesley Day", "2017-05-17", "2017-05-18", 11.0),
    ("Greve dos caminhoneiros", "2018-05-15", "2018-06-18", 6.4),
    ("Pandemia de Covid-19", "2020-01-23", "2020-03-23", 4.4),
    ("Inflação e alta de juros", "2021-06-07", "2021-11-30", 5.5),
    ("Estresse fiscal, dólar a R$ 6", "2024-08-28", "2024-12-18", 10.8),
]

_hist: dict = {}   # código -> (timestamp, fechamentos ajustados na moeda original, dividendos, giro diário em R$ milhões)
_splits: dict = {}  # código -> desdobramentos e bonificações (fator por data), usados na rentabilidade com histórico
_lock = threading.Lock()


def ysym(c):
    return SIMB.get(c, c + ".SA")


def _sem_tz(s):
    if getattr(s.index, "tz", None) is not None:
        s.index = s.index.tz_localize(None)
    return s


def limpar(c, salto=0.4, janela=10):
    """Corrige erros de cotação do Yahoo antes de qualquer conta (um único dado errado distorce retornos e o teste):
    1) um salto de mais de 40% num dia que se desfaz em até 10 pregões (o preço volta para perto de onde estava) é
       cotação errada, não movimento real, e sai da série;
    2) um salto de mais de 90% para baixo ou de 400% para cima num único dia é desdobramento ou grupamento não
       ajustado (ex.: XPML11 em jan/2026): a parte anterior da série é reescalada. Quedas reais e grandes, como a de
       77% da Americanas em 2023, ficam como estão."""
    if len(c) < 3:
        return c
    v = c.to_numpy(dtype=float).copy()
    n, ok = len(v), np.ones(len(v), bool)
    r = v[1:] / v[:-1]
    for k in np.where((r > 1 + salto) | (r < 1 / (1 + salto)))[0] + 1:
        if not ok[k]:
            continue
        j0 = k - 1
        while j0 > 0 and not ok[j0]:
            j0 -= 1
        ref = v[j0]
        if 1 / (1 + salto) <= v[k] / ref <= 1 + salto:
            continue
        fim = next((j for j in range(k + 1, min(k + janela + 1, n)) if 0.8 <= v[j] / ref <= 1.25), None)
        if fim is not None:
            ok[k:fim] = False
    c = c[ok]
    v = c.to_numpy(dtype=float).copy()
    r = v[1:] / v[:-1]
    for k in np.where((r < 0.1) | (r > 5))[0][::-1] + 1:
        v[:k] *= v[k] / v[k - 1]
    return pd.Series(v, index=c.index)


def giro_diario(close, volume, dias=63):
    """Mediana do volume financeiro diário (R$ milhões) nos últimos ~3 meses; None sem dado de volume."""
    try:
        g = (close * volume).dropna()
        g = g[g > 0].iloc[-dias:]
        return round(float(g.median()) / 1e6, 2) if len(g) >= 20 else None
    except Exception:
        return None


def parado(c, dias=20, anos=3):
    """A fonte parou de atualizar? Preço idêntico por 20 pregões seguidos ou mais nos últimos 3 anos (num ativo
    negociado todo dia, isso não acontece de verdade)."""
    if c is None or len(c) < dias:
        return False
    v = c[c.index > c.index[-1] - pd.DateOffset(years=anos)].to_numpy()
    seq = maior = 0
    for igual in v[1:] == v[:-1]:
        seq = seq + 1 if igual else 0
        maior = max(maior, seq)
    return maior + 1 >= dias


def _bcb_indice(serie):
    pts = []
    for ini in (2005, 2015):
        r = requests.get(f"https://api.bcb.gov.br/dados/serie/bcdata.sgs.{serie}/dados", timeout=20,
                         params={"formato": "json", "dataInicial": f"01/01/{ini}", "dataFinal": f"31/12/{ini + 9}"})
        pts += [(pd.Timestamp(x["data"][6:10] + "-" + x["data"][3:5] + "-" + x["data"][:2]), float(x["valor"])) for x in r.json()]
    return pd.Series(dict(pts), dtype=float).sort_index()


def _ipca_longo(etf):
    """Emenda o IMA-B 5+ do Banco Central (até mai/2023) com o ETF IB5M11 (depois disso)."""
    try:
        bcb = _bcb_indice(12468)
    except Exception:
        bcb = pd.Series(dtype=float)
    if bcb.empty or etf is None or etf.empty:
        return bcb if not bcb.empty else (etf if etf is not None else pd.Series(dtype=float))
    corte = bcb.index[-1]
    depois, base = etf[etf.index > corte], etf.asof(corte)
    if depois.empty or pd.isna(base):
        return bcb
    return pd.concat([bcb, depois / float(base) * float(bcb.iloc[-1])])


def baixar(codigos):
    """Baixa (com cache de 12h) o histórico máximo de vários ativos em uma única chamada ao Yahoo."""
    codigos = [c for c in dict.fromkeys(codigos) if c and c != "FII_IDX"]
    agora = time.time()
    velhos = lambda: [c for c in codigos if c not in _hist or agora - _hist[c][0] > TTL_HIST]
    if velhos():
        with _lock:
            falta = velhos()
            sint = [c for c in falta if c in SINTETICOS]
            falta = [c for c in falta if c not in SINTETICOS] + (["IB5M11"] if sint and "IB5M11" not in falta else [])
            if falta:
                syms = {ysym(c): c for c in falta}
                try:
                    df = yf.download(list(syms), period="max", auto_adjust=True, actions=True, progress=False,
                                     threads=True, group_by="column", multi_level_index=True)
                except Exception:
                    df = pd.DataFrame()
                for s, c in syms.items():
                    close, dv, giro = pd.Series(dtype=float), pd.Series(dtype=float), None
                    try:
                        bruto = _sem_tz(df["Close"][s].dropna().astype(float))
                        close = limpar(bruto[bruto > 0])
                        if c not in SIMB:  # índice e câmbio não têm volume que faça sentido
                            giro = giro_diario(bruto, _sem_tz(df["Volume"][s].astype(float)))
                    except Exception:
                        pass
                    try:
                        dv = _sem_tz(df["Dividends"][s].fillna(0).astype(float))
                        dv = dv[dv > 0]
                    except Exception:
                        pass
                    try:
                        sp = _sem_tz(df["Stock Splits"][s].fillna(0).astype(float))
                        _splits[c] = sp[sp > 0]
                    except Exception:
                        _splits[c] = pd.Series(dtype=float)
                    _hist[c] = (agora, close, dv, giro)
            if "IPCA_LONGO" in sint:
                _hist["IPCA_LONGO"] = (agora, _ipca_longo(_hist.get("IB5M11", (0, pd.Series(dtype=float)))[1]), pd.Series(dtype=float), None)
    return {c: _hist[c][1] for c in codigos if c in _hist}


def dividendos(codigo):
    """Proventos por cota (data-com), já baixados por `baixar`."""
    baixar([codigo])
    return _hist.get(codigo, (0, None, pd.Series(dtype=float), None))[2]


def desdobramentos(codigo):
    baixar([codigo])
    return _splits.get(codigo, pd.Series(dtype=float))


def ultimo_preco(codigo):
    baixar([codigo])
    c = _hist.get(codigo, (0, pd.Series(dtype=float)))[1]
    return float(c.iloc[-1]) if c is not None and len(c) else None


def fechamentos_brl(codigos):
    """Fechamentos diários em R$ (ativos em dólar são convertidos pela cotação do dia)."""
    usd = [c for c in codigos if c in EM_USD]
    raw = baixar(list(codigos) + (["DOLAR"] if usd else []))
    fx = raw.get("DOLAR", pd.Series(dtype=float))
    out = {}
    for c in codigos:
        s = raw.get(c)
        if s is None or s.empty:
            continue
        if c in EM_USD:
            if fx.empty:
                continue
            f = fx.reindex(s.index.union(fx.index)).ffill().reindex(s.index)
            s = (s * f).dropna()
        out[c] = s
    return out


def metricas_hist(codigo):
    """Métricas rápidas a partir do histórico em cache (moeda original do ativo)."""
    baixar([codigo])
    _, c, dv, giro = _hist.get(codigo, (0, pd.Series(dtype=float), pd.Series(dtype=float), None))
    if len(c) < 60:
        return None
    um_ano = c[c.index > c.index.max() - pd.Timedelta(days=365)]
    p = float(c.iloc[-1])
    sma200 = float(c.iloc[-200:].mean()) if len(c) >= 200 else None
    tres = c[c.index > c.index.max() - pd.Timedelta(days=3 * 365)]
    anos3 = (tres.index[-1] - tres.index[0]).days / 365.25
    div12 = float(dv[dv.index > c.index.max() - pd.Timedelta(days=365)].sum()) if len(dv) else 0.0
    ret = lambda n: round((p / float(c.iloc[-n - 1]) - 1) * 100, 1) if len(c) > n else None
    return {
        "preco": round(p, 2),
        "ret_1m": ret(21), "ret_12m": round((p / float(um_ano.iloc[0]) - 1) * 100, 1),
        "ret_3a_aa": round(((p / float(tres.iloc[0])) ** (1 / anos3) - 1) * 100, 1) if anos3 > 2.5 else None,
        "vol_aa": round(float(um_ano.pct_change().std() * 252 ** 0.5 * 100), 1),
        "queda_max_12m": round(float((um_ano / um_ano.cummax() - 1).min() * 100), 1),
        "dy_12m": round(div12 / p * 100, 1),
        "giro_dia": giro,
        "dados_parados": parado(c),
        "anos_hist": round((c.index[-1] - c.index[0]).days / 365.25, 1),
        "tendencia": None if sma200 is None else ("alta" if p > sma200 * 1.02 else "baixa" if p < sma200 * 0.98 else "lateral"),
        "serie": [round(float(x), 2) for x in um_ano.iloc[::5].tolist() + [p]],
    }


# ---------------------------------------------------------------- premissas de juros e inflação

def trajetoria_cdi(cdi_atual, focus_selic, meses):
    """CDI anual (%) mês a mês: parte do CDI de hoje e caminha até as medianas do Focus para o fim de cada ano."""
    cdi0 = cdi_atual if cdi_atual else 10.0
    hoje = date.today()
    pontos = [(0.0, cdi0)]
    for ano in sorted(focus_selic or {}):
        m = (int(ano) - hoje.year) * 12 + (12 - hoje.month)
        if m > 0:
            pontos.append((float(m), float(focus_selic[ano]) - 0.10))  # CDI fica ~0,10 p.p. abaixo da Selic
    xs, ys = zip(*pontos)
    return np.interp(np.arange(1, meses + 1), xs, ys)


def _mensal(aa):
    return (1 + np.asarray(aa, dtype=float) / 100) ** (1 / 12) - 1


def premissa_longo(classe, codigo, rf_longo, ipca_longo):
    """Retorno anual de equilíbrio (% a.a., em R$) antes de olhar o histórico do próprio ativo."""
    desval = min(max(ipca_longo - 2.5, 0.0), 6.0)  # desvalorização do real ~ diferencial de inflação
    if codigo == "GOLD11":
        return ((1 + desval / 100) * 1.035 - 1) * 100
    return {"acao": rf_longo + 4.0, "fii": rf_longo + 1.0,
            "exterior": ((1 + desval / 100) * 1.07 - 1) * 100, "cambio": desval}.get(classe, rf_longo)


# ---------------------------------------------------------------- matriz de retornos mensais históricos

def _retornos_mensais(series):
    if not series:
        return pd.DataFrame()
    df = pd.DataFrame({c: s.resample("ME").last() for c, s in series.items()})
    r = (df / df.shift(1) - 1).clip(-0.6, 1.0)  # corta erros grosseiros de dados do Yahoo
    hoje = pd.Timestamp.today()
    if len(r) and r.index[-1].year == hoje.year and r.index[-1].month == hoje.month:
        r = r.iloc[:-1]  # mês corrente ainda incompleto
    return r[r.index >= r.index.max() - pd.DateOffset(years=ANOS_HIST)] if len(r) else r


def matriz_historica(ativos):
    """Retornos mensais (meses x ativos) com lacunas preenchidas pelo proxy da classe, e as médias históricas."""
    mercado = [a for a, s in ativos.items() if s["tipo"] == "mercado"]
    precisa = set(BASE) | set(mercado)
    series = fechamentos_brl(sorted(precisa))
    r = _retornos_mensais(series)
    if r.empty or "IBOV" not in r:
        raise ValueError("histórico de mercado indisponível no momento")
    r = r[r["IBOV"].notna()]
    fii = [c for c in FII_CESTA if c in r]
    r["FII_IDX"] = r[fii].mean(axis=1) if fii else r["IBOV"] * 0.5
    cols, hist_aa, cobertura = {}, {}, {}
    for a, s in ativos.items():
        if s["tipo"] == "pos":
            cols[a] = pd.Series(0.0, index=r.index)
            continue
        proxy = PROXY_ATIVO.get(a) or PROXY_CLASSE.get(s["classe"], "IBOV")
        px = r[proxy] if proxy in r else pd.Series(0.0, index=r.index)
        proprio = r[a] if a in r and not parado(series.get(a)) else pd.Series(np.nan, index=r.index)
        cobertura[a] = int(proprio.notna().sum())
        base = proprio if cobertura[a] >= 24 else px
        base = base.dropna()
        hist_aa[a] = float((1 + base).prod() ** (12 / len(base)) - 1) * 100 if len(base) >= 12 else None
        if s["tipo"] == "ipca" and a not in r:
            col = px.fillna(0.0)
            col = col - col.mean()
        else:
            col = proprio.fillna(px).fillna(0.0)
        cols[a] = col
    H = pd.DataFrame(cols)
    return H, hist_aa, cobertura, r.index[0].strftime("%m/%Y")


# ---------------------------------------------------------------- simulação

def simular(carteiras, ativos, macro, cenarios, cenario="ponderado", inicial=0.0, mensal=0.0, anos=10, semente=7, meta=0.0):
    """carteiras: {nome: {ativo: peso}}; ativos: {ativo: {"classe","tipo": mercado|pos|ipca,"fator","real"}};
    macro: {"cdi","ipca","focus_selic"}; cenarios: [{"nome","prob","ajustes":{classe: p.p.}}]."""
    T = int(anos * 12)
    H, hist_aa, cobertura, desde = matriz_historica(ativos)
    cdi_path = trajetoria_cdi(macro.get("cdi"), macro.get("focus_selic"), T)
    rf_longo = float(np.mean(cdi_path[: min(T, 60)]))
    ipca_longo = float(macro.get("ipca") or 4.5)
    ipca_m = _mensal(ipca_longo)

    # média mensal aritmética de cada ativo, mês a mês (T,), antes das notícias
    vol_m = H.std().fillna(0.0)
    premissas, base_m = {}, {}
    for a, s in ativos.items():
        if s["tipo"] == "pos":
            aa = cdi_path * s.get("fator", 1.0)
            base_m[a] = _mensal(aa)
            premissas[a] = {"ret_aa": round(float(np.mean(aa)), 1), "vol_aa": 0.0, "classe": s["classe"]}
            continue
        if s["tipo"] == "ipca":
            g = ((1 + ipca_longo / 100) * (1 + s.get("real", 6.0) / 100) - 1) * 100
        else:
            eq = premissa_longo(s["classe"], a, rf_longo, ipca_longo)
            h = hist_aa.get(a)
            g = eq if h is None else 0.35 * min(max(h, -5.0), 25.0) + 0.65 * eq
        base_m[a] = np.full(T, _mensal(g) + vol_m[a] ** 2 / 2)  # converte retorno composto em média aritmética
        premissas[a] = {"ret_aa": round(g, 1), "vol_aa": round(float(vol_m[a] * 12 ** 0.5 * 100), 1), "classe": s["classe"]}

    # efeito das notícias: integral nos primeiros 12 meses, some linearmente até o mês 36
    t = np.arange(1, T + 1)
    decai = np.clip((36 - t) / 24, 0, 1)
    cenarios = cenarios or [{"nome": "Base", "prob": 100, "ajustes": {}}]
    nomes = [c["nome"] for c in cenarios]
    probs = np.array([max(float(c.get("prob", 0)), 0.0) for c in cenarios])
    probs = probs / probs.sum() if probs.sum() > 0 else np.full(len(cenarios), 1 / len(cenarios))

    rng = np.random.default_rng(semente)
    M = len(H)
    nblocos = -(-T // BLOCO)
    inicio = rng.integers(0, max(M - BLOCO + 1, 1), size=(N_CAMINHOS, nblocos))
    idx = (inicio[:, :, None] + np.arange(BLOCO)[None, None, :]).reshape(N_CAMINHOS, -1)[:, :T]
    idx = np.minimum(idx, M - 1)
    if cenario == "ponderado":
        cen_idx = rng.choice(len(cenarios), size=N_CAMINHOS, p=probs)
    else:
        k = nomes.index(cenario) if cenario in nomes else 0
        cen_idx = np.full(N_CAMINHOS, k)

    Hc = H - H.mean()  # só a variação em torno da média; a média vem das premissas
    contrib = np.arange(T + 1) * mensal
    investido = inicial + contrib
    cdi_val = np.empty(T + 1)
    cdi_val[0] = inicial
    for i, m in enumerate(_mensal(cdi_path)):
        cdi_val[i + 1] = cdi_val[i] * (1 + m) + mensal
    deflator = (1 + ipca_m) ** np.arange(T + 1)

    passo = max(1, -(-T // 120))
    pts = list(range(0, T + 1, passo))
    if pts[-1] != T:
        pts.append(T)

    resultado = {}
    for nome, pesos in carteiras.items():
        pesos = {a: w for a, w in pesos.items() if a in ativos and w > 0}
        tot = sum(pesos.values())
        if not tot:
            continue
        w = pd.Series({a: v / tot for a, v in pesos.items()})
        ruido = (Hc[w.index] @ w).to_numpy()[idx]                       # (N, T)
        media_cen = np.zeros((len(cenarios), T))
        for k, c in enumerate(cenarios):
            aj = c.get("ajustes", {})
            for a, wa in w.items():
                tilt = float(aj.get(ativos[a]["classe"], 0.0))
                media_cen[k] += wa * (base_m[a] + tilt / 1200 * decai)
        R = np.maximum(ruido + media_cen[cen_idx], -0.95)
        V = np.empty((N_CAMINHOS, T + 1))
        V[:, 0] = inicial
        for i in range(T):
            V[:, i + 1] = V[:, i] * (1 + R[:, i]) + mensal
        indice = np.cumprod(1 + R, axis=1)
        queda = (indice / np.maximum.accumulate(indice, axis=1) - 1).min(axis=1)
        pct = np.percentile(V[:, pts], [10, 25, 50, 75, 90], axis=0)
        final = V[:, -1]
        real_final = final / deflator[-1]
        resultado[nome] = {
            "faixas": {k: [round(float(x), 2) for x in pct[i]] for i, k in enumerate(["p10", "p25", "p50", "p75", "p90"])},
            "stats": {
                "p10": round(float(np.percentile(final, 10)), 2),
                "p50": round(float(np.percentile(final, 50)), 2),
                "p90": round(float(np.percentile(final, 90)), 2),
                "media": round(float(final.mean()), 2),
                "prob_perda": round(float((final < investido[-1] - 0.01).mean() * 100), 1),
                "prob_perda_real": round(float((real_final < investido[-1] - 0.01).mean() * 100), 1),
                "prob_cdi": round(float((final > cdi_val[-1]).mean() * 100), 1),
                "ret_aa": round(float((np.median(indice[:, -1]) ** (12 / T) - 1) * 100), 1),
                "vol_aa": round(float(np.std(ruido[:, :]) * 12 ** 0.5 * 100), 1),
                "queda_tipica": round(float(np.median(queda) * 100), 1),
                "queda_ruim": round(float(np.percentile(queda, 10) * 100), 1),
                "pior_12m": round(float(np.percentile(indice[:, 11] - 1, 5) * 100), 1) if T >= 12 else None,
                # meta em reais de hoje: compara com o valor final descontada a inflação do período
                "prob_meta": round(float((real_final >= meta).mean() * 100), 1) if meta > 0 else None,
            },
        }

    return {
        "meses": pts,
        "investido": [round(float(investido[i]), 2) for i in pts],
        "cdi": [round(float(cdi_val[i]), 2) for i in pts],
        "deflator": [round(float(deflator[i]), 5) for i in pts],
        "carteiras": resultado,
        "premissas": premissas,
        "cobertura": cobertura,
        "historico_desde": desde,
        "meses_historicos": M,
        "cdi_medio": round(rf_longo, 2),
        "ipca": round(ipca_longo, 2),
        "meta": meta or None,
    }


# ---------------------------------------------------------------- testes de estresse

def estresse(carteiras, ativos):
    """Quanto cada carteira teria variado em crises reais (buy and hold durante a janela da crise)."""
    mercado = [a for a, s in ativos.items() if s["tipo"] == "mercado"]  # títulos (pós e IPCA+) não têm cotação no Yahoo
    series = fechamentos_brl(sorted(set(BASE) | set(mercado)))

    def ret(cod, ini, fim):
        s = series.get(cod)
        if s is None or s.empty or s.index[0] > pd.Timestamp(ini) or s.index[-1] < pd.Timestamp(fim):
            return None
        a, b = s.asof(pd.Timestamp(ini)), s.asof(pd.Timestamp(fim))
        return None if pd.isna(a) or pd.isna(b) or a <= 0 else float(b / a - 1)

    out = []
    for nome, ini, fim, cdi in CRISES:
        dias = (pd.Timestamp(fim) - pd.Timestamp(ini)).days
        rf = (1 + cdi / 100) ** (dias / 365) - 1
        fii_vals = [x for x in (ret(c, ini, fim) for c in FII_CESTA) if x is not None]
        proxy = {"IBOV": ret("IBOV", ini, fim), "SP500": ret("SP500", ini, fim), "DOLAR": ret("DOLAR", ini, fim),
                 "OURO": ret("OURO", ini, fim), "IPCA_LONGO": ret("IPCA_LONGO", ini, fim),
                 "FII_IDX": float(np.mean(fii_vals)) if fii_vals else None}
        if proxy["IBOV"] is None:
            continue
        linha = {"nome": nome, "inicio": ini, "fim": fim, "ibov": round(proxy["IBOV"] * 100, 1),
                 "dolar": None if proxy["DOLAR"] is None else round(proxy["DOLAR"] * 100, 1), "carteiras": {}}
        for cn, pesos in carteiras.items():
            pesos = {a: w for a, w in pesos.items() if a in ativos and w > 0}
            tot = sum(pesos.values())
            if not tot:
                continue
            soma, estimado = 0.0, False
            for a, w in pesos.items():
                s = ativos[a]
                if s["tipo"] == "pos":
                    r = rf * s.get("fator", 1.0)
                else:
                    r = ret(a, ini, fim)
                    if r is None:
                        estimado = True
                        p = PROXY_ATIVO.get(a) or PROXY_CLASSE.get(s["classe"], "IBOV")
                        r = proxy.get(p)
                        if r is None:
                            r = rf if s["tipo"] == "ipca" else proxy["IBOV"] if s["classe"] in ("acao", "fii") else 0.0
                soma += w / tot * r
            linha["carteiras"][cn] = {"ret": round(soma * 100, 1), "estimado": estimado}
        out.append(linha)
    return out
