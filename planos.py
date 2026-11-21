"""Planos: Grátis (demonstração, com limites) e Premium (app completo).

De onde vem o Premium (vale o que terminar mais tarde):
- teste grátis: TESTE_GRATIS_DIAS dias (padrão 7) a partir do primeiro uso;
- Google Play Billing: assinatura comprada dentro do app Android (obrigatório para vender assinatura na Play Store);
- Mercado Pago: assinatura feita pelo site (fora do app da Play Store);
- código promocional: CODIGOS_PREMIUM="CODIGO:dias,OUTRO:30" (cada pessoa usa cada código uma vez);
- administradores (ADMIN_EMAILS) e ASSINATURA=nao (app de uso pessoal): sempre Premium;
- código mestre (CODIGO_MESTRE, só no servidor, nunca no código): acesso completo e sem prazo para quem digitar o código
  na opção escondida do app. Trocar o código no servidor tira o acesso de quem usou o código antigo.

A verificação das compras é sempre feita no servidor, consultando a Google ou o Mercado Pago: o aparelho nunca
decide sozinho que a pessoa é Premium.
"""
import base64, hashlib, hmac, json, os, time
from datetime import datetime

import requests

import armazem
import usuarios

GRATIS = {"ativos": 5, "contas": 5, "sim_anos": 10}
RECURSOS = {  # o que o Premium libera (para a tela de planos)
    "ia": "Análises com inteligência artificial (quando o servidor tem IA)",
    "ativos": "Ativos ilimitados (grátis: até 5)",
    "rebalancear": "Rebalanceamento com quantas cotas vender e comprar",
    "simulacao": "Simulação completa: até 30 anos, metas e cenários (grátis: até 10 anos)",
    "avisos": "Avisos de compra, venda, alvo, stop, preço e rebalanceamento",
    "contas": "Contas do mês ilimitadas (grátis: até 5), leitura de boleto em PDF/foto e de extrato",
}
PLAY_STATES_ATIVOS = {"SUBSCRIPTION_STATE_ACTIVE", "SUBSCRIPTION_STATE_IN_GRACE_PERIOD"}


def ligado():
    return os.getenv("ASSINATURA", "sim").strip().lower() not in ("nao", "não", "0", "false", "off", "desligado")


def precos():
    return {"mensal": float(os.getenv("PRECO_MENSAL", "14.90")), "anual": float(os.getenv("PRECO_ANUAL", "119.90"))}


def produtos_play():
    """IDs das assinaturas criadas no Play Console (Monetizar > Assinaturas)."""
    return {"mensal": os.getenv("PLAY_PRODUTO_MENSAL", "premium_mensal"), "anual": os.getenv("PLAY_PRODUTO_ANUAL", "premium_anual")}


def teste_dias():
    return max(int(os.getenv("TESTE_GRATIS_DIAS", "7")), 0)


def _doc(uid):
    d = armazem.ler("plano", uid)
    return d["dados"] if d else {}


def _atualizar(uid, fn):
    for _ in range(5):  # gravação otimista: refaz se outro pedido gravou no meio
        atual = armazem.ler("plano", uid)
        dados = dict(atual["dados"]) if atual else {}
        fn(dados)
        if armazem.gravar("plano", uid, dados, base=atual["versao"] if atual else 0):
            return dados
    raise RuntimeError("não consegui gravar o plano")


def estado(uid):
    """{"plano": "premium"|"gratis", "origem", "ate" (timestamp), "renova", "limites"}"""
    if not ligado():
        return {"plano": "premium", "origem": "livre", "ate": None, "renova": False, "limites": None}
    if usuarios.eh_admin(uid):
        return {"plano": "premium", "origem": "admin", "ate": None, "renova": False, "limites": None}
    d = _doc(uid)
    if d.get("mestre") and d["mestre"] == _hash_mestre():
        return {"plano": "premium", "origem": "acesso_completo", "ate": None, "renova": False, "limites": None}
    if "teste_inicio" not in d:  # o teste conta a partir do primeiro uso (inclusive de quem já tinha conta)
        d = _atualizar(uid, lambda x: x.setdefault("teste_inicio", time.time()))
    agora = time.time()
    ativas = [(f, x) for f, x in (d.get("fontes") or {}).items() if (x.get("ate") or 0) > agora]
    if ativas:
        f, x = max(ativas, key=lambda kv: kv[1]["ate"])
        return {"plano": "premium", "origem": f, "ate": x["ate"], "renova": bool(x.get("renova")), "limites": None}
    fim = d["teste_inicio"] + teste_dias() * 86400
    if agora < fim:
        return {"plano": "premium", "origem": "teste", "ate": fim, "renova": False, "limites": None}
    return {"plano": "gratis", "origem": None, "ate": None, "renova": False, "limites": GRATIS}


