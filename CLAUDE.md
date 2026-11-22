# Assistente Financeiro: contexto para quem (pessoa ou IA) for mexer no código

App de finanças pessoais em português do Brasil: carteira de investimentos com recomendações, simulação, gastos,
contas do mês, rentabilidade, proventos, fundamentos e avisos. Servidor FastAPI (`server.py`) e uma página única
(`index.html`, sem build). Publicado no Render a partir da `main` (deploy automático a cada commit), com os dados no
PostgreSQL do Neon (`DATABASE_URL`). Os valores das variáveis de ambiente ficam só no Render, nunca no repositório.

## Antes de mudar qualquer coisa

- Rode `sh testes/rodar_todos.sh` antes e depois. Os testes não usam internet (`testes/mocks.py` simula tudo).
- Para ver a interface: `python3 testes/servidor_teste.py` e abra http://127.0.0.1:8765.
- Textos da interface e mensagens ao usuário: português do Brasil, linguagem simples, sem jargão sem explicação.
- Seja honesto nos textos: nada de prometer retorno; quando um teste com o passado mostra que algo não funciona,
  a tela diz isso.

## Mapa dos arquivos

| Arquivo | Papel |
|---|---|
| `server.py` | Rotas da API, análise por ativo, carteira recomendada (IA ou regras), auditoria, avisos |
| `regras.py` | Motor de regras (funciona sem IA): alocação, escolha de ativos, gestão de risco, textos com fatos |
| `referencias.py` | Planos consagrados testados com dados do Brasil e as checagens da auditoria |
| `memoria.py` | Memória por usuário: recomendações anteriores e compras/vendas, para a IA ser coerente |
| `simulacao.py` | Histórico de preços (com limpeza), Monte Carlo, testes de estresse, série IPCA+ longo |
| `acertos.py` | Quanto o app acerta: teste dos sinais e da escolha de ações com o passado, histórico real |
| `simulador.py` | Simulador do passado (seguir o app mês a mês desde 2013) e a prova ao vivo mensal |
| `checagem.py` | Confere se cada número citado pela IA existe nos dados que ela recebeu |
| `investimentos.py` | Rentabilidade (Dietz modificado), proventos e leitura das planilhas da B3 |
| `fundamentos.py` | Indicadores de balanço e ranking (Yahoo, com conferências) |
| `gastos.py`, `contas.py` | Gastos por categoria, contas do mês, boletos, extratos |
| `planos.py`, `usuarios.py`, `armazem.py` | Assinatura, contas de usuário, armazenamento (arquivo ou PostgreSQL) |
| `ativos.py` | Lista de ativos que o app pode recomendar, setores, ETFs e units |

## Regras que protegem as recomendações (não desligar)

1. A IA nunca é a palavra final. Toda carteira passa por `checagens_duras` (server.py) e `referencias.checar`:
   soma 100%, risco dentro do perfil, prazo curto em renda fixa, nenhum papel novo acima de 10%, ativos novos com
   liquidez/histórico/cotação atualizada e pior crise real dentro do limite do perfil. Se a da IA não passar, vale a
   das regras, e a tela mostra o motivo.
2. Números citados pela IA são conferidos (`checagem.py`); texto com número inventado é trocado pelo das regras.
3. A IA recebe os planos de referência (`referencias.planos_ref`) e a memória do usuário (`memoria.contexto`), e
   precisa explicar mudanças grandes. Mudança brusca sem motivo vira aviso na auditoria; as regras mantêm o nível
   de risco anterior quando a opção nova não é claramente melhor.
4. Sinais de compra/venda só viram aviso quando IA e regras concordam.
5. Mudança em regra de alocação ou escolha de ativos: rode o simulador (`simulador.tudo`) antes e depois e compare com o
   modelo fixo do perfil. Regra que piora o resultado nos três perfis não entra (foi assim que `AJUSTE_MOMENTO` foi
   desligado). Cuidado para não ajustar regra até "ganhar no passado": a prova que vale é a ao vivo.
6. Mudança no modelo de um perfil (`server.PERFIS`): candidatos definidos antes de ver os resultados, escolha só com a
   primeira metade (2013-2019) e confirmação na segunda (2020-2026), sem arriscar mais que o modelo atual nem passar da
   pior crise do perfil. Guarde o modelo antigo em `PERFIS_ANTERIOR` (aparece no simulador) e o motivo em
   `REVISAO_MODELO` (explica a mudança a quem tinha recomendação antiga). Foi assim com o conservador em nov/2026.

## Armadilhas de dados já encontradas (o Yahoo erra)

- Cotações absurdas por poucos dias e desdobramentos não ajustados (ex.: XPML11 em jan/2026): `sim.limpar`.
- ETFs de renda fixa (IMAB11, B5P211, IRFM11, FIXA11) com preço parado de 2023 a 2025 e salto de ~50% em 2026:
  `sim.parado` os marca e eles não entram como ativo novo. Para títulos IPCA+ use a série `IPCA_LONGO`
  (IMA-B 5+ do Banco Central, série 12468, emendada com o ETF IB5M11).
- Units (TAEE11, KLBN11...): lucro por ação e valor de mercado do Yahoo misturam ação e unit. O P/L só aparece
  quando duas contas independentes batem (`fundamentos.indicadores`).
- Proventos de FIIs com anos faltando no Yahoo: ano zerado entre anos com pagamento é "sem dado".
- O IPCA do Banco Central (série 433) e o CDI (série 4391) têm limite de 10 anos por consulta.
- Preço ajustado do Yahoo embute os dividendos pagos depois: para dividend yield de uma data antiga, use o preço de
  tela reconstruído (`acertos._fator_div`), conferido com o preço sem ajuste. Retornos podem usar o preço ajustado.
- O IPCA de um mês só é divulgado uns 10 dias depois: em testes com o passado, no fim do mês t vale o IPCA de t-1.
- Em testes com o passado, nada pode depender de dados posteriores à data (nem o tamanho total da série).
  `testes/test_simulador.py` confere isso.

## Fluxo de trabalho

- Branch de trabalho, commit com mensagem em português explicando o porquê, pull request para a `main`.
- Juntar na `main` publica no ar (Render). Antes disso, confira os testes e, para mudanças visíveis, a interface.
- Não colocar segredos (chaves, `CODIGO_MESTRE`, `DATABASE_URL`) em arquivos do repositório.
