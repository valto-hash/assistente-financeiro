"""Indicadores fundamentalistas, histórico de proventos e ranking de ações e FIIs.

Fonte: Yahoo Finance (balanços e cotações). Os dados de empresas brasileiras no Yahoo têm falhas conhecidas, então:
- preço, dividend yield e liquidez são calculados pelo próprio app, a partir das cotações e dos proventos;
- units (ex.: TAEE11 = 1 ação ON + 2 PN) têm lucro, patrimônio e valor de mercado convertidos para a unit;
- valores fora de qualquer faixa razoável (ex.: P/L de 900) são escondidos, em vez de mostrados errados;
- cada indicador vem com a mediana do setor (ou da classe), para comparar, e uma explicação curta.
Comparar indicadores não é recomendação: um P/L baixo pode ser oportunidade ou sinal de lucro em queda.
"""
import statistics, threading, time
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pandas as pd
import yfinance as yf

import acertos
import simulacao as sim

UNIT_ACOES = {"TAEE11": 3, "KLBN11": 5, "SAPR11": 5, "ALUP11": 3, "SANB11": 2, "BPAC11": 3, "ENGI11": 5, "CPLE11": 5, "IGTI11": 3}
FINANCEIRAS = {"Bancos", "Bancária", "Seguros", "Serviços financeiros"}
TTL = 24 * 3600
_info: dict = {}
_lock = threading.Lock()

AJUDA = {
    "dy": "Proventos dos últimos 12 meses divididos pelo preço de hoje.",
    "pl": "Preço dividido pelo lucro por ação dos últimos 12 meses: quantos anos do lucro atual pagariam o preço. Menor "
          "costuma indicar mais barato, mas também pode refletir risco ou lucro prestes a cair.",
    "pvp": "Preço dividido pelo patrimônio por ação (ou por cota, no FII). Abaixo de 1, o mercado paga menos do que o "
           "patrimônio contábil.",
    "roe": "Lucro dividido pelo patrimônio: quanto a empresa gera para cada R$ 100 dos sócios em um ano.",
    "margem": "De cada R$ 100 vendidos, quanto vira lucro.",
    "margem_ebitda": "De cada R$ 100 vendidos, quanto vira geração de caixa operacional (EBITDA).",
    "div_ebitda": "Dívida menos o caixa, dividida pelo EBITDA do ano. Acima de 3 pede atenção; negativo quer dizer que "
                  "a empresa tem mais caixa que dívida.",
    "payout": "Parte do lucro distribuída aos acionistas.",
    "cresc_receita": "Receita do último trimestre contra a do mesmo trimestre do ano anterior.",
    "valor_mercado": "Quanto a empresa (ou o fundo) vale na bolsa hoje.",
    "giro": "Quanto se negocia por dia (mediana de 3 meses). Quanto maior, mais fácil comprar e vender sem mexer no preço.",
    "ret_12m": "Quanto a cota rendeu em 12 meses, com os proventos reinvestidos.",
    "dy_5a": "Média do dividend yield dos últimos 5 anos completos: mostra se o pagamento de hoje é normal ou fora da curva.",
    "cresc_div": "Crescimento médio por ano dos proventos por ação nos últimos 5 anos completos.",
}
ROTULO = {"dy": "Dividend yield (12m)", "pl": "P/L", "pvp": "P/VP", "roe": "ROE", "margem": "Margem líquida",
          "margem_ebitda": "Margem EBITDA", "div_ebitda": "Dív. líquida/EBITDA", "payout": "Payout",
          "cresc_receita": "Crescimento da receita", "valor_mercado": "Valor de mercado", "giro": "Negociado por dia",
          "ret_12m": "Retorno em 12 meses", "dy_5a": "Dividend yield médio (5 anos)", "cresc_div": "Crescimento dos proventos"}
FORMATO = {"dy": "pct", "pl": "x", "pvp": "x", "roe": "pct", "margem": "pct", "margem_ebitda": "pct", "div_ebitda": "x",
           "payout": "pct", "cresc_receita": "pct", "valor_mercado": "bi", "giro": "mi", "ret_12m": "pct", "dy_5a": "pct", "cresc_div": "pct"}
ORDEM = {"acao": ["dy", "pl", "pvp", "roe", "margem", "div_ebitda", "margem_ebitda", "payout", "cresc_receita", "dy_5a", "cresc_div",
                  "valor_mercado", "giro", "ret_12m"],
         "fii": ["dy", "pvp", "dy_5a", "cresc_div", "valor_mercado", "giro", "ret_12m"]}


