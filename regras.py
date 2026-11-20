"""Motor de regras: funciona sem IA e também explica as decisões (com fatos calculados) quando a IA está ativa.

Sem chave da Anthropic, o app usa estas regras para:
- analisar cada ativo (tendência, médias móveis, RSI, momento, volatilidade);
- ler o momento do mercado (juro real e tendência dos índices de referência);
- entender o objetivo escrito pelo investidor (prazo, valor, aporte mensal e tipo de objetivo);
- definir a alocação, escolher os ativos de cada classe e decidir o que fazer com o que ele já tem.

Em qualquer modo, `fatos_*` e `ir_venda` produzem os números que justificam cada decisão.
São estimativas educacionais, não recomendação profissional.
"""
import re
from datetime import date

CLASSES = ["renda_fixa", "acao", "fii", "exterior", "cambio"]
NOME = {"renda_fixa": "Renda fixa", "acao": "Ações Brasil", "fii": "Fundos imobiliários", "exterior": "Exterior", "cambio": "Dólar e ouro"}
NOME_MIN = {"renda_fixa": "renda fixa", "acao": "ações brasileiras", "fii": "fundos imobiliários", "exterior": "exterior", "cambio": "dólar e ouro"}


def minuscula_inicial(t):  # "Galpões..." -> "galpões...", mas mantém siglas como "FII" e "ETF"
    return t[0].lower() + t[1:] if len(t) > 1 and not t[1].isupper() else t


# ---------------------------------------------------------------- formatação pt-BR

def br(v, d=2):
    return f"{v:,.{d}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def brl(v, d=2):
    return ("-" if v < 0 else "") + "R$ " + br(abs(v), d)


def pct(v, d=1, sinal=False):
    if v is None: return "—"
    return ("+" if sinal and v > 0 else "") + br(v, d) + "%"


def fato(rotulo, valor, ref=""):
    return {"rotulo": rotulo, "valor": valor, "ref": ref}


# ---------------------------------------------------------------- análise técnica de um ativo

def tendencia_txt(m):
    p, s200 = m.get("preco"), m.get("sma200")
    if not p or not s200: return None
    d = (p / s200 - 1) * 100
    return f"{'alta' if d > 2 else 'baixa' if d < -2 else 'lateral'}: preço {pct(abs(d))} {'acima' if d >= 0 else 'abaixo'} da média de 200 dias"


def analise_ativo(m):
    """Decisão COMPRAR/VENDER/MANTER a partir de indicadores, com alvo, stop, resumo e riscos."""
    p, s50, s200, rsi = m["preco"], m.get("sma50"), m.get("sma200"), m.get("rsi14")
    vol = m.get("volatilidade_anual") or 25.0
    pontos, sinais = 0.0, []
    if s200:
        acima = p > s200
        pontos += 1 if acima else -1
        sinais.append(f"preço {pct(abs(p / s200 * 100 - 100))} {'acima' if acima else 'abaixo'} da média de 200 dias")
        if s50:
            pontos += 1 if s50 > s200 else -1
            sinais.append(f"média de 50 dias {'acima' if s50 > s200 else 'abaixo'} da de 200 (tendência de {'alta' if s50 > s200 else 'baixa'})")
    r3 = m.get("ret_3m")
    if r3 is not None:
        pontos += 0.5 if r3 > 0 else -0.5
        sinais.append(f"{pct(r3, sinal=True)} em 3 meses")
    if rsi is not None:
        sinais.append(f"RSI {br(rsi, 0)} ({'sobrecomprado: subiu rápido demais' if rsi > 70 else 'sobrevendido: caiu rápido demais' if rsi < 30 else 'neutro'})")
    if pontos >= 2 and (rsi is None or rsi < 70):
        dec = "COMPRAR"
    elif pontos <= -2 and (rsi is None or rsi > 30):
        dec = "VENDER"
    else:
        dec = "MANTER"
    conf = round(min(45 + 10 * abs(pontos), 75)) if dec != "MANTER" else 50
    frase = {"COMPRAR": "Indicadores em alta", "VENDER": "Indicadores em baixa", "MANTER": "Sinais mistos ou neutros"}[dec]
    dy = m.get("dividend_yield_12m") or 0
    resumo = f"{frase}: " + "; ".join(sinais[:4]) + "." + (f" Pagou {pct(dy)} em dividendos nos últimos 12 meses." if dy > 0.5 else "")
    riscos = []
    if vol > 35: riscos.append(f"Oscilação alta: {pct(vol, 0)} ao ano")
    if (m.get("queda_max_12m") or 0) < -20: riscos.append(f"Chegou a cair {pct(abs(m['queda_max_12m']), 0)} nos últimos 12 meses")
    if rsi is not None and rsi > 70: riscos.append("Subiu rápido: pode devolver parte da alta")
    riscos.append("Análise por indicadores de preço: as notícias não foram avaliadas")
    return {"decisao": dec, "confianca": conf, "alvo": round(p * (1 + 0.5 * vol / 100), 2), "stop": round(p * (1 - 0.3 * vol / 100), 2),
            "resumo": resumo, "riscos": riscos[:4]}


