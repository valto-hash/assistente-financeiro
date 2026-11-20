"""Contas do mês: ler boletos (linha digitável / código de barras), faturas em PDF e extratos bancários (OFX/CSV),
e identificar as contas que se repetem todo mês.

Tudo aqui funciona sem IA. Com IA, o servidor também lê fotos e PDFs difíceis (ver server.py).
"""
import csv, io, re, statistics, unicodedata
from datetime import date, datetime, timedelta

CATEGORIAS = ["Moradia", "Energia", "Água", "Gás", "Internet e telefone", "Cartão de crédito", "Educação", "Saúde",
              "Seguros", "Assinaturas", "Transporte", "Impostos", "Empréstimos", "Outros"]
PALAVRAS = [  # (categoria, padrão no texto já sem acentos e em minúsculas)
    ("Energia", r"\benel\b|cemig|\blight\b|copel|celesc|coelba|energisa|cpfl|equatorial|neoenergia|eletropaulo|elektro|celpe|cosern|\bedp\b|energia"),
    ("Água", r"sabesp|cedae|copasa|sanepar|embasa|compesa|saneago|caesb|corsan|casan|cagece|\baguas?\b|saneamento"),
    ("Gás", r"comgas|naturgy|gas natural|ultragaz|liquigas|supergasbras|\bgas\b"),
    ("Internet e telefone", r"\bvivo\b|\bclaro\b|\btim\b|\boi\b|\bsky\b|algar|nio fibra|brisanet|desktop|internet|telefon|telecom"),
    ("Cartão de crédito", r"fatura|cartao|nubank|nu pagamentos|credicard|mastercard|visa\b"),
    ("Moradia", r"aluguel|condominio|imobiliaria|quintoandar|quinto andar"),
    ("Educação", r"escola|colegio|faculdade|universidade|mensalidade|curso\b|educacional"),
    ("Saúde", r"unimed|amil|bradesco saude|sulamerica|sul america|hapvida|notredame|plano de saude|odonto"),
    ("Seguros", r"seguro|porto seguro|tokio marine|allianz|mapfre|liberty"),
    ("Assinaturas", r"netflix|spotify|amazon prime|prime video|disney|\bhbo\b|\bmax\b|youtube|apple\.com|icloud|google one|globoplay|"
                    r"deezer|paramount|crunchyroll|openai|chatgpt|anthropic|microsoft|xbox|playstation|smart ?fit|bluefit|academia|gympass|wellhub"),
    ("Impostos", r"\biptu\b|\bipva\b|\bdas\b|darf|simples nacional|receita federal|licenciamento|detran|prefeitura"),
    ("Empréstimos", r"emprestimo|financiamento|consorcio|crediario"),
    ("Transporte", r"sem parar|conectcar|veloe|estacionamento|combustivel|posto\b"),
]
BANCOS = {"001": "Banco do Brasil", "033": "Santander", "041": "Banrisul", "070": "BRB", "077": "Inter", "104": "Caixa",
          "212": "Banco Original", "237": "Bradesco", "260": "Nubank", "290": "PagBank", "323": "Mercado Pago", "336": "C6 Bank",
          "341": "Itaú", "380": "PicPay", "422": "Safra", "748": "Sicredi", "756": "Sicoob"}
SEGMENTOS = {"1": ("Prefeitura", "Impostos"), "2": ("Saneamento (água e esgoto)", "Água"), "3": ("Energia elétrica e gás", "Energia"),
             "4": ("Telecomunicações", "Internet e telefone"), "5": ("Órgão do governo", "Impostos"), "6": ("Carnê ou boleto de empresa", "Outros"),
             "7": ("Multa de trânsito", "Transporte"), "9": ("Uso exclusivo do banco", "Outros")}


def sem_acento(t):
    return "".join(c for c in unicodedata.normalize("NFD", t or "") if unicodedata.category(c) != "Mn").lower()


def categoria_de(texto):
    t = sem_acento(texto)
    return next((c for c, pad in PALAVRAS if re.search(pad, t)), "Outros")