def premium(uid):
    return estado(uid)["plano"] == "premium"


def registrar(uid, fonte, ate, **extra):
    _atualizar(uid, lambda d: d.setdefault("fontes", {}).update({fonte: {"ate": ate, "atualizado": time.time(), **extra}}))


def resumo_publico(uid):
    e = estado(uid)
    d = _doc(uid)
    return {**e, "precos": precos(), "produtos_play": produtos_play(), "recursos": RECURSOS, "gratis": GRATIS,
            "mercadopago": bool(os.getenv("MERCADOPAGO_TOKEN")), "teste_dias": teste_dias(),
            "codigos": bool(os.getenv("CODIGOS_PREMIUM")), "assinatura_ligada": ligado(),
            "fontes": {f: {"ate": x.get("ate"), "renova": x.get("renova"), "produto": x.get("produto")}
                       for f, x in (d.get("fontes") or {}).items()}}


# ---------------------------------------------------------------- código mestre (acesso completo sem pagar)

def _hash_mestre():
    codigo = os.getenv("CODIGO_MESTRE", "").strip()
    return hashlib.sha256(("mestre:" + codigo).encode()).hexdigest() if len(codigo) >= 8 else None


def ativar_mestre(uid, codigo):
    """Libera o app completo, sem prazo, para quem sabe o CODIGO_MESTRE (mínimo de 8 caracteres)."""
    esperado = os.getenv("CODIGO_MESTRE", "").strip()
    if len(esperado) < 8 or not hmac.compare_digest((codigo or "").strip().encode(), esperado.encode()):
        raise ValueError("Código inválido.")
    h = _hash_mestre()
    _atualizar(uid, lambda d: d.update(mestre=h, mestre_quando=time.time()))
    return estado(uid)


# ---------------------------------------------------------------- código promocional

def resgatar_codigo(uid, codigo):
    codigo = (codigo or "").strip().upper()
    validos = {}
    for item in os.getenv("CODIGOS_PREMIUM", "").split(","):
        if ":" in item:
            c, dias = item.rsplit(":", 1)
            if c.strip() and dias.strip().isdigit():
                validos[c.strip().upper()] = int(dias)
    if codigo not in validos:
        raise ValueError("Código inválido.")
    d = _doc(uid)
    if codigo in (d.get("codigos_usados") or []):
        raise ValueError("Você já usou este código.")
    atual = (d.get("fontes") or {}).get("codigo", {}).get("ate") or 0
    ate = max(atual, time.time()) + validos[codigo] * 86400
    _atualizar(uid, lambda x: (x.setdefault("codigos_usados", []).append(codigo),
                               x.setdefault("fontes", {}).update({"codigo": {"ate": ate, "atualizado": time.time()}})))
    return ate


# ---------------------------------------------------------------- Google Play Billing (app Android / TWA)

def _credencial_google():
    """Conta de serviço com acesso ao Play Console (GOOGLE_PLAY_CONTA_SERVICO: o JSON ou o caminho do arquivo)."""
    from google.oauth2 import service_account
    import google.auth.transport.requests as gtr
    bruto = os.getenv("GOOGLE_PLAY_CONTA_SERVICO", "").strip()
    if not bruto:
        raise RuntimeError("Assinatura pelo Google Play não configurada no servidor (GOOGLE_PLAY_CONTA_SERVICO).")
    info = json.loads(bruto) if bruto.startswith("{") else json.load(open(bruto, encoding="utf-8"))
    cred = service_account.Credentials.from_service_account_info(info, scopes=["https://www.googleapis.com/auth/androidpublisher"])
    cred.refresh(gtr.Request())
    return cred.token


def _api_play(metodo, caminho, **kw):
    pacote = os.getenv("ANDROID_PACKAGE", "")
    if not pacote:
        raise RuntimeError("ANDROID_PACKAGE não configurado no servidor.")
    url = f"https://androidpublisher.googleapis.com/androidpublisher/v3/applications/{pacote}/{caminho}"
    r = requests.request(metodo, url, headers={"Authorization": "Bearer " + _credencial_google()}, timeout=20, **kw)
    if r.status_code >= 400:
        raise RuntimeError(f"Google Play respondeu {r.status_code}: {r.text[:200]}")
    return r.json() if r.content else {}


def _ts(iso):
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp() if iso else 0


def _chave_token(token):
    return hashlib.sha256(token.encode()).hexdigest()


