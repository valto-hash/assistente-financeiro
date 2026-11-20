"""Contas de acesso: cadastro, login, sessões e exclusão.

- Senhas: scrypt com sal aleatório (nunca guardadas em texto).
- Sessões: token aleatório entregue ao aparelho; o servidor guarda só o hash dele, com validade.
- Cadastro exige o código de convite (CODIGO_CONVITE, ou a antiga senha APP_TOKEN), para que só as pessoas
  convidadas usem o app e a chave de IA de quem o hospeda.
"""
import hashlib, hmac, os, re, secrets, time, uuid

import armazem

SESSAO_DIAS = 180
COLECOES_DO_USUARIO = ["carteira", "contas", "avisos", "avisos_cfg", "avisos_estado", "niveis", "push"]
EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,190}\.[A-Za-z]{2,}$")


class ConviteInvalido(ValueError):
    pass


def convite():
    return os.getenv("CODIGO_CONVITE") or os.getenv("APP_TOKEN", "")


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


def cadastrar(nome, email, senha, codigo):
    """Cria a conta e devolve o id. Levanta ValueError com uma mensagem para a pessoa se algo estiver errado."""
    nome, email = " ".join((nome or "").split())[:80], normalizar_email(email)
    exigido = convite()
    if exigido and not hmac.compare_digest((codigo or "").strip().encode(), exigido.encode()):
        raise ConviteInvalido("Código de convite incorreto. Peça o código a quem administra o app.")
    if len(nome) < 2:
        raise ValueError("Informe seu nome.")
    if not EMAIL.match(email):
        raise ValueError("Informe um e-mail válido.")
    if len(senha or "") < 8:
        raise ValueError("A senha precisa ter pelo menos 8 caracteres.")
    uid = uuid.uuid4().hex
    primeiro = not armazem.listar("usuario")
    if not armazem.criar("email", email, {"uid": uid}):
        raise ValueError("Já existe uma conta com este e-mail. Use “Entrar”.")
    armazem.gravar("usuario", uid, {"nome": nome, "email": email, "senha": hash_senha(senha), "criado": time.time()})
    if primeiro:  # a primeira conta herda a carteira da época em que o app era de uma pessoa só
        armazem.migrar_legado(uid)
    return uid


def entrar(email, senha):
    """Devolve o id do usuário se e-mail e senha conferem; senão None (sem dizer qual dos dois errou)."""
    idx = armazem.ler("email", normalizar_email(email))
    u = armazem.ler("usuario", idx["dados"]["uid"]) if idx else None
    if not u:
        hash_senha(senha or "x")  # mesmo tempo de resposta quando o e-mail não existe
        return None
    return u["id"] if conferir_senha(senha or "", u["dados"]["senha"]) else None


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


def publico(uid):
    u = armazem.ler("usuario", uid)
    return {"id": uid, "nome": u["dados"]["nome"], "email": u["dados"]["email"]} if u else None


def trocar_senha(uid, atual, nova):
    u = armazem.ler("usuario", uid)
    if not u or not conferir_senha(atual or "", u["dados"]["senha"]):
        raise ValueError("Senha atual incorreta.")
    if len(nova or "") < 8:
        raise ValueError("A nova senha precisa ter pelo menos 8 caracteres.")
    armazem.gravar("usuario", uid, {**u["dados"], "senha": hash_senha(nova)})


def excluir(uid):
    """Apaga a conta e todos os dados dela (carteira, contas, avisos, sessões)."""
    u = armazem.ler("usuario", uid)
    if not u:
        return
    for col in COLECOES_DO_USUARIO:
        armazem.apagar(col, uid)
    for h, d in armazem.listar("sessao"):
        if d.get("uid") == uid:
            armazem.apagar("sessao", h)
    armazem.apagar("email", u["dados"]["email"])
    armazem.apagar("usuario", uid)