# ---------------------------------------------------------------- boletos

def _mod10(num):
    soma = 0
    for i, d in enumerate(reversed(num)):
        p = int(d) * (2 if i % 2 == 0 else 1)
        soma += p // 10 + p % 10
    return (10 - soma % 10) % 10


def _mod11_boleto(num):  # DV geral do boleto bancário (pesos 2 a 9 da direita para a esquerda)
    soma = sum(int(d) * (2 + i % 8) for i, d in enumerate(reversed(num)))
    dv = 11 - soma % 11
    return 1 if dv in (0, 10, 11) else dv


def _mod11_arrecadacao(num):
    soma = sum(int(d) * (2 + i % 8) for i, d in enumerate(reversed(num)))
    resto = soma % 11
    return 0 if resto in (0, 1) else 11 - resto


def _vencimento(fator, hoje=None):
    """Fator de vencimento FEBRABAN: dias desde 07/10/1997. Chegou a 9999 em 21/02/2025 e recomeçou em 1000
    em 22/02/2025; das duas leituras possíveis, fica a mais próxima de hoje."""
    if fator == 0:
        return None
    hoje = hoje or date.today()
    candidatos = [date(1997, 10, 7) + timedelta(days=fator)]
    if fator >= 1000:
        candidatos.append(date(2025, 2, 22) + timedelta(days=fator - 1000))
    return min(candidatos, key=lambda d: abs((d - hoje).days))


def _formatar_linha(linha):
    if len(linha) == 47:
        return f"{linha[0:5]}.{linha[5:10]} {linha[10:15]}.{linha[15:21]} {linha[21:26]}.{linha[26:32]} {linha[32]} {linha[33:]}"
    return " ".join(f"{linha[i:i + 11]}-{linha[i + 11]}" for i in range(0, 48, 12))


def decodificar(codigo, hoje=None):
    """Lê a linha digitável (47 ou 48 dígitos) ou o código de barras (44) e devolve valor, vencimento, banco ou
    segmento, categoria provável e se os dígitos verificadores conferem."""
    n = re.sub(r"\D", "", codigo or "")
    if len(n) == 47 and n[0] != "8":  # boleto bancário (linha digitável)
        campos_ok = all(_mod10(n[a:b]) == int(n[b]) for a, b in ((0, 9), (10, 20), (21, 31)))
        barras = n[0:4] + n[32] + n[33:47] + n[4:9] + n[10:20] + n[21:31]
        linha = n
    elif len(n) == 44 and n[0] != "8":  # boleto bancário (código de barras)
        campos_ok, barras = True, n
        c1, c2, c3 = barras[0:4] + barras[19:24], barras[24:34], barras[34:44]
        linha = c1 + str(_mod10(c1)) + c2 + str(_mod10(c2)) + c3 + str(_mod10(c3)) + barras[4] + barras[5:19]
    elif len(n) in (48, 44) and n[0] == "8":  # arrecadação: contas de consumo, tributos, carnês
        if len(n) == 48:
            blocos = [n[i:i + 12] for i in range(0, 48, 12)]
            barras = "".join(b[:11] for b in blocos)
            mod = _mod10 if barras[2] in "67" else _mod11_arrecadacao
            campos_ok = all(mod(b[:11]) == int(b[11]) for b in blocos)
            linha = n
        else:
            barras, campos_ok = n, True
            mod = _mod10 if barras[2] in "67" else _mod11_arrecadacao
            linha = "".join(barras[i:i + 11] + str(mod(barras[i:i + 11])) for i in range(0, 44, 11))
        dv_ok = (_mod10 if barras[2] in "67" else _mod11_arrecadacao)(barras[:3] + barras[4:]) == int(barras[3])
        seg, cat = SEGMENTOS.get(barras[1], ("Arrecadação", "Outros"))
        valor = int(barras[4:15]) / 100 if barras[2] in "68" else None
        return {"tipo": "arrecadacao", "emissor": seg, "categoria": cat, "valor": valor or None, "vencimento": None,
                "linha": _formatar_linha(linha), "codigo_barras": barras, "valido": campos_ok and dv_ok,
                "aviso": None if valor else "Este tipo de conta não traz o valor em reais no código; confira na conta."}
    else:
        return {"erro": "O código precisa ter 47 ou 48 dígitos (linha digitável) ou 44 (código de barras)."}
    dv_ok = _mod11_boleto(barras[:4] + barras[5:]) == int(barras[4])
    venc = _vencimento(int(barras[5:9]), hoje)
    valor = int(barras[9:19]) / 100
    banco = BANCOS.get(barras[:3], f"Banco {barras[:3]}")
    return {"tipo": "boleto", "emissor": banco, "categoria": "Outros", "valor": valor or None,
            "vencimento": venc.isoformat() if venc else None, "linha": _formatar_linha(linha), "codigo_barras": barras,
            "valido": campos_ok and dv_ok,
            "aviso": None if campos_ok and dv_ok else "Os dígitos verificadores não conferem: confira se digitou a linha certa."}


