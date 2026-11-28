"""Rentabilidade da carteira, proventos e importação das planilhas da B3 (Área do Investidor).

Rentabilidade
- Sem histórico de compras: mostra quanto a carteira de HOJE (mesmas quantidades e saldos) teria rendido em 1, 3, 6,
  12 e 24 meses, contra CDI, Ibovespa e IPCA. É uma medida da carteira atual, não do seu resultado passado.
- Com o histórico importado da B3: rentabilidade de verdade desde a primeira compra (renda variável), pelo método
  Dietz modificado mês a mês, encadeado (é o que gestores usam para não confundir rendimento com dinheiro novo).
- Os preços são ajustados por proventos e desdobramentos, então a rentabilidade já inclui dividendos e JCP.

Proventos
- Com a B3: os valores que caíram na conta (dividendos, JCP, rendimentos de FII), por mês e por ativo.
- Sem a B3: estimativa com as quantidades de hoje e os proventos por cota dos últimos 12 meses (data-com).

Planilhas da B3 aceitas (Excel ou CSV): Posição, Movimentação e Negociação. O formato é reconhecido pelos nomes das
colunas, não pela posição delas, para tolerar pequenas mudanças da B3.
"""
import csv, io, re, threading, time
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd
import requests

import acertos
import contas
import simulacao as sim

TICKER = re.compile(r"^([A-Z]{4}\d{1,2})F?$")
_ipca = {"t": 0, "s": None}
_lock = threading.Lock()


# ---------------------------------------------------------------- IPCA mensal (Banco Central, série 433)

def ipca_mensal():
    """Índice acumulado do IPCA no fim de cada mês (Series). Cache de 24h; None se o BC não responder."""
    if _ipca["s"] is not None and time.time() - _ipca["t"] < 86400:
        return _ipca["s"]
    pontos, hoje = [], date.today()
    try:
        for ini in range(2005, hoje.year + 1, 10):  # o BC limita a consulta a 10 anos por vez
            r = requests.get("https://api.bcb.gov.br/dados/serie/bcdata.sgs.433/dados", timeout=15,
                             params={"formato": "json", "dataInicial": f"01/01/{ini}", "dataFinal": f"31/12/{min(ini + 9, hoje.year)}"})
            pontos += [(datetime.strptime(x["data"], "%d/%m/%Y"), float(x["valor"].replace(",", "."))) for x in r.json()]
    except Exception:
        return _ipca["s"]
    if not pontos:
        return _ipca["s"]
    taxa = pd.Series({d + pd.offsets.MonthEnd(0): v for d, v in pontos}).sort_index()
    _ipca.update(t=time.time(), s=(1 + taxa / 100).cumprod())
    return _ipca["s"]


def _ipca_periodo(ini, fim, idx):
    """Inflação entre duas datas, pelos meses fechados (o IPCA sai com atraso de ~10 dias)."""
    if idx is None or not len(idx):
        return None
    a = idx.asof(pd.Timestamp(ini) - pd.offsets.MonthEnd(1)) if pd.Timestamp(ini) > idx.index[0] else None
    b = idx.asof(pd.Timestamp(fim))
    if a is None or pd.isna(a) or pd.isna(b):
        return None
    return float(b / a - 1)


# ---------------------------------------------------------------- planilhas da B3

def _n(v):
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace("R$", "").replace("\xa0", "").replace(" ", "")
    if s in ("", "-", "--"):
        return None
    neg = s.startswith("-") or (s.startswith("(") and s.endswith(")"))
    s = s.strip("-()")
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    elif s.count(".") >= 1 and re.fullmatch(r"\d{1,3}(\.\d{3})+", s):
        s = s.replace(".", "")
    try:
        x = float(s)
    except ValueError:
        return None
    return -x if neg else x


def _d(v):
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    s = str(v or "").strip()[:10]
    for f in ("%d/%m/%Y", "%Y-%m-%d", "%d/%m/%y"):
        try:
            return datetime.strptime(s, f).date()
        except ValueError:
            pass
    return None


def _tabelas(conteudo, nome=""):
    """Todas as tabelas do arquivo: [(nome da aba, linhas)]."""
    if conteudo[:2] == b"PK" or nome.lower().endswith((".xlsx", ".xlsm")):
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(conteudo), read_only=True, data_only=True)
        return [(ws.title, [list(r) for r in ws.iter_rows(values_only=True)]) for ws in wb.worksheets]
    texto = contas._decodificar_bytes(conteudo)
    amostra = texto[:4000]
    sep = ";" if amostra.count(";") > amostra.count(",") else "\t" if amostra.count("\t") > amostra.count(",") else ","
    return [(nome or "csv", list(csv.reader(io.StringIO(texto), delimiter=sep)))]


