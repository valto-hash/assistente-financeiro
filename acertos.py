"""Quanto o app acerta: registro dos sinais de compra/venda, avaliação depois de 3, 6 e 12 meses e teste com o passado.

Critério de acerto (o mesmo nas duas medições):
- sinal de COMPRA acerta se, no período, o ativo rendeu mais que o CDI (ou seja, valeu mais que deixar na renda fixa);
- sinal de VENDA acerta se o ativo rendeu menos que o CDI (vender e deixar no CDI teria sido melhor).
Também mostramos a "taxa base": com que frequência o ativo bate o CDI sem sinal nenhum. Se os sinais de compra
acertam 55% e a taxa base é 53%, a vantagem das regras é pequena, e o app mostra isso com honestidade.
"""
import threading, time
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd
import requests

import armazem
import regras
import simulacao as sim

HORIZONTES = {"3m": 63, "6m": 126, "12m": 252}  # pregões
DIAS = {"3m": 91, "6m": 182, "12m": 365}
_lock = threading.Lock()
_cdi = {"t": 0, "s": None}


# ---------------------------------------------------------------- CDI histórico (Banco Central, série 4391: CDI no mês, % a.m.)

def cdi_mensal():
    """Índice acumulado do CDI no início de cada mês (Series). Cache de 24h; None se o BC não responder."""
    if _cdi["s"] is not None and time.time() - _cdi["t"] < 86400:
        return _cdi["s"]
    pontos = []
    hoje = date.today()
    try:
        for ini in range(2004, hoje.year + 1, 10):  # o BC limita a consulta a 10 anos por vez
            fim = min(ini + 9, hoje.year)
            r = requests.get("https://api.bcb.gov.br/dados/serie/bcdata.sgs.4391/dados", timeout=15,
                             params={"formato": "json", "dataInicial": f"01/01/{ini}", "dataFinal": f"31/12/{fim}"})
            pontos += [(datetime.strptime(x["data"], "%d/%m/%Y"), float(x["valor"].replace(",", "."))) for x in r.json()]
    except Exception:
        return _cdi["s"]
    if not pontos:
        return _cdi["s"]
    taxa = pd.Series({d: v for d, v in pontos}).sort_index()
    idx = (1 + taxa / 100).cumprod().shift(1).fillna(1.0)  # valor do índice no início de cada mês
    _cdi.update(t=time.time(), s=idx)
    return idx


def cdi_periodo(ini, fim, idx, cdi_atual=10.0):
    """Rendimento do CDI entre duas datas (aproximado pelo mês; sem dados do BC, usa a taxa atual)."""
    if idx is not None and len(idx):
        def em(d):
            d = pd.Timestamp(d)
            mes = pd.Timestamp(d.year, d.month, 1)
            base = idx.asof(mes)
            prox = idx.asof(mes + pd.offsets.MonthBegin(1))
            frac = (d - mes).days / max((mes + pd.offsets.MonthBegin(1) - mes).days, 1)
            return base * (prox / base) ** frac if base and prox else base
        a, b = em(ini), em(fim)
        if a and b and not np.isnan(a) and not np.isnan(b):
            return b / a - 1
    return (1 + cdi_atual / 100) ** ((pd.Timestamp(fim) - pd.Timestamp(ini)).days / 365) - 1


# ---------------------------------------------------------------- sinal das regras em toda a série (mesma lógica de regras.analise_ativo)

def sinais_serie(c):
    """Decisão das regras em cada pregão, usando só dados até aquele dia (sem olhar o futuro)."""
    s50, s200 = c.rolling(50).mean(), c.rolling(200).mean()
    d = c.diff()
    rsi = 100 - 100 / (1 + d.clip(lower=0).rolling(14).mean() / (-d.clip(upper=0)).rolling(14).mean())
    r3 = c / c.shift(63) - 1
    pts = (np.where(s200.notna(), np.where(c > s200, 1.0, -1.0), 0.0)
           + np.where(s200.notna() & s50.notna(), np.where(s50 > s200, 1.0, -1.0), 0.0)
           + np.where(r3.notna(), np.where(r3 > 0, 0.5, -0.5), 0.0))
    rsi_v = rsi.to_numpy()
    compra = (pts >= 2) & ~(rsi_v >= 70)
    venda = (pts <= -2) & ~(rsi_v <= 30)
    out = pd.Series(np.where(compra, "COMPRAR", np.where(venda, "VENDER", "MANTER")), index=c.index)
    return out.where(s200.notna())  # sem 200 pregões de histórico, sem sinal


def _vazio():
    return {"n": 0, "acertos": 0, "vantagem": []}


def _resumo(g):
    """acerto: % dos sinais que acertaram. vantagem_media: quanto o sinal ganhou do CDI, em média, em pontos percentuais
    (compra: rendimento do ativo menos o CDI; venda: CDI menos o rendimento do ativo, ou seja, o que se evitou perder)."""
    return {"n": g["n"], "acerto": round(g["acertos"] / g["n"] * 100, 1) if g["n"] else None,
            "vantagem_media": round(float(np.mean(g["vantagem"])) * 100, 1) if g["vantagem"] else None}