_LINHA_BANCO = re.compile(r"\d{5}[.\s]?\d{5}\s*\d{5}[.\s]?\d{6}\s*\d{5}[.\s]?\d{6}\s*\d\s*\d{14}")
_LINHA_ARREC = re.compile(r"8\d{10}[-\s]?\d\s*\d{11}[-\s]?\d\s*\d{11}[-\s]?\d\s*\d{11}[-\s]?\d")
_DATA = r"(\d{2}/\d{2}/\d{4})"
_VALOR = r"(\d{1,3}(?:\.\d{3})*,\d{2})"


def _num(v):
    return float(v.replace(".", "").replace(",", ".")) if v else None


def ler_texto(texto, hoje=None):
    """Extrai de um texto (PDF de boleto ou fatura) o nome, a categoria, o valor, o vencimento e a linha digitável."""
    t = " ".join((texto or "").split())
    out = {"nome": None, "categoria": categoria_de(t), "valor": None, "vencimento": None, "linha": None, "tipo": "outro"}
    m = _LINHA_BANCO.search(t) or _LINHA_ARREC.search(t)
    if m:
        d = decodificar(m.group(0), hoje)
        if "erro" not in d:
            out.update(linha=d["linha"], tipo=d["tipo"], valor=d["valor"], vencimento=d["vencimento"], emissor=d["emissor"],
                       valido=d["valido"])
            if out["categoria"] == "Outros": out["categoria"] = d["categoria"]
    if not out["vencimento"] and (mv := re.search(r"vencimento\D{0,25}" + _DATA, t, re.I)):
        try:
            out["vencimento"] = datetime.strptime(mv.group(1), "%d/%m/%Y").date().isoformat()
        except ValueError:
            pass
    if not out["valor"]:
        for pad in (r"total (?:desta |da )?fatura\D{0,25}", r"valor (?:do documento|cobrado|a pagar|total)\D{0,25}", r"total a pagar\D{0,25}", r"valor\D{0,15}"):
            if (mv := re.search(pad + _VALOR, t, re.I)):
                out["valor"] = _num(mv.group(1)); break
    if (mb := re.search(r"(?:benefici[aá]rio|cedente)\s*:?\s*([A-Za-zÀ-ú0-9 .&/-]{3,60}?)(?:\s+(?:CNPJ|CPF|Ag[eê]ncia|Endere)|\s{2}|$)", t, re.I)):
        out["nome"] = mb.group(1).strip(" -.")
    if re.search(r"fatura", t, re.I) and re.search(r"cart[aã]o", t, re.I):
        out["tipo"], out["categoria"] = "fatura_cartao", "Cartão de crédito"
        emissor = next((b for b in ("Nubank", "Itaú", "Bradesco", "Inter", "C6", "Santander", "Banco do Brasil", "Caixa", "XP", "BTG", "Mercado Pago", "PicPay")
                        if re.search(re.escape(b), t, re.I)), None)
        out["nome"] = out["nome"] or f"Fatura do cartão{' ' + emissor if emissor else ''}"
    return out


