"""Controle de gastos do dia a dia: lançamentos com categoria automática, limite por categoria e resumo do mês.

- Cada lançamento tem data, descrição, valor (negativo = gasto, positivo = receita) e categoria.
- A categoria sai das palavras da descrição ("IFOOD" -> Alimentação fora). Quando a pessoa corrige uma categoria, o app
  aprende: a mesma descrição vai para a categoria escolhida nas próximas vezes (e, se ela pedir, nas que já estão lá).
- O extrato do banco (OFX ou CSV) vira lançamentos; importar o mesmo extrato de novo não duplica nada.
- Limite por categoria: o resumo mostra quanto já foi usado e o app avisa ao passar de 80% e de 100%.
"""
import calendar, re, statistics, time, uuid
from datetime import date

import armazem
import contas

DESPESAS = ["Mercado", "Alimentação fora", "Transporte", "Moradia", "Contas da casa", "Saúde", "Educação", "Lazer e viagens",
            "Assinaturas", "Compras", "Cuidados pessoais", "Pets", "Impostos e taxas", "Transferências", "Outros",
            "Fatura do cartão", "Investimentos"]
# não são consumo: a fatura paga é a soma das compras do cartão (que são os gastos de verdade) e aplicar é guardar dinheiro
FORA_DOS_GASTOS = ("Fatura do cartão", "Investimentos")
RECEITAS = ["Salário", "Renda extra", "Rendimentos", "Outras receitas"]
# ordem importa: a primeira que casar vence (padrões sem acento e em minúsculas)
PALAVRAS = [
    ("Fatura do cartão", r"fatura|pagamento (de )?cartao|pagto cartao|pag cartao"),
    ("Investimentos", r"aplicac|invest|tesouro direto|\bcdb\b|\blci\b|\blca\b|corretora|nuinvest|xp inv|btg pactual|rico inv|clear corr|poupanca"),
    ("Assinaturas", r"netflix|spotify|disney|hbo|\bmax\b|prime video|amazon prime|youtube|apple\.com|icloud|google (one|storage|play)|deezer|"
                    r"globoplay|paramount|crunchyroll|chatgpt|openai|claude\.ai|microsoft 365|xbox game pass|playstation plus"),
    ("Alimentação fora", r"ifood|i food|rappi|restaurante|lanchonete|\bbar\b|pizza|burger|mcdonald|\bbk\b|subway|starbucks|cafeteria|\bcafe\b|"
                         r"padaria|outback|coco bambu|habib|delivery|churrascaria|sorveteria|acai"),
    ("Mercado", r"supermerc|mercado(?! livre|livre|pago)|atacad|assai|carrefour|pao de acucar|hortifruti|sacolao|acougue|\bdia\b|"
                r"zaffari|guanabara|prezunic|big bompreco|sams club|makro"),
    ("Transporte", r"\buber\b|\b99\s?(app|pop|taxi)?\b|cabify|\bposto\b|combust|gasolina|etanol|shell|ipiranga|br mania|estacion|pedagio|"
                   r"sem parar|conectcar|veloe|\bmetro\b|onibus|bilhete unico|cptm|detran|ipva|licenciamento|oficina|auto pecas"),
    ("Moradia", r"aluguel|condominio|iptu|imobiliaria|quintoandar|quinto andar"),
    ("Contas da casa", r"enel|\blight\b|cemig|copel|celesc|cpfl|energisa|neoenergia|coelba|equatorial|sabesp|cedae|copasa|sanepar|embasa|"
                       r"comgas|naturgy|\bvivo\b|\bclaro\b|\btim\b|\boi\b|\bnet\b|internet|telefon|energia|\bagua\b"),
    ("Saúde", r"farmac|drogaria|droga raia|drogasil|pague menos|panvel|hospital|clinica|laborat|medic|dentist|odonto|unimed|amil|"
              r"sulamerica|hapvida|notredame|psicolog|fisioter|academia|smart ?fit|gympass|wellhub|bluefit"),
    ("Educação", r"escola|colegio|faculdade|universidade|\bcurso|udemy|alura|coursera|livraria|material escolar|mensalidade"),
    ("Lazer e viagens", r"cinema|ingresso|sympla|eventim|\bshow\b|teatro|parque|viagem|hotel|pousada|airbnb|booking|decolar|latam|"
                        r"gol linhas|azul linhas|\bgol\b|\bazul\b|steam|playstation|nintendo|clube"),
    ("Pets", r"\bpet|petz|cobasi|veterin|racao"),
    ("Cuidados pessoais", r"salao|barbearia|cabeleir|manicure|estetica|cosmetic|boticario|natura|sephora|perfumaria"),
    ("Compras", r"amazon|mercado ?livre|mercadolivre|shopee|aliexpress|shein|magalu|magazine luiza|americanas|casas bahia|renner|"
                r"riachuelo|\bc&a\b|\bcea\b|zara|centauro|netshoes|kabum|leroy|tok ?stok|ikea|decathlon"),
    ("Impostos e taxas", r"imposto|\bdarf\b|\bdas\b|\binss\b|tarifa|anuidade|\biof\b|juros|multa|encargo|cesta de servicos"),
    ("Transferências", r"\bpix\b|\bted\b|\bdoc\b|transf"),
]
PALAVRAS_RECEITA = [
    ("Salário", r"salario|folha de pag|pro ?labore|remuneracao|holerite|vencimentos|13o|decimo terceiro|ferias"),
    ("Rendimentos", r"rendimento|dividendo|juros s/? ?capital|\bjcp\b|proventos? b3|resgate"),
    ("Renda extra", r"\bpix\b|\bted\b|transf|recebid|venda"),
]


