"""Planos de investimento consagrados, testados com dados reais do Brasil, e a auditoria de cada recomendação.

Planos de referência (adaptados para o investidor brasileiro, com ativos que ele consegue comprar):
- CDI (Tesouro Selic): o mínimo que qualquer carteira precisa justificar por que tenta superar.
- Portfólio Permanente (Harry Browne): 1/4 em ações, 1/4 em títulos longos, 1/4 em caixa e 1/4 em ouro.
- All Weather (Ray Dalio/Bridgewater): pouca bolsa e muitos títulos longos, para atravessar qualquer cenário.
- 60/40: 60% em ações e 40% em títulos, a referência de fundos de pensão no mundo todo há décadas.
- Três fundos (Bogleheads): ações do país, ações de fora e títulos, com custo mínimo.

"Provas" aqui são os números de cada plano no período testado, calculados pelo app com cotações e índices reais
(rebalanceamento anual, sem custos e sem impostos). Isso mostra como cada plano se comportou de verdade em
2011-2026 no Brasil (inclui a recessão de 2015-16, a pandemia, a alta de juros de 2021-22 e a queda de out/2026),
mas o passado não garante o futuro.

A auditoria confere toda recomendação (da IA ou das regras) antes de ela chegar à pessoa. As checagens que
"bloqueiam" fazem o app descartar a carteira da IA e usar a das regras; as de "aviso" aparecem na tela.
"""
import threading, time
from datetime import date

import numpy as np
import pandas as pd

import acertos
import investimentos
import simulacao as sim

