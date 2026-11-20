"""Avisos: central de avisos por usuário, deduplicação e envio de notificações push (Web Push com VAPID).

As regras que decidem QUANDO avisar (sinal de compra/venda, alvo/stop, alerta de preço, rebalanceamento, conta a
vencer) ficam em server.py, em verificar_avisos(), porque usam as cotações e o motor de regras.
"""
import base64, json, os, threading, time, uuid

import armazem

_lock = threading.Lock()
MAX_AVISOS = 100
CFG_PADRAO = {"sinais": True, "alvo_stop": True, "recomendados": True, "rebalancear": True, "contas": True, "contas_dias": 3, "precos": []}


def atualizar(col, uid, padrao, fn):
    """Lê, altera e grava um documento do usuário sem perder alterações simultâneas."""
    with _lock:
        d = armazem.ler(col, uid)
        dados = json.loads(json.dumps(d["dados"])) if d else json.loads(json.dumps(padrao))
        r = fn(dados)
        armazem.gravar(col, uid, dados)
        return r if r is not None else dados


def config(uid):
    d = armazem.ler("avisos_cfg", uid)
    return {**CFG_PADRAO, **(d["dados"] if d else {})}


def estado(uid):
    d = armazem.ler("avisos_estado", uid)
    return d["dados"] if d else {"sinal": {}, "enviados": {}, "verificado": 0}


def lista(uid):
    d = armazem.ler("avisos", uid)
    return d["dados"]["itens"] if d else []


def registrar(uid, tipo, titulo, texto, aba="resumo", push=True):
    """Guarda o aviso na central do usuário e manda push para os aparelhos inscritos."""
    item = {"id": uuid.uuid4().hex[:12], "tipo": tipo, "titulo": titulo[:120], "texto": texto[:400], "aba": aba,
            "quando": time.time(), "lido": False}
    atualizar("avisos", uid, {"itens": []}, lambda d: d.update(itens=([item] + d["itens"])[:MAX_AVISOS]))
    if push:
        enviar_push(uid, titulo, texto, aba)
    return item


# ---------------------------------------------------------------- Web Push

def _b64url(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


_vapid = None


def vapid():
    """Chave VAPID do servidor: das variáveis VAPID_CHAVE_PRIVADA (PEM) ou gerada uma vez e guardada no armazenamento."""
    global _vapid
    if _vapid: return _vapid
    from cryptography.hazmat.primitives import serialization
    from py_vapid import Vapid
    pem = os.getenv("VAPID_CHAVE_PRIVADA", "").replace("\\n", "\n")
    if not pem:
        d = armazem.ler("config", "vapid")
        if d:
            pem = d["dados"]["privada"]
        else:
            v = Vapid(); v.generate_keys()
            pem = v.private_pem().decode()
            armazem.gravar("config", "vapid", {"privada": pem})
    v = Vapid.from_pem(pem.encode())
    publica = _b64url(v.public_key.public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint))
    _vapid = (v, publica)
    return _vapid


def inscrever(uid, sub):
    def f(d):
        d["subs"] = [s for s in d["subs"] if s.get("endpoint") != sub["endpoint"]][-9:] + [sub]
    atualizar("push", uid, {"subs": []}, f)


def cancelar(uid, endpoint):
    atualizar("push", uid, {"subs": []}, lambda d: d.update(subs=[s for s in d["subs"] if s.get("endpoint") != endpoint]))


def enviar_push(uid, titulo, texto, aba="resumo"):
    """Envia para todos os aparelhos do usuário. Inscrições que o serviço de push diz não existirem mais são removidas."""
    d = armazem.ler("push", uid)
    subs = d["dados"]["subs"] if d else []
    if not subs: return 0
    try:
        from pywebpush import WebPushException, webpush
        v, _ = vapid()
    except Exception as e:
        print("push indisponível:", repr(e), flush=True)
        return 0
    contato = os.getenv("VAPID_CONTATO", "mailto:avisos@assistente-financeiro.app")
    enviados, mortos = 0, []
    for s in subs:
        try:
            webpush(s, json.dumps({"titulo": titulo, "texto": texto, "aba": aba}, ensure_ascii=False),
                    vapid_private_key=v, vapid_claims={"sub": contato}, ttl=86400, timeout=10)
            enviados += 1
        except WebPushException as e:
            if getattr(e, "response", None) is not None and e.response.status_code in (404, 410):
                mortos.append(s["endpoint"])
            else:
                print("falha no push:", repr(e)[:200], flush=True)
        except Exception as e:
            print("falha no push:", repr(e)[:200], flush=True)
    for ep in mortos:
        cancelar(uid, ep)
    return enviados
