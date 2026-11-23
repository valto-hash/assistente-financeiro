"""Simulador do passado: e se alguém tivesse seguido o app todo mês desde 2013?

Como funciona (o "walk-forward" que gestores usam para testar uma estratégia):
1. No fim de cada mês, o app recebe SÓ os dados que existiam naquela data: preços, proventos, Selic e IPCA da época.
2. Ele monta a carteira recomendada exatamente com as regras que usa hoje (panorama por juro real e tendência,
   alocação do perfil, escolha dos ativos, um por setor, preferência pelo que a pessoa já tem).
3. A pessoa simulada segue a recomendação com as regras de operação do app: o dinheiro novo vai para o que está
   abaixo do recomendado; só vende o que saiu da carteira ou o que passou muito da faixa e os aportes não resolvem.
   Cada compra e venda paga 0,1% de custo.
4. No mês seguinte, a carteira rende o que os ativos renderam de verdade. E assim por diante, até hoje.

O mesmo dinheiro, nas mesmas datas, é aplicado em estratégias de comparação: o modelo fixo do perfil só com ETFs
(o que o app faria sem tentar escolher nada), 100% CDI e os planos consagrados que cabem no perfil.

Limites (aparecem na tela): a IA não entra, porque ela "sabe" o que aconteceu depois; a lista de ativos é a de hoje
(viés de sobrevivência); os resultados são antes do imposto de renda (o IR estimado das vendas é mostrado à parte);
a expectativa de inflação da época é aproximada pelo IPCA dos 12 meses anteriores.
"""
import time
from datetime import date

import numpy as np
import pandas as pd
import requests

import acertos
import armazem
import referencias
import regras
import simulacao as sim
from ativos import ETF_ACAO, ETF_EXT, ETF_RF, RF, SETOR, UNIVERSO

INICIO = "2013-01"
VERSAO = 4               # mude quando o cálculo mudar: o resultado guardado no banco é refeito
CUSTO = 0.001            # 0,1% por compra ou venda (emolumentos da B3 + diferença entre compra e venda)
INICIAL, MENSAL = 10000.0, 1000.0
ETFS = ETF_ACAO | ETF_EXT | ETF_RF
LCI_BRUTO = 0.90 / 0.85  # LCI a 90% do CDI, isenta, equivale a ~106% do CDI de um investimento tributado
NUCLEO = {"renda_fixa": {"TESOURO_SELIC": .3, "LCI_LCA": .15, "TESOURO_IPCA": .55}, "acao": {"BOVA11": .6, "DIVO11": .4},
          "fii": {"KNCR11": .5, "HGLG11": .5}, "exterior": {"IVVB11": 1.0}, "cambio": {"DOLAR": .5, "GOLD11": .5}}
COMP_ATIVO = {"ACOES_BR": {"BOVA11": 1}, "EXTERIOR": {"IVVB11": 1}, "IPCA_LONGO": {"TESOURO_IPCA": 1}, "CDI": {"TESOURO_SELIC": 1},
              "OURO": {"GOLD11": 1}, "FII": {c: 1 / len(sim.FII_CESTA) for c in sim.FII_CESTA}, "SMALL": {"SMAL11": 1},
              "DIVID": {"DIVO11": 1}, "DOLAR": {"DOLAR": 1}}


# ---------------------------------------------------------------- dados de cada mês (só o que existia na data)

_bcb_cache = {}