def categoria_auto(descricao, valor, regras=None):
    """Categoria pelo que a pessoa já ensinou (regras) ou pelas palavras da descrição."""
    regras = regras or {}
    k = contas._chave(descricao)
    if k and k in regras:
        return regras[k]
    t = contas.sem_acento(descricao)
    tabela = PALAVRAS_RECEITA if valor > 0 else PALAVRAS
    padrao = "Outras receitas" if valor > 0 else "Outros"
    return next((c for c, pad in tabela if re.search(pad, t)), padrao)


def _vazio():
    return {"itens": [], "limites": {}, "regras": {}}


def ler(uid):
    d = armazem.ler("gastos", uid)
    return {**_vazio(), **(d["dados"] if d else {})}


def _gravar(uid, d):
    d["itens"] = sorted(d["itens"], key=lambda x: (x["data"], x.get("criado", 0)))[-20000:]
    armazem.gravar("gastos", uid, d)


def _valida(x):
    try:
        dt = date.fromisoformat(str(x.get("data", ""))[:10])
    except ValueError:
        raise ValueError("Data inválida.")
    desc = " ".join(str(x.get("descricao", "")).split())[:120]
    try:
        valor = round(float(x.get("valor")), 2)
    except (TypeError, ValueError):
        raise ValueError("Valor inválido.")
    if not desc:
        raise ValueError("Informe a descrição.")
    if not valor or abs(valor) > 1e8:
        raise ValueError("Valor inválido.")
    return dt, desc, valor


def _categoria_valida(cat, valor):
    return cat if cat in (RECEITAS if valor > 0 else DESPESAS) else None


def adicionar(uid, novos, origem="manual"):
    """novos: [{data, descricao, valor, categoria?}]. Ignora os que já existem (mesma data, valor e descrição)."""
    d = ler(uid)
    vistos = {(x["data"], x["valor"], x.get("chave") or contas._chave(x["descricao"])) for x in d["itens"]}
    criados, repetidos = [], 0
    for x in novos:
        dt, desc, valor = _valida(x)
        k = contas._chave(desc)
        chave_dup = (dt.isoformat(), valor, k)
        if origem == "extrato" and chave_dup in vistos:
            repetidos += 1
            continue
        vistos.add(chave_dup)
        cat = _categoria_valida(x.get("categoria"), valor) or categoria_auto(desc, valor, d["regras"])
        it = {"id": uuid.uuid4().hex[:12], "data": dt.isoformat(), "descricao": desc, "valor": valor, "categoria": cat,
              "chave": k, "origem": origem, "criado": time.time()}
        d["itens"].append(it)
        criados.append(it)
    _gravar(uid, d)
    return criados, repetidos


