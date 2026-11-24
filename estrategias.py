"""Estratégias que a pessoa pode escolher seguir.

- "app": a recomendada pelo app. Parte do modelo do perfil (server.PERFIS, revisto com validação fora da amostra),
  escolhe os ativos de cada classe pelas regras (e pela IA no Premium) e passa pela auditoria completa.
- "modelo_fixo": a mesma divisão do modelo do perfil, só com ETFs amplos e títulos (a linha "Modelo fixo" do simulador).
- os planos consagrados de referencias.PLANOS (Permanente, All Weather, 60/40, Três fundos...), seguidos com os ativos que
  o simulador usa para testá-los (simulador.COMP_ATIVO).

Todas são testadas do mesmo jeito (referencias.rodar: mesmo período, rebalanceamento anual, sem custos), e só podem ser
escolhidas as que cabem no perfil, pelos mesmos critérios da auditoria: a maior queda no período não passa do que o
perfil aceita, e a pior crise real testada (2008, 2015, 2020...) fica dentro do limite do perfil.
"""
import referencias
import regras
from simulador import COMP_ATIVO, fixo_de

PADRAO = "app"
NOME_PADRAO = "Recomendada pelo app"
# cada ETF ou título do núcleo vira o índice que ele segue, no teste com o passado (LCI rende 90% do CDI, sem imposto)
COMP_DE_ATIVO = {"TESOURO_SELIC": "CDI", "CDB_CDI": "CDI", "LCI_LCA": "LCI", "TESOURO_IPCA": "IPCA_LONGO", "BOVA11": "ACOES_BR",
                 "DIVO11": "DIVID", "SMAL11": "SMALL", "IVVB11": "EXTERIOR", "DOLAR": "DOLAR", "GOLD11": "OURO",
                 "KNCR11": "FII", "HGLG11": "FII", "KNRI11": "FII", "XPML11": "FII", "MXRF11": "FII"}
NOME_CL = {"renda_fixa": "renda fixa", "acao": "ações", "fii": "FIIs", "exterior": "exterior", "cambio": "dólar e ouro"}
CAMPOS = ("ret_aa", "real_aa", "vol_aa", "maior_queda", "pior_12m", "acima_cdi_12m", "meses_recuperar", "metade1", "metade2")


def _comp_de_ativos(ativos):
    out = {}
    for a, w in ativos.items():
        k = COMP_DE_ATIVO.get(a, "ACOES_BR")
        out[k] = out.get(k, 0) + w
    return out


def _br(v, d=0):
    return f"{v:.{d}f}".replace(".", ",")


def ativos_plano(pesos):
    """Ativos (e o motivo de cada um) para seguir um plano: cada componente vira o ativo que a pessoa compra."""
    at, mot = {}, {}
    for k, w in pesos.items():
        for a, f in COMP_ATIVO[k].items():
            at[a] = at.get(a, 0) + w * f
            mot[a] = (f"{referencias.COMPONENTES[k]}: {_br(w)}% do plano" +
                      (f", dividido igualmente entre {len(COMP_ATIVO[k])} fundos" if len(COMP_ATIVO[k]) > 1 else "") + ".")
    return {a: round(w, 2) for a, w in at.items() if w > 0}, mot


def ativos_modelo(modelo, perfil, nucleo=None):
    """O modelo do perfil com os ETFs e títulos do núcleo do perfil (e o motivo de cada um)."""
    at = {a: round(w, 2) for a, w in fixo_de(modelo, nucleo).items() if w > 0}
    mot = {}
    for a in at:
        c = next(c for c, v in modelo.items() if v and a in ({**regras.NUCLEO_PADRAO, **(nucleo or {})}[c]))
        mot[a] = f"Parte do modelo do perfil {perfil}: {_br(modelo[c], 1).replace(',0', '')}% em {NOME_CL[c]}, só com ETFs e títulos."
    return at, mot