def _cabecalho(linhas, exige):
    """Acha a linha de cabeçalho (nas 15 primeiras) que tem todas as colunas exigidas. Devolve (índice, {nome: coluna})."""
    for i, row in enumerate(linhas[:15]):
        cab = [contas.sem_acento(str(c or "")).strip() for c in row]
        if all(any(re.search(p, c) for c in cab) for p in exige):
            return i, cab
    return None, None


def _col(cab, padrao):
    return next((j for j, c in enumerate(cab) if re.search(padrao, c)), None)


def _ticker(v):
    s = str(v or "").strip().upper()
    m = TICKER.match(s.split(" - ")[0].split()[0]) if s else None
    return m.group(1) if m else None


def ler_b3(conteudo, nome=""):
    """Lê Posição, Movimentação ou Negociação da B3. Devolve {"posicao": {...}, "rf": {...}, "movs": [...],
    "proventos": [...], "tipos": [...], "ignorados": n}."""
    out = {"posicao": {}, "rf": {}, "movs": [], "proventos": [], "tipos": [], "ignorados": 0, "precos": {}}
    try:
        tabelas = _tabelas(conteudo, nome)
    except Exception as e:
        raise ValueError("Não consegui abrir o arquivo. Envie a planilha baixada da Área do Investidor da B3 (Excel ou CSV).") from e
    for aba, linhas in tabelas:
        aba_n = contas.sem_acento(aba)
        # Negociação: Data do Negócio, Tipo de Movimentação (Compra/Venda), Código de Negociação, Quantidade, Preço
        i, cab = _cabecalho(linhas, [r"data do negocio", r"tipo de movimentacao", r"codigo de negociacao", r"quantidade"])
        if i is not None:
            cd, ct, ck, cq, cp = (_col(cab, r"data do negocio"), _col(cab, r"tipo de movimentacao"), _col(cab, r"codigo de negociacao"),
                                  _col(cab, r"^quantidade"), _col(cab, r"^preco"))
            for row in linhas[i + 1:]:
                if len(row) <= max(cd, ct, ck, cq):
                    continue
                t, d, q = _ticker(row[ck]), _d(row[cd]), _n(row[cq])
                tipo = contas.sem_acento(str(row[ct] or ""))
                if not (t and d and q) or tipo not in ("compra", "venda"):
                    out["ignorados"] += 1 if any(row) else 0
                    continue
                out["movs"].append({"data": d.isoformat(), "ticker": t, "tipo": tipo, "qtd": abs(q),
                                    "preco": _n(row[cp]) if cp is not None and cp < len(row) else None})
            out["tipos"].append("negociacao")
            continue
        # Movimentação: Entrada/Saída, Data, Movimentação, Produto, Quantidade, Preço unitário, Valor da Operação
        i, cab = _cabecalho(linhas, [r"entrada/saida|entrada e saida|^entrada", r"^data", r"^movimentacao", r"^produto"])
        if i is not None:
            ce, cd, cm, cpr = _col(cab, r"entrada"), _col(cab, r"^data"), _col(cab, r"^movimentacao"), _col(cab, r"^produto")
            cq, cp, cv = _col(cab, r"^quantidade"), _col(cab, r"preco"), _col(cab, r"valor")
            for row in linhas[i + 1:]:
                if len(row) <= max(ce, cd, cm, cpr):
                    continue
                t, d = _ticker(row[cpr]), _d(row[cd])
                mov, ent = contas.sem_acento(str(row[cm] or "")), contas.sem_acento(str(row[ce] or ""))
                q = abs(_n(row[cq]) or 0) if cq is not None and cq < len(row) else 0
                preco = _n(row[cp]) if cp is not None and cp < len(row) else None
                valor = abs(_n(row[cv]) or 0) if cv is not None and cv < len(row) else 0
                if not (t and d):
                    out["ignorados"] += 1 if any(row) else 0
                    continue
                credito = ent.startswith("credito") or ent.startswith("entrada")
                if re.search(r"dividendo|juros sobre capital|rendimento|amortizacao|restituicao de capital", mov):
                    if valor > 0 and credito:
                        tipo = ("JCP" if "juros" in mov else "Rendimento" if "rendimento" in mov else
                                "Amortização" if re.search(r"amortiz|restitui", mov) else "Dividendo")
                        out["proventos"].append({"data": d.isoformat(), "ticker": t, "tipo": tipo, "valor": round(valor, 2)})
                elif re.search(r"liquidacao|^compra|^venda", mov) and q:
                    out["movs"].append({"data": d.isoformat(), "ticker": t, "tipo": "compra" if credito else "venda", "qtd": q,
                                        "preco": preco or (valor / q if valor else None)})
                elif re.search(r"desdobro|bonificacao|grupamento|fracao em ativos", mov) and q:
                    out["movs"].append({"data": d.isoformat(), "ticker": t, "tipo": "evento", "qtd": q if credito else -q, "preco": None,
                                        "evento": mov[:40]})
                else:
                    out["ignorados"] += 1
            out["tipos"].append("movimentacao")
            continue
        # Posição (ações, BDRs, ETFs, FIIs): Código de Negociação, Quantidade, Preço de Fechamento
        i, cab = _cabecalho(linhas, [r"codigo de negociacao", r"^quantidade"])
        if i is not None:
            ck, cq, cp = _col(cab, r"codigo de negociacao"), _col(cab, r"^quantidade$|^quantidade "), _col(cab, r"preco de fechamento|^preco")
            for row in linhas[i + 1:]:
                if len(row) <= max(ck, cq):
                    continue
                t, q = _ticker(row[ck]), _n(row[cq])
                if t and q:
                    out["posicao"][t] = out["posicao"].get(t, 0) + q
                    if cp is not None and cp < len(row) and _n(row[cp]):
                        out["precos"][t] = _n(row[cp])
            out["tipos"].append("posicao")
            continue
        # Posição em Tesouro Direto e renda fixa: Produto + Valor Atualizado
        i, cab = _cabecalho(linhas, [r"^produto", r"valor atualizado|valor liquido|valor bruto"])
        if i is not None:
            cpr = _col(cab, r"^produto")
            cv = next((j for p in (r"valor atualizado curva", r"valor atualizado$", r"valor atualizado", r"valor liquido", r"valor bruto")
                       if (j := _col(cab, p)) is not None), None)
            for row in linhas[i + 1:]:
                if len(row) <= max(cpr, cv):
                    continue
                prod, v = contas.sem_acento(str(row[cpr] or "")), _n(row[cv])
                if not v or v <= 0:
                    continue
                destino = ("TESOURO_SELIC" if "tesouro selic" in prod else
                           "TESOURO_IPCA" if re.search(r"tesouro (ipca|renda|educa)", prod) else
                           "TESOURO_PREFIXADO" if "tesouro prefixado" in prod else
                           "LCI_LCA" if re.search(r"\blc[ia]\b", prod) else
                           "CDB_CDI" if re.search(r"\b(cdb|rdb|lc)\b", prod) else None)
                if destino:
                    out["rf"][destino] = round(out["rf"].get(destino, 0) + v, 2)
                else:
                    out["ignorados"] += 1
            out["tipos"].append("renda_fixa" if "tesouro" not in aba_n else "tesouro")
    if not out["tipos"]:
        raise ValueError("Não reconheci a planilha. Na Área do Investidor da B3, baixe em Extratos a Posição, a "
                         "Movimentação ou a Negociação, no formato Excel.")
    out["movs"].sort(key=lambda x: x["data"])
    out["proventos"].sort(key=lambda x: x["data"])
    return out