def editar(uid, gid, mud, semelhantes=False):
    """Edita um lançamento. Se a categoria mudar, o app aprende a regra; com semelhantes=True, aplica às outras
    com a mesma descrição."""
    d = ler(uid)
    it = next((x for x in d["itens"] if x["id"] == gid), None)
    if not it:
        raise KeyError(gid)
    base = {**it, **{k: v for k, v in mud.items() if k in ("data", "descricao", "valor") and v is not None}}
    dt, desc, valor = _valida(base)
    it.update(data=dt.isoformat(), descricao=desc, valor=valor, chave=contas._chave(desc))
    cat = mud.get("categoria")
    alterados = 1
    if cat:
        if not _categoria_valida(cat, valor):
            raise ValueError("Categoria inválida.")
        it["categoria"] = cat
        if it["chave"]:
            d["regras"][it["chave"]] = cat
            if semelhantes:
                for x in d["itens"]:
                    if x is not it and x.get("chave") == it["chave"] and (x["valor"] > 0) == (valor > 0) and x["categoria"] != cat:
                        x["categoria"] = cat
                        alterados += 1
    elif _categoria_valida(it["categoria"], valor) is None:  # trocou gasto por receita (ou o contrário)
        it["categoria"] = categoria_auto(desc, valor, d["regras"])
    _gravar(uid, d)
    return it, alterados


def apagar(uid, gid):
    d = ler(uid)
    n = len(d["itens"])
    d["itens"] = [x for x in d["itens"] if x["id"] != gid]
    if len(d["itens"]) == n:
        raise KeyError(gid)
    _gravar(uid, d)


def definir_limites(uid, limites):
    d = ler(uid)
    out = {}
    for c, v in (limites or {}).items():
        try:
            v = round(float(v), 2)
        except (TypeError, ValueError):
            continue
        if c in DESPESAS and c not in FORA_DOS_GASTOS and v > 0:
            out[c] = v
    d["limites"] = out
    _gravar(uid, d)
    return out


def _ym(s):
    return s[:7]


def _mes_anterior(ym, n=1):
    a, m = int(ym[:4]), int(ym[5:7]) - n
    while m < 1:
        a, m = a - 1, m + 12
    return f"{a:04d}-{m:02d}"


def _por_categoria(itens, todas=False):
    out = {}
    for x in itens:
        if x["valor"] < 0 and (todas or x["categoria"] not in FORA_DOS_GASTOS):
            out[x["categoria"]] = out.get(x["categoria"], 0) + -x["valor"]
    return out


