# Testes

Todos rodam sem internet: `mocks.py` simula as cotações (Yahoo), o Banco Central, o boletim Focus, as notícias e a IA.

- `sh testes/rodar_todos.sh`: roda tudo e mostra o que falhou.
- `python3 testes/servidor_teste.py`: sobe o app em http://127.0.0.1:8765 com os dados simulados (login com Google e
  e-mail também simulados), para testar a interface no navegador.

| Arquivo | O que confere |
|---|---|
| `test_garantias.py` | Dados parados na fonte, planos de referência, auditoria que descarta a carteira da IA, memória e coerência |
| `test_diferenciais.py` | Gastos por categoria, planilhas da B3, rentabilidade, proventos, fundamentos e ranking |
| `test_trader.py` | Limpeza de cotações, liquidez, histórico mínimo, peso pelo risco, setor, armadilha de dividendos |
| `test_mestre.py` | Código mestre (acesso completo sem pagar) |
| `test_confiab.py` | Consenso IA x regras, checagem dos números da IA, registro e avaliação dos sinais |
| `test_lancamento.py` | Login (Google e e-mail), recuperação de senha, planos, cobrança, teste de perfil, páginas da loja |