def verificar_play(uid, token):
    """Consulta a compra no Google Play, confirma (acknowledge) se preciso e atualiza o plano. Devolve o estado."""
    token = (token or "").strip()
    if not token or len(token) > 2000:
        raise ValueError("Compra inválida.")
    dono = armazem.ler("play_token", _chave_token(token))
    if dono and dono["dados"]["uid"] != uid:
        raise ValueError("Esta assinatura já está ligada a outra conta do app.")
    j = _api_play("GET", f"purchases/subscriptionsv2/tokens/{token}")
    itens = j.get("lineItems") or []
    produto = itens[0].get("productId") if itens else None
    if produto not in produtos_play().values():
        raise ValueError("Produto desconhecido.")
    ate = max((_ts(i.get("expiryTime")) for i in itens), default=0)
    estado_play = j.get("subscriptionState", "")
    ativo = estado_play in PLAY_STATES_ATIVOS or (estado_play == "SUBSCRIPTION_STATE_CANCELED" and ate > time.time())
    if ativo and j.get("acknowledgementState") != "ACKNOWLEDGEMENT_STATE_ACKNOWLEDGED":
        _api_play("POST", f"purchases/subscriptions/{produto}/tokens/{token}:acknowledge", json={})  # sem isso a Google estorna em 3 dias
    armazem.gravar("play_token", _chave_token(token), {"uid": uid, "token": token})
    renova = bool(itens and (itens[0].get("autoRenewingPlan") or {}).get("autoRenewEnabled"))
    registrar(uid, "play", ate if ativo else min(ate, time.time()), produto=produto, estado=estado_play, renova=renova,
              token=_chave_token(token))
    return estado(uid)


def notificacao_play(corpo):
    """Notificação em tempo real do Google Play (Pub/Sub push): renovação, cancelamento, pausa, reembolso."""
    try:
        dados = json.loads(base64.b64decode(corpo["message"]["data"]))
    except (KeyError, ValueError, TypeError):
        return False
    token = (dados.get("subscriptionNotification") or {}).get("purchaseToken")
    if not token:
        return False  # notificação de teste ou de outro tipo
    dono = armazem.ler("play_token", _chave_token(token))
    if not dono:
        return False
    verificar_play(dono["dados"]["uid"], token)
    return True


# ---------------------------------------------------------------- Mercado Pago (assinatura pelo site)

def _mp(metodo, caminho, **kw):
    tok = os.getenv("MERCADOPAGO_TOKEN", "")
    if not tok:
        raise RuntimeError("Assinatura pelo Mercado Pago não configurada no servidor (MERCADOPAGO_TOKEN).")
    r = requests.request(metodo, "https://api.mercadopago.com" + caminho, timeout=20,
                         headers={"Authorization": "Bearer " + tok, "Content-Type": "application/json"}, **kw)
    if r.status_code >= 400:
        raise RuntimeError(f"Mercado Pago respondeu {r.status_code}: {r.text[:200]}")
    return r.json()


def criar_assinatura_mp(uid, periodo, url_retorno):
    """Cria a assinatura recorrente e devolve o link de pagamento do Mercado Pago."""
    if periodo not in ("mensal", "anual"):
        raise ValueError("Período inválido.")
    u = usuarios.publico(uid)
    corpo = {"reason": f"{os.getenv('APP_NOME', 'Assistente Financeiro')} Premium ({periodo})", "external_reference": uid,
             "payer_email": u["email"], "back_url": url_retorno, "status": "pending",
             "auto_recurring": {"frequency": 1 if periodo == "mensal" else 12, "frequency_type": "months",
                                "transaction_amount": precos()[periodo], "currency_id": "BRL"}}
    j = _mp("POST", "/preapproval", json=corpo)
    _atualizar(uid, lambda d: d.update(mp_id=j.get("id")))
    return j.get("init_point")


def atualizar_mp(preapproval_id):
    """Consulta a assinatura no Mercado Pago (nunca confia só no aviso recebido) e atualiza o plano da pessoa."""
    j = _mp("GET", f"/preapproval/{preapproval_id}")
    uid = j.get("external_reference")
    if not uid or not armazem.ler("usuario", uid):
        return None
    status = j.get("status")
    prox = _ts(j.get("next_payment_date")) if j.get("next_payment_date") else 0
    ate = (prox or time.time() + 31 * 86400) + 3 * 86400 if status == "authorized" else time.time()
    registrar(uid, "mercadopago", ate, renova=status == "authorized", estado=status, assinatura=preapproval_id)
    return uid


def conferir_mp(uid):
    d = _doc(uid)
    if d.get("mp_id"):
        try: atualizar_mp(d["mp_id"])
        except Exception as e: print("falha ao conferir assinatura do Mercado Pago:", repr(e)[:200], flush=True)
    return estado(uid)
