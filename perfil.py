"""Teste de perfil de investidor e objetivos, feito ao criar a conta (e refeito quando a pessoa quiser).

Segue a lógica da verificação de adequação (suitability): o perfil sai da TOLERÂNCIA a perdas (o que a pessoa faria
numa queda, o que prefere, quanto a perda mudaria a vida dela, experiência) e é LIMITADO pela CAPACIDADE de correr
risco (prazo, reserva de emergência, idade). O objetivo vira um texto que o resto do app já entende
("Aposentadoria em 25 anos, juntar R$ 1.000.000, investindo R$ 1.500 por mês").
"""
from regras import brl

# Cada tipo de investidor, reformulado em 24/11/2026. "limite" é a maior queda que a carteira recomendada pode ter tido
# em qualquer momento: dia a dia de 2013 até hoje (corretora simulada), mês a mês (simulador) e na pior crise real
# testada (2008, 2015, 2020...). "rf_min" é a parte mínima em renda fixa (rodada 4 de ferramentas/refinar_perfis.py: sem
# ela, a busca deixava moderado e arrojado iguais, com 85% em risco). O servidor usa os dois em tudo.
DEFINICOES = {
    "conservador": {"nome": "Conservador", "limite": 8, "rf_min": 70,
                    "curto": "Prioriza não perder dinheiro: pelo menos 70% em renda fixa e quedas de no máximo 8% no caminho.",
                    "para_quem": "Para quem pode precisar do dinheiro em pouco tempo, ainda está montando a reserva de emergência "
                                 "ou não ficaria tranquilo vendo o dinheiro cair."},
    "moderado": {"nome": "Moderado", "limite": 18, "rf_min": 40,
                 "curto": "Equilíbrio entre segurança e crescimento: pelo menos 40% em renda fixa e quedas de até 18% no caminho.",
                 "para_quem": "Para quem investe por alguns anos, já tem reserva de emergência e aceita ver a carteira cair de "
                              "vez em quando em troca de render mais."},
    "arrojado": {"nome": "Arrojado", "limite": 30, "rf_min": 15,
                 "curto": "Busca o maior crescimento no longo prazo: pelo menos 15% em renda fixa e quedas de até 30% no caminho.",
                 "para_quem": "Para quem investe por muitos anos, tem a reserva de emergência completa e não precisaria vender "
                              "nada numa crise."}}
for _k, _d in DEFINICOES.items():
    _d["texto"] = (f"{_d['nome']}: {_d['curto'][0].lower() + _d['curto'][1:]} A carteira recomendada não pode ter caído mais de "
                   f"{_d['limite']}% em nenhum momento dos testes com dados reais (dia a dia desde 2013 e nas crises reais) e "
                   f"tem pelo menos {_d['rf_min']}% em renda fixa.")

