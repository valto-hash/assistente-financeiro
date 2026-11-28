"""Imposto de renda dos investimentos em bolsa: apuração mensal (DARF) e relatório para a declaração anual.

Fontes das operações: as negociações importadas da B3 (Área do Investidor) e as compras e vendas que a pessoa registra no
app ("Registrei compra/venda"), guardadas aqui. Regras usadas (pessoa física, mercado à vista):
- ações (inclusive units): 15% sobre o lucro do mês; isento se o total de VENDAS de ações no mês for até R$ 20.000;
- ETFs de ações e BDRs: 15%, sem isenção;
- fundos imobiliários (FIIs e Fiagros): 20%, sem isenção;
- day trade (compra e venda do mesmo ativo no mesmo dia): 20%, sem isenção;
- prejuízo compensa lucro futuro do mesmo tipo (operações comuns entre si, FIIs entre si, day trade entre si);
- DARF código 6015, vencimento no último dia útil do mês seguinte; abaixo de R$ 10 o valor passa para o mês seguinte.
Limites: o preço de cada negócio vem da B3 ou do que a pessoa digitou, sem as taxas da corretora (que reduziriam o
lucro); o IR retido na fonte ("dedo-duro") aparece na nota de corretagem e pode ser abatido do DARF; feriados não entram
no cálculo do vencimento. É uma conferência: o valor oficial é o do programa da Receita.
"""
import time
import uuid
from datetime import date, timedelta

import armazem
from ativos import ETF_ACAO, ETF_EXT, ETF_RF, RF, UNIVERSO

ISENCAO_ACOES = 20000.0
DARF_MINIMO = 10.0
ALIQ = {"comum": 0.15, "fii": 0.20, "day": 0.20}
NOME_TIPO = {"acao": "Ações", "etf": "ETFs e BDRs", "fii": "Fundos imobiliários", "day": "Day trade"}


# ---------------------------------------------------------------- operações registradas no app

def _ler(uid):
    d = armazem.ler("operacoes", uid)
    return (d["dados"] if d else None) or {"itens": []}


def operacoes(uid):
    return _ler(uid)["itens"]


def registrar(uid, data, ticker, tipo, qtd, preco):
    if tipo not in ("compra", "venda"):
        raise ValueError("Tipo deve ser compra ou venda.")
    try:
        d = date.fromisoformat(str(data)[:10])
    except ValueError:
        raise ValueError("Data inválida.")
    if d > date.today() + timedelta(days=1):
        raise ValueError("A data não pode ser no futuro.")
    if not (qtd and qtd > 0 and preco and preco > 0):
        raise ValueError("Informe quantidade e preço maiores que zero.")
    x = _ler(uid)
    it = {"id": uuid.uuid4().hex[:12], "data": d.isoformat(), "ticker": str(ticker).upper()[:12], "tipo": tipo,
          "qtd": round(float(qtd), 6), "preco": round(float(preco), 6), "origem": "app", "criado": time.time()}
    x["itens"] = sorted(x["itens"] + [it], key=lambda m: (m["data"], m["criado"]))[-20000:]
    armazem.gravar("operacoes", uid, x)
    return it


def apagar(uid, oid):
    x = _ler(uid)
    n = len(x["itens"])
    x["itens"] = [m for m in x["itens"] if m["id"] != oid]
    if len(x["itens"]) == n:
        raise KeyError(oid)
    armazem.gravar("operacoes", uid, x)


def todas(uid, movs_b3=None):
    """Negociações da B3 + operações registradas no app, sem repetir a mesma operação."""
    out, vistas = [], set()
    for m in (movs_b3 or []) + operacoes(uid):
        if m.get("tipo") not in ("compra", "venda", "evento"):
            continue
        k = (m["data"], m["ticker"], m["tipo"], round(m["qtd"], 4), round(m.get("preco") or 0, 2))
        if k in vistas:
            continue
        vistas.add(k)
        out.append(m)
    return sorted(out, key=lambda m: (m["data"], {"evento": 0, "compra": 1, "venda": 2}[m["tipo"]]))


# ---------------------------------------------------------------- apuração

