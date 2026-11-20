"""Armazena os dados do app: contas de acesso, sessões e, para cada usuário, carteira, contas a pagar e avisos.

Cada dado é um "documento" identificado por (coleção, id), com versão e data de atualização.
Dois modos, escolhidos por variáveis de ambiente:
- DATABASE_URL definido: PostgreSQL, tabela "docs" (recomendado em hospedagens cujo disco é apagado a cada deploy).
- Caso contrário: um arquivo JSON por documento em DATA_DIR (padrão ./dados): dados/<coleção>/<id>.json.
  Só é permanente se essa pasta estiver num disco persistente.

A versão permite gravação otimista: quem grava informa a versão em que se baseou; se outro aparelho gravou antes,
a gravação é recusada (conflito) em vez de sobrescrever em silêncio.
"""
import hashlib, json, os, re, tempfile, threading
from datetime import datetime, timezone

DATABASE_URL = os.getenv("DATABASE_URL", "")
DATA_DIR = os.getenv("DATA_DIR", "")
_lock = threading.RLock()
_criada = False


def modo():
    return "banco" if DATABASE_URL else "arquivo"


def persistente():
    """Banco de dados, ou uma pasta configurada de propósito (presumivelmente um volume), sobrevivem a novos deploys."""
    return bool(DATABASE_URL or DATA_DIR)


def _agora():
    return datetime.now(timezone.utc)


def _pasta():
    return DATA_DIR or "dados"


def _arquivo(col, id_):
    seguro = re.sub(r"[^A-Za-z0-9_.-]", "_", id_)
    if seguro != id_ or len(seguro) > 80:  # e-mails e outros ids viram um nome de arquivo seguro
        seguro = hashlib.sha256(id_.encode()).hexdigest()
    return os.path.join(_pasta(), col, seguro + ".json")


def _conectar():
    global _criada
    import psycopg  # só é necessário quando DATABASE_URL está definido
    c = psycopg.connect(DATABASE_URL, connect_timeout=10, autocommit=True)
    if not _criada:
        c.execute("""create table if not exists docs (col text not null, id text not null, versao integer not null,
                     atualizado timestamptz not null, dados jsonb not null, primary key (col, id))""")
        _criada = True
    return c


def _reg(id_, versao, atualizado, dados):
    return {"id": id_, "versao": versao, "atualizado": atualizado.isoformat(timespec="seconds"), "dados": dados}


def _gravar_arquivo(caminho, reg):
    os.makedirs(os.path.dirname(caminho), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(caminho), suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:  # grava num temporário e troca: nunca fica pela metade
        json.dump(reg, f, ensure_ascii=False)
    os.replace(tmp, caminho)


def ler(col, id_):
    """Devolve {"id", "versao", "atualizado", "dados"} ou None."""
    if DATABASE_URL:
        with _conectar() as c:
            r = c.execute("select versao, atualizado, dados from docs where col = %s and id = %s", (col, id_)).fetchone()
        return _reg(id_, *r) if r else None
    try:
        with open(_arquivo(col, id_), encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return None


def gravar(col, id_, dados, base=None):
    """Grava o documento. Com `base`, só grava se a versão atual for essa (senão devolve None: conflito).
    Sem `base`, grava sempre. Devolve o registro gravado."""
    agora = _agora()
    with _lock:
        if DATABASE_URL:
            from psycopg.types.json import Jsonb
            with _conectar() as c:
                if base is None:
                    r = c.execute("""insert into docs values (%s, %s, 1, %s, %s) on conflict (col, id) do update
                                     set versao = docs.versao + 1, atualizado = excluded.atualizado, dados = excluded.dados
                                     returning versao""", (col, id_, agora, Jsonb(dados))).fetchone()
                elif base == 0:
                    r = c.execute("insert into docs values (%s, %s, 1, %s, %s) on conflict do nothing returning versao",
                                  (col, id_, agora, Jsonb(dados))).fetchone()
                else:
                    r = c.execute("""update docs set versao = versao + 1, atualizado = %s, dados = %s
                                     where col = %s and id = %s and versao = %s returning versao""",
                                  (agora, Jsonb(dados), col, id_, base)).fetchone()
            return _reg(id_, r[0], agora, dados) if r else None
        atual = ler(col, id_)
        versao = atual["versao"] if atual else 0
        if base is not None and base != versao:
            return None
        reg = _reg(id_, versao + 1, agora, dados)
        _gravar_arquivo(_arquivo(col, id_), reg)
        return reg


def criar(col, id_, dados):
    """Cria só se ainda não existir (ex.: índice de e-mail único). Devolve True se criou."""
    return gravar(col, id_, dados, base=0) is not None


def apagar(col, id_):
    with _lock:
        if DATABASE_URL:
            with _conectar() as c:
                c.execute("delete from docs where col = %s and id = %s", (col, id_))
            return
        try:
            os.remove(_arquivo(col, id_))
        except FileNotFoundError:
            pass


def listar(col):
    """Todos os documentos de uma coleção: [(id, dados)]."""
    if DATABASE_URL:
        with _conectar() as c:
            return [(r[0], r[1]) for r in c.execute("select id, dados from docs where col = %s", (col,)).fetchall()]
    pasta = os.path.join(_pasta(), col)
    out = []
    for nome in sorted(os.listdir(pasta)) if os.path.isdir(pasta) else []:
        if nome.endswith(".json"):
            try:
                with open(os.path.join(pasta, nome), encoding="utf-8") as f:
                    r = json.load(f)
                out.append((r["id"], r["dados"]))
            except (OSError, ValueError, KeyError):
                continue
    return out


def migrar_legado(uid):
    """Na primeira conta criada, adota a carteira salva quando o app ainda era de um usuário só."""
    try:
        if DATABASE_URL:
            with _conectar() as c:
                if c.execute("select to_regclass('carteira')").fetchone()[0] is None:
                    return False
                r = c.execute("select dados from carteira where id = 'principal'").fetchone()
                if r and not ler("carteira", uid):
                    gravar("carteira", uid, r[0])
                c.execute("alter table carteira rename to carteira_migrada")
                return bool(r)
        antigo = os.path.join(_pasta(), "carteira.json")
        if not os.path.exists(antigo):
            return False
        with open(antigo, encoding="utf-8") as f:
            d = json.load(f).get("dados")
        if d and not ler("carteira", uid):
            gravar("carteira", uid, d)
        os.replace(antigo, os.path.join(_pasta(), "carteira_migrada.json"))
        return bool(d)
    except Exception as e:  # a migração nunca impede o cadastro
        print("migração da carteira antiga falhou:", repr(e), flush=True)
        return False