def _bcb(serie, desde=2005):
    """Série do Banco Central, em trechos de 10 anos (limite da API). A API do BC às vezes falha: até 3 tentativas por
    trecho e cache de 12h, para duas rodadas seguidas não darem resultados diferentes."""
    c = _bcb_cache.get((serie, desde))
    if c and time.time() - c[0] < 12 * 3600:
        return c[1]
    pts, hoje = [], date.today()
    for ini in range(desde, hoje.year + 1, 10):
        for tentativa in range(3):
            try:
                r = requests.get(f"https://api.bcb.gov.br/dados/serie/bcdata.sgs.{serie}/dados", timeout=20,
                                 params={"formato": "json", "dataInicial": f"01/01/{ini}", "dataFinal": f"31/12/{min(ini + 9, hoje.year)}"})
                r.raise_for_status()
                dados = r.json()
                break
            except Exception:
                if tentativa == 2:
                    raise
                time.sleep(2 * (tentativa + 1))
        pts += [(pd.Timestamp(x["data"][6:10] + "-" + x["data"][3:5] + "-" + x["data"][:2]), float(x["valor"].replace(",", ".")))
                for x in dados]
    s = pd.Series(dict(pts), dtype=float).sort_index()
    _bcb_cache[(serie, desde)] = (time.time(), s)
    return s


def _taxas(meses, R):
    """Selic e IPCA de 12 meses no fim de cada mês (Banco Central). Sem o BC, aproxima pelo CDI e por 4,5% e avisa
    (o terceiro valor diz o que foi aproximado; resultado aproximado não fica guardado)."""
    aprox = []
    try:
        selic = _bcb(432).resample("ME").last().reindex(meses, method="ffill")
    except Exception:
        selic = ((1 + R["CDI"]).rolling(12).apply(np.prod, raw=True) - 1).reindex(meses) * 100 + 0.1
        aprox.append("Selic")
    try:
        # o IPCA de um mês só sai uns 10 dias depois: no fim do mês t, o último conhecido é o de t-1
        ipca = _bcb(13522).resample("ME").last().shift(1).reindex(meses, method="ffill")
    except Exception:
        ipca = pd.Series(4.5, index=meses)
        aprox.append("IPCA")
    return selic.ffill().fillna(10.0), ipca.ffill().fillna(4.5), aprox


def _metricas_mes(c, dv, meses):
    """As métricas que o app usa (as mesmas de simulacao.metricas_hist), calculadas no fim de cada mês."""
    if c is None or len(c) < 253:  # precisa de 1 ano de pregões até a data (conferido abaixo, mês a mês, só com o passado)
        return {}
    tela = c / acertos._fator_div(c, dv) if len(dv) else c
    div12 = (dv.reindex(c.index.union(dv.index), fill_value=0.0).rolling("365D").sum().reindex(c.index)
             if len(dv) else pd.Series(0.0, index=c.index))
    vol = c.pct_change().rolling(252).std() * 252 ** 0.5 * 100
    v, idx = c.to_numpy(), c.index
    out = {}
    for d in meses:
        i = idx.searchsorted(d, side="right") - 1
        if i < 252:
            continue
        p = v[i]
        i3 = idx.searchsorted(idx[i] - pd.DateOffset(years=3))
        anos = (idx[i] - idx[0]).days / 365.25
        jan = v[i - 251:i + 1]
        out[d] = {"preco": p, "ret_12m": (p / v[i - 252] - 1) * 100,
                  "ret_3a_aa": ((p / v[i3]) ** (1 / 3) - 1) * 100 if anos >= 3 and i3 < i else None,
                  "vol_aa": float(vol.iloc[i]), "queda_max_12m": float((jan / np.maximum.accumulate(jan) - 1).min() * 100),
                  "dy_12m": float(div12.iloc[i] / tela.iloc[i] * 100), "anos_hist": anos, "giro_dia": None}
    return out


def _indicador(idx_mensal, t):
    """Tendência, 12 meses e último mês de um índice, para o panorama da época (média de 10 meses ~ 200 pregões)."""
    s = idx_mensal[idx_mensal.index <= t]
    if len(s) < 13:
        return None
    p, med = float(s.iloc[-1]), float(s.iloc[-10:].mean())
    return {"tendencia": "alta" if p > med * 1.02 else "baixa" if p < med * 0.98 else "lateral",
            "ret_12m": (p / float(s.iloc[-13]) - 1) * 100, "ret_1m": (p / float(s.iloc[-2]) - 1) * 100}