def custo_medio(movs):
    """Quantidade e preço médio por ativo a partir das compras e vendas (vendas não mudam o preço médio;
    desdobramentos e bonificações mudam a quantidade, não o custo)."""
    q, custo = {}, {}
    for m in sorted(movs, key=lambda x: (x["data"], x["tipo"] != "compra")):
        t = m["ticker"]
        if m["tipo"] == "compra" and m.get("preco"):
            q[t] = q.get(t, 0) + m["qtd"]; custo[t] = custo.get(t, 0) + m["qtd"] * m["preco"]
        elif m["tipo"] == "venda":
            if q.get(t, 0) > 0:
                pm = custo[t] / q[t]
                vend = min(m["qtd"], q[t])
                q[t] -= vend; custo[t] -= pm * vend
                if q[t] <= 1e-9:
                    q[t], custo[t] = 0, 0
        elif m["tipo"] == "evento":
            q[t] = max(q.get(t, 0) + m["qtd"], 0)
    return {t: {"qtd": round(q[t], 6), "pm": round(custo[t] / q[t], 4) if q[t] > 0 else 0} for t in q}


# ---------------------------------------------------------------- rentabilidade

def _cdi_periodo(ini, fim, idx, cdi_atual):
    return acertos.cdi_periodo(ini, fim, idx, cdi_atual)