def classes(pesos_comp):
    out = {}
    for k, w in pesos_comp.items():
        c = referencias.CLASSE_COMP[k]
        out[c] = out.get(c, 0) + w
    return {c: round(out.get(c, 0), 1) for c in NOME_CL}


def motivo_fora(perfil, limite, maior_queda, pior_crise, queda_dia, rf=None, rf_min=None):
    """Por que uma estratégia não cabe no perfil (None se cabe): renda fixa mínima e as três medidas de queda."""
    if rf_min is not None and rf is not None and rf < rf_min - 0.5:
        return f"Tem {_br(rf)}% em renda fixa; o perfil {perfil} pede pelo menos {rf_min}%."
    if queda_dia is not None and queda_dia < limite:
        return f"Na corretora simulada, chegou a cair {_br(-queda_dia, 1)}% (dia a dia, desde 2013); o perfil {perfil} aceita até {_br(-limite)}%."
    if maior_queda is not None and maior_queda < limite:
        return f"Chegou a cair {_br(-maior_queda, 1)}% no teste mês a mês; o perfil {perfil} aceita até {_br(-limite)}%."
    if pior_crise and pior_crise[1] < limite:
        return (f"Na pior crise testada ({pior_crise[0]}), teria caído {_br(-pior_crise[1], 1)}%; o perfil {perfil} "
                f"aceita até {_br(-limite)}%.")
    return None


def lista(perfil, modelo, limite, crises, ref=None, nucleo=None, satelites=True, quedas_dia=None, rf_min=None, crises_sem_cambio=None):
    """Todas as estratégias para o perfil, com o teste com o passado e se cabem nele (pelas três medidas de queda do perfil:
    teste mês a mês, pior crise real e, quando já calculada, a corretora simulada dia a dia).
    crises(carteiras) -> {id: (nome da crise, variação %)}: a pior crise real de cada carteira (por ativo).
    satelites=False: a recomendada já é só com ETFs e títulos, então o "modelo só com ETFs" (igual a ela) não aparece."""
    ref = ref or referencias.planos_ref()
    quedas_dia = quedas_dia or {}
    R = referencias.componentes()
    R = R.assign(LCI=R["CDI"] * 0.9)
    at_m, mot_m = ativos_modelo(modelo, perfil, nucleo)
    mm = referencias.metricas(referencias.rodar(_comp_de_ativos(at_m), R), R) or {}
    est = [{"id": PADRAO, "nome": NOME_PADRAO, "tipo": "app", "autor": f"modelo do perfil {perfil}, reformulado em 24/11/2026",
            "ideia": ("O modelo do seu perfil, escolhido com testes com dados reais (639 carteiras e depois um refinamento até "
                      "nenhuma vizinha ser claramente melhor) por ter rendido mais sem passar do limite de queda do perfil. " +
                      ("Além dos ETFs, o app escolhe até 2 ações de empresas de qualidade (no máximo 10% cada): nos testes, isso "
                       "melhorou o resultado neste perfil. " if satelites else
                       "Só ETFs e títulos: nos testes, escolher ações individuais não melhorou o resultado neste perfil. ") +
                      "Toda recomendação passa pela auditoria."),
            "classes": dict(modelo), "ativos": at_m, "motivos": mot_m, "satelites": satelites, **{k: mm.get(k) for k in CAMPOS}}]
    if satelites:
        est.append({"id": "modelo_fixo", "nome": "Modelo do perfil, só ETFs e títulos", "tipo": "fixo", "autor": f"modelo do perfil {perfil}",
                    "ideia": "A mesma divisão da recomendada, mas sem escolher ações: só ETFs amplos e títulos. É a mais simples de "
                             "seguir e de manter.", "classes": dict(modelo), "ativos": at_m, "motivos": mot_m, **{k: mm.get(k) for k in CAMPOS}})
    for p in ref["planos"]:
        at, mot = ativos_plano(p["pesos"])
        est.append({**{k: p[k] for k in ("id", "nome", "autor", "ideia", "pesos")}, "tipo": "plano", "classes": classes(p["pesos"]),
                    "ativos": at, "motivos": mot, **{k: p.get(k) for k in CAMPOS}})
    cr = crises({e["id"]: e["ativos"] for e in est if e["id"] != "modelo_fixo"})
    cr["modelo_fixo"] = cr.get(PADRAO)
    sc = crises_sem_cambio({e["id"]: e["ativos"] for e in est if e["id"] != "modelo_fixo"}) if crises_sem_cambio else {}
    sc["modelo_fixo"] = sc.get(PADRAO)
    for e in est:
        e["pior_crise"] = list(cr[e["id"]]) if cr.get(e["id"]) else None
        e["queda_dia"] = quedas_dia.get(e["id"])
        e["crise_sem_cambio"] = list(sc[e["id"]]) if sc.get(e["id"]) else None
        motivo = motivo_fora(perfil, limite, e["maior_queda"], e["pior_crise"], e["queda_dia"], e["classes"].get("renda_fixa"), rf_min)
        e["cabe"] = e["tipo"] != "plano" or motivo is None
        e["motivo_nao_cabe"] = motivo if e["tipo"] == "plano" else None
    return {"perfil": perfil, "limite": limite, "rf_min": rf_min, "padrao": PADRAO, "estrategias": est,
            "periodo": {"desde": ref["desde"], "ate": ref["ate"]}, "componentes": ref["componentes"]}