INICIO = "2011-04"  # primeiro mês com todas as séries (FIIs desde mar/2011)
PLANOS = [
    {"id": "cdi", "nome": "100% CDI", "autor": "Tesouro Selic ou CDB de 100% do CDI",
     "pesos": {"CDI": 100},
     "ideia": "Não correr risco nenhum de bolsa. É a régua: uma carteira com risco só faz sentido se, no longo prazo, "
              "render mais do que isso."},
    {"id": "permanente", "nome": "Portfólio Permanente", "autor": "Harry Browne, 1981",
     "pesos": {"ACOES_BR": 25, "IPCA_LONGO": 25, "CDI": 25, "OURO": 25},
     "ideia": "Um quarto para cada cenário: crescimento (ações), queda de juros (títulos longos), crise de crédito "
              "(caixa) e inflação ou medo (ouro). Rebalanceia uma vez por ano e não tenta prever nada."},
    {"id": "all_weather", "nome": "All Weather (Todas as Estações)", "autor": "Ray Dalio / Bridgewater, divulgado em 2014",
     "pesos": {"ACOES_BR": 15, "EXTERIOR": 15, "IPCA_LONGO": 40, "CDI": 15, "OURO": 15},
     "ideia": "Equilibra o risco entre os cenários de crescimento e de inflação; por isso tem pouca bolsa e muitos títulos "
              "longos. Na versão original, 7,5% em commodities: aqui somados ao ouro."},
    {"id": "60_40", "nome": "60/40 clássica", "autor": "referência de fundos de pensão desde os anos 1950",
     "pesos": {"ACOES_BR": 30, "EXTERIOR": 30, "IPCA_LONGO": 40},
     "ideia": "60% em ações (metade no Brasil, metade nos EUA) para crescer e 40% em títulos para amortecer as quedas."},
    {"id": "tres_fundos", "nome": "Três fundos", "autor": "Taylor Larimore e a comunidade Bogleheads",
     "pesos": {"ACOES_BR": 40, "EXTERIOR": 20, "IPCA_LONGO": 20, "CDI": 20},
     "ideia": "Três investimentos amplos e baratos (ações daqui, ações de fora e renda fixa), sem escolher empresa nenhuma."},
    {"id": "wellesley", "nome": "Renda e crescimento 35/65", "autor": "inspirada no fundo Vanguard Wellesley Income, ativo desde 1970",
     "pesos": {"DIVID": 20, "EXTERIOR": 15, "IPCA_LONGO": 35, "CDI": 30},
     "ideia": "Conservadora: 65% em renda fixa e 35% em ações de empresas que pagam bons dividendos. Busca renda e quedas pequenas."},
    {"id": "golden_butterfly", "nome": "Golden Butterfly (Borboleta Dourada)", "autor": "Tyler, do site Portfolio Charts",
     "pesos": {"ACOES_BR": 20, "SMALL": 20, "IPCA_LONGO": 20, "CDI": 20, "OURO": 20},
     "ideia": "Uma variação do Permanente com mais ações, incluindo empresas menores, que crescem mais no longo prazo. Busca "
              "quedas pequenas sem abrir mão de crescimento."},
    {"id": "coffeehouse", "nome": "Coffeehouse", "autor": "Bill Schultheis, livro The Coffeehouse Investor, 1998",
     "pesos": {"IPCA_LONGO": 20, "CDI": 20, "ACOES_BR": 10, "DIVID": 10, "SMALL": 20, "EXTERIOR": 10, "FII": 10},
     "ideia": "40% em renda fixa e 60% divididos entre vários tipos de ações e imóveis. Diversifica muito e não mexe: o autor "
              "dizia para ir tomar um café em vez de acompanhar o mercado."},
    {"id": "swensen", "nome": "Carteira de Swensen (Yale)", "autor": "David Swensen, gestor do fundo da Universidade Yale, livro Unconventional Success, 2005",
     "pesos": {"ACOES_BR": 30, "EXTERIOR": 20, "FII": 20, "IPCA_LONGO": 15, "CDI": 15},
     "ideia": "A versão para pessoa física da gestão do fundo de Yale: muito diversificada, com bastante imóveis (aqui, FIIs) e "
              "títulos protegidos da inflação."},
    {"id": "core_four", "nome": "Core Four", "autor": "Rick Ferri, comunidade Bogleheads",
     "pesos": {"ACOES_BR": 48, "EXTERIOR": 24, "FII": 8, "IPCA_LONGO": 10, "CDI": 10},
     "ideia": "Quatro investimentos amplos com foco em crescimento: 80% em ações e imóveis e 20% em renda fixa."},
    {"id": "bolsa", "nome": "100% bolsa brasileira", "autor": "Ibovespa (BOVA11): a referência do outro extremo",
     "pesos": {"ACOES_BR": 100},
     "ideia": "Tudo em ações brasileiras, sem proteção nenhuma. Mostra quanto a bolsa rendeu e quanto chegou a cair no período."},
]
COMPONENTES = {"ACOES_BR": "Ibovespa (BOVA11)", "EXTERIOR": "S&P 500 em reais (IVVB11)", "IPCA_LONGO": "Tesouro IPCA+ longo (IMA-B 5+)",
               "CDI": "CDI", "OURO": "Ouro em reais", "DOLAR": "Dólar", "FII": "FIIs grandes (cesta de 5)",
               "SMALL": "Empresas menores (SMAL11)", "DIVID": "Boas pagadoras de dividendos (DIVO11)"}
CLASSE_COMP = {"ACOES_BR": "acao", "EXTERIOR": "exterior", "IPCA_LONGO": "renda_fixa", "CDI": "renda_fixa", "OURO": "cambio",
               "DOLAR": "cambio", "FII": "fii", "SMALL": "acao", "DIVID": "acao"}
NOME_CLASSE = {"acao": "ações", "fii": "FIIs", "exterior": "exterior", "cambio": "dólar e ouro", "renda_fixa": "renda fixa"}
_cache = {"t": 0, "R": None}
_lock = threading.Lock()


# ---------------------------------------------------------------- séries mensais (retorno de cada mês, em R$)

def _mensal(s):
    m = s.resample("ME").last().pct_change().clip(-0.6, 1.0)
    hoje = pd.Timestamp.today()
    return m[(m.index.year < hoje.year) | (m.index.month < hoje.month)]  # mês corrente ainda incompleto