def _fator_rf(spec, ini, fim, idx_cdi, cdi_atual, imab=None):
    """Quanto um título de renda fixa rendeu entre duas datas (pós-fixado: CDI x fator; IPCA+: IMA-B 5+ como referência)."""
    if spec["tipo"] == "ipca" and imab is not None and len(imab) and imab.index[0] <= pd.Timestamp(ini):
        a, b = imab.asof(pd.Timestamp(ini)), imab.asof(pd.Timestamp(fim))
        if not pd.isna(a) and not pd.isna(b) and a > 0:
            return float(b / a)
    cdi = _cdi_periodo(ini, fim, idx_cdi, cdi_atual)
    return 1 + cdi * spec.get("fator", 1.0)


def _bench(ini, fim, idx_cdi, ibov, idx_ipca, cdi_atual):
    b = {"cdi": round(_cdi_periodo(ini, fim, idx_cdi, cdi_atual) * 100, 2)}
    if ibov is not None and len(ibov) and ibov.index[0] <= pd.Timestamp(ini):
        b["ibov"] = round((float(ibov.asof(pd.Timestamp(fim))) / float(ibov.asof(pd.Timestamp(ini))) - 1) * 100, 2)
    ip = _ipca_periodo(ini, fim, idx_ipca)
    b["ipca"] = round(ip * 100, 2) if ip is not None else None
    return b


def pct_cdi(ret, cdi):
    """"% do CDI" só faz sentido com rentabilidade positiva e CDI de pelo menos meio ponto no período."""
    return round(ret / cdi * 100) if cdi and cdi >= 0.5 and ret > 0 else None


JANELAS = [("1m", "1 mês", 1), ("3m", "3 meses", 3), ("6m", "6 meses", 6), ("12m", "12 meses", 12), ("24m", "24 meses", 24)]


def rentabilidade_atual(pos, specs, cdi_atual=10.0, hoje=None):
    """Carteira de hoje (mesmas quantidades e saldos) nas janelas de 1 a 24 meses e série semanal de 12 meses."""
    hoje = pd.Timestamp(hoje or date.today())
    mercado = [t for t, s in specs.items() if s["tipo"] == "mercado" and (pos.get(t) or {}).get("qtd", 0) > 0]
    rf = [t for t, s in specs.items() if s["tipo"] != "mercado" and (pos.get(t) or {}).get("saldo", 0) > 0]
    precos = sim.fechamentos_brl(sorted(set(mercado) | {"IBOV", "IMAB11"}))
    ibov, imab = precos.get("IBOV"), precos.get("IMAB11")
    idx_cdi, idx_ipca = acertos.cdi_mensal(), ipca_mensal()
    fora = [t for t in mercado if t not in precos]
    mercado = [t for t in mercado if t in precos]
    ult = {t: precos[t].index[-1] for t in mercado}
    fim = max([hoje.normalize()] + [d for d in ult.values()]) if mercado else hoje.normalize()

    def valor(t, d):  # valor do ativo na data d (R$)
        if t in specs and specs[t]["tipo"] != "mercado":
            return pos[t]["saldo"] / _fator_rf(specs[t], d, fim, idx_cdi, cdi_atual, imab)
        s = precos[t]
        if s.index[0] > d:
            return None
        return pos[t]["qtd"] * float(s.asof(d))

    periodos, por_ativo = [], {}
    for chave, rot, meses in JANELAS:
        ini = fim - pd.DateOffset(months=meses)
        v0 = v1 = 0.0
        faltam = []
        for t in mercado + rf:
            a, b = valor(t, ini), valor(t, fim)
            if a is None or b is None:
                faltam.append(t)
                continue
            v0 += a; v1 += b
            if chave == "12m":
                por_ativo[t] = {"ret": round((b / a - 1) * 100, 1), "ganho": round(b - a, 2)}
        if v0 <= 0:
            continue
        ret = (v1 / v0 - 1) * 100
        bch = _bench(ini, fim, idx_cdi, ibov, idx_ipca, cdi_atual)
        periodos.append({"chave": chave, "rotulo": rot, "carteira": round(ret, 2), **bch, "pct_cdi": pct_cdi(ret, bch["cdi"]),
                         "sem_historico": faltam})
    # série semanal de 12 meses (base 100) para o gráfico
    datas = pd.date_range(fim - pd.DateOffset(months=12), fim, freq="7D")
    base_ativos = [t for t in mercado + rf if valor(t, datas[0]) is not None]
    serie = {"datas": [], "carteira": [], "cdi": [], "ibov": []}
    if base_ativos:
        v_ini = sum(valor(t, datas[0]) for t in base_ativos)
        ib0 = float(ibov.asof(datas[0])) if ibov is not None and len(ibov) and ibov.index[0] <= datas[0] else None
        for d in list(datas) + ([fim] if datas[-1] < fim else []):
            serie["datas"].append(d.strftime("%Y-%m-%d"))
            serie["carteira"].append(round(sum(valor(t, d) for t in base_ativos) / v_ini * 100, 2))
            serie["cdi"].append(round((1 + _cdi_periodo(datas[0], d, idx_cdi, cdi_atual)) * 100, 2))
            serie["ibov"].append(round(float(ibov.asof(d)) / ib0 * 100, 2) if ib0 else None)
    total = sum(valor(t, fim) for t in mercado + rf)
    contrib = sorted(({"ticker": t, **v, "peso": round(valor(t, fim) / total * 100, 1) if total else 0} for t, v in por_ativo.items()),
                     key=lambda x: -x["ganho"])
    return {"modo": "atual", "periodos": periodos, "serie": serie, "por_ativo": contrib, "fora": fora,
            "ate": fim.strftime("%Y-%m-%d"), "cdi_real": idx_cdi is not None, "ipca_real": idx_ipca is not None}