def preparar(inicio=INICIO):
    """Tudo o que o simulador precisa, calculado uma vez para os três perfis."""
    R = referencias.componentes()
    meses = R.index[R.index >= pd.Timestamp(inicio + "-01")]
    mercado = [a for a in UNIVERSO if a not in RF]
    sim.baixar(mercado)
    F = {}
    for a in mercado:
        _, c, dv, _ = sim._hist.get(a, (0, None, pd.Series(dtype=float), None))
        if c is not None and not sim.parado(c):
            F[a] = _metricas_mes(c, dv, meses)
    proprias = sim.fechamentos_brl(mercado)
    ret = {}
    for a, (cl, _, _) in UNIVERSO.items():
        if a in RF:
            ret[a] = R["IPCA_LONGO"] if a == "TESOURO_IPCA" else R["CDI"] * (LCI_BRUTO if a == "LCI_LCA" else 1.0)
        else:
            ret[a] = referencias.serie_ativo(a, {"tipo": "mercado", "classe": cl}, R, proprias)[0]
    indices = {nome: (1 + R[k]).cumprod() for nome, k in (("IBOV", "ACOES_BR"), ("IFIX (FIIs grandes)", "FII"),
                                                         ("S&P 500 em reais", "EXTERIOR"), ("Dólar", "DOLAR")) if k in R}
    selic, ipca, aprox = _taxas(R.index, R)
    cdi12 = ((1 + R["CDI"]).rolling(12).apply(np.prod, raw=True) - 1) * 100
    return {"R": R, "meses": meses, "F": F, "ret": pd.DataFrame(ret).fillna(0.0), "indices": indices,
            "selic": selic, "ipca": ipca, "cdi12": cdi12, "aproximado": aprox}


# ---------------------------------------------------------------- operar como o app manda

def _ir(a, ganho, vendas_acoes_mes):
    """IR estimado de uma venda (regras gerais de pessoa física): só para mostrar, não é descontado."""
    if ganho <= 0 or a in RF:
        return 0.0
    c = UNIVERSO.get(a, ("acao",))[0]
    if c == "fii":
        return ganho * 0.20
    if c == "acao" and a not in ETFS and vendas_acoes_mes <= 20000:
        return 0.0
    return ganho * 0.15


def operar(hold, base, pesos, aporte, mensal):
    """Executa a recomendação do mês com as regras de operação do app. Devolve (custos, ir, operações)."""
    total = sum(hold.values()) + aporte
    alvo = {a: w / 100 * total for a, w in pesos.items() if w > 0}
    caixa, custos, ops, vendas = aporte, 0.0, 0, {}

    def vender(a, valor):
        nonlocal caixa, custos, ops
        valor = min(valor, hold[a])
        if valor <= 1:
            return
        frac = valor / hold[a]
        vendas[a] = vendas.get(a, 0) + valor
        vendas.setdefault("_ganho_" + a, 0)
        vendas["_ganho_" + a] += valor - base.get(a, valor) * frac
        base[a] = base.get(a, 0) * (1 - frac)
        hold[a] -= valor
        caixa += valor * (1 - CUSTO); custos += valor * CUSTO; ops += 1
        if hold[a] <= 1:
            caixa += hold.pop(a); base.pop(a, None)

    for a in list(hold):  # saiu da carteira recomendada: vende
        if a not in alvo:
            vender(a, hold[a])
    for a in list(hold):  # passou muito da faixa e os próximos 6 aportes não resolvem: vende o excesso
        p_at, p_alvo = hold[a] / total * 100, pesos[a]
        faixa = min(5, 0.25 * max(p_alvo, 4))
        excesso = hold[a] - alvo[a]
        if p_at - p_alvo > faixa and not (mensal > 0 and excesso <= 6 * mensal and p_at - p_alvo < 10):
            vender(a, excesso)
    falta = {a: max(v - hold.get(a, 0), 0) for a, v in alvo.items()}
    tf = sum(falta.values())
    if caixa > 0:
        partes = ({a: caixa * f / tf for a, f in falta.items()} if tf >= caixa else
                  {a: f + (caixa - tf) * pesos[a] / 100 for a, f in falta.items()})
        for a, v in partes.items():
            if v > 1:
                hold[a] = hold.get(a, 0) + v * (1 - CUSTO); base[a] = base.get(a, 0) + v
                custos += v * CUSTO; ops += 1
    acoes_mes = sum(v for k, v in vendas.items() if not k.startswith("_") and UNIVERSO.get(k, ("",))[0] == "acao" and k not in ETFS)
    ir = sum(_ir(a, vendas["_ganho_" + a], acoes_mes) for a in vendas if not a.startswith("_"))
    return custos, ir, ops