def tipo_ativo(t):
    """acao, etf (ETF de ações e BDR), fii, ou None (renda fixa e o que não é bolsa)."""
    if t in RF or t in ("DOLAR", "VOO"):
        return None
    if t in ETF_ACAO | ETF_EXT | ETF_RF or t == "GOLD11":
        return "etf"
    c = UNIVERSO.get(t, (None,))[0]
    if c == "fii":
        return "fii"
    if len(t) >= 6 and t[4:6] in ("32", "33", "34", "35", "39"):
        return "etf"  # BDR: 15% sem isenção, como os ETFs
    if c in ("acao", "exterior"):
        return "acao" if c == "acao" else "etf"
    return "fii" if t.endswith("11") and c is None and t not in UNIVERSO else "acao"


def ultimo_dia_util(ano, mes):
    d = (date(ano + mes // 12, mes % 12 + 1, 1) - timedelta(days=1))
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def apurar(movs):
    """Apuração mês a mês. Devolve meses (lucros, vendas, imposto, DARF) e a posição com o preço médio ao fim."""
    q, custo = {}, {}
    meses = {}
    por_dia = {}
    for m in movs:
        if m["tipo"] in ("compra", "venda"):
            por_dia.setdefault((m["data"], m["ticker"]), {"compra": [0.0, 0.0], "venda": [0.0, 0.0]})
            p = por_dia[(m["data"], m["ticker"])][m["tipo"]]
            p[0] += m["qtd"]; p[1] += m["qtd"] * (m.get("preco") or 0)
    day_usado = {}
    for m in movs:
        t, ym = m["ticker"], m["data"][:7]
        tp = tipo_ativo(t)
        if tp is None:
            continue
        mes = meses.setdefault(ym, {"vendas_acoes": 0.0, "lucro": {"acao": 0.0, "etf": 0.0, "fii": 0.0, "day": 0.0},
                                    "vendas": {"acao": 0.0, "etf": 0.0, "fii": 0.0}, "operacoes": 0})
        mes["operacoes"] += 1
        if m["tipo"] == "evento":
            q[t] = max(q.get(t, 0) + m["qtd"], 0)
            continue
        dia = por_dia[(m["data"], t)]
        dt = min(dia["compra"][0], dia["venda"][0])  # quantidade de day trade no dia
        ja = day_usado.get((m["data"], t, m["tipo"]), 0.0)
        q_dt = max(min(dt - ja, m["qtd"]), 0.0)
        day_usado[(m["data"], t, m["tipo"])] = ja + q_dt
        q_comum = m["qtd"] - q_dt
        if m["tipo"] == "venda" and q_dt > 0:
            pc = dia["compra"][1] / dia["compra"][0]
            mes["lucro"]["day"] += q_dt * ((m.get("preco") or 0) - pc)
        if q_comum <= 0:
            continue
        if m["tipo"] == "compra":
            q[t] = q.get(t, 0) + q_comum
            custo[t] = custo.get(t, 0) + q_comum * (m.get("preco") or 0)
        else:
            pm = custo[t] / q[t] if q.get(t, 0) > 0 else (m.get("preco") or 0)
            vend = min(q_comum, q.get(t, 0)) if q.get(t, 0) > 0 else q_comum
            valor = q_comum * (m.get("preco") or 0)
            mes["lucro"][tp] += q_comum * ((m.get("preco") or 0) - pm)
            mes["vendas"][tp] += valor
            if tp == "acao":
                mes["vendas_acoes"] += valor
            if q.get(t, 0) > 0:
                q[t] -= vend; custo[t] -= pm * vend
                if q[t] <= 1e-9:
                    q[t], custo[t] = 0.0, 0.0
    # imposto mês a mês, com prejuízo a compensar e DARF mínimo
    preju = {"comum": 0.0, "fii": 0.0, "day": 0.0}
    acumulado = 0.0
    out = []
    for ym in sorted(meses):
        mm = meses[ym]
        L = mm["lucro"]
        isento = mm["vendas_acoes"] <= ISENCAO_ACOES
        lucro_isento = max(L["acao"], 0) if isento else 0.0
        comum = L["etf"] + (L["acao"] if not isento or L["acao"] < 0 else 0.0)
        bases = {}
        for k, v in (("comum", comum), ("fii", L["fii"]), ("day", L["day"])):
            if v >= 0:
                usa = min(preju[k], v)
                preju[k] -= usa
                bases[k] = v - usa
            else:
                preju[k] += -v
                bases[k] = 0.0
        imposto = sum(bases[k] * ALIQ[k] for k in bases)
        a_pagar = imposto + acumulado
        a, mes_n = int(ym[:4]), int(ym[5:])
        venc = ultimo_dia_util(a + (mes_n == 12), mes_n % 12 + 1)
        if 0 < a_pagar < DARF_MINIMO:
            acumulado, darf = a_pagar, 0.0
        else:
            acumulado, darf = 0.0, a_pagar
        out.append({"mes": ym, "vendas_acoes": round(mm["vendas_acoes"], 2), "isento_acoes": isento and mm["vendas_acoes"] > 0,
                    "lucro_isento": round(lucro_isento, 2),
                    "lucro": {k: round(v, 2) for k, v in L.items()}, "vendas": {k: round(v, 2) for k, v in mm["vendas"].items()},
                    "base": {k: round(v, 2) for k, v in bases.items()}, "imposto": round(imposto, 2),
                    "darf": round(darf, 2), "acumulado_proximo": round(acumulado, 2), "vencimento": venc.isoformat(),
                    "codigo": "6015", "prejuizo_a_compensar": {k: round(v, 2) for k, v in preju.items()}})
    posicao = {t: {"qtd": round(q[t], 6), "custo": round(custo[t], 2), "pm": round(custo[t] / q[t], 4)}
               for t in q if q[t] > 1e-9}
    return {"meses": out, "posicao": posicao, "prejuizo_a_compensar": {k: round(v, 2) for k, v in preju.items()}}


# ---------------------------------------------------------------- declaração anual

GRUPO_BEM = {"acao": ("03", "01", "Ações (inclusive as listadas em bolsa)"), "fii": ("07", "03", "Fundos de Investimento Imobiliário (FII)"),
             "etf": ("07", "09", "Fundos de índice (ETF) / BDR: confira o código no programa")}


def declaracao(movs, proventos, ano, rf_saldos=None):
    """Bens e direitos em 31/12 (custo de aquisição, não o valor de mercado), rendimentos isentos e tributados."""
    ate = [m for m in movs if m["data"] <= f"{ano}-12-31"]
    ap = apurar(ate)
    ant = apurar([m for m in movs if m["data"] <= f"{ano - 1}-12-31"])["posicao"]
    bens = []
    for t, x in sorted(ap["posicao"].items()):
        tp = tipo_ativo(t) or "acao"
        g, c, desc = GRUPO_BEM[tp]
        bens.append({"ticker": t, "grupo": g, "codigo": c, "tipo": desc, "qtd": x["qtd"], "custo_31_12": x["custo"],
                     "custo_ano_anterior": (ant.get(t) or {}).get("custo", 0.0),
                     "discriminacao": f"{x['qtd']:g} cotas/ações de {t}, custo médio de R$ {x['pm']:.2f}".replace(".", ",")})
    for t, saldo in (rf_saldos or {}).items():
        bens.append({"ticker": t, "grupo": "04", "codigo": "03" if t == "LCI_LCA" else "02",
                     "tipo": "Aplicação de renda fixa (confira o código no programa)", "qtd": None, "custo_31_12": round(saldo, 2),
                     "custo_ano_anterior": None, "discriminacao": f"{RF.get(t, t)}: informe o valor aplicado do informe de rendimentos"})
    do_ano = [p for p in proventos if p["data"].startswith(str(ano))]
    isentos = {"Dividendos": 0.0, "Rendimentos de FIIs": 0.0}
    tributados = {"Juros sobre capital próprio": 0.0}
    for p in do_ano:
        if p["tipo"] == "JCP":
            tributados["Juros sobre capital próprio"] += p["valor"]
        elif p["tipo"] == "Rendimento" or tipo_ativo(p["ticker"]) == "fii":
            isentos["Rendimentos de FIIs"] += p["valor"]
        elif p["tipo"] == "Dividendo":
            isentos["Dividendos"] += p["valor"]
    meses_ano = [m for m in ap["meses"] if m["mes"].startswith(str(ano))]
    isentos["Lucro com ações até R$ 20 mil de vendas no mês"] = sum(m["lucro_isento"] for m in meses_ano)
    return {"ano": ano, "bens": bens, "isentos": {k: round(v, 2) for k, v in isentos.items()},
            "tributacao_exclusiva": {k: round(v, 2) for k, v in tributados.items()},
            "renda_variavel": meses_ano, "prejuizo_a_compensar_31_12": ap["prejuizo_a_compensar"],
            "darf_pagos_no_ano": round(sum(m["darf"] for m in meses_ano), 2)}