# ---------------------------------------------------------------- momento do mercado

def juro_real(taxas):
    s, i = taxas.get("selic"), taxas.get("ipca_esperado") or taxas.get("ipca12")
    return ((1 + s / 100) / (1 + i / 100) - 1) * 100 if s is not None and i is not None else None


def panorama(taxas, mercado):
    """Visão por classe sem IA: juro real para a renda fixa e tendência dos índices para o resto."""
    real = juro_real(taxas)
    classes = {}
    if real is not None:
        v = "POSITIVA" if real >= 5 else "NEUTRA" if real >= 2 else "NEGATIVA"
        classes["renda_fixa"] = (v, {"POSITIVA": 1, "NEUTRA": 0, "NEGATIVA": -1}[v],
                                 f"Juro real de {pct(real)} ao ano (Selic de {pct(taxas['selic'], 2)} contra inflação esperada de "
                                 f"{pct(taxas.get('ipca_esperado') or taxas.get('ipca12'), 2)}): "
                                 + ("a renda fixa paga bem acima da inflação." if v == "POSITIVA" else "retorno real moderado." if v == "NEUTRA" else "pouco acima da inflação."))

    def por_tendencia(chave, rotulo, extra=""):
        m = mercado.get(chave)
        if not m: return ("NEUTRA", 0, f"Sem dados recentes de {rotulo}.")
        t, r12 = m.get("tendencia"), m.get("ret_12m")
        v = "POSITIVA" if t == "alta" and (r12 or 0) > 0 else "NEGATIVA" if t == "baixa" else "NEUTRA"
        return (v, {"POSITIVA": 1, "NEUTRA": 0, "NEGATIVA": -1}[v],
                f"{rotulo} em tendência de {t or 'indefinida'}, com {pct(r12, sinal=True)} em 12 meses e {pct(m.get('ret_1m'), sinal=True)} no último mês.{extra}")

    juro_alto = real is not None and real >= 6
    classes["acao"] = por_tendencia("IBOV", "Ibovespa", " Juro real alto concorre com a bolsa." if juro_alto else "")
    v, a, mo = por_tendencia("IFIX (FIIs grandes)", "Os FIIs grandes")
    if juro_alto and v == "POSITIVA":  # juro alto costuma pressionar os FIIs
        v, a, mo = "NEUTRA", 0, mo + " Com o juro real alto, a alta tende a ser limitada."
    classes["fii"] = (v, a, mo)
    classes["exterior"] = por_tendencia("S&P 500 em reais", "O S&P 500 em reais")
    classes["cambio"] = por_tendencia("Dólar", "O dólar", " Serve como proteção em crises locais.")
    out = {c: {"visao": classes[c][0], "ajuste": classes[c][1], "motivo": classes[c][2]} for c in classes}
    fatores = [x[2] for x in (classes.get("renda_fixa"), classes["acao"], classes["cambio"]) if x]
    resumo = ("Leitura feita por indicadores, sem análise de notícias. "
              + (f"O juro real de {pct(real)} ao ano {'favorece' if (real or 0) >= 5 else 'não favorece especialmente'} a renda fixa; " if real is not None else "")
              + f"a bolsa brasileira está com visão {out['acao']['visao'].lower()} e o exterior, {out['exterior']['visao'].lower()}.")
    return {"resumo": resumo, "classes": out, "fatores": fatores}


# ---------------------------------------------------------------- objetivo escrito pelo investidor