def ler_pdf(conteudo, hoje=None):
    from pypdf import PdfReader
    leitor = PdfReader(io.BytesIO(conteudo))
    texto = "\n".join((p.extract_text() or "") for p in leitor.pages[:6])
    return ler_texto(texto, hoje), len(texto.strip())


# ---------------------------------------------------------------- extrato e contas recorrentes

def _decodificar_bytes(b):
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return b.decode(enc)
        except UnicodeDecodeError:
            continue
    return b.decode("utf-8", "ignore")


def _data(s):
    s = (s or "").strip()[:19]
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d/%m/%y", "%Y%m%d", "%d-%m-%Y", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(s[:len(datetime.now().strftime(fmt))] if fmt != "%Y-%m-%dT%H:%M:%S" else s, fmt).date()
        except ValueError:
            continue
    return None


def _valor_txt(s):
    s = (s or "").strip().replace("R$", "").replace(" ", "")
    neg = s.startswith("-") or s.startswith("(") or s.endswith("D")
    s = s.strip("-()CD+")
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".") if s.rfind(",") > s.rfind(".") else s.replace(",", "")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        v = float(s)
    except ValueError:
        return None
    return -v if neg else v


def ler_ofx(texto):
    out = []
    for bloco in re.split(r"<STMTTRN>", texto, flags=re.I)[1:]:
        bloco = re.split(r"</STMTTRN>", bloco, flags=re.I)[0]
        campo = lambda nome: (m.group(1).strip() if (m := re.search(rf"<{nome}>\s*([^<\r\n]+)", bloco, re.I)) else "")
        d, v = _data(campo("DTPOSTED")[:8]), _valor_txt(campo("TRNAMT").replace(",", "."))
        desc = " ".join(x for x in (campo("NAME"), campo("MEMO")) if x) or campo("PAYEE")
        if d and v is not None:
            out.append({"data": d, "descricao": desc, "valor": v})
    return out


def ler_csv(texto):
    amostra = texto[:4000]
    try:
        dialeto = csv.Sniffer().sniff(amostra, delimiters=";,\t|")
    except csv.Error:
        dialeto = csv.excel
        dialeto.delimiter = ";" if amostra.count(";") > amostra.count(",") else ","
    linhas = list(csv.reader(io.StringIO(texto), dialeto))
    achar = lambda cab, pads: next((i for i, c in enumerate(cab) if re.search(pads, sem_acento(c))), None)
    for k, cab in enumerate(linhas[:15]):  # a linha de cabeçalho pode não ser a primeira
        i_data = achar(cab, r"^data|date|dt\b")
        i_desc = achar(cab, r"descri|historico|title|titulo|lancamento|estabelecimento|memo|detalhe")
        i_val = achar(cab, r"^valor|amount|quantia|montante")
        i_deb, i_cred = achar(cab, r"debito|saida"), achar(cab, r"credito|entrada")
        if i_data is not None and i_desc is not None and (i_val is not None or i_deb is not None):
            break
    else:
        return []
    out = []
    for row in linhas[k + 1:]:
        if len(row) <= max(i for i in (i_data, i_desc, i_val, i_deb, i_cred) if i is not None):
            continue
        d = _data(row[i_data])
        if i_val is not None:
            v = _valor_txt(row[i_val])
        else:
            deb, cred = _valor_txt(row[i_deb]) or 0, (_valor_txt(row[i_cred]) or 0) if i_cred is not None else 0
            v = cred - abs(deb)
        if d and v is not None and row[i_desc].strip():
            out.append({"data": d, "descricao": row[i_desc].strip(), "valor": v})
    if out and all(t["valor"] >= 0 for t in out):  # fatura de cartão em CSV: compras vêm positivas
        for t in out: t["valor"] = -t["valor"]
    return out


def ler_extrato(conteudo, nome=""):
    texto = _decodificar_bytes(conteudo)
    if "<OFX>" in texto.upper() or "OFXHEADER" in texto.upper() or nome.lower().endswith(".ofx"):
        return ler_ofx(texto)
    return ler_csv(texto)


