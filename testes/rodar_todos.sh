#!/bin/sh
# Roda todas as baterias de teste do servidor, sem rede (preços, Banco Central e IA simulados em testes/mocks.py).
# Uso, na raiz do repositório: sh testes/rodar_todos.sh
# Para o modo PostgreSQL de test_lancamento.py, suba um Postgres local (teste/teste, banco carteira_teste) e rode
# "python3 testes/test_lancamento.py banco".
cd "$(dirname "$0")/.." || exit 1
falhou=0
for t in test_simulador test_estrategias test_corretora test_garantias test_diferenciais test_trader test_mestre test_confiab test_lancamento test_novidades; do
  printf '%-22s ' "$t"
  saida=$(python3 "testes/$t.py" arquivo 2>&1)
  if echo "$saida" | grep -q "TUDO OK"; then echo "ok"; else echo "FALHOU"; echo "$saida" | grep -E "FALHA|Traceback|Error" | head -5; falhou=1; fi
done
exit $falhou