_NUM = r"(\d{1,3}(?:\.\d{3})+(?:,\d+)?|\d+(?:,\d+)?)"
_MULT = r"(milh(?:ão|ao|ões|oes)|mil\b|k\b)"  # "milhão" antes de "mil", senão "mil" casa primeiro
_DINHEIRO = re.compile(r"R\$\s*" + _NUM + r"(?:\s*" + _MULT + r")?|" + _NUM + r"\s*" + _MULT, re.I)
_MENSAL = re.compile(r"^\s*(?:reais\s*)?(?:por\s+m[eê]s|/\s*m[eê]s|ao\s+m[eê]s|mensa(?:l|is)|todo\s+m[eê]s|a\s+cada\s+m[eê]s)", re.I)
_PRAZO = re.compile(r"(\d+(?:,\d+)?)\s*(anos?|mes(?:es)?)\b", re.I)
_ANO = re.compile(r"\b(?:em|até|ate|para|no fim de|no final de)\s+(20\d{2})\b", re.I)
TIPOS = [  # (padrão, descrição, liquidez quando não há prazo)
    (r"reserva de emerg|emerg[eê]ncia", "Reserva de emergência", "ALTA"),
    (r"aposentad|aposentar|independ[eê]ncia financeira|renda passiva|viver de renda", "Aposentadoria e independência financeira", "BAIXA"),
    (r"apartamento|\bcasa\b|im[oó]vel|entrada", "Compra de imóvel", None),
    (r"\bcarro\b|ve[ií]culo|\bmoto\b", "Compra de veículo", None),
    (r"viagem|viajar|interc[aâ]mbio", "Viagem", None),
    (r"casamento|festa", "Casamento", None),
    (r"faculdade|estud|educa[cç][aã]o|escola", "Educação", None),
    (r"crescer|longo prazo|patrim[oô]nio|multiplicar", "Fazer o patrimônio crescer", "BAIXA"),
]


def _valor(txt, mult):
    v = float(txt.replace(".", "").replace(",", "."))
    m = (mult or "").lower()
    return v * (1e6 if m.startswith("milh") else 1e3 if m in ("mil", "k") else 1)


def objetivo(texto):
    """Entende o objetivo por padrões de texto. Não inventa: o que não reconhece fica em branco e vira ponto de atenção."""
    t = " ".join(texto.split())
    low = t.lower()
    tipos = [(d, liq) for pad, d, liq in TIPOS if re.search(pad, low)]
    valor = aporte = 0.0
    for mt in _DINHEIRO.finditer(t):
        num_, mult = (mt.group(1), mt.group(2)) if mt.group(1) else (mt.group(3), mt.group(4))
        v = _valor(num_, mult)
        if _MENSAL.match(t[mt.end():mt.end() + 25]):
            aporte = aporte or v
        elif not valor:
            valor = v
    prazo = 0.0
    for mt in _PRAZO.finditer(t):
        antes = low[max(0, mt.start() - 12):mt.start()]
        if re.search(r"(tenho|idade|com)\s*$", antes):  # "tenho 30 anos" é idade, não prazo
            continue
        n = float(mt.group(1).replace(",", "."))
        prazo = n if mt.group(2).lower().startswith("ano") else n / 12
        break
    if not prazo and (ma := _ANO.search(t)):
        prazo = max(int(ma.group(1)) - date.today().year, 0)
    reserva = any(d == "Reserva de emergência" for d, _ in tipos)
    principal = next((d for d, _ in tipos if d != "Reserva de emergência"), None) or ("Reserva de emergência" if reserva else "Seu objetivo")
    if prazo:
        liq = "ALTA" if prazo <= 2 else "MEDIA" if prazo <= 5 else "BAIXA"
    else:
        liq = next((l for d, l in tipos if d == principal and l), None)
    metas = [{"descricao": principal, "prazo_anos": round(prazo, 1), "valor_alvo": round(valor, 2)}]
    if reserva and principal != "Reserva de emergência":
        metas.append({"descricao": "Reserva de emergência", "prazo_anos": 0, "valor_alvo": 0})
    partes = [f"Você quer: {principal.lower()}" if principal != "Seu objetivo" else
              "Você quer investir" if (valor or prazo or aporte) else "Não reconheci no texto um tipo de objetivo, prazo ou valor"]
    if valor: partes.append(f"juntando {brl(valor, 0)}")
    if prazo: partes.append(f"em {br(prazo, 0 if prazo == int(prazo) else 1)} {'ano' if prazo == 1 else 'anos'}")
    if aporte: partes.append(f"investindo {brl(aporte, 0)} por mês")
    atencao = []
    if not prazo and principal not in ("Reserva de emergência",):
        atencao.append("Não identifiquei o prazo. Diga para quando você precisa do dinheiro (ex.: “em 5 anos”).")
    if not valor and principal not in ("Reserva de emergência", "Fazer o patrimônio crescer", "Aposentadoria e independência financeira"):
        atencao.append("Não identifiquei quanto você precisa juntar (ex.: “R$ 150 mil”).")
    if not reserva and principal != "Reserva de emergência":
        atencao.append("Se ainda não tem, separe uma reserva de emergência (de 3 a 6 meses de gastos) antes de investir com mais risco.")
    return {"resumo": ", ".join(partes) + ".", "metas": metas, "aporte_mensal": round(aporte, 2), "liquidez": liq,
            "influencia": "", "atencao": atencao[:3]}