def componentes():
    """Retornos mensais dos componentes dos planos (cache de 12h)."""
    if _cache["R"] is not None and time.time() - _cache["t"] < 12 * 3600:
        return _cache["R"]
    with _lock:
        s = sim.fechamentos_brl(["BOVA11", "IBOV", "IVVB11", "SP500", "IPCA_LONGO", "OURO", "DOLAR", "SMAL11", "DIVO11", *sim.FII_CESTA])
        R = {}
        if "BOVA11" in s:
            R["ACOES_BR"] = _mensal(s["BOVA11"]).combine_first(_mensal(s["IBOV"])) if "IBOV" in s else _mensal(s["BOVA11"])
            for k, c in (("SMALL", "SMAL11"), ("DIVID", "DIVO11")):  # antes de existirem, valem pelo Ibovespa
                R[k] = _mensal(s[c]).combine_first(R["ACOES_BR"]) if c in s and not sim.parado(s[c]) else R["ACOES_BR"]
        if "SP500" in s:
            R["EXTERIOR"] = _mensal(s["IVVB11"]).combine_first(_mensal(s["SP500"])) if "IVVB11" in s else _mensal(s["SP500"])
        for k, c in (("IPCA_LONGO", "IPCA_LONGO"), ("OURO", "OURO"), ("DOLAR", "DOLAR")):
            if c in s:
                R[k] = _mensal(s[c])
        fiis = [_mensal(s[c]) for c in sim.FII_CESTA if c in s]
        if fiis:
            R["FII"] = pd.concat(fiis, axis=1).mean(axis=1)
        idx = acertos.cdi_mensal()
        if idx is not None and len(idx):
            cdi = (idx.shift(-1) / idx - 1).dropna()
            cdi.index = cdi.index + pd.offsets.MonthEnd(0)
            R["CDI"] = cdi
        R = pd.DataFrame(R)
        R = R[R.index >= pd.Timestamp(INICIO + "-01")]
        if "CDI" in R:
            R["CDI"] = R["CDI"].fillna(R["CDI"].mean())
        R = R.dropna(how="any", subset=[c for c in ("ACOES_BR", "CDI") if c in R])
        _cache.update(t=time.time(), R=R)
        return R


def _ipca_mensal(indice):
    ip = investimentos.ipca_mensal()
    if ip is None or not len(ip):
        return None
    r = (ip / ip.shift(1) - 1).reindex(indice)
    return r if r.notna().mean() > 0.95 else None


# ---------------------------------------------------------------- teste com o passado

def rodar(pesos, R):
    """Retorno mensal da carteira (pesos por coluna de R), rebalanceada para os pesos-alvo todo mês de janeiro."""
    cols = [c for c in pesos if c in R and pesos[c] > 0]
    tot = sum(pesos[c] for c in cols)
    if not cols or tot <= 0:
        return None
    alvo = np.array([pesos[c] / tot for c in cols])
    M = R[cols].fillna(0.0).to_numpy()
    w, out = alvo.copy(), []
    for i, d in enumerate(R.index):
        if d.month == 1 and i:
            w = alvo.copy()
        r = float(w @ M[i])
        out.append(r)
        w = w * (1 + M[i]) / (1 + r)
    return pd.Series(out, index=R.index)


