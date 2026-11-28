"""Renda fixa: comparador líquido (depois do IR e da custódia) e vencimentos dos títulos que a pessoa tem.

Regras usadas: IR pela tabela regressiva sobre o rendimento (até 180 dias 22,5%; até 360, 20%; até 720, 17,5%; acima, 15%);
LCI e LCA isentas de IR; custódia da B3 no Tesouro Direto de 0,20% ao ano sobre o valor (o Tesouro Selic é isento até
R$ 10 mil); CDB, LCI e LCA sem custódia. Conta em dias úteis (252 por ano). IOF (só em resgates com menos de 30 dias)
não entra. É uma comparação com as taxas informadas, não uma oferta: as taxas reais dependem do banco e do dia.
"""
from datetime import date

TIPOS = {"cdb": "CDB (% do CDI)", "lci": "LCI/LCA (% do CDI, isenta)", "selic": "Tesouro Selic", "pre": "Prefixado (% ao ano)",
         "ipca": "Tesouro IPCA+ (juro real % ao ano)"}


def aliquota_ir(dias):
    return 0.225 if dias <= 180 else 0.20 if dias <= 360 else 0.175 if dias <= 720 else 0.15


def simular(opcao, valor, dias, cdi, ipca, selic=None):
    """opcao: {tipo, taxa}. Devolve bruto, IR, custódia, líquido e o rendimento líquido ao ano."""
    du = dias * 252 / 365
    anos = du / 252
    tipo, taxa = opcao["tipo"], float(opcao.get("taxa") or 0)
    if tipo in ("cdb", "lci"):
        aa = cdi * taxa / 100
    elif tipo == "selic":
        aa = (selic if selic is not None else cdi + 0.1)
    elif tipo == "pre":
        aa = taxa
    elif tipo == "ipca":
        aa = ((1 + ipca / 100) * (1 + taxa / 100) - 1) * 100
    else:
        raise ValueError("Tipo de renda fixa inválido.")
    bruto = valor * ((1 + aa / 100) ** anos)
    ganho = bruto - valor
    ir = 0.0 if tipo == "lci" else ganho * aliquota_ir(dias)
    custodia = 0.0
    if tipo in ("selic", "pre", "ipca"):
        base = valor if tipo != "selic" else max(valor - 10000, 0)
        custodia = base * 0.002 * anos
    liquido = bruto - ir - custodia
    liq_aa = ((liquido / valor) ** (1 / anos) - 1) * 100 if anos > 0 else 0.0
    return {"tipo": tipo, "nome": TIPOS[tipo], "taxa": taxa, "bruto": round(bruto, 2), "ir": round(ir, 2),
            "custodia": round(custodia, 2), "liquido": round(liquido, 2), "liquido_aa": round(liq_aa, 2),
            "aliquota_ir": 0 if tipo == "lci" else aliquota_ir(dias) * 100}


def comparar(opcoes, valor, dias, cdi, ipca, selic=None):
    if not (0 < valor <= 1e9) or not (1 <= dias <= 365 * 40):
        raise ValueError("Informe um valor e um prazo válidos.")
    res = [simular(o, valor, dias, cdi, ipca, selic) for o in opcoes[:8]]
    melhor = max(res, key=lambda r: r["liquido"])
    for r in res:
        r["melhor"] = r is melhor
        # equivale a um CDB de quantos % do CDI (mesmo prazo, mesmo líquido)?
        lo, hi = 0.0, 400.0
        for _ in range(60):
            m = (lo + hi) / 2
            if simular({"tipo": "cdb", "taxa": m}, valor, dias, cdi, ipca, selic)["liquido"] < r["liquido"]:
                lo = m
            else:
                hi = m
        r["equivale_cdb_pct_cdi"] = round((lo + hi) / 2, 1)
    return {"valor": valor, "dias": dias, "cdi": cdi, "ipca": ipca, "opcoes": res, "melhor": melhor["tipo"]}


def vencimentos(pos, hoje=None):
    """Títulos com data de vencimento informada, do mais próximo ao mais distante."""
    hoje = hoje or date.today()
    out = []
    for t, p in pos.items():
        v = (p or {}).get("venc")
        if not v:
            continue
        try:
            d = date.fromisoformat(str(v)[:10])
        except ValueError:
            continue
        dias = (d - hoje).days
        out.append({"ticker": t, "vencimento": d.isoformat(), "dias": dias, "saldo": (p or {}).get("saldo", 0),
                    "situacao": "vencido" if dias < 0 else "vence em até 30 dias" if dias <= 30 else "a vencer",
                    "aliquota_ir_hoje": None})
    return sorted(out, key=lambda x: x["vencimento"])