# ---------------------------------------------------------------- alocação e escolha de ativos

def alvo_classes(modelo, pan_classes, obj):
    """Alocação por classe: começa no modelo do perfil e ajusta pelo prazo do objetivo e pelo momento do mercado."""
    alvo, motivos = dict(modelo), []
    liq = (obj or {}).get("liquidez")
    risco = [c for c in CLASSES if c != "renda_fixa"]

    def levar_para_rf(meta_rf):
        falta = meta_rf - alvo["renda_fixa"]
        tot = sum(alvo[c] for c in risco)
        if falta <= 0 or tot <= 0: return
        for c in risco: alvo[c] -= falta * alvo[c] / tot
        alvo["renda_fixa"] = meta_rf

    if liq == "ALTA":
        levar_para_rf(90)
        motivos.append("Você vai precisar do dinheiro em até 2 anos (ou a qualquer momento): quase tudo fica em renda fixa segura e com liquidez.")
    elif liq == "MEDIA":
        levar_para_rf(max(modelo["renda_fixa"], 65))
        motivos.append("Com prazo entre 2 e 5 anos, a maior parte fica em renda fixa para a bolsa não atrapalhar a meta.")
    rf = (pan_classes or {}).get("renda_fixa", {}).get("visao")
    if rf == "POSITIVA" and liq != "ALTA":
        levar_para_rf(min(alvo["renda_fixa"] + 5, modelo["renda_fixa"] + 10, 100))
        motivos.append("O juro real está alto: mais 5 pontos em renda fixa, que paga bem acima da inflação sem risco de bolsa.")
    acao = (pan_classes or {}).get("acao", {}).get("visao")
    if acao == "NEGATIVA" and alvo["acao"] > 3:
        alvo["acao"] -= 3; alvo["renda_fixa"] += 3
        motivos.append("O Ibovespa está em tendência de baixa: 3 pontos a menos em ações.")
    s = sum(alvo.values())
    alvo = {c: round(max(v, 0) / s * 100, 1) for c, v in alvo.items()}
    if not motivos:
        motivos.append("Alocação do seu perfil, sem ajustes: o momento do mercado não pediu mudanças.")
    return alvo, " ".join(motivos)


def pontuacao(m, c):
    """Quanto maior, melhor: tendência, retorno de 12 meses, dividendos (ações e FIIs) e menos oscilação."""
    if not m: return -9
    s = {"alta": 1, "baixa": -1}.get(m.get("tendencia"), 0)
    s += max(min((m.get("ret_12m") or 0) / 30, 1), -1)
    if c in ("acao", "fii"): s += min((m.get("dy_12m") or 0) / 10, 1.2)
    s -= max(((m.get("vol_aa") or 25) - 25) / 50, 0)
    return round(s, 2)