def metricas(r, R):
    if r is None or len(r) < 24:
        return None
    idx = np.concatenate([[1.0], (1 + r).cumprod().to_numpy()])
    anos = len(r) / 12
    dd = idx / np.maximum.accumulate(idx) - 1
    seq = maior = 0
    for x in dd[1:]:
        seq = seq + 1 if x < -1e-9 else 0
        maior = max(maior, seq)
    cdi = R["CDI"] if "CDI" in R else pd.Series(0.0, index=r.index)
    i_c = (1 + r).cumprod()
    i_cdi = (1 + cdi.reindex(r.index).fillna(0)).cumprod()
    r12, c12 = i_c / i_c.shift(12) - 1, i_cdi / i_cdi.shift(12) - 1
    ok = r12.notna()
    ip = _ipca_mensal(r.index)
    real = None
    if ip is not None:
        real = ((idx[-1] / float((1 + ip.fillna(0)).prod())) ** (1 / anos) - 1) * 100
    meio = len(r) // 2
    cagr = lambda x: round((float((1 + x).prod()) ** (12 / len(x)) - 1) * 100, 1)
    return {"metade1": {"ate": r.index[meio - 1].strftime("%m/%Y"), "ret_aa": cagr(r.iloc[:meio])},
            "metade2": {"desde": r.index[meio].strftime("%m/%Y"), "ret_aa": cagr(r.iloc[meio:])},
            "ret_aa": round((idx[-1] ** (1 / anos) - 1) * 100, 1), "real_aa": round(real, 1) if real is not None else None,
            "vol_aa": round(float(r.std() * 12 ** 0.5 * 100), 1), "maior_queda": round(float(dd.min() * 100), 1),
            "pior_12m": round(float(r12[ok].min() * 100), 1), "acima_cdi_12m": round(float((r12[ok] > c12[ok]).mean() * 100)),
            "meses_recuperar": int(maior), "final_10k": round(float(10000 * idx[-1]), 0)}


def planos_ref():
    """Os planos consagrados com os números do período testado (cache de 12h junto com as séries)."""
    R = componentes()
    out = []
    for p in PLANOS:
        m = metricas(rodar(p["pesos"], R), R)
        if m:
            classes = {}
            for k, w in p["pesos"].items():
                classes[CLASSE_COMP[k]] = classes.get(CLASSE_COMP[k], 0) + w
            out.append({**{k: p[k] for k in ("id", "nome", "autor", "ideia", "pesos")}, "classes": classes, **m})
    return {"planos": out, "desde": R.index[0].strftime("%m/%Y"), "ate": R.index[-1].strftime("%m/%Y"), "meses": len(R),
            "componentes": COMPONENTES}


def serie_ativo(a, spec, R, proprias):
    """Retornos mensais de um ativo da carteira: os dele quando existem (e a fonte não parou), senão os da classe."""
    if spec["tipo"] == "pos":
        return R["CDI"] * spec.get("fator", 1.0), 1.0
    proxy = {"acao": "ACOES_BR", "fii": "FII", "exterior": "EXTERIOR", "cambio": "DOLAR", "renda_fixa": "IPCA_LONGO"}.get(spec["classe"], "ACOES_BR")
    if a == "GOLD11":
        proxy = "OURO"
    if spec["tipo"] == "ipca":
        return R["IPCA_LONGO"], 1.0
    base = R[proxy] if proxy in R else R["ACOES_BR"]
    s = proprias.get(a)
    if s is None or sim.parado(s):
        return base, 0.0
    m = _mensal(s).reindex(R.index)
    return m.combine_first(base), float(m.notna().mean())


def testar_carteira(pesos, specs):
    """Teste com o passado da carteira recomendada, no mesmo período e do mesmo jeito que os planos de referência."""
    R = componentes()
    mercado = [a for a, s in specs.items() if s["tipo"] == "mercado"]
    proprias = sim.fechamentos_brl(mercado) if mercado else {}
    cols, cob = {}, 0.0
    tot = sum(w for w in pesos.values() if w > 0)
    for a, w in pesos.items():
        if w <= 0 or a not in specs:
            continue
        cols[a], c = serie_ativo(a, specs[a], R, proprias)
        cob += w / tot * c
    m = metricas(rodar(pesos, pd.DataFrame(cols)), R) if cols else None
    if m:
        m["cobertura"] = round(cob * 100)
    return m


# ---------------------------------------------------------------- auditoria da recomendação