def _rodar(d, decidir, inicial, mensal):
    """Laço do mês a mês. decidir(t, hold) -> pesos (% por ativo)."""
    hold, base = {}, {}
    vals, aportes, rets, datas = [], [], [], []
    custos = ir = 0.0
    ops = 0
    meses = list(d["meses"])
    for i, t in enumerate(meses[:-1]):
        aporte = inicial if i == 0 else mensal
        antes = sum(hold.values())
        c, x, o = operar(hold, base, decidir(t, hold), aporte, mensal)
        custos += c; ir += x; ops += o
        prox = meses[i + 1]
        for a in hold:
            hold[a] *= 1 + float(d["ret"].at[prox, a]) if a in d["ret"] else 1
        depois = sum(hold.values())
        rets.append(depois / (antes + aporte) - 1)
        vals.append(depois); aportes.append(aporte); datas.append(prox)
    return {"datas": datas, "valores": vals, "aportes": aportes, "rets": rets, "custos": custos, "ir": ir, "operacoes": ops,
            "final": hold}


def _tir(aportes, final):
    """Taxa interna de retorno ao ano (o retorno de quem aplicou aos poucos)."""
    n = len(aportes)

    def vpl(r):
        return sum(-a / (1 + r) ** k for k, a in enumerate(aportes)) + final / (1 + r) ** n
    lo, hi = -0.05, 0.10
    for _ in range(100):
        m = (lo + hi) / 2
        if vpl(m) > 0:
            lo = m
        else:
            hi = m
    return ((1 + (lo + hi) / 2) ** 12 - 1) * 100


def _resumo(nome, x, extra=None):
    idx = np.cumprod(1 + np.array(x["rets"]))
    dd = idx / np.maximum.accumulate(np.concatenate([[1.0], idx]))[1:] - 1
    investido = float(np.sum(x["aportes"]))
    r12 = [idx[k] / idx[k - 12] - 1 for k in range(12, len(idx))]
    return {"nome": nome, **(extra or {}), "final": round(x["valores"][-1], 0), "investido": round(investido, 0),
            "ganho_pct": round((x["valores"][-1] / investido - 1) * 100, 1), "tir_aa": round(_tir(x["aportes"], x["valores"][-1]), 1),
            "maior_queda": round(float(dd.min()) * 100, 1), "pior_12m": round(min(r12) * 100, 1) if r12 else None,
            "custos": round(x["custos"], 0), "ir_estimado": round(x["ir"], 0), "operacoes": x["operacoes"],
            "serie": [round(v / a * 100, 1) for v, a in zip(x["valores"], np.cumsum(x["aportes"]))]}


def pesos_plano(pesos):
    """Pesos por ativo de um plano consagrado (cada componente vira o ativo que a pessoa compra)."""
    out = {}
    for k, w in pesos.items():
        for a, f in COMP_ATIVO[k].items():
            out[a] = out.get(a, 0) + w * f
    return out