def resumo(uid, ym=None, hoje=None):
    """Resumo do mês: receitas, gastos, saldo, gasto por categoria (com limite, mês anterior e média de 3 meses),
    maiores gastos e observações em linguagem simples."""
    hoje = hoje or date.today()
    ym = ym or hoje.strftime("%Y-%m")
    d = ler(uid)
    por_mes = {}
    for x in d["itens"]:
        por_mes.setdefault(_ym(x["data"]), []).append(x)
    itens = por_mes.get(ym, [])
    rec = round(sum(x["valor"] for x in itens if x["valor"] > 0), 2)
    cat = _por_categoria(itens)
    fora = {c: v for c, v in _por_categoria(itens, True).items() if c in FORA_DOS_GASTOS}
    desp = round(sum(cat.values()), 2)
    ant = _por_categoria(por_mes.get(_mes_anterior(ym), []))
    tres = [_por_categoria(por_mes[m]) for m in (_mes_anterior(ym, k) for k in (1, 2, 3)) if m in por_mes]
    media3 = {c: statistics.mean(m.get(c, 0) for m in tres) for c in DESPESAS} if tres else {}
    # ritmo do mês corrente: quanto do mês já passou (para avisar "no ritmo atual, vai passar do limite")
    corrente = ym == hoje.strftime("%Y-%m")
    dias_mes = calendar.monthrange(int(ym[:4]), int(ym[5:7]))[1]
    fracao = min(hoje.day / dias_mes, 1.0) if corrente else 1.0
    linhas = []
    for c in sorted(set(cat) | set(d["limites"]), key=lambda c: -cat.get(c, 0)):
        v, lim = round(cat.get(c, 0), 2), d["limites"].get(c)
        linhas.append({"categoria": c, "valor": v, "limite": lim, "usado": round(v / lim * 100, 1) if lim else None,
                       "mes_anterior": round(ant.get(c, 0), 2) if ant else None,
                       "media_3m": round(media3.get(c, 0), 2) if media3 else None,
                       "pct": round(v / desp * 100, 1) if desp else 0})
    obs = []
    for l in linhas:
        if l["limite"] and l["usado"] >= 100:
            obs.append({"tipo": "bad", "texto": f"{l['categoria']}: passou do limite (gastou {contas_brl(l['valor'])} de {contas_brl(l['limite'])})."})
        elif l["limite"] and corrente and l["usado"] >= 80:
            obs.append({"tipo": "warn", "texto": f"{l['categoria']}: já usou {l['usado']:.0f}% do limite e o mês ainda não acabou."})
        elif l["limite"] and corrente and fracao >= 0.2 and l["valor"] / fracao > l["limite"] * 1.1:
            obs.append({"tipo": "warn", "texto": f"{l['categoria']}: no ritmo atual, o mês fecha em cerca de "
                                                 f"{contas_brl(l['valor'] / fracao)}, acima do limite de {contas_brl(l['limite'])}."})
    for l in sorted(linhas, key=lambda l: -l["valor"]):
        m3 = l["media_3m"]
        if m3 and m3 >= 100 and not corrente and l["valor"] > m3 * 1.3:
            obs.append({"tipo": "info", "texto": f"{l['categoria']}: {contas_brl(l['valor'])}, {((l['valor'] / m3) - 1) * 100:.0f}% "
                                                 f"acima da média dos 3 meses anteriores ({contas_brl(m3)})."})
    if rec and not corrente:
        sobra = rec - desp - fora.get("Fatura do cartão", 0)
        obs.append({"tipo": "good" if sobra > 0 else "warn",
                    "texto": ((f"Sobrou {contas_brl(sobra)} ({sobra / rec * 100:.0f}% do que entrou) depois dos gastos"
                               + (f"; você já aplicou {contas_brl(fora['Investimentos'])}." if fora.get("Investimentos") else ": dá para investir."))
                              if sobra > 0 else
                              f"Os gastos passaram as receitas em {contas_brl(-sobra)}. Veja as maiores categorias abaixo.")})
    maiores = sorted((x for x in itens if x["valor"] < 0), key=lambda x: x["valor"])[:5]
    meses = sorted(por_mes)
    historico = [{"mes": m, "receitas": round(sum(x["valor"] for x in por_mes[m] if x["valor"] > 0), 2),
                  "gastos": round(sum(_por_categoria(por_mes[m]).values()), 2)} for m in meses[-6:]]
    return {"mes": ym, "receitas": rec, "gastos": desp, "saldo": round(rec - desp - sum(fora.values()), 2), "categorias": linhas,
            "investido": round(fora.get("Investimentos", 0), 2), "faturas": round(fora.get("Fatura do cartão", 0), 2),
            "itens": sorted(itens, key=lambda x: (x["data"], x.get("criado", 0)), reverse=True),
            "limites": d["limites"], "observacoes": obs[:5], "maiores": maiores, "historico": historico,
            "meses": meses, "tem_dados": bool(d["itens"]), "despesas": DESPESAS, "receitas_cat": RECEITAS,
            "media_gastos_3m": round(statistics.mean(h["gastos"] for h in historico[-4:-1]), 2) if len(historico) >= 2 else None}


def contas_brl(v):
    return ("-" if v < 0 else "") + "R$ " + f"{abs(v):,.0f}".replace(",", ".")


def alertas_limite(uid, hoje=None):
    """Para os avisos: categorias do mês atual que passaram de 80% ou de 100% do limite."""
    hoje = hoje or date.today()
    d = ler(uid)
    if not d["limites"]:
        return []
    ym = hoje.strftime("%Y-%m")
    cat = _por_categoria([x for x in d["itens"] if _ym(x["data"]) == ym])
    out = []
    for c, lim in d["limites"].items():
        usado = cat.get(c, 0) / lim * 100
        if usado >= 80:
            out.append({"categoria": c, "nivel": 100 if usado >= 100 else 80, "usado": round(usado), "valor": round(cat.get(c, 0), 2),
                        "limite": lim, "mes": ym})
    return out


def do_extrato(transacoes):
    """Transações do extrato (contas.ler_extrato) no formato de lançamento."""
    return [{"data": t["data"].isoformat(), "descricao": contas.nome_bonito(t["descricao"]) or t["descricao"], "valor": t["valor"]}
            for t in transacoes if t.get("valor")]


# ---------------------------------------------------------------- lançamento rápido por texto ou voz (e pelo WhatsApp)

_NUM = r"(\d{1,3}(?:\.\d{3})+(?:,\d{1,2})?|\d+(?:[.,]\d{1,2})?)"
_RECEITA = r"\b(recebi|ganhei|entrou|caiu|recebido|salario|reembolso|vendi)\b"
_RUIDO = (r"\b(gastei|paguei|comprei|recebi|ganhei|entrou|caiu|foi|de|do|da|no|na|em|com|pra|para|um|uma|o|a|os|as|reais|real|"
          r"conto|contos|hoje|ontem|anteontem|r\$|mil|vezes|parcelado|parcelada|cartao|credito|x)\b")