def rentabilidade_historico(movs, cdi_atual=10.0, hoje=None):
    """Rentabilidade real da renda variável desde a primeira compra (Dietz modificado mensal, encadeado).
    As quantidades de antes de um desdobramento são convertidas pela tabela de desdobramentos do Yahoo, porque os preços
    ajustados também estão na unidade de hoje."""
    hoje = pd.Timestamp(hoje or date.today()).normalize()
    trades = [m for m in movs if m["tipo"] in ("compra", "venda")]
    if not trades:
        return None
    tickers = sorted({m["ticker"] for m in trades})
    precos = sim.fechamentos_brl(tickers + ["IBOV"])
    ibov = precos.pop("IBOV", None)
    split = {t: sim.desdobramentos(t) for t in tickers}
    fora = [t for t in tickers if t not in precos]

    def ajuste(t, d):  # fator para levar uma quantidade da data d para a unidade de hoje
        s = split.get(t)
        return float(s[s.index > pd.Timestamp(d)].prod()) if s is not None and len(s) else 1.0

    eventos = sorted(((pd.Timestamp(m["data"]), m["ticker"], (1 if m["tipo"] == "compra" else -1) * m["qtd"] * ajuste(m["ticker"], m["data"]))
                      for m in trades if m["ticker"] in precos), key=lambda x: x[0])
    if not eventos:
        return None
    ini = eventos[0][0]
    fins = list(pd.date_range(ini, hoje, freq="ME"))
    if not fins or fins[-1] < hoje:
        fins.append(hoje)
    h = {}
    k = 0

    def valor(d):
        return sum(q * float(precos[t].asof(d)) for t, q in h.items() if q > 1e-9 and precos[t].index[0] <= d)

    v_ant, d_ant = 0.0, ini - pd.Timedelta(days=1)
    indice, datas, rets = [100.0], [d_ant.strftime("%Y-%m-%d")], []
    for fm in fins:
        fluxo = fluxo_pond = 0.0
        dias = max((fm - d_ant).days, 1)
        while k < len(eventos) and eventos[k][0] <= fm:
            d, t, q = eventos[k]
            p = float(precos[t].asof(d)) if precos[t].index[0] <= d else None
            if p is not None:
                h[t] = h.get(t, 0) + q
                fluxo += q * p
                fluxo_pond += q * p * (fm - d).days / dias
            k += 1
        v = valor(fm)
        den = v_ant + fluxo_pond
        r = (v - v_ant - fluxo) / den if den > 0 else 0.0
        rets.append((fm, r))
        indice.append(indice[-1] * (1 + r))
        datas.append(fm.strftime("%Y-%m-%d"))
        v_ant, d_ant = v, fm
    idx_cdi, idx_ipca = acertos.cdi_mensal(), ipca_mensal()

    def acumulado(desde):
        x = 1.0
        for fm, r in rets:
            if fm > desde:
                x *= 1 + r
        return (x - 1) * 100

    periodos = []
    for chave, rot, meses in JANELAS[:4] + [("inicio", "Desde o início", None)]:
        desde = ini - pd.Timedelta(days=1) if meses is None else hoje - pd.DateOffset(months=meses)
        if meses is not None and desde < ini:
            continue
        ret = acumulado(desde)
        bch = _bench(max(desde, ini), hoje, idx_cdi, ibov, idx_ipca, cdi_atual)
        periodos.append({"chave": chave, "rotulo": rot, "carteira": round(ret, 2), **bch, "pct_cdi": pct_cdi(ret, bch["cdi"])})
    anos = (hoje - ini).days / 365.25
    cdi_serie = [round((1 + _cdi_periodo(ini, pd.Timestamp(d), idx_cdi, cdi_atual)) * 100, 2) for d in datas]
    ib0 = float(ibov.asof(ini)) if ibov is not None and len(ibov) and ibov.index[0] <= ini else None
    return {"modo": "historico", "desde": ini.strftime("%Y-%m-%d"), "periodos": periodos, "fora": fora,
            "ao_ano": round(((indice[-1] / 100) ** (1 / anos) - 1) * 100, 2) if anos >= 1 else None,
            "serie": {"datas": datas, "carteira": [round(x, 2) for x in indice], "cdi": cdi_serie,
                      "ibov": [round(float(ibov.asof(pd.Timestamp(d))) / ib0 * 100, 2) if ib0 else None for d in datas]},
            "valor_hoje": round(valor(hoje), 2), "ate": hoje.strftime("%Y-%m-%d"),
            "cdi_real": idx_cdi is not None, "ipca_real": idx_ipca is not None}