def simular(d, perfil, modelo, limite_queda, inicial=INICIAL, mensal=MENSAL, anterior=None, cabem=None):
    """Roda o app e as estratégias de comparação para um perfil. anterior: o modelo do perfil antes de uma revisão.
    cabem: os planos que cabem no perfil pelos critérios da auditoria (queda e crises); sem isso, só pela maior queda."""
    R = d["R"]

    app, app_antigo = decisor(d, modelo), decisor(d, anterior or modelo, momento=True, classe_pequena=6)

    fixo = {a: modelo[c] * w for c, ws in NUCLEO.items() for a, w in ws.items() if modelo.get(c)}
    linhas = [_resumo("Seguindo o app", _rodar(d, app, inicial, mensal), {"id": "app"}),
              _resumo("O app antes deste teste (até nov/2026)", _rodar(d, app_antigo, inicial, mensal), {"id": "app_antigo"}),
              _resumo(f"Modelo fixo do perfil, só com ETFs e títulos", _rodar(d, lambda t, h: fixo, inicial, mensal), {"id": "fixo"}),
              _resumo("100% CDI", _rodar(d, lambda t, h: {"TESOURO_SELIC": 100}, inicial, mensal), {"id": "cdi"})]
    try:
        ref = referencias.para_perfil(referencias.planos_ref(), limite_queda)
        for p in ref["planos"]:
            if p["id"] == "cdi" or not (p["id"] in cabem if cabem is not None else p["cabe"]):
                continue
            pesos_p = pesos_plano(p["pesos"])
            linhas.append(_resumo(p["nome"], _rodar(d, lambda t, h, pp=pesos_p: pp, inicial, mensal), {"id": p["id"], "plano": True}))
    except Exception as e:
        print("planos no simulador falharam:", repr(e)[:200], flush=True)
    if anterior and anterior != modelo:
        fixo_ant = {a: anterior[c] * w for c, ws in NUCLEO.items() for a, w in ws.items() if anterior.get(c)}
        linhas.append(_resumo("Modelo fixo anterior do perfil (até nov/2026)", _rodar(d, lambda t, h: fixo_ant, inicial, mensal),
                              {"id": "fixo_antigo"}))
    app_, fixo_, cdi_ = linhas[0], linhas[2], linhas[3]
    melhores = sorted((l for l in linhas if l["id"] not in ("app_antigo", "fixo_antigo")), key=lambda l: -l["final"])
    return {"perfil": perfil, "linhas": linhas, "datas": [x.strftime("%Y-%m-%d") for x in _rodar_datas(d)],
            "desde": d["meses"][0].strftime("%m/%Y"), "ate": d["meses"][-1].strftime("%m/%Y"), "inicial": inicial, "mensal": mensal,
            "posicao": [l["id"] for l in melhores].index("app") + 1, "total": len(melhores),
            "vs_fixo": round(app_["final"] - fixo_["final"], 0), "vs_cdi": round(app_["final"] - cdi_["final"], 0),
            "modelo": modelo, "modelo_anterior": anterior if anterior and anterior != modelo else None}


def decisor(d, modelo, momento=None, classe_pequena=None):
    """A decisão do app no fim do mês t, só com os dados até t (as mesmas funções que montam a carteira de hoje)."""
    def app(t, hold):
        taxas = {"selic": float(d["selic"].at[t]), "ipca12": float(d["ipca"].at[t])}
        mercado = {k: v for k, v in ((n, _indicador(s, t)) for n, s in d["indices"].items()) if v}
        pan = regras.panorama(taxas, mercado)
        alvo, _ = regras.alvo_classes(modelo, pan["classes"], None, momento)
        cand = {a: {"classe": c, "nome": nm, "descricao": "", "m": (d["F"].get(a) or {}).get(t)} for a, (c, nm, _) in UNIVERSO.items()}
        cdi = float(d["cdi12"].at[t]) if not np.isnan(d["cdi12"].at[t]) else 10.0
        pesos, _ = regras.escolher_ativos(alvo, cand, dict(hold), {}, None, ETFS, cdi, SETOR, classe_pequena)
        return pesos
    return app


def _rodar_datas(d):
    return list(d["meses"])[1:]


# ---------------------------------------------------------------- prova ao vivo (sem olhar o passado)

