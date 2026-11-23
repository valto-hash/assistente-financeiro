"""Corretora simulada: o app testado como num testador de estratégias (estilo MetaTrader), com dados reais, dia a dia.

O simulador mês a mês (simulador.py) usa retornos mensais e só estima o imposto. Aqui cada decisão vira ordens, como numa
conta de corretora de verdade:
- o app decide no último dia de cada mês, só com os dados até ali (a mesma função do simulador: simulador.decisor) e com
  as mesmas regras de operação (simulador.operar: aportes no que está abaixo do recomendado, vendas só quando o app mandaria);
- as ordens são executadas no fechamento do pregão seguinte, pelo preço de tela da época (sem o ajuste por proventos
  pagos depois), em quantidades inteiras de ações, cotas e ETFs (mercado fracionário); 0,03% de emolumentos da B3 e 0,05%
  de diferença entre compra e venda; corretagem zero. Antes de um ETF existir, vale o índice que ele segue;
- títulos e dólar aceitam frações: Tesouro Selic e CDB rendem o CDI, LCI/LCA 90% do CDI sem imposto, Tesouro IPCA+ segue o
  IMA-B 5+; Tesouro paga 0,20% ao ano de custódia, descontada do próprio título (sem venda e sem imposto); dólar (fundo
  cambial ou conta) paga 0,5% de câmbio em cada operação;
- dividendos e rendimentos caem na conta na data-com e entram nas compras do mês seguinte;
- o imposto de renda segue as regras da Receita: ações 15% sobre o lucro do mês quando as vendas de ações passam de
  R$ 20 mil; ETFs 15% e FIIs 20% sempre; prejuízo compensado depois na mesma categoria; pago (DARF) no mês seguinte com o
  dinheiro da conta. Tesouro e CDB: tabela regressiva (22,5% a 15%) descontada no resgate; LCI/LCA isenta;
- o patrimônio é marcado a mercado todo dia, já descontando imposto e custódia a pagar.
"""
import math
import time

import numpy as np
import pandas as pd

import acertos
import referencias
import simulacao as sim
import simulador as S
from ativos import ETF_ACAO, ETF_EXT, ETF_RF, RF, UNIVERSO

VERSAO = 2
EMOL, SPREAD, CAMBIO = 0.0003, 0.0005, 0.005
CUSTODIA_AA = 0.002
ETFS = ETF_ACAO | ETF_EXT | ETF_RF | {"GOLD11", "VOO"}
TESOURO = {"TESOURO_SELIC", "TESOURO_IPCA", "TESOURO_PREFIXADO"}
PROXY = {"acao": "IBOV", "exterior": "SP500", "fii": "FII_IDX", "cambio": "OURO"}
META = "2019-12-31"  # fim da 1ª metade (a mesma divisão usada na revisão dos modelos)


def _cat(a):
    if a in ("LCI_LCA", "POUPANCA"):
        return "isento"
    if a in RF:
        return "rf"
    if a == "DOLAR":
        return "dolar"
    if a in ETFS:
        return "etf"
    return "fii" if UNIVERSO.get(a, ("acao",))[0] == "fii" else "acao"


def _fracionado(a):
    return a in RF or a == "DOLAR"


def _ir_rf(dias):
    return 0.225 if dias <= 180 else 0.20 if dias <= 360 else 0.175 if dias <= 720 else 0.15


# ---------------------------------------------------------------- preços diários (dados reais)

def _cdi_diario(cal):
    """Índice diário do CDI: a taxa de cada mês (Banco Central) dividida pelos pregões do mês."""
    idx = acertos.cdi_mensal()
    if idx is None or not len(idx):
        r_m = pd.Series(0.008, index=pd.period_range(cal[0], cal[-1], freq="M"))
    else:
        m = (idx.shift(-1) / idx - 1).dropna()
        m.index = pd.PeriodIndex(m.index, freq="M")
        r_m = m
    per = pd.PeriodIndex(cal, freq="M")
    n = pd.Series(1, index=cal).groupby(per).transform("count").to_numpy()
    rm = r_m.reindex(per).ffill().bfill().fillna(0.008).to_numpy()
    diario = (1 + rm) ** (1 / n) - 1
    return pd.Series(np.cumprod(1 + diario) * 100, index=cal), pd.Series(diario, index=cal)