_IGNORAR = re.compile(r"aplicac|resgate|invest|tesouro|\bcdb\b|\blci\b|\blca\b|poupanca|saque|transferencia entre contas|"
                      r"mesma titularidade|estorno|rendimento|pagamento recebido|salario")
_RUIDO = re.compile(r"\b(pix|enviado|enviada|transferencia|pagamento|pagto|pgto|pag|compra|debito|credito|automatico|deb|aut|"
                    r"boleto|conta|no|na|de|do|da|em|com|cartao|ted|doc|parc(?:ela)?|\d+/\d+)\b")


def _chave(desc):
    t = re.sub(r"[\d*#/._-]+", " ", sem_acento(desc))
    t = _RUIDO.sub(" ", t)
    palavras = [p for p in t.split() if len(p) > 1]
    return " ".join(palavras[:3])


_PREFIXOS = re.compile(r"^\s*(?:pix\s+(?:enviad[oa]|transf\w*)|transf\w*\s+enviad[oa]|d[eé]bito\s+autom[aá]tico|deb\.?\s*aut\.?|"
                       r"pagamento(?:\s+de)?|pagto\.?|pgto\.?|pag\s*\*|compra(?:\s+no\s+d[eé]bito)?|boleto|conta)\s*[-:*]?\s*", re.I)


def nome_bonito(desc):
    """'DEBITO AUTOMATICO ENEL DISTRIBUICAO SP' -> 'Enel Distribuicao SP'; 'PAG*NETFLIX.COM' -> 'Netflix.com'."""
    t = re.sub(r"\s+", " ", desc or "").strip()
    for _ in range(2):
        t = _PREFIXOS.sub("", t)
    t = re.sub(r"[*#]+", " ", t).strip(" -.") or desc.strip()
    palavras = [p if (len(p) <= 2 and p.isupper() and p.isalpha() and p not in ("DE", "DA", "DO")) else p.capitalize() for p in t.split()]
    return " ".join(palavras)[:60]


def recorrentes(transacoes):
    """Acha saídas que se repetem uma vez por mês: mesmo favorecido, valor parecido e dia do mês parecido."""
    grupos = {}
    for t in transacoes:
        if t["valor"] >= 0 or _IGNORAR.search(sem_acento(t["descricao"])):
            continue
        k = _chave(t["descricao"])
        if k:
            grupos.setdefault(k, []).append(t)
    out = []
    for k, ts in grupos.items():
        meses = {(t["data"].year, t["data"].month) for t in ts}
        if len(meses) < 2:
            continue
        por_mes = {}
        for t in ts:  # se houver mais de um no mês, fica o maior (ex.: conta + taxa)
            m = (t["data"].year, t["data"].month)
            if m not in por_mes or abs(t["valor"]) > abs(por_mes[m]["valor"]):
                por_mes[m] = t
        ts = sorted(por_mes.values(), key=lambda t: t["data"])
        valores = [abs(t["valor"]) for t in ts]
        dias = [t["data"].day for t in ts]
        media = statistics.mean(valores)
        variacao = statistics.pstdev(valores) / media if media else 1
        cat = categoria_de(ts[-1]["descricao"])
        consumo = cat in ("Energia", "Água", "Gás", "Cartão de crédito")
        if variacao > (0.6 if consumo else 0.3):
            continue
        espalhamento = statistics.pstdev(dias)
        confianca = "alta" if len(meses) >= 3 and espalhamento <= 5 else "media"
        nome = nome_bonito(ts[-1]["descricao"])
        out.append({"nome": nome, "categoria": cat, "valor": round(statistics.median(valores), 2), "dia": int(round(statistics.median(dias))),
                    "meses": len(meses), "ultima": ts[-1]["data"].isoformat(), "variavel": variacao > 0.08, "confianca": confianca})
    return sorted(out, key=lambda x: (x["confianca"] != "alta", -x["valor"]))
