"""Guarda a carteira do usuário (ativos registrados, lista acompanhada, perfil e objetivo) no servidor.

Dois modos, escolhidos por variáveis de ambiente:
- DATABASE_URL definido: PostgreSQL (recomendado em hospedagens cujo disco é apagado a cada deploy, como o plano
  gratuito do Render). Serve qualquer Postgres: o do próprio provedor, Neon, Supabase etc.
- Caso contrário: um arquivo JSON em DATA_DIR (padrão: ./dados). Só é permanente se essa pasta estiver num disco
  persistente (volume). Por isso o app também mantém uma cópia em cada aparelho e reenvia ao servidor se ele perder
  os dados.

Cada gravação aumenta a "versão". O aparelho informa a versão em que se baseou; se outro aparelho gravou antes,
a gravação é recusada (conflito) e o app pergunta qual versão manter, em vez de sobrescrever em silêncio.
"""
import json, os, tempfile, threading
from datetime import datetime, timezone

DATABASE_URL = os.getenv("DATABASE_URL", "")
DATA_DIR = os.getenv("DATA_DIR", "")
_lock = threading.Lock()
_criada = False


def modo():
    return "banco" if DATABASE_URL else "arquivo"


def persistente():
    """Banco de dados, ou uma pasta configurada de propósito (presumivelmente um volume), sobrevivem a novos deploys."""
    return bool(DATABASE_URL or DATA_DIR)


def _arquivo():
    return os.path.join(DATA_DIR or "dados", "carteira.json")


def _agora():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _conectar():
    global _criada
    import psycopg  # só é necessário quando DATABASE_URL está definido
    c = psycopg.connect(DATABASE_URL, connect_timeout=10, autocommit=True)
    if not _criada:
        c.execute("""create table if not exists carteira (
            id text primary key, versao integer not null, atualizado timestamptz not null, dados jsonb not null)""")
        _criada = True
    return c


def ler():
    """Devolve {"versao", "atualizado", "dados"} ou None se nada foi salvo ainda."""
    if DATABASE_URL:
        with _conectar() as c:
            r = c.execute("select versao, atualizado, dados from carteira where id = 'principal'").fetchone()
        return {"versao": r[0], "atualizado": r[1].isoformat(timespec="seconds"), "dados": r[2]} if r else None
    try:
        with open(_arquivo(), encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return None


def gravar(dados, base):
    """Grava se `base` for a versão atual. Devolve o registro novo, ou None se houve conflito."""
    with _lock:
        if DATABASE_URL:
            from psycopg.types.json import Jsonb
            agora = datetime.now(timezone.utc)
            with _conectar() as c:
                if base == 0:
                    r = c.execute("""insert into carteira (id, versao, atualizado, dados) values ('principal', 1, %s, %s)
                                     on conflict (id) do nothing returning versao""", (agora, Jsonb(dados))).fetchone()
                else:
                    r = c.execute("""update carteira set versao = versao + 1, atualizado = %s, dados = %s
                                     where id = 'principal' and versao = %s returning versao""", (agora, Jsonb(dados), base)).fetchone()
            return {"versao": r[0], "atualizado": agora.isoformat(timespec="seconds"), "dados": dados} if r else None
        atual = ler()
        if (atual["versao"] if atual else 0) != base:
            return None
        novo = {"versao": base + 1, "atualizado": _agora(), "dados": dados}
        os.makedirs(os.path.dirname(_arquivo()), exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(_arquivo()), suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:  # grava num arquivo temporário e troca: nunca fica pela metade
            json.dump(novo, f, ensure_ascii=False)
        os.replace(tmp, _arquivo())
        return novo