def escolher_ativos(alvo, cand, atual, sinais, liq, etfs):
    """Escolhe os ativos de cada classe. cand: {código: {classe, nome, descricao, m(métricas)}}; atual: {código: R$}.
    Núcleo em ETFs/títulos amplos; até 2 complementos individuais (no máximo 10% cada), preferindo o que você já tem."""
    pesos, motivos = {}, {}
    for c in CLASSES:
        alvo_c = alvo.get(c, 0)
        if alvo_c <= 0: continue
        meus = {a: v for a, v in atual.items() if cand.get(a, {}).get("classe") == c and v > 0}
        g = {}
        if c == "renda_fixa":
            base = {"ALTA": {"TESOURO_SELIC": .6, "CDB_CDI": .4}, "MEDIA": {"TESOURO_SELIC": .45, "TESOURO_IPCA": .55}}.get(
                liq, {"TESOURO_SELIC": .4, "TESOURO_IPCA": .6})
            tot_meus = sum(meus.values())
            parte_meus = min(.5, tot_meus / max(sum(atual.values()), 1) * 100 / alvo_c) if tot_meus else 0
            for a, v in meus.items():
                g[a] = parte_meus * v / tot_meus
                motivos[a] = "Você já tem: continua como parte da renda fixa e da liquidez da carteira."
            for a, w in base.items():
                g[a] = g.get(a, 0) + w * (1 - parte_meus)
            motivos.setdefault("TESOURO_SELIC", "Reserva e liquidez: rende a Selic, pode ser resgatado em 1 dia e quase não oscila.")
            motivos.setdefault("CDB_CDI", "Rende perto do CDI com garantia do FGC; boa opção para dinheiro com data marcada.")
            motivos.setdefault("TESOURO_IPCA", "Protege da inflação: paga IPCA mais um juro real fixo; ideal para prazos mais longos.")
        else:
            nucleo = {"acao": {"BOVA11": .6, "DIVO11": .4}, "fii": {"KNCR11": .5, "HGLG11": .5},
                      "exterior": {"IVVB11": 1.0}, "cambio": {"DOLAR": .5, "GOLD11": .5}}[c]
            if alvo_c < 6:  # classe pequena: um único ativo amplo basta
                nucleo = {next(iter(nucleo)): 1.0}
            individuais = c in ("acao", "fii")
            total_atual = max(sum(atual.values()), 1)
            # 1º o que você já tem e não está com sinal de venda (evita custo e IR); depois os mais bem pontuados
            meus_ok = sorted((a for a in meus if a not in nucleo and sinais.get(a) != "VENDER"), key=lambda a: -meus[a])
            n_sat = 0 if alvo_c < 8 else 1 if alvo_c < 18 else 2
            if individuais:
                pont = {a: pontuacao(x.get("m"), c) for a, x in cand.items()
                        if x.get("classe") == c and a not in nucleo and a not in meus and sinais.get(a) != "VENDER"}
                novos = [a for a, s in sorted(pont.items(), key=lambda kv: -kv[1]) if s > 0]
                escolhidos = meus_ok[:2] + novos[:max(n_sat - len(meus_ok[:2]), 0)]
            else:
                escolhidos = meus_ok[:1]
            limite = (10 / alvo_c) if individuais else 0.5  # ação ou FII individual: no máximo 10% da carteira
            parte = 0
            for a in escolhidos:
                if a in meus:  # mantém o tamanho atual, só cortando o excesso
                    w = min(limite, 0.35 if individuais else 0.5, max(meus[a] / total_atual * 100 / alvo_c, 2 / alvo_c))
                else:
                    w = min(0.2, limite)
                g[a] = w; parte += w
                m = cand[a].get("m") or {}
                dados = ", ".join(x for x in [f"tendência de {m.get('tendencia')}" if m.get("tendencia") else "",
                                              f"{pct(m.get('ret_12m'), sinal=True)} em 12 meses" if m.get("ret_12m") is not None else "",
                                              f"{pct(m.get('dy_12m'))} de dividendos" if (m.get("dy_12m") or 0) > 1 else ""] if x)
                motivos[a] = (f"Você já tem e ele não está com sinal de venda: fica como complemento de {NOME_MIN[c]}, "
                              f"limitado para não concentrar{' (' + dados + ')' if dados else ''}." if a in meus else
                              f"Complemento de {NOME_MIN[c]} com os melhores indicadores da lista{': ' + dados if dados else ''}; "
                              "peso limitado para não concentrar.")
            for a, w in nucleo.items():
                g[a] = g.get(a, 0) + w * (1 - parte)
                desc = cand.get(a, {}).get("descricao", "")
                motivos.setdefault(a, f"Núcleo da parte de {NOME_MIN[c]}: {minuscula_inicial(desc) if desc else 'investimento amplo'}"
                                      + (", sem depender de uma única empresa." if c != "cambio" else "."))
            # pesos muito pequenos (abaixo de 2% da carteira) de ativos novos vão para o ativo principal da classe
            principal = next(iter(nucleo))
            for a in [a for a, w in g.items() if a != principal and a not in meus and alvo_c * w / sum(g.values()) < 2]:
                g[principal] += g.pop(a)
        tot = sum(g.values())
        for a, w in g.items():
            if w > 0: pesos[a] = round(alvo_c * w / tot, 2)
    return dict(sorted(pesos.items(), key=lambda kv: -kv[1])), motivos