def info(t):
    """Dados de balanço do Yahoo (cache de 24h; {} se não responder)."""
    agora = time.time()
    x = _info.get(t)
    if x and agora - x[0] < TTL:
        return x[1]
    try:
        d = yf.Ticker(sim.ysym(t)).info or {}
    except Exception:
        d = {}
    if d or not x:
        with _lock:
            _info[t] = (agora, d)
    return d if d else (x[1] if x else {})


def _ok(v, lo, hi):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    return v if lo < v < hi and not np.isnan(v) else None


def proventos_anuais(t, anos=10, fii=False):
    """Proventos por cota em cada ano (anos completos + o ano corrente até hoje), DY médio de 5 anos e crescimento."""
    sim.baixar([t])
    _, c, dv, _ = sim._hist.get(t, (0, pd.Series(dtype=float), pd.Series(dtype=float), None))
    if c is None or not len(c):
        return {"anos": [], "dy_5a": None, "cresc_div": None, "anos_pagou": 0}
    hoje = c.index[-1]
    por_ano = dv.groupby(dv.index.year).sum() if len(dv) else pd.Series(dtype=float)
    primeiro = max(c.index[0].year + (0 if c.index[0].month == 1 else 1), hoje.year - anos)
    linhas = [{"ano": a, "valor": round(float(por_ano.get(a, 0.0)), 4), "parcial": a == hoje.year} for a in range(primeiro, hoje.year + 1)]
    if fii:  # FII distribui todo semestre: ano zerado entre anos com pagamento é falha do Yahoo, não ano sem rendimento
        for k in range(1, len(linhas) - 1):
            if linhas[k]["valor"] == 0 and any(l["valor"] > 0 for l in linhas[:k]) and any(l["valor"] > 0 for l in linhas[k + 1:]):
                linhas[k]["valor"] = None
    completos = [l for l in linhas if not l["parcial"]]
    dy_5a = cresc = None
    if len(completos) >= 5 and len(dv):
        tela = c / acertos._fator_div(c, dv)  # preço da época (o ajustado subestima o preço antigo)
        dys = []
        for l in completos[-5:]:
            p = tela[tela.index.year == l["ano"]]
            if len(p) and l["valor"] is not None:
                dys.append(l["valor"] / float(p.mean()) * 100)
        dy_5a = round(statistics.mean(dys), 2) if len(dys) >= 4 else None
        a, b = completos[-5]["valor"], completos[-1]["valor"]
        cresc = round(((b / a) ** (1 / 4) - 1) * 100, 1) if a and b and a > 0 and b > 0 else None
    return {"anos": linhas, "dy_5a": dy_5a, "cresc_div": cresc, "anos_pagou": sum(1 for l in completos if (l["valor"] or 0) > 0),
            "anos_total": sum(1 for l in completos if l["valor"] is not None), "sem_dado": [l["ano"] for l in linhas if l["valor"] is None]}


def indicadores(t, classe, setor=None):
    """Indicadores de um ativo (só os confiáveis), na unidade em que ele é negociado."""
    m = sim.metricas_hist(t) or {}
    preco = m.get("preco")
    i = info(t)
    out = {"dy": m.get("dy_12m"), "giro": m.get("giro_dia"), "ret_12m": m.get("ret_12m")}
    f = UNIT_ACOES.get(t, 1)
    # valor de mercado: nas units, o "marketCap" do Yahoo mistura ações e units; preço x quantidade de units é o que bate
    vm = (preco * i["sharesOutstanding"] if f > 1 and preco and i.get("sharesOutstanding") else
          i.get("marketCap") if f == 1 else None)
    if vm:
        out["valor_mercado"] = _ok(vm / 1e9, 0, 1e5)
    if classe == "acao" and preco:
        # P/L: valor de mercado / lucro da empresa, conferido com preço / lucro por ação. Se as duas contas não
        # baterem (comum nas units no Yahoo), o P/L fica escondido em vez de aparecer errado.
        lucro, eps, bv = i.get("netIncomeToCommon"), i.get("trailingEps"), i.get("bookValue")
        pl1 = vm / lucro if vm and lucro and lucro > 0 else None
        outros = [preco / (eps * k) for k in {1, f}] if eps and eps > 0 else []
        if pl1 and outros:
            out["pl"] = _ok(pl1, 0, 200) if any(abs(pl1 / c - 1) <= 0.3 for c in outros) else None
            out["pl_inconsistente"] = out["pl"] is None
        elif pl1:
            out["pl"] = _ok(pl1, 0, 200)
        elif outros and f == 1:
            out["pl"] = _ok(outros[0], 0, 200)
        out["prejuizo"] = bool((lucro is not None and lucro < 0) or (lucro is None and eps is not None and eps < 0))
        if bv:  # patrimônio por ação já vem na unidade negociada (conferido com o P/VP do próprio Yahoo)
            out["pvp"] = _ok(preco / bv, 0, 50)
        out["roe"] = _ok((i.get("returnOnEquity") or np.nan) * 100, -100, 150)
        out["margem"] = _ok((i.get("profitMargins") or np.nan) * 100, -200, 100)
        out["payout"] = _ok((i.get("payoutRatio") or np.nan) * 100, 0, 500)
        out["cresc_receita"] = _ok((i.get("revenueGrowth") or np.nan) * 100, -95, 500)
        if setor not in FINANCEIRAS:
            ebitda = i.get("ebitda")
            if ebitda and ebitda > 0 and i.get("totalDebt") is not None:
                out["div_ebitda"] = _ok((i["totalDebt"] - (i.get("totalCash") or 0)) / ebitda, -10, 20)
            out["margem_ebitda"] = _ok((i.get("ebitdaMargins") or np.nan) * 100, 0, 100)
    elif classe == "fii" and preco:
        bv = i.get("bookValue")
        if bv:
            out["pvp"] = _ok(preco / bv, 0.1, 5)
    return ({k: (round(v, 2) if isinstance(v, float) else v) for k, v in out.items() if v is not None and not isinstance(v, bool) or v is True},
            i.get("longName"), preco)