# ---------------------------------------------------------------- proventos

def proventos_estimados(pos, usd=None, hoje=None):
    """Proventos dos últimos 12 meses com as quantidades de hoje (pela data-com) e a projeção para os próximos 12."""
    hoje = pd.Timestamp(hoje or date.today())
    ini = hoje - pd.DateOffset(months=12)
    tickers = [t for t, p in pos.items() if (p or {}).get("qtd", 0) > 0]
    sim.baixar(tickers)
    por_mes, por_ativo = {}, []
    for t in tickers:
        dv = sim.dividendos(t)
        if dv is None or not len(dv):
            continue
        dv = dv[(dv.index > ini) & (dv.index <= hoje)]
        if not len(dv):
            continue
        fx = (usd or 0) if t in sim.EM_USD else 1
        if not fx:
            continue
        q, pm = pos[t]["qtd"], pos[t].get("pm") or 0
        total = float(dv.sum()) * q * fx
        for d, v in dv.items():
            k = d.strftime("%Y-%m")
            por_mes[k] = por_mes.get(k, 0) + float(v) * q * fx
        preco = sim.ultimo_preco(t)
        por_ativo.append({"ticker": t, "valor": round(total, 2), "por_cota": round(float(dv.sum()), 4), "pagamentos": int(len(dv)),
                          "yoc": round(float(dv.sum()) / pm * 100, 2) if pm else None,
                          "dy": round(float(dv.sum()) / preco * 100, 2) if preco else None})
    total = sum(x["valor"] for x in por_ativo)
    meses = [(hoje - pd.DateOffset(months=k)).strftime("%Y-%m") for k in range(11, -1, -1)]
    return {"fonte": "estimado", "total_12m": round(total, 2), "media_mensal": round(total / 12, 2), "projecao_12m": round(total, 2),
            "por_mes": [{"mes": m, "valor": round(por_mes.get(m, 0), 2)} for m in meses],
            "por_ativo": sorted(por_ativo, key=lambda x: -x["valor"])}


