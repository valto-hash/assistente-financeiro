"""Armazena os dados do app: contas de acesso, sessões e, para cada usuário, carteira, contas a pagar e avisos.

Cada dado é um "documento" identificado por (coleção, id), com versão e data de atualização.
Dois modos, escolhidos por variáveis de ambiente:
- DATABASE_URL definido: PostgreSQL, tabela "docs" (recomendado em hospedagens cujo disco é apagado a cada deploy).
- Caso contrário: um arquivo JSON por documento em DATA_DIR (padrão ./dados): dados/<coleção>/<id>.json.
  Só é permanente se essa pasta estiver num disco persistente.

A versão permite gravação otimista: quem grava informa a versão em que se baseou; se outro aparelho gravou antes,
a gravação é recusada (conflito) em vez de sobrescrever em silêncio.

Para mudar de servidor sem perder nada:  python armazem.py exportar backup.jsonl  (no servidor antigo)
                                         python armazem.py importar backup.jsonl  (no novo, com as mesmas variáveis)
"""
import hashlib, json, os, re, sys, tempfile, threading
from datetime import datetime, timezone

DATABASE_URL = os.getenv("DATABASE_URL", "")
DATA_DIR = os.getenv("DATA_DIR", "")
_lock = threading.RLock()
_criada = False
_pool = None


def modo():
    return "banco" if DATABASE_URL else "arquivo"


def _num_volume(caminho):
    """True se a pasta está num disco montado à parte (volume), e não no disco do próprio contêiner."""
    p = os.path.abspath(caminho)
    while True:
        if os.path.ismount(p):
            return p != "/"
        pai = os.path.dirname(p)
        if pai == p:
            return False
        p = pai


def diagnostico():
    """Os dados sobrevivem a um novo deploy (atualização do app)? Devolve {"modo", "persistente", "motivo"}."""
    if DATABASE_URL:
        return {"modo": "banco", "persistente": True, "motivo": "Os dados ficam no banco PostgreSQL (DATABASE_URL)."}
    pasta = os.path.abspath(_pasta())
    if DATA_DIR and _num_volume(pasta):
        return {"modo": "arquivo", "persistente": True, "motivo": f"Os dados ficam em {pasta}, num disco persistente."}
    hospedagem = any(os.getenv(v) for v in ("RENDER", "K_SERVICE", "FLY_APP_NAME", "RAILWAY_ENVIRONMENT", "DYNO")) \
        or os.path.exists("/.dockerenv") or os.path.exists("/run/.containerenv")
    if not hospedagem:
        return {"modo": "arquivo", "persistente": True, "motivo": f"Os dados ficam em {pasta}, no disco deste computador."}
    return {"modo": "arquivo", "persistente": False,
            "motivo": f"Os dados ficam em {pasta}, no disco temporário do servidor: são APAGADOS a cada atualização (deploy). "
                      "Configure DATABASE_URL com um PostgreSQL (ex.: Neon, gratuito) ou monte um disco persistente em DATA_DIR."}


def persistente():
    return diagnostico()["persistente"]


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
    """Conexão do pool (reaproveitada entre pedidos: abrir uma conexão nova com um banco remoto custa caro)."""
    global _criada, _pool
    with _lock:
        if _pool is None:
            from psycopg_pool import ConnectionPool  # só é necessário quando DATABASE_URL está definido
            _pool = ConnectionPool(DATABASE_URL, min_size=1, max_size=int(os.getenv("DB_CONEXOES", "8")), open=True,
                                   kwargs={"autocommit": True, "connect_timeout": 10},
                                   check=ConnectionPool.check_connection, max_idle=300)
        if not _criada:
            with _pool.connection() as c:
                c.execute("""create table if not exists docs (col text not null, id text not null, versao integer not null,
                             atualizado timestamptz not null, dados jsonb not null, primary key (col, id))""")
            _criada = True
    return _pool.connection()


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


# ---------------------------------------------------------------- exportar e importar (mudança de servidor)

def todos():
    """Todos os documentos, de todas as coleções: [{"col", "id", "versao", "atualizado", "dados"}]."""
    if DATABASE_URL:
        with _conectar() as c:
            rows = c.execute("select col, id, versao, atualizado, dados from docs order by col, id").fetchall()
        return [{"col": r[0], **_reg(r[1], r[2], r[3], r[4])} for r in rows]
    out, raiz = [], _pasta()
    for col in sorted(os.listdir(raiz)) if os.path.isdir(raiz) else []:
        pasta = os.path.join(raiz, col)
        if not os.path.isdir(pasta):
            continue
        for nome in sorted(os.listdir(pasta)):
            if nome.endswith(".json"):
                try:
                    with open(os.path.join(pasta, nome), encoding="utf-8") as f:
                        out.append({"col": col, **json.load(f)})
                except (OSError, ValueError):
                    continue
    return out


def exportar_linhas():
    for d in todos():
        yield json.dumps(d, ensure_ascii=False) + "\n"


def importar_linhas(linhas, sobrescrever=False):
    """Grava os documentos exportados. Por padrão não sobrescreve o que já existe. Devolve (gravados, pulados)."""
    gravados = pulados = 0
    for ln in linhas:
        ln = ln.strip()
        if not ln:
            continue
        d = json.loads(ln)
        if not sobrescrever and ler(d["col"], d["id"]):
            pulados += 1
            continue
        gravar(d["col"], d["id"], d["dados"])
        gravados += 1
    return gravados, pulados


if __name__ == "__main__":
    uso = "uso: python armazem.py exportar ARQUIVO.jsonl | importar ARQUIVO.jsonl [--sobrescrever] | diagnostico"
    if len(sys.argv) < 2:
        sys.exit(uso)
    cmd = sys.argv[1]
    if cmd == "diagnostico":
        print(json.dumps(diagnostico(), ensure_ascii=False, indent=2))
    elif cmd == "exportar" and len(sys.argv) > 2:
        n = 0
        with open(sys.argv[2], "w", encoding="utf-8") as f:
            for ln in exportar_linhas():
                f.write(ln); n += 1
        print(f"{n} documentos exportados para {sys.argv[2]} ({modo()})")
    elif cmd == "importar" and len(sys.argv) > 2:
        with open(sys.argv[2], encoding="utf-8") as f:
            g, p = importar_linhas(f, "--sobrescrever" in sys.argv)
        print(f"{g} documentos importados, {p} já existiam e foram mantidos ({modo()})")
    else:
        sys.exit(uso)
