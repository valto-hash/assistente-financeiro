"""Confere se os números citados nos textos da IA existem nos dados que o app calculou ou recebeu.

A IA escreve explicações; os números (preços, rendimentos, pesos, valores) vêm do código. Se um texto da IA citar um
número que não está nos dados (um "número inventado"), o texto é trocado pela explicação calculada pelas regras.
"""
import re

_NUM = re.compile(r"(?<![\w])-?(?:\d{1,3}(?:\.\d{3})+(?:,\d+)?|\d+(?:[.,]\d+)?)(?![\w])")
_MULT = re.compile(r"\s*(mil\b|milh(?:ão|ões|ao|oes)\b|mi\b|bilh(?:ão|ões|ao|oes)\b|bi\b)", re.I)
# números de regras gerais que a IA pode citar sem estarem nos dados (limites, IR, FGC, prazos comuns)
PERMITIDOS = {0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 15, 17.5, 18, 20, 22.5, 24, 25, 30, 36, 40, 50, 60, 70, 100, 180, 200, 250,
              360, 365, 1000, 20000, 250000}


def _valor(t):
    """Valor e número de casas decimais escritas ("1.234,56" -> 1234.56 com 2 casas; "12,3" -> 12.3 com 1)."""
    t = t.strip()
    if re.fullmatch(r"-?\d{1,3}(?:\.\d{3})+(?:,\d+)?", t):  # 1.234,56
        dec = t.split(",")[1] if "," in t else ""
        return float(t.replace(".", "").replace(",", ".")), len(dec)
    dec = re.split(r"[.,]", t)[1] if re.search(r"[.,]", t) else ""
    return float(t.replace(",", ".")), len(dec)


def _achados(texto, crus=False):
    """(valor, tolerância) de cada número do texto. A tolerância é a do arredondamento escrito: "12,3" aceita de 12,25 a
    12,35; "R$ 150 mil" aceita de 149,5 mil a 150,5 mil. Valores inteiros a partir de 100 aceitam 1% (ex.: "R$ 3.200"
    para 3.187), porque costumam ser arredondados."""
    out = []
    texto = texto or ""
    for m in _NUM.finditer(texto):
        try:
            v, casas = _valor(m.group(0))
        except ValueError:
            continue
        f = 1.0
        mult = _MULT.match(texto, m.end())
        if mult:
            w = mult.group(1).lower()
            f = 1e3 if w == "mil" else 1e9 if w.startswith("bi") else 1e6
            if crus: out.append((v, 0.5 * 10 ** -casas))
        tol = 0.5 * 10 ** -casas * f
        if casas == 0 and abs(v * f) >= 100: tol = max(tol, abs(v * f) * 0.01)
        out.append((v * f, tol))
    return out


def numeros(texto, crus=False):
    """Números citados no texto ("R$ 150 mil" vira 150000; com crus=True devolve também o 150)."""
    return [v for v, _ in _achados(texto, crus)]


def conhecidos(*fontes):
    """Todos os números presentes nos dados (inclusive dentro de textos como manchetes e fatos)."""
    vistos = set()

    def visitar(x):
        if isinstance(x, bool) or x is None:
            return
        if isinstance(x, (int, float)):
            vistos.add(abs(float(x)))
        elif isinstance(x, str):
            vistos.update(abs(v) for v in numeros(x, crus=True))
        elif isinstance(x, dict):
            for k, v in x.items():
                if k != "serie": visitar(v)  # a série de preços diária não conta (tem números demais)
        elif isinstance(x, (list, tuple, set)):
            for v in x: visitar(v)
    for f in fontes:
        visitar(f)
    return vistos


def suspeitos(texto, base):
    """Números do texto que não correspondem (pelo arredondamento escrito) a nenhum número dos dados."""
    ruins = []
    for n, tol in _achados(texto):
        a = abs(n)
        if a in PERMITIDOS or (1990 <= a <= 2045 and a == int(a)):
            continue
        if any(abs(a - k) <= tol + 1e-9 for k in base):
            continue
        ruins.append(n)
    return ruins


class Conferencia:
    """Acumula o resultado da checagem de vários textos de uma resposta."""
    def __init__(self, *fontes):
        self.base = conhecidos(*fontes)
        self.textos = 0
        self.trocados = []

    def ok(self, texto, onde=""):
        if not texto:
            return True
        self.textos += 1
        r = suspeitos(texto, self.base)
        if r:
            self.trocados.append({"onde": onde, "numeros": r[:3]})
        return not r

    def resumo(self):
        return {"textos": self.textos, "trocados": len(self.trocados), "detalhes": self.trocados[:5]}