def precos(ativos, inicio):
    """Preço de tela diário e proventos por cota de cada ativo, num calendário de pregões da B3."""
    base = sim.fechamentos_brl(["IBOV", "SP500", "OURO", "DOLAR", "IPCA_LONGO", *sim.FII_CESTA])
    cal = base["IBOV"].index
    cal = cal[cal >= pd.Timestamp(inicio)]
    cdi, cdi_d = _cdi_diario(cal)
    lci = pd.Series(np.cumprod(1 + cdi_d.to_numpy() * 0.9) * 100, index=cal)
    al = lambda s: s.reindex(s.index.union(cal)).ffill().reindex(cal)
    fii_idx = pd.concat([al(base[c]).pct_change() for c in sim.FII_CESTA if c in base], axis=1).mean(axis=1).fillna(0)
    prox = {"IBOV": al(base["IBOV"]).pct_change().fillna(0), "SP500": al(base["SP500"]).pct_change().fillna(0),
            "OURO": al(base["OURO"]).pct_change().fillna(0), "FII_IDX": fii_idx}
    mercado = [a for a in ativos if not _fracionado(a)]
    sim.baixar(mercado)
    P, D = {}, {}
    for a in ativos:
        if a in ("TESOURO_SELIC", "CDB_CDI", "TESOURO_PREFIXADO", "PORQUINHO", "POUPANCA"):
            P[a] = cdi
        elif a == "LCI_LCA":
            P[a] = lci
        elif a == "TESOURO_IPCA":
            P[a] = al(base["IPCA_LONGO"]).bfill()
        elif a == "DOLAR":
            P[a] = al(base["DOLAR"]).bfill()
        else:
            _, c, dv, _ = sim._hist.get(a, (0, pd.Series(dtype=float), pd.Series(dtype=float), None))
            tela = (c / acertos._fator_div(c, dv)) if c is not None and len(c) and len(dv) else c
            if a in sim.EM_USD:  # cotado em dólar: preço convertido em reais, proventos já dentro do preço
                tela, dv = sim.fechamentos_brl([a]).get(a), pd.Series(dtype=float)
            r_px = prox[PROXY.get(UNIVERSO.get(a, ("acao",))[0], "IBOV")]
            if tela is None or not len(tela) or sim.parado(tela):
                s = pd.Series(np.cumprod(1 + r_px.to_numpy()) * 100, index=cal)  # sem dado confiável: o índice da classe
                dv = pd.Series(dtype=float)
            else:
                s = al(tela)
                ini = s.first_valid_index()
                if ini is not None and ini > cal[0]:  # antes de existir: o índice que ele segue, emendado no 1º preço
                    k = cal.get_loc(ini)
                    volta = np.cumprod(1 + r_px.iloc[1:k + 1].to_numpy()[::-1])[::-1]
                    s.iloc[:k] = float(s.iloc[k]) / volta
            P[a] = s
            dvv = dv[(dv.index >= cal[0])] if len(dv) else dv
            D[a] = dvv.groupby(cal[np.clip(cal.searchsorted(dvv.index), 0, len(cal) - 1)]).sum() if len(dvv) else pd.Series(dtype=float)
    Pm = pd.DataFrame(P).ffill().bfill()
    Dm = pd.DataFrame({a: D.get(a, pd.Series(dtype=float)).reindex(cal).fillna(0.0) for a in ativos}, index=cal)
    return Pm, Dm


# ---------------------------------------------------------------- a conta da corretora