def _mais_meses(d, n):
    m = d.month - 1 + n
    a, m = d.year + m // 12, m % 12 + 1
    return date(a, m, min(d.day, calendar.monthrange(a, m)[1]))


def interpretar(texto, hoje=None, cartoes=None):
    """'gastei 52,90 no mercado ontem' -> {data, descricao, valor, parcelas, cartao}. Sem valor, ValueError."""
    hoje = hoje or date.today()
    bruto = " ".join(str(texto or "").split())[:300]
    t = contas.sem_acento(bruto).lower()
    sem_datas = re.sub(r"\b\d{1,2}/\d{1,2}(?:/\d{2,4})?\b", " ", t)
    m = re.search(r"r\$\s*" + _NUM, sem_datas) or re.search(_NUM + r"\s*(mil|reais|real|contos?)?\b", sem_datas)
    if not m:
        raise ValueError("Não achei o valor. Escreva, por exemplo: gastei 50 no mercado.")
    v = float(m.group(1).replace(".", "").replace(",", ".")) if "," in m.group(1) or re.search(r"\.\d{3}", m.group(1)) \
        else float(m.group(1).replace(",", "."))
    if len(m.groups()) > 1 and m.group(2) == "mil":
        v *= 1000
    if not 0 < v <= 1e7:
        raise ValueError("Valor inválido.")
    dt = hoje
    if re.search(r"\banteontem\b", t):
        dt = date.fromordinal(hoje.toordinal() - 2)
    elif re.search(r"\bontem\b", t):
        dt = date.fromordinal(hoje.toordinal() - 1)
    md = re.search(r"\b(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b", t)
    if md:
        a = int(md.group(3)) if md.group(3) else hoje.year
        a = a + 2000 if a < 100 else a
        try:
            dt = date(a, int(md.group(2)), int(md.group(1)))
        except ValueError:
            pass
    mp = re.search(r"\b(?:em\s*)?(\d{1,2})\s*(?:x|vezes)\b", t)
    parcelas = int(mp.group(1)) if mp and 1 < int(mp.group(1)) <= 48 else 1
    cartao = None
    if cartoes and re.search(r"\bcartao\b|\bcredito\b|\d\s*x\b|vezes", t):
        cartao = next((c["id"] for c in cartoes if contas.sem_acento(c["nome"]).lower() in t), cartoes[0]["id"])
    receita = bool(re.search(_RECEITA, t)) and not cartao
    # descrição: as palavras que sobram, com os acentos originais
    nomes_cartao = {contas.sem_acento(w).lower() for c in (cartoes or []) for w in c["nome"].split()}
    palavras = []
    for w in bruto.split():
        n = re.sub(r"[^\w$/]", "", contas.sem_acento(w).lower())
        if (not n or len(n) < 2 or re.search(r"\d", n) or re.fullmatch(_RUIDO, n) or n in nomes_cartao
                or n in ("dia", "dias", "cartao", "x", "r$", "r")):
            continue
        palavras.append(re.sub(r"[^\w\-]", "", w, flags=re.UNICODE))
    desc = " ".join(p for p in palavras if p)
    desc = (desc[:1].upper() + desc[1:])[:80] if desc else ("Recebimento" if receita else "Gasto")
    return {"data": dt.isoformat(), "descricao": desc, "valor": round(v if receita else -v, 2), "parcelas": parcelas,
            "cartao": cartao}


# ---------------------------------------------------------------- cartões de crédito: fatura e parcelas

def cartoes(uid):
    return ler(uid).get("cartoes", [])


def salvar_cartao(uid, c):
    nome = " ".join(str(c.get("nome", "")).split())[:40]
    try:
        fecha, vence = int(c.get("fecha")), int(c.get("vence"))
        limite = round(float(c.get("limite") or 0), 2)
    except (TypeError, ValueError):
        raise ValueError("Informe o dia de fechamento, o de vencimento e o limite.")
    if not nome or not (1 <= fecha <= 31 and 1 <= vence <= 31) or limite < 0:
        raise ValueError("Informe o nome e dias entre 1 e 31.")
    d = ler(uid)
    lst = d.setdefault("cartoes", [])
    cid = c.get("id")
    atual = next((x for x in lst if x["id"] == cid), None) if cid else None
    if atual:
        atual.update(nome=nome, fecha=fecha, vence=vence, limite=limite)
    else:
        if len(lst) >= 10:
            raise ValueError("No máximo 10 cartões.")
        atual = {"id": uuid.uuid4().hex[:10], "nome": nome, "fecha": fecha, "vence": vence, "limite": limite}
        lst.append(atual)
    _gravar(uid, d)
    return atual