PERGUNTAS = [
    {"id": "objetivo", "tipo": "escolha", "titulo": "Qual é o seu principal objetivo com os investimentos?", "opcoes": [
        {"v": "reserva", "t": "Montar minha reserva de emergência"},
        {"v": "imovel", "t": "Comprar um imóvel (ou dar a entrada)"},
        {"v": "carro", "t": "Comprar um carro"},
        {"v": "aposentadoria", "t": "Aposentadoria ou independência financeira"},
        {"v": "renda", "t": "Ter uma renda extra todo mês"},
        {"v": "educacao", "t": "Educação (minha ou dos filhos)"},
        {"v": "viagem", "t": "Uma viagem"},
        {"v": "crescer", "t": "Fazer o patrimônio crescer, sem data marcada"}]},
    {"id": "prazo", "tipo": "escolha", "titulo": "Em quanto tempo você vai precisar desse dinheiro?", "opcoes": [
        {"v": "ate1", "t": "Em menos de 1 ano"}, {"v": "1a3", "t": "De 1 a 3 anos"}, {"v": "3a5", "t": "De 3 a 5 anos"},
        {"v": "5a10", "t": "De 5 a 10 anos"}, {"v": "mais10", "t": "Daqui a mais de 10 anos"}]},
    {"id": "valores", "tipo": "valores", "titulo": "Quanto você quer juntar e quanto consegue investir?", "campos": [
        {"id": "meta", "t": "Quanto quer juntar (R$)", "opcional": True},
        {"id": "aporte", "t": "Quanto consegue investir por mês (R$)", "opcional": True},
        {"id": "renda", "t": "Sua renda mensal (R$)", "opcional": True, "dica": "Ajuda a calcular a reserva e a sobra do mês."}]},
    {"id": "idade", "tipo": "escolha", "titulo": "Qual a sua idade?", "opcoes": [
        {"v": "ate25", "t": "Até 25 anos"}, {"v": "25a34", "t": "De 25 a 34"}, {"v": "35a44", "t": "De 35 a 44"},
        {"v": "45a59", "t": "De 45 a 59"}, {"v": "60mais", "t": "60 anos ou mais"}]},
    {"id": "reserva", "tipo": "escolha", "titulo": "Você já tem uma reserva de emergência?", "opcoes": [
        {"v": "sim", "t": "Sim, cobre 6 meses ou mais dos meus gastos"},
        {"v": "parcial", "t": "Tenho, mas cobre menos de 6 meses"}, {"v": "nao", "t": "Ainda não"}]},
    {"id": "experiencia", "tipo": "varias", "titulo": "Em quais destes você já investiu?", "opcoes": [
        {"v": "poupanca", "t": "Poupança"}, {"v": "rendafixa", "t": "CDB, LCI ou Tesouro Direto"},
        {"v": "fundos", "t": "Fundos de investimento"}, {"v": "acoes", "t": "Ações ou fundos imobiliários"},
        {"v": "exterior", "t": "Investimentos no exterior"}, {"v": "nenhum", "t": "Nunca investi"}]},
    {"id": "queda", "tipo": "escolha", "titulo": "Seus investimentos caíram 20% em um mês. O que você faz?", "opcoes": [
        {"v": "vende_tudo", "t": "Vendo tudo para não perder mais"}, {"v": "vende_parte", "t": "Vendo uma parte"},
        {"v": "espera", "t": "Espero, porque sei que o mercado oscila"}, {"v": "compra_mais", "t": "Aproveito para comprar mais"}]},
    {"id": "frase", "tipo": "escolha", "titulo": "Qual frase combina mais com você?", "opcoes": [
        {"v": "seguranca", "t": "Prefiro não perder nada, mesmo ganhando pouco"},
        {"v": "equilibrio", "t": "Aceito pequenas perdas por um ganho um pouco maior"},
        {"v": "crescimento", "t": "Aceito oscilações grandes buscando ganhar mais no longo prazo"}]},
    {"id": "impacto", "tipo": "escolha", "titulo": "Se você perdesse 20% desse dinheiro, sua vida mudaria?", "opcoes": [
        {"v": "muito", "t": "Sim, muito"}, {"v": "um_pouco", "t": "Um pouco"}, {"v": "nada", "t": "Não mudaria"}]},
]

_PONTOS = {"queda": {"vende_tudo": 0, "vende_parte": 1, "espera": 2, "compra_mais": 3},
           "frase": {"seguranca": 0, "equilibrio": 2, "crescimento": 4},
           "impacto": {"muito": 0, "um_pouco": 1, "nada": 2}}
_PRAZO_ANOS = {"ate1": 1, "1a3": 2, "3a5": 4, "5a10": 7, "mais10": 15}
_ATE_65 = {"ate25": 42, "25a34": 35, "35a44": 25, "45a59": 13, "60mais": 5}
_OBJ = {"reserva": "Reserva de emergência", "imovel": "Comprar um imóvel", "carro": "Comprar um carro",
        "aposentadoria": "Aposentadoria", "renda": "Viver de renda (renda passiva todo mês)", "educacao": "Educação",
        "viagem": "Viagem", "crescer": "Fazer o patrimônio crescer no longo prazo"}
_ORDEM = ["conservador", "moderado", "arrojado"]


def _num(x):
    try:
        v = float(str(x).replace(".", "").replace(",", ".")) if isinstance(x, str) else float(x or 0)
    except (TypeError, ValueError):
        return 0.0
    return min(max(v, 0.0), 1e10)