def registrar_vivo(d, perfis):
    """Uma vez por mês, guarda a carteira que o app recomendaria para cada perfil com os dados do último mês fechado.
    Como ninguém sabe o mês seguinte, isto é um teste de verdade, sem o risco de ajustar regra olhando o resultado."""
    t = d["meses"][-1]
    k = t.strftime("%Y-%m")
    reg = (armazem.ler("simulador_vivo", "todos") or {}).get("dados") or {"meses": {}}
    planos = {p["id"]: pesos_plano(p["pesos"]) for p in referencias.PLANOS}  # as estratégias que a pessoa pode escolher
    if k in reg["meses"]:
        if "planos" not in reg["meses"][k]:  # o mês seguinte ainda não aconteceu: dá para guardar os planos também
            reg["meses"][k]["planos"] = planos
            armazem.gravar("simulador_vivo", "todos", reg)
        return reg
    reg["meses"][k] = {"app": {p: decisor(d, m)(t, {}) for p, m in perfis.items()},
                       "fixo": {p: {a: m[c] * w for c, ws in NUCLEO.items() for a, w in ws.items() if m.get(c)} for p, m in perfis.items()},
                       "planos": planos, "registrado": time.time()}
    armazem.gravar("simulador_vivo", "todos", reg)
    return reg


def resultado_vivo(d, reg, perfis):
    """Quanto renderam, mês a mês, as carteiras guardadas (cada uma vale para o mês seguinte ao do registro)."""
    meses = sorted(reg["meses"])
    out = {p: {"app": 1.0, "fixo": 1.0, "cdi": 1.0} for p in perfis}
    pl, pl_meses = {}, []
    rend = lambda pesos, prox: sum(w / (sum(pesos.values()) or 1) * float(d["ret"].at[prox, a]) for a, w in pesos.items() if a in d["ret"])
    usados = []
    for k in meses:
        t = pd.Timestamp(k + "-01") + pd.offsets.MonthEnd(0)
        prox = t + pd.offsets.MonthEnd(1)
        if prox not in d["ret"].index:
            continue
        usados.append(prox.strftime("%m/%Y"))
        for p in perfis:
            for chave in ("app", "fixo"):
                pesos = reg["meses"][k][chave].get(p) or {}
                tot = sum(pesos.values()) or 1
                out[p][chave] *= 1 + sum(w / tot * float(d["ret"].at[prox, a]) for a, w in pesos.items() if a in d["ret"])
            out[p]["cdi"] *= 1 + float(d["ret"].at[prox, "TESOURO_SELIC"])
        if reg["meses"][k].get("planos"):
            pl_meses.append(prox.strftime("%m/%Y"))
            for pid, pesos in reg["meses"][k]["planos"].items():
                pl[pid] = pl.get(pid, 1.0) * (1 + rend(pesos, prox))
    return {"desde": meses[0] if meses else None, "meses": usados,
            "perfis": {p: {k: round((v - 1) * 100, 2) for k, v in x.items()} for p, x in out.items()},
            "planos": {pid: round((v - 1) * 100, 2) for pid, v in pl.items()}, "planos_meses": pl_meses}


def tudo(perfis, limites, inicial=INICIAL, mensal=MENSAL, anteriores=None, cabem=None):
    t0 = time.time()
    d = preparar()
    out = {p: simular(d, p, perfis[p], limites[p], inicial, mensal, (anteriores or {}).get(p), (cabem or {}).get(p)) for p in perfis}
    vivo = None
    try:
        vivo = resultado_vivo(d, registrar_vivo(d, perfis), perfis)
    except Exception as e:
        print("prova ao vivo falhou:", repr(e)[:200], flush=True)
    print(f"simulador do passado pronto em {time.time() - t0:.0f}s", flush=True)
    return {"perfis": out, "custo_operacao": CUSTO * 100, "vivo": vivo, "calculado": time.time(), "versao": VERSAO,
            "aproximado": d["aproximado"]}
