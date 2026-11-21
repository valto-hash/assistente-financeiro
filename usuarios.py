"""Contas de acesso: cadastro (e-mail e senha ou conta Google), login, sessões, recuperação de senha e exclusão.

- Senhas: scrypt com sal aleatório (nunca guardadas em texto). Contas criadas pelo Google podem não ter senha.
- Sessões: token aleatório entregue ao aparelho; o servidor guarda só o hash dele, com validade.
- Cadastro pode exigir um código de convite (CODIGO_CONVITE, ou a antiga senha APP_TOKEN). Sem nenhum dos dois,
  qualquer pessoa cria conta (o normal para um app publicado na loja).
- Se o servidor perder os dados (ex.: hospedagem sem disco permanente), a pessoa recria a conta com o mesmo e-mail
  e o aparelho informa o id antigo: a conta volta com o mesmo id e o app reenvia a cópia guardada no aparelho.
"""
import hashlib, hmac, os, re, secrets, time, uuid

import armazem

SESSAO_DIAS = 180
COLECOES_DO_USUARIO = ["carteira", "contas", "financas", "avisos", "avisos_cfg", "avisos_estado", "niveis", "push",
                       "perfil_teste", "plano"]
EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,190}\.[A-Za-z]{2,}$")
UID = re.compile(r"^[0-9a-f]{32}$")
CODIGO_VALIDADE = 30 * 60
CODIGO_TENTATIVAS = 5


class ConviteInvalido(ValueError):
    pass


def convite():
    return os.getenv("CODIGO_CONVITE") or os.getenv("APP_TOKEN", "")


def admins():
    return {normalizar_email(e) for e in os.getenv("ADMIN_EMAILS", "").split(",") if e.strip()}


def hash_senha(senha, sal=None):
    sal = sal or secrets.token_bytes(16)
    h = hashlib.scrypt(senha.encode(), salt=sal, n=2 ** 14, r=8, p=1, dklen=32)
    return f"scrypt${sal.hex()}${h.hex()}"


def conferir_senha(senha, guardado):
    try:
        _, sal, h = guardado.split("$")
        return hmac.compare_digest(hash_senha(senha, bytes.fromhex(sal)).split("$")[2], h)
    except (ValueError, AttributeError):
        return False


def normalizar_email(e):
    return (e or "").strip().lower()


def _conferir_convite(codigo):
    exigido = convite()
    if exigido and not hmac.compare_digest((codigo or "").strip().encode(), exigido.encode()):
        raise ConviteInvalido("Código de convite incorreto. Peça o código a quem administra o app.")


def _novo_uid(uid_anterior):
    """Id da conta nova. Se o aparelho informa o id de uma conta que o servidor não tem mais, reaproveita esse id."""
    if uid_anterior and UID.match(uid_anterior) and not armazem.ler("usuario", uid_anterior):
        return uid_anterior
    return uuid.uuid4().hex


def _reservar_email(email, uid):
    """Índice de e-mail único. Um índice que aponta para uma conta que não existe mais é substituído."""
    if armazem.criar("email", email, {"uid": uid}):
        return True
    idx = armazem.ler("email", email)
    if idx and not armazem.ler("usuario", idx["dados"]["uid"]):
        armazem.gravar("email", email, {"uid": uid})
        return True
    return False


def cadastrar(nome, email, senha, codigo, uid_anterior=None):
    """Cria a conta e devolve o id. Levanta ValueError com uma mensagem para a pessoa se algo estiver errado."""
    nome, email = " ".join((nome or "").split())[:80], normalizar_email(email)
    _conferir_convite(codigo)
    if len(nome) < 2:
        raise ValueError("Informe seu nome.")
    if not EMAIL.match(email):
        raise ValueError("Informe um e-mail válido.")
    if len(senha or "") < 8:
        raise ValueError("A senha precisa ter pelo menos 8 caracteres.")
    uid = _novo_uid(uid_anterior)
    primeiro = not armazem.listar("usuario")
    if not _reservar_email(email, uid):
        raise ValueError("Já existe uma conta com este e-mail. Use “Entrar”.")
    armazem.gravar("usuario", uid, {"nome": nome, "email": email, "senha": hash_senha(senha), "criado": time.time()})
    if primeiro:  # a primeira conta herda a carteira da época em que o app era de uma pessoa só
        armazem.migrar_legado(uid)
    return uid


def entrar(email, senha):
    """Devolve o id do usuário se e-mail e senha conferem; senão None (sem dizer qual dos dois errou)."""
    idx = armazem.ler("email", normalizar_email(email))
    u = armazem.ler("usuario", idx["dados"]["uid"]) if idx else None
    if not u or not u["dados"].get("senha"):
        hash_senha(senha or "x")  # mesmo tempo de resposta quando o e-mail não existe
        return None
    return u["id"] if conferir_senha(senha or "", u["dados"]["senha"]) else None


def entrar_google(info, codigo="", uid_anterior=None):
    """Login com uma conta Google já verificada (claims do ID token). Devolve (uid, conta_nova).
    Conta existente com o mesmo e-mail é vinculada ao Google (o Google confirmou que o e-mail é da pessoa)."""
    sub, email = str(info.get("sub") or ""), normalizar_email(info.get("email"))
    if not sub or not info.get("email_verified") or not EMAIL.match(email):
        raise ValueError("Sua conta Google não tem um e-mail verificado.")
    g = armazem.ler("google", sub)
    if g and armazem.ler("usuario", g["dados"]["uid"]):
        return g["dados"]["uid"], False
    idx = armazem.ler("email", email)
    u = armazem.ler("usuario", idx["dados"]["uid"]) if idx else None
    if u:
        armazem.gravar("usuario", u["id"], {**u["dados"], "google": sub})
        armazem.gravar("google", sub, {"uid": u["id"]})
        return u["id"], False
    _conferir_convite(codigo)
    nome = " ".join(str(info.get("name") or email.split("@")[0]).split())[:80]
    uid = _novo_uid(uid_anterior)
    primeiro = not armazem.listar("usuario")
    if not _reservar_email(email, uid):
        raise ValueError("Não consegui criar a conta agora. Tente de novo.")
    armazem.gravar("usuario", uid, {"nome": nome, "email": email, "senha": None, "google": sub, "criado": time.time()})
    armazem.gravar("google", sub, {"uid": uid})
    if primeiro:
        armazem.migrar_legado(uid)
    return uid, True


