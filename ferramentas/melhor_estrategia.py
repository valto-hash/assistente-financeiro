"""Garantia de melhor decisão: a recomendada de cada perfil contra todas as estratégias que a pessoa pode escolher, nos
dois testes com dados reais (simulador mês a mês e corretora simulada dia a dia).

Regra (fixada antes de rodar com dados reais, 23/11/2026; a mesma de estrategias.dominantes, usada pelo servidor):
Uma estratégia que a pessoa pode escolher no perfil "domina" a recomendada se, nos DOIS testes:
  (a) rendeu mais ao ano (retorno ponderado pelo tempo) em 2013-2019 E em 2020-2026, cada metade por 0,2 ponto ou mais;
  (b) a maior queda não foi pior que a da recomendada em mais de 1 ponto;
  (c) o patrimônio final foi maior.
Se houver mais de uma, vale a de maior patrimônio final na corretora simulada, e ela passa a ser a recomendada do perfil.

Uso, na raiz do repositório: python3 ferramentas/melhor_estrategia.py (precisa de internet; alguns minutos).
"""
import os, sys, tempfile, json
os.environ["DATA_DIR"] = tempfile.mkdtemp(); os.environ["APP_TOKEN"] = ""
os.environ.pop("ANTHROPIC_API_KEY", None)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import server, estrategias, corretora, simulador  # noqa: E402

if __name__ == "__main__":
    sim = server._simulador()
    cor = server._corretora()
    for p in server.PERFIS:
        cabem = [e["id"] for e in server.estrategias_perfil(p)["estrategias"] if e["cabe"] and e["id"] != "app"]
        linhas = estrategias.linhas_testes(sim["perfis"][p], cor, p, ["app"] + cabem)
        print(f"\n===== {p}")
        for eid, (ls, lc) in linhas.items():
            if ls and lc:
                print(f"  {eid:16s} simulador: R$ {ls['final']:>9,.0f} {ls['metade1_aa']:5.1f}% | {ls['metade2_aa']:5.1f}% queda {ls['maior_queda']:6.1f}"
                      f"   corretora: R$ {lc['final']:>9,.0f} {lc['metade1_aa']:5.1f}% | {lc['metade2_aa']:5.1f}% queda {lc['maior_queda']:6.1f}"
                      f" IR pago R$ {lc['ir_pago']:,.0f}")
        dom = estrategias.dominantes("app", linhas)
        print("  dominam a recomendada:", [x["id"] for x in dom] or "nenhuma")
    print("\nficou decidido:", json.dumps(server._padroes(), ensure_ascii=False, indent=1))
