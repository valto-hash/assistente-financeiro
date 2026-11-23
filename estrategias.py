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
from simulador import COMP_ATIVO, NUCLEO

PADRAO = "app"
NOME_PADRAO = "Recomendada pelo app"
# como o modelo do perfil vira componentes no teste com o passado (a mesma divisão de NUCLEO, por índice)
COMP_MODELO = {"renda_fixa": {"CDI": .45, "IPCA_LONGO": .55}, "acao": {"ACOES_BR": .6, "DIVID": .4}, "fii": {"FII": 1.0},
               "exterior": {"EXTERIOR": 1.0}, "cambio": {"DOLAR": .5, "OURO": .5}}
NOME_CL = {"renda_fixa": "renda fixa", "acao": "ações", "fii": "FIIs", "exterior": "exterior", "cambio": "dólar e ouro"}
CAMPOS = ("ret_aa", "real_aa", "vol_aa", "maior_queda", "pior_12m", "acima_cdi_12m", "meses_recuperar", "metade1", "metade2")


def _comp_modelo(modelo):
    out = {}
    for c, v in modelo.items():
        for k, w in COMP_MODELO[c].items():
            if v:
                out[k] = out.get(k, 0) + v * w
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


def ativos_modelo(modelo, perfil):
    at, mot = {}, {}
    for c, ws in NUCLEO.items():
        for a, w in ws.items():
            if modelo.get(c):
                at[a] = round(modelo[c] * w, 2)
                mot[a] = f"Parte do modelo do perfil {perfil}: {_br(modelo[c])}% em {NOME_CL[c]}, só com ETFs e títulos."
    return at, mot


def classes(pesos_comp):
    out = {}
    for k, w in pesos_comp.items():
        c = referencias.CLASSE_COMP[k]
        out[c] = out.get(c, 0) + w
    return {c: round(out.get(c, 0), 1) for c in NOME_CL}


def lista(perfil, modelo, limite, crises, ref=None):
    """Todas as estratégias para o perfil, com o teste com o passado e se cabem nele.
    crises(carteiras) -> {id: (nome da crise, variação %)}: a pior crise real de cada carteira (por ativo)."""
    ref = ref or referencias.planos_ref()
    R = referencias.componentes()
    mm = referencias.metricas(referencias.rodar(_comp_modelo(modelo), R), R) or {}
    at_m, mot_m = ativos_modelo(modelo, perfil)
    est = [{"id": PADRAO, "nome": NOME_PADRAO, "tipo": "app", "autor": f"modelo do perfil {perfil}, revisto em nov/2026",
            "ideia": "Parte do modelo do seu perfil (escolhido entre vários candidatos com testes no passado) e escolhe os ativos "
                     "de cada classe pelas regras, com conferência de liquidez, histórico e risco em toda recomendação. Os números são "
                     "do modelo do perfil; quanto a escolha de ativos acrescentou aparece no Simulador do passado.",
            "classes": dict(modelo), "ativos": at_m, **{k: mm.get(k) for k in CAMPOS}},
           {"id": "modelo_fixo", "nome": "Modelo do perfil, só ETFs e títulos", "tipo": "fixo", "autor": f"modelo do perfil {perfil}",
            "ideia": "A mesma divisão da recomendada, mas sem escolher ações nem fundos: só ETFs amplos e títulos. É a mais simples "
                     "de seguir e de manter.",
            "classes": dict(modelo), "ativos": at_m, "motivos": mot_m, **{k: mm.get(k) for k in CAMPOS}}]
    for p in ref["planos"]:
        at, mot = ativos_plano(p["pesos"])
        est.append({**{k: p[k] for k in ("id", "nome", "autor", "ideia", "pesos")}, "tipo": "plano", "classes": classes(p["pesos"]),
                    "ativos": at, "motivos": mot, **{k: p.get(k) for k in CAMPOS}})
    cr = crises({e["id"]: e["ativos"] for e in est if e["id"] != "modelo_fixo"})
    cr["modelo_fixo"] = cr.get(PADRAO)
    for e in est:
        e["pior_crise"] = list(cr[e["id"]]) if cr.get(e["id"]) else None
        motivo = None
        if e["maior_queda"] is not None and e["maior_queda"] < limite - 0.5:
            motivo = (f"Chegou a cair {_br(-e['maior_queda'])}% no período; o perfil {perfil} aceita até {_br(-limite)}%.")
        elif e["pior_crise"] and e["pior_crise"][1] < limite - 2:
            motivo = (f"Na pior crise testada ({e['pior_crise'][0]}), teria caído {_br(-e['pior_crise'][1])}%; o perfil {perfil} "
                      f"aceita até {_br(-limite)}%.")
        e["cabe"] = e["tipo"] != "plano" or motivo is None
        e["motivo_nao_cabe"] = motivo if e["tipo"] == "plano" else None
    return {"perfil": perfil, "limite": limite, "padrao": PADRAO, "estrategias": est,
            "periodo": {"desde": ref["desde"], "ate": ref["ate"]}, "componentes": ref["componentes"]}


def resumo_texto(e):
    return ", ".join(f"{_br(v)}% em {NOME_CL[c]}" for c, v in sorted(e["classes"].items(), key=lambda kv: -kv[1]) if v)