def _hash_token(token):
    return hashlib.sha256(token.encode()).hexdigest()


def criar_sessao(uid):
    token = secrets.token_urlsafe(32)
    armazem.gravar("sessao", _hash_token(token), {"uid": uid, "expira": time.time() + SESSAO_DIAS * 86400})
    return token


def sessao_uid(token):
    if not token or len(token) > 200:
        return None
    s = armazem.ler("sessao", _hash_token(token))
    if not s or s["dados"].get("expira", 0) < time.time():
        return None
    return s["dados"]["uid"] if armazem.ler("usuario", s["dados"]["uid"]) else None


def encerrar_sessao(token):
    armazem.apagar("sessao", _hash_token(token))


def encerrar_todas(uid, exceto=None):
    for h, d in armazem.listar("sessao"):
        if d.get("uid") == uid and h != exceto:
            armazem.apagar("sessao", h)


def eh_admin(uid):
    u = armazem.ler("usuario", uid)
    return bool(u and u["dados"]["email"] in admins())


def publico(uid):
    u = armazem.ler("usuario", uid)
    if not u:
        return None
    d = u["dados"]
    return {"id": uid, "nome": d["nome"], "email": d["email"], "google": bool(d.get("google")),
            "tem_senha": bool(d.get("senha")), "admin": d["email"] in admins(), "criado": d.get("criado")}


def trocar_senha(uid, atual, nova):
    """Troca a senha. Conta criada pelo Google, sem senha, pode definir uma sem informar a atual."""
    u = armazem.ler("usuario", uid)
    if not u:
        raise ValueError("Conta não encontrada.")
    if u["dados"].get("senha") and not conferir_senha(atual or "", u["dados"]["senha"]):
        raise ValueError("Senha atual incorreta.")
    if len(nova or "") < 8:
        raise ValueError("A nova senha precisa ter pelo menos 8 caracteres.")
    armazem.gravar("usuario", uid, {**u["dados"], "senha": hash_senha(nova)})


def confirmar_exclusao(uid, senha):
    """Quem tem senha confirma com ela; conta só do Google confirma digitando EXCLUIR."""
    u = armazem.ler("usuario", uid)
    if not u:
        return False
    if u["dados"].get("senha"):
        return conferir_senha(senha or "", u["dados"]["senha"])
    return (senha or "").strip().upper() == "EXCLUIR"


# ---------------------------------------------------------------- esqueci minha senha (código por e-mail)

def _hash_codigo(email, codigo):
    return hashlib.sha256(f"{email}:{codigo}".encode()).hexdigest()


def pedir_codigo(email):
    """Gera um código de 6 dígitos válido por 30 minutos. Devolve (codigo, nome) ou None se o e-mail não tem conta."""
    email = normalizar_email(email)
    idx = armazem.ler("email", email)
    u = armazem.ler("usuario", idx["dados"]["uid"]) if idx else None
    if not u:
        return None
    codigo = f"{secrets.randbelow(10 ** 6):06d}"
    armazem.gravar("recuperacao", email, {"hash": _hash_codigo(email, codigo), "expira": time.time() + CODIGO_VALIDADE,
                                          "tentativas": 0})
    return codigo, u["dados"]["nome"]


def redefinir_senha(email, codigo, nova):
    """Confere o código e troca a senha; encerra as sessões abertas. Devolve o uid."""
    email = normalizar_email(email)
    r = armazem.ler("recuperacao", email)
    d = r["dados"] if r else None
    if not d or d["expira"] < time.time() or d["tentativas"] >= CODIGO_TENTATIVAS:
        raise ValueError("Código vencido. Peça um novo.")
    if not hmac.compare_digest(d["hash"], _hash_codigo(email, (codigo or "").strip())):
        armazem.gravar("recuperacao", email, {**d, "tentativas": d["tentativas"] + 1})
        raise ValueError("Código incorreto.")
    if len(nova or "") < 8:
        raise ValueError("A nova senha precisa ter pelo menos 8 caracteres.")
    idx = armazem.ler("email", email)
    u = armazem.ler("usuario", idx["dados"]["uid"]) if idx else None
    if not u:
        raise ValueError("Conta não encontrada.")
    armazem.gravar("usuario", u["id"], {**u["dados"], "senha": hash_senha(nova)})
    armazem.apagar("recuperacao", email)
    encerrar_todas(u["id"])
    return u["id"]


def excluir(uid):
    """Apaga a conta e todos os dados dela (carteira, contas, avisos, plano, sessões)."""
    u = armazem.ler("usuario", uid)
    if not u:
        return
    for col in COLECOES_DO_USUARIO:
        armazem.apagar(col, uid)
    encerrar_todas(uid)
    if u["dados"].get("google"):
        armazem.apagar("google", u["dados"]["google"])
    armazem.apagar("recuperacao", u["dados"]["email"])
    armazem.apagar("email", u["dados"]["email"])
    armazem.apagar("usuario", uid)