def rodar(d, Pm, Dm, decidir, inicial=S.INICIAL, mensal=S.MENSAL):
    """Segue as decisões mês a mês com ordens reais, dia a dia. decidir(t, valores) -> pesos (% por ativo)."""
    cal, cols = Pm.index, list(Pm.columns)
    ix = {a: i for i, a in enumerate(cols)}
    Pn, Dn = Pm.to_numpy(), Dm.reindex(columns=cols).fillna(0.0).to_numpy()
    qtd, pm = np.zeros(len(cols)), np.zeros(len(cols))   # quantidade e preço médio
    lotes = {}                                           # renda fixa: lotes (data, qtd, preço) para a tabela regressiva
    caixa = ir_pend = 0.0
    custodia = np.zeros(len(cols))                       # custódia do Tesouro acumulada no mês, por título
    perda = {"rv": 0.0, "fii": 0.0}                       # prejuízo a compensar
    tot = {"emol": 0.0, "custodia": 0.0, "ir": 0.0, "proventos": 0.0, "cambio": 0.0}
    ordens, vendas_res, aplicado = [], [], 0.0
    execs = {}
    for t in d["meses"]:
        k = cal.searchsorted(t, side="right")
        if k < len(cal):
            execs[k] = t
    mes_ir = {"vendas_acoes": 0.0, "ganho": {"acao": 0.0, "etf": 0.0, "fii": 0.0}}
    eq, twr, aportes_dia = np.zeros(len(cal)), np.zeros(len(cal)), np.zeros(len(cal))
    is_tes = np.array([a in TESOURO for a in cols])
    v_ant = None

    def vender(j, q, i, motivo):
        nonlocal caixa
        a = cols[j]
        if q <= 0:
            return
        px = Pn[i, j] * (1 - (0 if _fracionado(a) else SPREAD))
        bruto = q * px
        custo = bruto * (EMOL if not _fracionado(a) else 0) + (bruto * CAMBIO if a == "DOLAR" else 0)
        ganho = bruto - custo - q * pm[j]
        cat, ir_ret = _cat(a), 0.0
        if cat == "rf":  # tabela regressiva, lote a lote (o mais antigo primeiro)
            resta = q
            for lt in lotes.get(a, []):
                if resta <= 0:
                    break
                usa = min(lt[1], resta)
                g = usa * (Pn[i, j] - lt[2])
                ir_ret += max(g, 0) * _ir_rf((cal[i] - lt[0]).days)
                lt[1] -= usa; resta -= usa
            lotes[a] = [lt for lt in lotes.get(a, []) if lt[1] > 1e-9]
        elif cat == "dolar":
            ir_ret = max(ganho, 0) * 0.15
        elif cat in ("acao", "etf", "fii"):
            mes_ir["ganho"][cat] += ganho
            if cat == "acao":
                mes_ir["vendas_acoes"] += bruto
        tot["emol"] += custo if a != "DOLAR" else 0
        tot["cambio"] += custo if a == "DOLAR" else 0
        tot["ir"] += ir_ret
        caixa += bruto - custo - ir_ret
        qtd[j] -= q
        if qtd[j] <= 1e-9:
            qtd[j] = 0.0; pm[j] = 0.0
        ordens.append((cal[i].strftime("%Y-%m-%d"), a, "V", round(q, 4), round(Pn[i, j], 4), round(bruto, 2), motivo))
        if cat not in ("rf", "isento"):  # estatística de operações: renda variável e dólar (resgate de título não é operação)
            vendas_res.append(ganho - ir_ret)

    def comprar(j, valor, i):
        nonlocal caixa
        a = cols[j]
        fr = _fracionado(a)
        px = Pn[i, j] * (1 + (0 if fr else SPREAD))
        unit = px * (1 + (CAMBIO if a == "DOLAR" else 0 if fr else EMOL))
        valor = min(valor, caixa)
        q = valor / unit if fr else math.floor(valor / unit)
        if q <= (1e-6 if fr else 0):
            return
        custo_total = q * unit
        pm[j] = (pm[j] * qtd[j] + custo_total) / (qtd[j] + q)
        qtd[j] += q
        caixa -= custo_total
        tot["emol"] += q * px * EMOL if not fr else 0
        tot["cambio"] += q * px * CAMBIO if a == "DOLAR" else 0
        if _cat(a) == "rf":
            lotes.setdefault(a, []).append([cal[i], q, Pn[i, j]])
        ordens.append((cal[i].strftime("%Y-%m-%d"), a, "C", round(q, 4), round(Pn[i, j], 4), round(q * px, 2), ""))

    n_exec = 0
    for i in range(len(cal)):
        # proventos na data-com e custódia do Tesouro (cobrada no dia da operação do mês)
        prov = float(qtd @ Dn[i])
        if prov:
            caixa += prov; tot["proventos"] += prov
        custodia += np.where(is_tes, qtd * Pn[i], 0.0) * CUSTODIA_AA / 252
        aporte = 0.0
        if i in execs:
            t = execs[i]
            aporte = inicial if n_exec == 0 else mensal
            n_exec += 1
            caixa += aporte; aplicado += aporte
            caixa -= ir_pend
            for j in np.nonzero(custodia)[0]:  # a B3 desconta a custódia do próprio título
                if qtd[j] > 0:
                    qtd[j] = max(qtd[j] - custodia[j] / Pn[i, j], 0.0)
                tot["custodia"] += float(custodia[j])
            ir_pend = 0.0
            custodia[:] = 0.0
            # decisão com o fechamento do mês (dia anterior à execução), ordens no fechamento de hoje
            vals_t = {cols[j]: float(qtd[j] * Pn[i - 1, j]) for j in np.nonzero(qtd)[0]} if i else {}
            pesos = decidir(t, dict(vals_t))
            pesos = {a: w for a, w in pesos.items() if a in ix and w > 0}
            hold, base = dict(vals_t), {a: float(qtd[ix[a]] * pm[ix[a]]) for a in vals_t}
            S.operar(hold, base, pesos, max(caixa, 0.0), mensal)
            for a, v_ant_a in vals_t.items():  # vendas primeiro (o dinheiro entra antes das compras)
                j = ix[a]
                novo = hold.get(a, 0.0)
                if novo <= 1:
                    vender(j, qtd[j], i, "saiu da carteira recomendada")
                elif novo < v_ant_a - 1:
                    q = (v_ant_a - novo) / Pn[i, j]
                    vender(j, min(qtd[j], q if _fracionado(a) else round(q)), i, "acima da faixa")
            compras = {a: (hold[a] - vals_t.get(a, 0.0)) / (1 - S.CUSTO) for a in hold if hold[a] > vals_t.get(a, 0.0) + 1}
            tc = sum(compras.values())
            if tc > 0 and caixa > 0:
                fator = min(1.0, caixa / tc)
                for a, v in sorted(compras.items(), key=lambda kv: -kv[1]):
                    comprar(ix[a], v * fator, i)
            if caixa < -0.01:  # imposto maior que o dinheiro da conta: vende o necessário (renda fixa primeiro)
                ordem = sorted(np.nonzero(qtd)[0], key=lambda j: (not _fracionado(cols[j]), -qtd[j] * Pn[i, j]))
                for j in ordem:
                    if caixa >= 0:
                        break
                    q = min(qtd[j], -caixa / Pn[i, j] * 1.01 if _fracionado(cols[j]) else math.ceil(-caixa / Pn[i, j]))
                    vender(j, q, i, "pagar o imposto")
            # imposto do mês (DARF no mês seguinte)
            g = mes_ir["ganho"]
            rv = g["etf"] + (g["acao"] if mes_ir["vendas_acoes"] > 20000 or g["acao"] < 0 else 0)
            base_rv = rv - perda["rv"] if rv > 0 else 0
            perda["rv"] = max(perda["rv"] - max(rv, 0), 0) + max(-rv, 0)
            base_fii = g["fii"] - perda["fii"] if g["fii"] > 0 else 0
            perda["fii"] = max(perda["fii"] - max(g["fii"], 0), 0) + max(-g["fii"], 0)
            ir_mes = max(base_rv, 0) * 0.15 + max(base_fii, 0) * 0.20
            ir_pend += ir_mes; tot["ir"] += ir_mes
            mes_ir = {"vendas_acoes": 0.0, "ganho": {"acao": 0.0, "etf": 0.0, "fii": 0.0}}
        v = float(qtd @ Pn[i]) + caixa - ir_pend - float(custodia.sum())
        eq[i], aportes_dia[i] = v, aporte
        twr[i] = 0.0 if v_ant is None or v_ant <= 0 else (v - aporte) / v_ant - 1
        v_ant = v
    return _relatorio(cal, eq, twr, aportes_dia, aplicado, ordens, vendas_res, tot, qtd, pm, Pn, cols, caixa)