def _br(v, d=1):
    return f"{v:.{d}f}".replace(".", ",")


def _chk(lista, ident, titulo, ok, detalhe, bloqueia=False):
    lista.append({"id": ident, "titulo": titulo, "ok": bool(ok), "bloqueia": bloqueia and not ok, "detalhe": detalhe})


def checar(pesos, alvo, modelo, perfil, liquidez, held, individual, elegivel, limite_crise, pior_crise, com_objetivo):
    """Checagens objetivas (as que bloqueiam): soma, faixas do perfil, prazo, concentração, liquidez e pior crise."""
    out = []
    soma = sum(pesos.values())
    _chk(out, "soma", "Os pesos somam 100%", abs(soma - 100) <= 0.6, f"Soma: {_br(soma)}%.", True)
    fora = []  # só a direção perigosa: menos renda fixa ou mais risco do que o perfil aceita (ser mais prudente é permitido)
    for c, v in alvo.items():
        if c == "renda_fixa" and v < modelo[c] - 10.6:
            fora.append(f"renda fixa {v:.0f}% (mínimo {modelo[c] - 10:.0f}%)")
        elif c != "renda_fixa" and v > modelo[c] + 10.6:
            fora.append(f"{NOME_CLASSE.get(c, c)} {v:.0f}% (máximo {modelo[c] + 10:.0f}%)")
    _chk(out, "perfil", f"Risco dentro do perfil {perfil}", not fora,
         "Acima do que o perfil aceita: " + "; ".join(fora) if fora else
         "Nenhuma classe de risco acima do modelo do perfil + 10 p.p., e renda fixa no mínimo do modelo - 10 p.p.", True)
    if liquidez == "ALTA":
        rf = alvo.get("renda_fixa", 0)
        _chk(out, "prazo", "Dinheiro de curto prazo protegido", rf >= 85,
             f"O objetivo é para até 2 anos: {rf:.0f}% em renda fixa (mínimo 85%).", True)
    grandes = [a for a, w in pesos.items() if individual(a) and w > 10.5 and a not in held]
    _chk(out, "concentracao", "Nenhum papel novo acima de 10%", not grandes,
         ("Acima de 10%: " + ", ".join(grandes)) if grandes else "Ações e FIIs individuais novos com no máximo 10% cada.", True)
    ruins = [a for a, w in pesos.items() if w > 0 and a not in held and not elegivel(a)]
    _chk(out, "qualidade", "Ativos novos com liquidez, histórico e dados confiáveis", not ruins,
         ("Não passaram: " + ", ".join(ruins)) if ruins else "Todos os ativos novos negociam o bastante, têm 3 anos de bolsa e cotação atualizada.", True)
    if pior_crise is not None:
        nome, v = pior_crise
        _chk(out, "crise", "Aguenta as crises reais dentro do seu perfil", v >= limite_crise - 2,
             f"Na pior crise testada ({nome}), teria variado {v:+.0f}%; o perfil {perfil} aceita até {limite_crise:.0f}%.", True)
    return out


def para_perfil(ref, limite):
    """Marca os planos que cabem no perfil: a maior queda do plano no período não passa do que o perfil aceita."""
    planos = [{**p, "cabe": p["maior_queda"] >= limite - 0.5} for p in ref["planos"]]
    return {**ref, "planos": planos, "limite": limite}


