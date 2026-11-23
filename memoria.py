"""Memória de cada investidor para a IA: as recomendações anteriores e o que a pessoa fez desde então.

Cada análise da IA é um pedido novo: ela não guarda conversa nenhuma, então não "esquece no meio". O risco é outro:
sem saber o que recomendou da última vez, ela pode mudar de ideia sem motivo. Por isso o app guarda:
- as últimas recomendações (data, quem fez, alocação por classe, principais ativos e o resultado da auditoria);
- as ações registradas pela pessoa (compras, vendas, teste de perfil);
- as "entradas" de cada recomendação (perfil, objetivo, ativos que tinha, reserva), para saber o que mudou.
A IA recebe um resumo curto disso e precisa explicar qualquer mudança grande; a auditoria confere.
"""
import time
from datetime import date

import armazem

MAX_REC, MAX_EV = 12, 40


def ler(uid):
    d = armazem.ler("memoria", uid)
    return {"recomendacoes": [], "eventos": [], **(d["dados"] if d else {})}


def _gravar(uid, d):
    armazem.gravar("memoria", uid, d)


def entrada(perfil, objetivo, ativos, orc, estrategia=None):
    """O que levou à recomendação. Se nada disso mudou, a recomendação também não deveria mudar muito.
    estrategia: o nome da estratégia escolhida pela pessoa (None = a recomendada pelo app)."""
    return {"perfil": perfil, "objetivo": " ".join((objetivo or "").split())[:300], "ativos": sorted(ativos),
            "reserva_meses": orc.get("reserva_meses"), "contas_mensais": round(orc.get("contas_mensais") or 0),
            **({"estrategia": estrategia} if estrategia else {})}


def evento(uid, tipo, texto):
    d = ler(uid)
    d["eventos"] = (d["eventos"] + [{"data": date.today().isoformat(), "tipo": tipo, "texto": texto[:200]}])[-MAX_EV:]
    _gravar(uid, d)


def registrar(uid, res, ent):
    """Guarda a recomendação, só quando ela muda (a mesma no mesmo dia não se repete)."""
    d = ler(uid)
    rec = {"data": date.today().isoformat(), "quando": time.time(), "fonte": res.get("fonte"), "alvo": res.get("alvo") or {},
           "pesos": {s["ticker"]: s["peso"] for s in (res.get("sugerida") or [])[:12]}, "entrada": ent,
           "auditoria_ok": (res.get("auditoria") or {}).get("aprovada")}
    ult = d["recomendacoes"][-1] if d["recomendacoes"] else None
    if ult and ult.get("entrada") == ent and ult["data"] == rec["data"] and \
            max([abs(ult["alvo"].get(c, 0) - v) for c, v in rec["alvo"].items()] or [0]) < 1:
        return False
    d["recomendacoes"] = (d["recomendacoes"] + [rec])[-MAX_REC:]
    _gravar(uid, d)
    return True


def _mudancas(ant, atual):
    out = []
    if ant.get("perfil") != atual.get("perfil"):
        out.append(f"perfil mudou de {ant.get('perfil')} para {atual.get('perfil')}")
    if ant.get("estrategia") != atual.get("estrategia"):
        out.append(f"a estratégia escolhida mudou de {ant.get('estrategia') or 'Recomendada pelo app'} para "
                   f"{atual.get('estrategia') or 'Recomendada pelo app'}")
    if ant.get("objetivo") != atual.get("objetivo"):
        out.append("o objetivo foi reescrito" if atual.get("objetivo") else "o objetivo foi apagado")
    novos, saiu = sorted(set(atual["ativos"]) - set(ant.get("ativos", []))), sorted(set(ant.get("ativos", [])) - set(atual["ativos"]))
    if novos:
        out.append("passou a ter " + ", ".join(novos))
    if saiu:
        out.append("deixou de ter " + ", ".join(saiu))
    if ant.get("reserva_meses") != atual.get("reserva_meses") or abs((ant.get("contas_mensais") or 0) - (atual.get("contas_mensais") or 0)) > 50:
        out.append("o orçamento (contas do mês ou reserva) mudou")
    return out


def contexto(uid, ent):
    """Resumo para a IA e dados para a checagem de consistência. Devolve (contexto_ia, consistencia) ou (None, None)."""
    d = ler(uid)
    ult = d["recomendacoes"][-1] if d["recomendacoes"] else None
    if not ult and not d["eventos"]:
        return None, None
    ctx = {"acoes_registradas_pelo_investidor": [f"{e['data']}: {e['texto']}" for e in d["eventos"][-10:]],
           "recomendacoes_anteriores": len(d["recomendacoes"])}
    cons = None
    if ult:
        dias = (date.today() - date.fromisoformat(ult["data"])).days
        mud = _mudancas(ult.get("entrada") or {}, ent)
        ctx["ultima_recomendacao"] = {"dias_atras": dias, "feita_por": "IA" if ult.get("fonte") == "ia" else "regras",
                                      "alocacao_por_classe": ult["alvo"], "principais_ativos": ult["pesos"]}
        ctx["o_que_mudou_desde_entao"] = mud or ["nada no perfil, no objetivo, nos ativos que a pessoa tem nem no orçamento"]
        cons = {"anterior": ult["alvo"], "dias": dias, "mudou_entrada": bool(mud), "mudancas": mud}
    return ctx, cons


def diferenca_posicoes(ant, nova):
    """Compras e vendas registradas entre duas versões da carteira (para a memória)."""
    out = []
    for t in sorted(set(ant) | set(nova)):
        a, n = ant.get(t) or {}, nova.get(t) or {}
        qa, qn = a.get("qtd") or 0, n.get("qtd") or 0
        sa, sn = a.get("saldo") or 0, n.get("saldo") or 0
        if abs(qn - qa) > 1e-9:
            if qn > qa:
                out.append(f"comprou {qn - qa:g} de {t} (agora {qn:g})")
            else:
                out.append(f"vendeu {qa - qn:g} de {t}" + (" (zerou a posição)" if qn <= 0 else f" (agora {qn:g})"))
        elif abs(sn - sa) >= 1:
            out.append(f"{'aplicou' if sn > sa else 'resgatou'} R$ {abs(sn - sa):,.0f} em {t}".replace(",", "."))
    return out[:8]