def proventos_b3(lista, pos, hoje=None):
    """Proventos que caíram na conta (planilha de Movimentação da B3)."""
    hoje = pd.Timestamp(hoje or date.today())
    ini = hoje - pd.DateOffset(months=12)
    meses = [(hoje - pd.DateOffset(months=k)).strftime("%Y-%m") for k in range(11, -1, -1)]
    por_mes, por_ativo, total_geral = {}, {}, 0.0
    for p in lista:
        d = pd.Timestamp(p["data"])
        total_geral += p["valor"]
        if ini < d <= hoje:
            por_mes[p["data"][:7]] = por_mes.get(p["data"][:7], 0) + p["valor"]
            a = por_ativo.setdefault(p["ticker"], {"ticker": p["ticker"], "valor": 0.0, "pagamentos": 0, "tipos": set()})
            a["valor"] += p["valor"]; a["pagamentos"] += 1; a["tipos"].add(p["tipo"])
    total = sum(por_mes.values())
    for a in por_ativo.values():
        pm, q = (pos.get(a["ticker"]) or {}).get("pm") or 0, (pos.get(a["ticker"]) or {}).get("qtd") or 0
        a["yoc"] = round(a["valor"] / (pm * q) * 100, 2) if pm and q else None
        a["valor"] = round(a["valor"], 2); a["tipos"] = sorted(a["tipos"])
    est = proventos_estimados(pos, hoje=hoje)
    return {"fonte": "b3", "total_12m": round(total, 2), "media_mensal": round(total / 12, 2), "total_desde_inicio": round(total_geral, 2),
            "desde": lista[0]["data"] if lista else None, "projecao_12m": est["projecao_12m"],
            "por_mes": [{"mes": m, "valor": round(por_mes.get(m, 0), 2)} for m in meses],
            "por_ativo": sorted(por_ativo.values(), key=lambda x: -x["valor"])}


# ---------------------------------------------------------------- agenda de proventos (próximos pagamentos estimados)

def agenda(pos, hoje=None, excluir=frozenset()):
    """Para cada ação ou FII com quantidade: os proventos dos últimos 12 meses (data-com e valor por cota, do Yahoo) e a
    próxima data-com ESTIMADA pelo intervalo de costume, com o valor do último pagamento. É estimativa pelo histórico:
    a empresa ou o fundo é que anuncia a data e o valor de verdade."""
    hoje = pd.Timestamp(hoje or date.today())
    out = []
    for t, p in pos.items():
        q = float((p or {}).get("qtd") or 0)
        if q <= 0 or t in excluir:
            continue
        dv = sim.dividendos(t)
        if dv is None or not len(dv):
            continue
        dv = dv[dv.index <= hoje]
        ult12 = dv[dv.index > hoje - pd.DateOffset(years=1)]
        if not len(ult12):
            continue
        datas = list(dv.index[-13:])
        gaps = [(b - a).days for a, b in zip(datas, datas[1:])]
        intervalo = int(np.median(gaps)) if gaps else 365
        intervalo = 30 if intervalo < 45 else 91 if intervalo < 120 else 182 if intervalo < 250 else 365
        prox = dv.index[-1] + pd.Timedelta(days=intervalo)
        while prox < hoje:
            prox += pd.Timedelta(days=intervalo)
        ultimo = float(dv.iloc[-1])
        out.append({"ticker": t, "qtd": q, "frequencia": {30: "mensal", 91: "trimestral", 182: "semestral", 365: "anual"}[intervalo],
                    "pagamentos_12m": [{"data_com": d.strftime("%Y-%m-%d"), "por_cota": round(float(v), 4), "total": round(float(v) * q, 2)}
                                       for d, v in ult12.items()][::-1],
                    "total_12m": round(float(ult12.sum()) * q, 2),
                    "proxima_estimada": prox.strftime("%Y-%m-%d"), "valor_estimado": round(ultimo * q, 2), "ultimo_por_cota": round(ultimo, 4)})
    out.sort(key=lambda x: x["proxima_estimada"])
    total_mes = {}
    for x in out:
        passo = {"mensal": 1, "trimestral": 3, "semestral": 6, "anual": 12}[x["frequencia"]]
        for k in range(12):  # projeção de 12 meses pelo costume (um pagamento por mês, a cada trimestre...)
            d = pd.Timestamp(x["proxima_estimada"]) + pd.DateOffset(months=passo * k)
            if d > hoje + pd.DateOffset(years=1):
                break
            total_mes[d.strftime("%Y-%m")] = round(total_mes.get(d.strftime("%Y-%m"), 0) + x["valor_estimado"], 2)
    return {"ativos": out, "proximos_meses": dict(sorted(total_mes.items())),
            "total_12m": round(sum(x["total_12m"] for x in out), 2)}