def _aa(r, dias):
    return (float(np.prod(1 + r)) ** (252 / max(dias, 1)) - 1) * 100 if len(r) else None


def _relatorio(cal, eq, twr, aportes, aplicado, ordens, vendas_res, tot, qtd, pm, Pn, cols, caixa):
    ini = int(np.argmax(aportes > 0))
    eq, twr, aportes, cal_ = eq[ini:], twr[ini:], aportes[ini:], cal[ini:]
    idx = np.cumprod(1 + twr)
    dd = idx / np.maximum.accumulate(idx) - 1
    k_fundo = int(np.argmin(dd)); k_topo = int(np.argmax(idx[:k_fundo + 1])) if k_fundo else 0
    meio = cal_.searchsorted(pd.Timestamp(META), side="right")
    ganhos = [g for g in vendas_res if g > 0]; perdas = [g for g in vendas_res if g < 0]
    fluxos = pd.Series(aportes, index=cal_).groupby(pd.PeriodIndex(cal_, freq="M")).sum()
    final = float(eq[-1])
    # imposto se resgatasse tudo no último dia (estimativa: ações e ETFs 15%, FIIs 20%, renda fixa 15%)
    lat = sum(max(qtd[j] * Pn[-1, j] - qtd[j] * pm[j], 0) * (0.20 if _cat(cols[j]) == "fii" else 0 if _cat(cols[j]) == "isento" else 0.15)
              for j in range(len(cols)) if qtd[j] > 0)
    mensal_ix = pd.Series(eq, index=cal_).groupby(pd.PeriodIndex(cal_, freq="M")).last()
    apl_cum = np.cumsum(fluxos.to_numpy())
    compras = sum(1 for o in ordens if o[2] == "C")
    return {"final": round(final, 0), "aplicado": round(aplicado, 0), "lucro": round(final - aplicado, 0),
            "tir_aa": round(S._tir(list(fluxos.to_numpy()), final), 1) if len(fluxos) > 1 else None,
            "twr_aa": round(_aa(twr[1:], len(twr) - 1), 1),
            "metade1_aa": round(_aa(twr[1:meio], meio - 1), 1) if meio > 1 else None,
            "metade2_aa": round(_aa(twr[meio:], len(twr) - meio), 1) if meio < len(twr) else None,
            "maior_queda": round(float(dd.min()) * 100, 1),
            "queda_de": cal_[k_topo].strftime("%d/%m/%Y"), "queda_ate": cal_[k_fundo].strftime("%d/%m/%Y"),
            "ordens": len(ordens), "compras": compras, "vendas": len(ordens) - compras,
            "vendas_com_lucro": len(ganhos), "vendas_com_prejuizo": len(perdas),
            "lucro_bruto": round(sum(ganhos), 0), "prejuizo_bruto": round(sum(perdas), 0),
            "fator_lucro": round(sum(ganhos) / -sum(perdas), 2) if perdas else None,
            "maior_ganho": round(max(ganhos), 0) if ganhos else 0, "maior_perda": round(min(perdas), 0) if perdas else 0,
            "custos": round(tot["emol"] + tot["cambio"], 0), "custodia": round(tot["custodia"], 0), "ir_pago": round(tot["ir"], 0),
            "proventos": round(tot["proventos"], 0), "ir_se_resgatar": round(lat, 0), "caixa_final": round(caixa, 0),
            "curva": {"datas": [str(p) for p in mensal_ix.index], "patrimonio": [round(float(x), 0) for x in mensal_ix.to_numpy()],
                      "aplicado": [round(float(x), 0) for x in apl_cum]},
            "ultimas_ordens": [list(o) for o in ordens[-25:]],
            "posicao_final": sorted(([cols[j], round(float(qtd[j]), 4), round(float(qtd[j] * Pn[-1, j]), 0)]
                                     for j in range(len(cols)) if qtd[j] > 0), key=lambda x: -x[2])}


