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
| `estrategias.py` | Estratégias que a pessoa pode escolher (recomendada, modelo só com ETFs, planos consagrados) e a regra de melhor decisão |
| `corretora.py` | Corretora simulada: o app dia a dia com ordens, custos, proventos e IR (estilo testador do MetaTrader) |
| `perfil.py` | Teste de perfil e a definição de cada tipo de investidor (`DEFINICOES`) |
| `checagem.py` | Confere se cada número citado pela IA existe nos dados que ela recebeu |
| `investimentos.py` | Rentabilidade (Dietz modificado), proventos, agenda de proventos e leitura das planilhas da B3 |
| `ir.py` | Imposto de renda: operações registradas, apuração mensal com DARF e declaração anual |
| `rendafixa.py` | Comparador de renda fixa líquido (IR, custódia) e vencimentos |
| `fundamentos.py` | Indicadores de balanço e ranking (Yahoo, com conferências) |
| `gastos.py`, `contas.py` | Gastos por categoria, lançamento por frase (também pelo WhatsApp), cartões e faturas, contas do mês, boletos, extratos |
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
6. Os tipos de investidor estão em `perfil.DEFINICOES` (nome, para quem, limite de queda, renda fixa mínima); o limite
   vira `server.PIOR_CRISE` e vale para três medidas: queda dia a dia na corretora, queda no simulador mês a mês e pior
   crise real; a renda fixa mínima vale na IA, na auditoria e no encaixe das estratégias. Mudança no modelo de um perfil
   (`server.PERFIS`, `NUCLEOS`, `ESCOLHE_ATIVOS`): candidatos e regra escritos antes de rodar, dentro do limite nas três
   medidas e da renda fixa mínima (`ferramentas/rodadas_perfis.py`, `ferramentas/refinar_perfis.py`). Se a busca
   igualar dois perfis ou empurrar tudo para o máximo de risco, é sinal de "ganhar no passado": não aplique. Depois, `ferramentas/simulacao_app.py` tem de mostrar a recomendada vencendo todas
   as estratégias que cabem no perfil, nos dois testes. Guarde o modelo anterior em `PERFIS_ANTERIOR` e o motivo em
   `REVISAO_MODELO`. Foi assim em 24/11/2026.
7. Estratégia escolhida pela pessoa (`estrategias.py`): só pode ser seguida se couber no perfil (maior queda e pior crise
   real dentro de `PIOR_CRISE`) e passar na auditoria; senão, vale a recomendada e a tela mostra o motivo.
8. Sempre que a pessoa descreve a situação dela (perfil, objetivo, prazo, aporte, meta, estratégia), a tela roda o teste
   pessoal (`server.teste_pessoal`) com os números dela, em todos os períodos reais desde 2013. Não tire esse gatilho.
9. Garantia de melhor decisão (`estrategias.dominantes`, `server._atualizar_padroes`): se uma estratégia disponível vencer
   a recomendada nas duas metades nos dois testes com dados reais (simulador e corretora), com queda não pior, a
   recomendada passa a segui-la. Não afrouxe a regra (margem de 0,2 ponto por metade, 1 ponto de queda) para "ganhar
   no passado".

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
- Não colocar segredos (chaves, `CODIGO_MESTRE`, `DATABASE_URL`, `WHATSAPP_*`) em arquivos do repositório.
- Regras de imposto em `ir.py` (isenção de R$ 20 mil, alíquotas, DARF): mudou a lei, mude o código e `testes/test_novidades.py`.
