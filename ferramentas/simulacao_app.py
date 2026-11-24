"""O app inteiro nos dois testes com dados reais, do jeito que o servidor roda (perfis, núcleos, escolha de ativos,
estratégias que cabem em cada perfil e a regra de melhor decisão). Confere se a recomendada de cada perfil:
  1. respeita o limite de queda do perfil nas três medidas (dia a dia, mês a mês e pior crise real);
  2. termina com mais dinheiro que cada outra estratégia que o app oferece e cabe no perfil, nos dois testes;
  3. não é dominada por nenhuma (estrategias.dominantes).
Uso, na raiz do repositório: python3 ferramentas/simulacao_app.py  (precisa de internet)
"""
import os, sys, tempfile, time
os.environ["DATA_DIR"] = tempfile.mkdtemp(); os.environ["APP_TOKEN"] = ""
os.environ.pop("ANTHROPIC_API_KEY", None)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import server, estrategias, simulador  # noqa: E402

if __name__ == "__main__":
    t0 = time.time()
    sim = server._simulador()
    cor = server._corretora()
    server.cache.clear()  # as estratégias passam a usar a queda dia a dia que a corretora acabou de calcular
    problemas = []
    for p in server.PERFIS:
        lim = server.PIOR_CRISE[p]
        e = server.estrategias_perfil(p)
        cabem = [x["id"] for x in e["estrategias"] if x["cabe"]]
        rec = next(x for x in e["estrategias"] if x["id"] == "app")
        linhas = estrategias.linhas_testes(sim["perfis"][p], cor, p, cabem)
        s_app, c_app = linhas["app"]
        print(f"\n===== {p.upper()}: {server.teste_perfil.DEFINICOES[p]['curto']}")
        print(f"  modelo: {server.PERFIS[p]} | renda fixa: {({**server.regras.NUCLEO_PADRAO, **server.NUCLEOS[p]})['renda_fixa']}"
              f" | escolhe ações: {'sim' if server.ESCOLHE_ATIVOS[p] else 'não'}")
        print(f"  queda máxima da recomendada: dia a dia {c_app['maior_queda']}% | mês a mês {s_app['maior_queda']}% | pior crise "
              f"{rec['pior_crise'][0]} {rec['pior_crise'][1]}% (limite {lim:.0f}%)")
        dentro = c_app["maior_queda"] >= lim and s_app["maior_queda"] >= lim and rec["pior_crise"][1] >= lim
        if not dentro:
            problemas.append(f"{p}: a recomendada passa do limite de queda")
        print(f"  {'estratégia':40s} {'simulador mês a mês':>32s}   {'corretora dia a dia (custos e IR)':>40s}")
        for i, (ls, lc) in sorted(linhas.items(), key=lambda kv: -(kv[1][1] or {}).get("final", 0)):
            if not (ls and lc):
                continue
            nome = server.ESTRATEGIA_NOMES.get(i, i)
            print(f"  {nome[:40]:40s} R$ {ls['final']:>9,.0f} {ls['metade1_aa']:5.1f}|{ls['metade2_aa']:5.1f}% q {ls['maior_queda']:6.1f}"
                  f"   R$ {lc['final']:>9,.0f} {lc['metade1_aa']:5.1f}|{lc['metade2_aa']:5.1f}% q {lc['maior_queda']:6.1f} IR {lc['ir_pago']:>7,.0f}")
            if i != "app" and (ls["final"] >= s_app["final"] or lc["final"] >= c_app["final"]):
                problemas.append(f"{p}: {nome} terminou com mais dinheiro que a recomendada em algum teste")
        fora = [x for x in e["estrategias"] if not x["cabe"]]
        print(f"  não cabem no perfil: {', '.join(x['nome'] for x in fora) or 'nenhuma'}")
        dom = estrategias.dominantes("app", linhas)
        print(f"  dominam a recomendada: {[d['id'] for d in dom] or 'nenhuma'} | simulador: {sim['perfis'][p]['posicao']}º de {sim['perfis'][p]['total']}")
        if dom:
            problemas.append(f"{p}: dominada por {[d['id'] for d in dom]}")
    print(f"\nprova ao vivo: desde {sim.get('vivo', {}).get('desde')}; meses já medidos: {sim.get('vivo', {}).get('meses')}")
    print("\nTUDO CERTO: em cada perfil, a recomendada respeita o limite e vence todas as que cabem, nos dois testes"
          if not problemas else "\nPROBLEMAS:\n- " + "\n- ".join(problemas))
    print(f"({time.time() - t0:.0f}s)")