def apagar_cartao(uid, cid):
    d = ler(uid)
    n = len(d.get("cartoes", []))
    d["cartoes"] = [c for c in d.get("cartoes", []) if c["id"] != cid]
    if len(d["cartoes"]) == n:
        raise KeyError(cid)
    for x in d["itens"]:
        if x.get("cartao") == cid:
            x.pop("cartao", None)
    _gravar(uid, d)


def fatura_de(cartao, dt):
    """Mês (AAAA-MM) e dia de vencimento da fatura em que cai uma compra feita em dt."""
    fecha = min(cartao["fecha"], calendar.monthrange(dt.year, dt.month)[1])
    fechamento = dt if dt.day < fecha else _mais_meses(dt, 1)
    fechamento = date(fechamento.year, fechamento.month, min(cartao["fecha"], calendar.monthrange(fechamento.year, fechamento.month)[1]))
    venc = fechamento if cartao["vence"] > cartao["fecha"] else _mais_meses(fechamento, 1)
    venc = date(venc.year, venc.month, min(cartao["vence"], calendar.monthrange(venc.year, venc.month)[1]))
    return venc.strftime("%Y-%m"), venc


def adicionar_compra(uid, x):
    """Compra no cartão, à vista ou parcelada: cada parcela vira um lançamento no mês dela, ligado à fatura."""
    d = ler(uid)
    c = next((k for k in d.get("cartoes", []) if k["id"] == x.get("cartao")), None)
    if not c:
        raise ValueError("Cartão não encontrado.")
    dt, desc, valor = _valida(x)
    n = int(x.get("parcelas") or 1)
    if not 1 <= n <= 48:
        raise ValueError("Parcelas entre 1 e 48.")
    total = abs(valor)
    base = round(total / n, 2)
    grupo = uuid.uuid4().hex[:10]
    novos = []
    for k in range(n):
        v = base if k < n - 1 else round(total - base * (n - 1), 2)
        dk = _mais_meses(dt, k)
        fat, venc = fatura_de(c, _mais_meses(dt, k))
        novos.append({"data": dk.isoformat(), "descricao": desc + (f" ({k + 1}/{n})" if n > 1 else ""), "valor": -v,
                      "categoria": x.get("categoria"), "_extra": {"cartao": c["id"], "fatura": fat, "vencimento": venc.isoformat(),
                                                                  "parcela": f"{k + 1}/{n}", "grupo": grupo}})
    criados, _ = adicionar(uid, novos, origem=x.get("origem") or "cartao")
    d = ler(uid)
    por_id = {i["id"]: i for i in d["itens"]}
    for it, nv in zip(criados, novos):
        por_id[it["id"]].update(nv["_extra"])
        it.update(nv["_extra"])
    _gravar(uid, d)
    return criados


def faturas(uid, hoje=None):
    """Por cartão: fatura atual e as próximas (com as parcelas futuras), total, vencimento e limite usado."""
    hoje = hoje or date.today()
    d = ler(uid)
    out = []
    for c in d.get("cartoes", []):
        atual, _ = fatura_de(c, hoje)
        grupos = {}
        for x in d["itens"]:
            if x.get("cartao") == c["id"] and x.get("fatura"):
                g = grupos.setdefault(x["fatura"], {"mes": x["fatura"], "vencimento": x.get("vencimento"), "total": 0.0, "itens": []})
                g["total"] = round(g["total"] - x["valor"], 2)
                g["itens"].append({k: x[k] for k in ("data", "descricao", "valor", "parcela") if k in x})
        abertas = [g for m, g in sorted(grupos.items()) if m >= atual]
        usado = round(sum(g["total"] for g in abertas), 2)
        out.append({**c, "fatura_atual": atual, "faturas": abertas[:12], "limite_usado": usado,
                    "limite_disponivel": round(c["limite"] - usado, 2) if c["limite"] else None})
    return out