def comparar(carteira, ref_p, perfil):
    """Compara a recomendada com TODOS os planos que cabem no perfil (não com um só):
    - algum deles foi, ao mesmo tempo, melhor e menos arriscado? (lista todos);
    - em que posição ela ficou entre eles;
    - o resultado se repetiu nas duas metades do período, ou dependeu de uma fase boa?"""
    out = []
    if not carteira or not ref_p:
        return out, []
    compat = [p for p in ref_p["planos"] if p["cabe"] and p["id"] != "cdi"]
    if not compat:
        return out, []
    dominam = [p for p in compat if p["ret_aa"] >= carteira["ret_aa"] + 0.5 and p["maior_queda"] >= carteira["maior_queda"] - 0.5
               and p["vol_aa"] <= carteira["vol_aa"] + 0.5]
    dominam.sort(key=lambda p: -p["ret_aa"])
    _chk(out, "dominada", "Nenhum plano consagrado foi melhor e menos arriscado", not dominam,
         ("No mesmo período, " + "; ".join(f"o {p['nome']} rendeu {_br(p['ret_aa'])}% ao ano com queda máxima de {p['maior_queda']:.0f}%"
                                           for p in dominam)
          + f", contra {_br(carteira['ret_aa'])}% e {carteira['maior_queda']:.0f}% da recomendada. Vale considerar uma carteira "
          + ("mais parecida com eles." if len(dominam) > 1 else "mais parecida com ele.")) if dominam else
         f"Comparada com os {len(compat)} planos consagrados que cabem no perfil {perfil}, nenhum teve, ao mesmo tempo, mais "
         "retorno e menos risco que a recomendada no período.")
    acima = sum(1 for p in compat if carteira["ret_aa"] > p["ret_aa"])
    rets = sorted(p["ret_aa"] for p in compat)
    _chk(out, "ranking", "Retorno entre os planos que cabem no seu perfil", acima * 2 >= len(compat),
         f"Rendeu mais que {acima} dos {len(compat)} planos que cabem no perfil {perfil} (eles renderam de {_br(rets[0])}% a "
         f"{_br(rets[-1])}% ao ano; a recomendada, {_br(carteira['ret_aa'])}%)."
         + ("" if acima * 2 >= len(compat) else " Ou seja, ficou na metade de baixo: a segurança extra custou retorno no período."))
    cdi = next((p for p in ref_p["planos"] if p["id"] == "cdi"), None)
    if cdi and carteira.get("metade1"):
        m1, m2 = carteira["metade1"], carteira["metade2"]
        ok1, ok2 = m1["ret_aa"] >= cdi["metade1"]["ret_aa"], m2["ret_aa"] >= cdi["metade2"]["ret_aa"]
        _chk(out, "periodos", "Bateu o CDI nas duas metades do período", ok1 and ok2,
             f"Até {m1['ate']}: {_br(m1['ret_aa'])}% ao ano (CDI {_br(cdi['metade1']['ret_aa'])}%); desde {m2['desde']}: "
             f"{_br(m2['ret_aa'])}% (CDI {_br(cdi['metade2']['ret_aa'])}%)."
             + ("" if ok1 and ok2 else " O resultado dependeu de uma fase boa: em parte do tempo, deixar no CDI teria sido melhor."))
    return out, [p["id"] for p in dominam]


def quando(dias, de=False):
    if dias == 0:
        return "de hoje" if de else "hoje"
    return (f"de {dias} {'dia' if dias == 1 else 'dias'} atrás" if de else f"em {dias} {'dia' if dias == 1 else 'dias'}")


def consistencia(alvo, anterior, mudou_entrada, dias):
    """A recomendação mudou muito em pouco tempo sem que nada importante tenha mudado?"""
    if not anterior or dias is None or dias > 30 or mudou_entrada:
        return []
    difs = {c: alvo.get(c, 0) - anterior.get(c, 0) for c in set(alvo) | set(anterior)}
    grande = {c: d for c, d in difs.items() if abs(d) > 10}
    out = []
    _chk(out, "consistencia", "Coerente com a recomendação anterior", not grande,
         ("Mudou mais de 10 p.p. em " + ", ".join(f"{NOME_CLASSE.get(c, c)} ({d:+.0f} p.p.)" for c, d in grande.items())
          + f" {quando(dias)}, sem mudança no seu perfil, objetivo, carteira ou orçamento.") if grande
         else f"Sem mudanças bruscas em relação à recomendação {quando(dias, True)}.")
    return out