def backtest(codigos, cdi_atual=10.0, anos=20):
    """Roda as regras no primeiro pregão de cada mês dos últimos `anos` e mede o resultado 3, 6 e 12 meses depois."""
    idx = cdi_mensal()
    series = sim.fechamentos_brl(sorted(set(codigos) | {"IBOV"}))
    ibov = series.get("IBOV")
    tot = {h: {"COMPRAR": _vazio(), "VENDER": _vazio(), "base": _vazio()} for h in HORIZONTES}
    por_ativo = {}
    desde = None
    for cod in codigos:
        c = series.get(cod)
        if c is None or len(c) < 300:
            continue
        c = c[c.index >= c.index.max() - pd.DateOffset(years=anos)]
        sinais = sinais_serie(c)
        datas = c.groupby([c.index.year, c.index.month]).head(1).index  # 1º pregão de cada mês
        meu = {h: {"COMPRAR": _vazio(), "VENDER": _vazio(), "base": _vazio()} for h in HORIZONTES}
        pos = {d: i for i, d in enumerate(c.index)}
        for d in datas:
            s = sinais.get(d)
            if not isinstance(s, str):
                continue
            i = pos[d]
            for h, n in HORIZONTES.items():
                if i + n >= len(c):
                    continue
                fim = c.index[i + n]
                ret = c.iloc[i + n] / c.iloc[i] - 1
                exc = ret - cdi_periodo(d, fim, idx, cdi_atual)
                desde = min(desde, d) if desde else d
                for alvo in (tot[h], meu[h]):
                    alvo["base"]["n"] += 1; alvo["base"]["acertos"] += exc > 0
                    if s in ("COMPRAR", "VENDER"):
                        g = alvo[s]
                        g["n"] += 1; g["acertos"] += (exc > 0) if s == "COMPRAR" else (exc < 0)
                        g["vantagem"].append(exc if s == "COMPRAR" else -exc)
        por_ativo[cod] = {h: {k: _resumo(v) for k, v in meu[h].items()} for h in HORIZONTES}
    return {"geral": {h: {k: _resumo(v) for k, v in tot[h].items()} for h in HORIZONTES}, "por_ativo": por_ativo,
            "desde": desde.strftime("%m/%Y") if desde else None, "ativos": len(por_ativo), "cdi_real": idx is not None}


# ---------------------------------------------------------------- histórico real dos sinais do app

def registrar(ticker, decisao, preco, fonte, confianca=None, consenso=None, hoje=None):
    """Guarda um sinal de compra/venda. Repete o registro só se a decisão mudar ou depois de 30 dias,
    para não contar o mesmo sinal todos os dias."""
    if decisao not in ("COMPRAR", "VENDER") or not preco:
        return False
    hoje = hoje or date.today()
    with _lock:
        idx = armazem.ler("sinais_ultimo", "todos")
        ult = idx["dados"] if idx else {}
        k = f"{ticker}:{fonte}"
        u = ult.get(k)
        dias = (hoje - date.fromisoformat(u["data"])).days if u else None
        if u and u["decisao"] == decisao and 0 <= dias < 30:
            return False
        if dias is None or dias >= 0:
            ult[k] = {"decisao": decisao, "data": hoje.isoformat()}
        armazem.gravar("sinais_ultimo", "todos", ult)
        ano = str(hoje.year)
        d = armazem.ler("sinais", ano)
        lista = d["dados"]["itens"] if d else []
        lista.append({"ticker": ticker, "data": hoje.isoformat(), "decisao": decisao, "preco": preco, "fonte": fonte,
                      "confianca": confianca, "consenso": consenso})
        armazem.gravar("sinais", ano, {"itens": lista[-20000:]})
    return True


def todos_registros():
    out = []
    for _, d in armazem.listar("sinais"):
        out += d.get("itens", [])
    return sorted(out, key=lambda x: x["data"])


def avaliar(cdi_atual=10.0, hoje=None):
    """Avalia os sinais registrados que já completaram 3, 6 ou 12 meses."""
    hoje = hoje or date.today()
    regs = todos_registros()
    idx = cdi_mensal()
    series = sim.fechamentos_brl(sorted({r["ticker"] for r in regs})) if regs else {}
    grupos = {}
    recentes = []
    for r in regs:
        c = series.get(r["ticker"])
        d0 = pd.Timestamp(r["data"])
        fontes = [r["fonte"]] + (["consenso"] if r.get("consenso") == "concordam" else [])
        status = {}
        for h, dias in DIAS.items():
            fim = d0 + pd.Timedelta(days=dias)
            if fim.date() > hoje or c is None or c.index[-1] < fim or c.index[0] > d0:
                continue
            p0, p1 = c.asof(d0), c.asof(fim)
            if not p0 or np.isnan(p0) or np.isnan(p1):
                continue
            exc = (p1 / p0 - 1) - cdi_periodo(d0, fim, idx, cdi_atual)
            ok = exc > 0 if r["decisao"] == "COMPRAR" else exc < 0
            status[h] = {"acertou": bool(ok), "vs_cdi": round(float(exc) * 100, 1)}  # rendimento do ativo menos o CDI (p.p.)
            for f in fontes:
                g = grupos.setdefault(f, {hh: _vazio() for hh in DIAS})[h]
                g["n"] += 1; g["acertos"] += ok; g["vantagem"].append(exc if r["decisao"] == "COMPRAR" else -exc)
        pend = [h for h in DIAS if h not in status]
        recentes.append({**r, "avaliacao": status, "pendente": pend})
    return {"fontes": {f: {h: _resumo(g) for h, g in v.items()} for f, v in grupos.items()},
            "total": len(regs), "pendentes": sum(1 for x in recentes if "3m" in x["pendente"]),
            "desde": regs[0]["data"] if regs else None, "ultimos": recentes[-15:][::-1]}