# ---------------------------------------------------------------- tudo: app, modelo fixo e planos

def tudo(perfis, anteriores=None):
    """Roda a corretora para a recomendada de cada perfil, o modelo fixo e todos os planos consagrados."""
    t0 = time.time()
    d = S.preparar()
    planos = {p["id"]: S.pesos_plano(p["pesos"]) for p in referencias.PLANOS}
    fixos = {p: {a: m[c] * w for c, ws in S.NUCLEO.items() for a, w in ws.items() if m.get(c)} for p, m in perfis.items()}
    ativos = sorted(set(UNIVERSO) | {a for p in planos.values() for a in p} | {a for f in fixos.values() for a in f})
    ativos = [a for a in ativos if a in ("DOLAR",) or a in RF or a in d["ret"]]
    Pm, Dm = precos(ativos, d["meses"][0])
    out = {"perfis": {}, "planos": {}}
    for p, m in perfis.items():
        out["perfis"][p] = {"app": rodar(d, Pm, Dm, S.decisor(d, m)),
                            "fixo": rodar(d, Pm, Dm, lambda t, h, w=fixos[p]: w)}
    for pid, w in planos.items():
        out["planos"][pid] = rodar(d, Pm, Dm, lambda t, h, w=w: w)
    cal = Pm.index
    return _py({**out, "desde": cal[cal.searchsorted(d["meses"][0], side="right")].strftime("%d/%m/%Y"),
            "ate": cal[-1].strftime("%d/%m/%Y"), "inicial": S.INICIAL, "mensal": S.MENSAL, "versao": VERSAO,
            "nomes": {p["id"]: p["nome"] for p in referencias.PLANOS}, "aproximado": d.get("aproximado") or [],
            "calculado": time.time(), "segundos": round(time.time() - t0)})


def _py(x):
    """Números do numpy viram números comuns (para o JSON)."""
    if isinstance(x, dict):
        return {k: _py(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_py(v) for v in x]
    if isinstance(x, np.integer):
        return int(x)
    if isinstance(x, np.floating):
        return float(x)
    return x