# ---------------------------------------------------------------- o que fazer com cada ativo que você já tem

def acao_mantido(i, peso_alvo, total, sinal):
    """i: {ticker, pct, valor, pl, pl_pct, classe}. Devolve (ação, motivo) coerentes com a carteira recomendada."""
    dif = (peso_alvo - i["pct"]) / 100 * total
    folga = max(150, 0.02 * total)
    if peso_alvo <= 0:
        if sinal == "VENDER":
            return "VENDER", "Os indicadores estão em baixa e o ativo ficou fora da carteira recomendada."
        return "VENDER", "Ficou fora da carteira recomendada: o dinheiro rende mais protegido ou diversificado nos ativos sugeridos."
    if dif < -folga:
        if (i.get("pl_pct") or 0) > 30:
            return "REALIZAR_LUCRO", f"Já valorizou {pct(i['pl_pct'], 0)} e pesa mais do que o recomendado: vender uma parte garante parte do ganho."
        return "REDUZIR", f"Pesa {pct(i['pct'])} da carteira, acima dos {pct(peso_alvo)} recomendados: reduzir diminui a concentração."
    if dif > folga:
        return "AUMENTAR", f"Pesa {pct(i['pct'])}, abaixo dos {pct(peso_alvo)} recomendados."
    return "MANTER", "Já está perto do peso recomendado."


def ir_venda(t, c, valor_venda, pl_pct, etfs):
    """Estimativa simples do IR numa venda (regras gerais para pessoa física; confirme com um contador)."""
    if valor_venda <= 0: return None
    if c == "renda_fixa":
        return "Renda fixa: IR de 22,5% a 15% sobre o rendimento, conforme o tempo aplicado (LCI e LCA são isentas)."
    ganho = valor_venda * pl_pct / (100 + pl_pct) if pl_pct and pl_pct > 0 else 0
    if t == "DOLAR":
        return "Dólar: ganho com a variação do câmbio pode ser tributado; confira as regras do seu caso."
    if ganho <= 0:
        return "Sem lucro nesta posição: não há IR na venda (o prejuízo pode abater ganhos futuros da mesma categoria)."
    if c == "fii":
        return f"FII: 20% sobre o lucro, sem isenção. Lucro estimado de {brl(ganho)}, IR de ≈ {brl(ganho * .2)}."
    if t == "VOO":
        return f"Exterior: 15% sobre o lucro, apurado na declaração anual. IR de ≈ {brl(ganho * .15)} sobre lucro de {brl(ganho)}."
    if t in etfs or c == "exterior":
        return f"ETF: 15% sobre o lucro, sem a isenção de R$ 20 mil. IR de ≈ {brl(ganho * .15)} sobre lucro de {brl(ganho)}."
    if valor_venda <= 20000:
        return (f"Ações: vendas de até R$ 20 mil no mês são isentas. Se o total vendido no mês passar disso, "
                f"15% sobre o lucro (≈ {brl(ganho * .15)}).")
    return f"Ações: vendas acima de R$ 20 mil no mês pagam 15% sobre o lucro. IR de ≈ {brl(ganho * .15)} sobre lucro de {brl(ganho)}."


def fatos_metricas(m, c):
    if not m: return []
    fs = []
    if (t := tendencia_txt(m)): fs.append(fato("Tendência", t))
    r12 = m.get("ret_12m")
    if r12 is not None: fs.append(fato("Retorno em 12 meses", pct(r12, sinal=True)))
    if m.get("ret_3a_aa") is not None: fs.append(fato("Retorno ao ano (3 anos)", pct(m["ret_3a_aa"], sinal=True)))
    vol = m.get("vol_aa", m.get("volatilidade_anual"))
    if vol is not None: fs.append(fato("Oscilação ao ano", pct(vol, 0), "abaixo de 20% é baixa; acima de 35%, alta"))
    q = m.get("queda_max_12m")
    if q is not None and q < -5: fs.append(fato("Maior queda em 12 meses", pct(q, 0)))
    dy = m.get("dy_12m", m.get("dividend_yield_12m"))
    if dy and c in ("acao", "fii"): fs.append(fato("Dividendos em 12 meses", pct(dy)))
    rsi = m.get("rsi14")
    if rsi is not None: fs.append(fato("RSI (14 dias)", br(rsi, 0), "acima de 70: subiu rápido; abaixo de 30: caiu rápido"))
    return fs