def _medianas(linhas, chave_grupo):
    grupos = {}
    for l in linhas:
        grupos.setdefault(l[chave_grupo], []).append(l)
    out = {}
    for g, ls in grupos.items():
        out[g] = {}
        for k in FORMATO:
            vals = [l["ind"][k] for l in ls if l["ind"].get(k) is not None]
            if len(vals) >= 3:
                out[g][k] = round(statistics.median(vals), 2)
    return out


def ranking(universo, setores, etfs, classe):
    """Indicadores de todos os ativos da lista de uma classe (ações sem ETFs, ou FIIs)."""
    cods = [a for a, (c, _, _) in universo.items() if c == classe and a not in etfs]
    sim.baixar(cods)
    with ThreadPoolExecutor(8) as ex:
        res = dict(zip(cods, ex.map(lambda a: indicadores(a, classe, setores.get(a)), cods)))
    linhas = [{"ticker": a, "nome": universo[a][1], "setor": setores.get(a) or "Outros", "preco": res[a][2], "ind": res[a][0]}
              for a in cods if res[a][2]]
    med_setor, med_classe = _medianas(linhas, "setor"), _medianas([{**l, "g": classe} for l in linhas], "g").get(classe, {})
    return {"classe": classe, "linhas": linhas, "medianas_setor": med_setor, "mediana_classe": med_classe,
            "colunas": [k for k in ORDEM[classe] if k not in ("dy_5a", "cresc_div")], "rotulos": ROTULO, "formatos": FORMATO,
            "atualizado": time.time()}


def ficha(t, classe, setor, rank=None):
    """Tudo de um ativo: indicadores com a mediana do setor e explicação, e os proventos por ano."""
    ind, nome, preco = indicadores(t, classe, setor)
    prov = proventos_anuais(t, fii=classe == "fii")
    ind["dy_5a"], ind["cresc_div"] = prov["dy_5a"], prov["cresc_div"]
    med, base = {}, None
    if rank:
        if setor and rank["medianas_setor"].get(setor) and sum(1 for l in rank["linhas"] if l["setor"] == setor) >= 3:
            med, base = rank["medianas_setor"][setor], f"setor {setor.lower()}"
        else:
            med, base = rank["mediana_classe"], "ações da lista" if classe == "acao" else "FIIs da lista"
    lista = []
    for k in ORDEM.get(classe, []):
        if ind.get(k) is None:
            continue
        lista.append({"chave": k, "rotulo": ROTULO[k], "valor": ind[k], "formato": FORMATO[k], "ajuda": AJUDA[k],
                      "referencia": med.get(k)})
    return {"ticker": t, "nome": nome, "classe": classe, "setor": setor, "preco": preco, "indicadores": lista,
            "prejuizo": bool(ind.get("prejuizo")), "pl_inconsistente": bool(ind.get("pl_inconsistente")),
            "comparado_com": base, "proventos": prov,
            "fonte": "Cotações e proventos: Yahoo Finance, calculados pelo app. Balanços: Yahoo Finance (últimos 12 meses)."}