def resumo_texto(e):
    return ", ".join(f"{_br(v)}% em {NOME_CL[c]}" for c, v in sorted(e["classes"].items(), key=lambda kv: -kv[1]) if v)


# ---------------------------------------------------------------- garantia de melhor decisão (ferramentas/melhor_estrategia.py)

MARGEM_METADE, TOLERA_QUEDA = 0.2, 1.0


def linhas_testes(sim_perfil, cor, perfil, ids):
    """O resultado de cada estratégia nos dois testes com dados reais: {id: (linha do simulador, relatório da corretora)}."""
    sl = {("modelo_fixo" if l["id"] == "fixo" else l["id"]): l for l in (sim_perfil or {}).get("linhas", [])}
    cp = ((cor or {}).get("perfis") or {}).get(perfil) or {}
    out = {}
    for i in ids:
        c = cp.get("app") if i == PADRAO else cp.get("fixo") if i == "modelo_fixo" else ((cor or {}).get("planos") or {}).get(i)
        out[i] = (sl.get(i), c)
    return out


def dominantes(rec, linhas):
    """As estratégias que, nos DOIS testes, renderam mais nas duas metades do período (por MARGEM_METADE ponto ou mais),
    com maior queda no máximo TOLERA_QUEDA ponto pior e patrimônio final maior que a recomendada. A melhor primeiro."""
    r = linhas.get(rec)
    if not r or not all(r):
        return []
    out = []
    for i, c in linhas.items():
        if i == rec or not all(c):
            continue
        ok = all(x.get("metade1_aa") is not None and y.get("metade1_aa") is not None
                 and x["metade1_aa"] >= y["metade1_aa"] + MARGEM_METADE and x["metade2_aa"] >= y["metade2_aa"] + MARGEM_METADE
                 and x["maior_queda"] >= y["maior_queda"] - TOLERA_QUEDA and x["final"] > y["final"]
                 for x, y in zip(c, r))
        if ok:
            out.append({"id": i, "simulador": {k: c[0][k] for k in ("final", "metade1_aa", "metade2_aa", "maior_queda")},
                        "corretora": {k: c[1][k] for k in ("final", "metade1_aa", "metade2_aa", "maior_queda")},
                        "antes": {"simulador": {k: r[0][k] for k in ("final", "metade1_aa", "metade2_aa", "maior_queda")},
                                  "corretora": {k: r[1][k] for k in ("final", "metade1_aa", "metade2_aa", "maior_queda")}}})
    return sorted(out, key=lambda x: -x["corretora"]["final"])