def avaliar(r):
    """r: {objetivo, prazo, meta, aporte, renda, idade, reserva, experiencia: [..], queda, frase, impacto}."""
    validos = {p["id"]: {o["v"] for o in p.get("opcoes", [])} for p in PERGUNTAS}
    def esc(k, padrao):
        v = r.get(k)
        return v if v in validos.get(k, ()) else padrao
    objetivo, prazo, idade, reserva = esc("objetivo", "crescer"), esc("prazo", "5a10"), esc("idade", "35a44"), esc("reserva", "parcial")
    queda, frase, impacto = esc("queda", "espera"), esc("frase", "equilibrio"), esc("impacto", "um_pouco")
    exp = [x for x in (r.get("experiencia") or []) if x in validos["experiencia"]]
    meta, aporte, renda = _num(r.get("meta")), _num(r.get("aporte")), _num(r.get("renda"))

    tolerancia = _PONTOS["queda"][queda] + _PONTOS["frase"][frase] + _PONTOS["impacto"][impacto] \
        + min(sum(1 for x in exp if x in ("fundos", "acoes", "exterior")), 2)
    perfil = "conservador" if tolerancia <= 4 else "moderado" if tolerancia <= 7 else "arrojado"
    motivos = [f"Sua tolerância a perdas somou {tolerancia} de 11 pontos: perfil {perfil}."]

    teto = "arrojado"
    if objetivo == "reserva" or prazo == "ate1":
        teto = "conservador"
        motivos.append("O dinheiro tem uso em menos de 1 ano (ou é a reserva de emergência): só cabe risco baixo.")
    elif prazo == "1a3":
        teto = "moderado"
        motivos.append("Com prazo de 1 a 3 anos, não cabe o perfil arrojado.")
    if reserva == "nao" and teto == "arrojado":
        teto = "moderado"
        motivos.append("Sem reserva de emergência, uma queda pode obrigar você a vender no pior momento: no máximo moderado.")
    if idade == "60mais" and teto == "arrojado":
        teto = "moderado"
        motivos.append("Aos 60 anos ou mais, menos tempo para se recuperar de quedas: no máximo moderado.")
    if _ORDEM.index(perfil) > _ORDEM.index(teto):
        perfil = teto

    anos = _ATE_65[idade] if objetivo == "aposentadoria" and prazo == "mais10" else _PRAZO_ANOS[prazo]
    partes = [_OBJ[objetivo]] + ([] if objetivo == "reserva" else [f"em {anos} {'ano' if anos == 1 else 'anos'}"])
    if meta: partes.append(f"juntar {brl(meta, 0)}")
    if aporte: partes.append(f"investindo {brl(aporte, 0)} por mês")
    texto = ", ".join(partes) + "."

    atencao = []
    if reserva != "sim" and objetivo != "reserva":
        atencao.append("Monte (ou complete) a reserva de emergência antes de investir com mais risco: o app separa isso primeiro.")
    if "nenhum" in exp or not exp:
        atencao.append("Como você está começando, a carteira usa fundos e títulos amplos, que não dependem de uma única empresa.")
    if meta and aporte and anos:
        juntado = aporte * 12 * anos
        if juntado < meta * 0.5:
            atencao.append(f"Só com os aportes você junta cerca de {brl(juntado, 0)} em {anos} anos, metade da meta ou menos: "
                           "talvez seja preciso aumentar o aporte ou o prazo. A simulação mostra a chance real.")
    return {"perfil": perfil, "definicao": DEFINICOES[perfil], "tolerancia": tolerancia, "teto": teto, "objetivo_texto": texto, "prazo_anos": anos,
            "meta": meta, "aporte": aporte, "renda": renda, "reserva": reserva, "motivos": motivos, "atencao": atencao,
            "respostas": {"objetivo": objetivo, "prazo": prazo, "meta": meta, "aporte": aporte, "renda": renda, "idade": idade,
                          "reserva": reserva, "experiencia": exp, "queda": queda, "frase": frase, "impacto": impacto}}
