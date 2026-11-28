# Assistente Financeiro

Carteira de investimentos com recomendações explicadas, simulação do futuro, contas do mês e avisos no celular.
Cada pessoa tem a própria conta (e-mail e senha ou Google): carteira, contas e avisos ficam separados e guardados no servidor.

- **Teste de perfil** ao criar a conta: perfil de investidor (tolerância a perdas limitada pelo prazo, reserva e idade) e objetivo.
- **Carteira recomendada** por regras (ou com IA no Premium): escolhe o nível de risco testando 5 opções em 2.000 cenários e
  nas crises reais (2008, 2015, 2020…), escolhe ativos pela qualidade de longo prazo, um por setor, e diz o que fazer com
  cada ativo em **cotas inteiras**, preferindo os próximos aportes a vender (evita IR).
- **81 ativos** organizados por tipo e setor (ações, FIIs, ETFs, exterior, dólar e ouro) e 7 tipos de renda fixa,
  com busca; qualquer outro código da B3 também pode ser acompanhado.
- **Planos:** Grátis (até 5 investimentos, simulação de 10 anos, 5 contas, análises por regras) e Premium (tudo, com IA
  quando o servidor tem chave), com 7 dias de teste. Cobrança pelo Google Play (app Android) e Mercado Pago (site).
- Pronto para a **Google Play** como app Android (TWA): veja [docs/PUBLICAR_NA_PLAY.md](docs/PUBLICAR_NA_PLAY.md).
- Roda em qualquer servidor com Docker: veja [docs/HOSPEDAGEM.md](docs/HOSPEDAGEM.md).

## Rodar

```bash
cp .env.example .env               # preencha
docker compose up -d --build       # app + PostgreSQL + HTTPS automático (precisa de um domínio apontando para o servidor)
```
Só o app (com um PostgreSQL externo em `DATABASE_URL`): `docker build -t assistente . && docker run -p 8000:8000 --env-file .env assistente`.
Para testar no computador: `pip install -r requirements.txt && uvicorn server:app --reload` (os dados ficam na pasta `dados/`).

`/api/saude` mostra se o servidor está no ar e se o armazenamento é permanente.

## Configuração (variáveis de ambiente)

Todas estão em [.env.example](.env.example), com explicação. As principais:

| Variável | Para quê |
|---|---|
| `DATABASE_URL` | PostgreSQL onde ficam contas, carteiras, planos e avisos (recomendado; ex.: Neon, gratuito). Sem ele, os dados ficam em arquivos em `DATA_DIR`, que precisa ser um disco permanente: **no Render grátis o disco é apagado a cada atualização**. O app avisa os administradores quando os dados estão em risco. |
| `ADMIN_EMAILS` | E-mails dos administradores: sempre Premium, veem o diagnóstico do armazenamento e podem exportar todos os dados (menu da conta). |
| `APP_NOME`, `APP_URL`, `RESPONSAVEL`, `CONTATO_EMAIL` | Nome do app, endereço público e dados do responsável (aparecem na política de privacidade e nos termos). |
| `CODIGO_CONVITE` (ou `APP_TOKEN`) | Código exigido para criar conta. Vazio = cadastro aberto (o normal na Play Store). |
| `GOOGLE_CLIENT_ID` | Liga o "Entrar com o Google" (ID do cliente OAuth do tipo Aplicativo da Web, no Google Cloud). |
| `SMTP_HOST`, `SMTP_PORTA`, `SMTP_USUARIO`, `SMTP_SENHA`, `SMTP_REMETENTE` | E-mail para o "esqueci minha senha" (código de 6 dígitos). |
| `WHATSAPP_TOKEN`, `WHATSAPP_PHONE_ID`, `WHATSAPP_VERIFY_TOKEN`, `WHATSAPP_APP_SECRET`, `WHATSAPP_NUMERO` | Lançar gastos pelo WhatsApp (API oficial da Meta, WhatsApp Cloud). Sem as quatro primeiras, o recurso fica desligado e não aparece na tela. Webhook: `/api/whatsapp/webhook`. |
| `ASSINATURA`, `TESTE_GRATIS_DIAS`, `PRECO_MENSAL`, `PRECO_ANUAL`, `CODIGOS_PREMIUM` | Planos: `ASSINATURA=nao` deixa todos Premium (uso pessoal); dias de teste (7); preços (14,90 e 119,90); códigos promocionais `CODIGO:dias`. |
| `CODIGO_MESTRE` | Seu código de acesso completo, sem pagar (mínimo 8 caracteres). No app: menu da conta, toque 5 vezes em "Versão" e digite o código. Nunca coloque o valor no código ou no GitHub; trocar o código revoga quem usou o antigo. |
| `ANDROID_PACKAGE`, `ANDROID_SHA256`, `PLAY_PRODUTO_MENSAL`, `PLAY_PRODUTO_ANUAL`, `GOOGLE_PLAY_CONTA_SERVICO`, `RTDN_CHAVE` | App Android e assinatura pelo Google Play (veja o guia de publicação). |
| `MERCADOPAGO_TOKEN` | Assinatura pelo site com o Mercado Pago (quem usa pelo navegador, fora do app da Play Store). |
| `ANTHROPIC_API_KEY` | Opcional. Com ela, o Premium tem análises com IA (Claude). Sem ela, tudo funciona pelo motor de regras. `USAR_IA=nao` desliga a IA mesmo com a chave. |
| `MODEL`, `MODELO_DECISOES`, `EFFORT_DECISOES` | Modelos do Claude: análises (padrão `claude-sonnet-5-5`) e carteira recomendada (padrão `claude-opus-5-5`, `high`). Para gastar menos: `MODELO_DECISOES=claude-haiku-5-5` e `EFFORT_DECISOES=low`. |
| `CRON_CHAVE`, `AVISOS_INTERVALO_MIN`, `AVISOS_AUTOMATICOS` | Avisos automáticos (a cada 30 min). Em hospedagens que desligam o servidor sem uso, chame `POST /api/cron/avisos` com o cabeçalho `X-Cron-Chave` de um agendador externo. |
| `VAPID_CHAVE_PRIVADA`, `VAPID_CONTATO` | Notificações push (a chave é gerada e guardada sozinha se não for definida). |

Notificações no celular exigem o app servido por HTTPS. No iPhone, só funcionam com o app adicionado à Tela de Início
(Compartilhar → Adicionar à Tela de Início).

## Dados que não se perdem

- No servidor: PostgreSQL (`DATABASE_URL`) ou disco permanente. Para mudar de servidor: menu da conta > *Exportar todos
  os dados* (administrador) e `python armazem.py importar backup.jsonl` no servidor novo.
- No aparelho: a carteira também fica guardada no celular (o app pede ao navegador para não apagá-la). Se o servidor
  perder a conta, basta criar a conta de novo com o mesmo e-mail (ou entrar com o Google): ela volta com o mesmo
  identificador e o aparelho reenvia os dados.

## Simulador do passado (eficácia do app)

Na aba Mercado: e se alguém tivesse seguido o app desde jan/2013, com R$ 10 mil no início e R$ 1.000 por mês? No fim
de cada mês o app recebe só os dados daquela data (preços, proventos, Selic e IPCA da época), monta a carteira com as
regras de hoje e a pessoa simulada segue as regras de operação do app (aportes no que está abaixo do recomendado,
vendas só quando o app mandaria, 0,1% de custo por operação). O mesmo dinheiro vai para o modelo fixo do perfil só com
ETFs, para o CDI e para os planos consagrados que cabem no perfil. Mostra patrimônio final, retorno ao ano, maior
queda, custos e o IR estimado das vendas.

O que o simulador mudou: ajustar a alocação pela tendência e pelo juro do momento deixava o resultado menor nos três
perfis, então foi desligado (`regras.AJUSTE_MOMENTO`); com 4% ou mais em dólar e ouro, a carteira passa a ter os dois.
A tela mostra também a versão antiga.

### Os três tipos de investidor (reformulados em 24/11/2026)

Cada perfil tem uma definição só (`perfil.DEFINICOES`, a mesma na tela, no teste de perfil, na IA e na auditoria): para
quem é, quanto aceita cair e a renda fixa mínima. O limite de queda vale para três medidas ao mesmo tempo: a maior queda
dia a dia de 2013 até hoje na corretora simulada, a maior queda no simulador mês a mês e a pior crise real testada
(2008, 2015, 2020...).

| Perfil | Para quem | Aceita cair até | Renda fixa mínima | Carteira recomendada (só ETFs e títulos) |
|---|---|---|---|---|
| Conservador | pode precisar do dinheiro em pouco tempo, está montando a reserva ou não ficaria tranquilo vendo o dinheiro cair | 8% | 70% | 70% renda fixa (Tesouro Selic 70%, LCI 30%), 6% ações, 16,5% exterior, 7,5% ouro |
| Moderado | investe por alguns anos, já tem reserva e aceita quedas de vez em quando para render mais | 18% | 40% | 40% renda fixa (85% Tesouro IPCA+, 15% Selic), 12% ações, 33% exterior, 15% dólar e ouro |
| Arrojado | investe por muitos anos, tem a reserva completa e não precisaria vender numa crise | 30% | 15% | 15% renda fixa (85% Tesouro IPCA+), 17% ações, 46,75% exterior, 21,25% dólar e ouro |

Como chegaram aqui (regras escritas antes de cada rodada, resultados em `ferramentas/*_resultado.txt`):
- rodada 1 (`ferramentas/rodadas_perfis.py`): 639 carteiras de ETFs e títulos; elegíveis só as que respeitam o limite
  nas três medidas; escolhida a de maior retorno na corretora em 2013-2019 (a 2ª metade só conferiu);
- rodada 3 (`ferramentas/refinar_perfis.py`): refinamento até nenhuma carteira vizinha ser claramente melhor. Sem uma
  renda fixa mínima, levou moderado e arrojado à mesma carteira, com 85% em risco: o teste "ganhando no passado" (o dólar
  e o ouro subiram justamente nas crises brasileiras). Não foi aplicada;
- rodada 4: o mesmo refinamento com a renda fixa mínima de cada perfil; convergiu em duas voltas. É a carteira de hoje;
- em todas, escolher ações individuais além dos ETFs foi testado e não melhorou nenhum perfil, então o app não faz isso.

O app depois das mudanças (`ferramentas/simulacao_app.py`, 24/11/2026; R$ 10 mil em 2013 + R$ 1.000 por mês; a
corretora já com custos e imposto pago):

| Perfil | Simulador mês a mês | Corretora dia a dia | Maior queda dia a dia | Se o real não tivesse se desvalorizado (pior crise) | Melhor alternativa que cabe (corretora) | Vence o CDI em janelas de 5 anos |
|---|---|---|---|---|---|---|
| Conservador | R$ 477 mil | R$ 457 mil | -6,0% | -7,9% | 100% CDI: R$ 378 mil | 100% |
| Moderado | R$ 525 mil | R$ 515 mil | -16,7% | -26,0% | All Weather: R$ 460 mil | 86% |
| Arrojado | R$ 606 mil | R$ 604 mil | -17,1% | -32,5% | 60/40: R$ 484 mil | 92% |

Em cada perfil, a recomendada respeita o limite e termina com mais dinheiro que todas as outras estratégias que o app
oferece e cabem no perfil, nos dois testes; nenhuma a domina. Pontos honestos:
- muitas carteiras foram testadas e as escolhas usaram o mesmo período, então parte da vantagem pode ser sorte dele;
  a prova ao vivo (carteira de cada mês guardada antes de o mês acontecer) é o teste que vale;
- o dólar e o ouro subiram em todas as crises brasileiras testadas e seguraram as quedas. Se numa crise o real não se
  desvalorizar, a queda pode ser bem maior: em 2008, com o S&P 500 e o ouro pela variação em dólar, o moderado teria
  caído 26% e o arrojado 32,5%, acima dos limites deles. O app mostra esse número em cada estratégia;
- nos testes, o arrojado caiu quase o mesmo que o moderado (17,1% contra 16,7% dia a dia); o limite dele é maior porque
  a proteção do câmbio pode não se repetir;
- nenhuma carteira tem fundos imobiliários: nos testes, eles não melhoraram nenhum perfil.

### Teste com a sua descrição

Sempre que a pessoa descreve a situação dela (perfil, objetivo, prazo, aporte, meta ou estratégia), a aba Investir
testa a carteira que ela segue, e todas as outras que cabem no perfil dela, com os números dela: o valor que tem, o
aporte por mês e o prazo (`server.teste_pessoal`, `POST /api/teste_pessoal`). Usa todos os períodos reais desde 2013,
um começando a cada 3 meses, com as regras e os custos de operação do simulador. Mostra quanto ela teria no período do
meio, no pior e no melhor, a maior queda no caminho, em quantos períodos chegou à meta e venceu o CDI, e sugere outra
estratégia só quando ela foi claramente melhor para aquela descrição (mais chance de chegar à meta, ou mais dinheiro no
período do meio, sem um pior caso mais baixo). Prazo maior que o histórico disponível é limitado e avisado.

### Escolher a estratégia

Na aba Investir, a pessoa escolhe qual estratégia seguir (`estrategias.py`, `GET /api/estrategias`): a recomendada pelo
app (padrão), o modelo do perfil só com ETFs e títulos, ou um dos 11 planos consagrados. Cada uma mostra a divisão, a
ideia, o teste com o passado (mesmo período e mesmo método para todas), a pior crise real e, quando já calculado, o
resultado no simulador. Só podem ser escolhidas as que cabem no perfil pelos critérios da auditoria (maior queda e pior
crise dentro do limite); com objetivo de curto prazo, também é preciso ter 85% ou mais em renda fixa. A carteira de uma
estratégia de divisão fixa não usa IA: é montada com os mesmos ETFs e títulos do teste, passa pela auditoria completa e
garante a reserva de emergência. Se ela não couber (mudou o perfil, objetivo de curto prazo), vale a recomendada e a tela
diz o motivo. A escolha fica salva com a carteira no servidor, entra na memória (trocar de estratégia não vira aviso de
incoerência), aparece destacada no simulador, e a prova ao vivo guarda todo mês também a carteira de cada plano.

Como essas mudanças saíram de testes com o passado, existe a **prova ao vivo**: todo mês
o app guarda a carteira que recomendaria para cada perfil, antes de o mês acontecer, e o resultado real aparece depois.
Limites: a IA não entra (ela sabe o que aconteceu depois), lista de ativos de hoje (viés de sobrevivência), valores antes
do IR. O resultado fica guardado no banco por 7 dias (`simulador.py`).

### Corretora simulada (como o testador de estratégias do MetaTrader)

Na aba Mercado, o segundo teste com dados reais (`corretora.py`, `GET /api/corretora`): as mesmas decisões do app (e do
modelo fixo e de cada plano), mas executadas como numa conta de corretora, dia a dia, desde 2013. As ordens saem no
pregão seguinte à decisão, pelo preço de tela da época, em quantidades inteiras de cotas, com emolumentos da B3 (0,03%),
diferença entre compra e venda (0,05%), custódia do Tesouro (0,20% ao ano, descontada do título), câmbio do dólar (0,5%),
proventos caindo na conta e o imposto de renda pago como a Receita manda (ações com a isenção de R$ 20 mil por mês, ETFs
15%, FIIs 20%, prejuízo compensado, tabela regressiva no Tesouro e no CDB, LCI isenta). O relatório segue o do
MetaTrader: patrimônio, lucro líquido, retorno de cada metade, maior queda dia a dia, ordens, vendas com lucro, fator de
lucro, custos, imposto pago e o que ainda seria pago no resgate, além das últimas ordens e da posição final.

Resultado de 24/11/2026, com os perfis da rodada 4 (R$ 10 mil em fev/2013 e R$ 1.000 por mês, já descontados custos e
imposto pago): conservador R$ 457 mil, moderado R$ 515 mil, arrojado R$ 604 mil, contra R$ 378 mil no CDI na mesma
corretora. Dia a dia as quedas aparecem maiores que no teste mês a mês, porque as cotações oscilam dentro do mês; por
isso o limite de cada perfil é conferido também dia a dia.

### Garantia de melhor decisão

Regra fixada antes de rodar com dados reais (`estrategias.dominantes`, `ferramentas/melhor_estrategia.py`): se uma
estratégia que a pessoa pode escolher no perfil render mais que a recomendada nas duas metades do período (2013-2019 e
2020 em diante, por 0,2 ponto ou mais em cada), nos dois testes (simulador e corretora), sem cair mais de 1 ponto além
dela e terminando com mais dinheiro, a recomendada do perfil passa a seguir essa estratégia, e a tela explica o motivo. Uma estratégia só "cabe" no perfil
se as três medidas de queda ficarem dentro do limite dele.
A conferência roda sozinha toda vez que os testes são refeitos (uma vez por semana) e fica guardada no banco
(`decisao/padrao`). Em 24/11/2026, com os perfis reformulados, a recomendada terminou com mais dinheiro que todas as
alternativas que cabem em cada perfil, nos dois testes, e nenhuma a domina. Ninguém garante o futuro: a garantia é que a
recomendada nunca fica atrás de uma alternativa disponível que se mostrou melhor de forma consistente nos testes.

### Quanto você ganha com cada FII e ação

Na aba Ativos, o app pergunta quanto a pessoa recebe por mês de proventos de cada ação e FII (campo `renda` da posição;
ETFs ficam de fora, porque não distribuem). Mostra ao lado o que o histórico de 12 meses indica e avisa quando os dois
são muito diferentes; o cartão de cada ativo mostra o rendimento sobre o que foi pago. A carteira recomendada usa isso: a
IA recebe o informado e o estimado, e toda sugestão de venda ou redução diz quanto de renda por mês a pessoa deixaria de
receber.

## O que veio da comparação com os concorrentes (28/11/2026)

- **Imposto de renda** (`ir.py`, aba Meus ativos): apuração mês a mês das vendas de ações, ETFs, BDRs e FIIs com as regras da
  Receita (ações isentas quando as vendas do mês somam até R$ 20 mil; 15% em ações, ETFs e BDRs; 20% em FIIs e day trade;
  prejuízo guardado por tipo e abatido depois; DARF código 6015 até o último dia útil do mês seguinte; abaixo de R$ 10 fica
  para o mês seguinte). Monta a declaração anual: bens e direitos pelo custo, dividendos e rendimentos de FIIs isentos, JCP
  em tributação exclusiva. Usa a planilha da B3 e as compras e vendas registradas no app (`/api/operacoes`). Avisa que
  não substitui um contador.
- **Lançamento rápido** por frase ou voz ("gastei 52,90 no mercado ontem", "comprei TV 2400 em 10x no cartão"):
  `gastos.interpretar`, `/api/gastos/rapido`. A voz usa o reconhecimento do navegador.
- **Cartões de crédito**: fechamento, vencimento e limite; compra parcelada vira uma parcela em cada fatura
  (`gastos.adicionar_compra`, `gastos.faturas`, `/api/cartoes`).
- **WhatsApp**: a pessoa liga o número com um código de 6 dígitos ("vincular 123456") e manda os gastos como mensagem;
  o app confere a assinatura da Meta em cada mensagem e responde o que anotou. Precisa de uma conta do WhatsApp Business
  (variáveis acima).
- **Agenda de proventos** (`investimentos.agenda`): o que cada FII e ação pagou em 12 meses e a próxima data-com,
  estimada pelo costume de cada um (a tela diz que é estimativa).
- **Comparador de renda fixa** (`rendafixa.py`, aba Mercado): CDB, LCI/LCA, Tesouro Selic, prefixado e IPCA+ pelo valor
  líquido no fim do prazo (tabela regressiva de IR, isenção de LCI/LCA, custódia de 0,20% ao ano no Tesouro) e quanto
  cada um equivale em CDB % do CDI. **Vencimentos**: a pessoa informa a data de cada título e o app mostra o que vence.
- **Planilhas** (CSV para Excel e Google Planilhas): carteira, compras e vendas, imposto e gastos (`/api/exportar/{tipo}`).
- **Verificação em duas etapas** com app autenticador (TOTP, RFC 6238, em `usuarios.py`): com ela ligada, entrar com
  senha, com Google ou criar nova senha pede também o código.

Não feito, porque depende de contrato ou conta de quem publica: Open Finance (sincronizar bancos e corretoras
automaticamente, por um agregador como Pluggy ou Belvo), app nas lojas (contas de desenvolvedor Google Play e Apple),
fundos de investimento, criptomoedas e conta compartilhada da família.

## Auditoria das recomendações, planos consagrados e memória

- **Auditoria:** toda carteira recomendada (da IA ou das regras) passa por checagens objetivas antes de aparecer: soma
  100%, risco dentro do perfil, dinheiro de curto prazo em renda fixa, nenhum papel novo acima de 10%, ativos novos com
  liquidez, histórico e cotação atualizada, e a pior crise real dentro do limite do perfil. Se a carteira da IA não
  passar, o app usa a das regras e mostra o motivo. A tela "Investir" mostra cada checagem.
- **Planos consagrados (11):** 100% CDI, Portfólio Permanente (Harry Browne), All Weather (Ray Dalio), 60/40, Três
  fundos (Bogleheads), Renda e crescimento 35/65 (inspirada no Vanguard Wellesley), Golden Butterfly, Coffeehouse
  (Bill Schultheis), Carteira de Swensen (Yale), Core Four (Rick Ferri) e 100% bolsa brasileira. Adaptados com ativos
  brasileiros e testados com dados reais de 04/2011 até hoje (rebalanceamento anual, sem custos nem impostos), com o
  resultado de cada metade do período. A carteira recomendada é testada do mesmo jeito e comparada com TODOS os planos
  que cabem no perfil (maior queda dentro do limite): avisa se algum foi melhor e menos arriscado (lista todos), mostra
  a posição dela entre eles e se ela bateu o CDI nas duas metades. A tela tem um gráfico de retorno x maior queda.
  A IA recebe todos esses números e precisa comparar a carteira dela com pelo menos três planos.
- **Memória:** o app guarda as últimas recomendações de cada pessoa e as compras e vendas registradas. A IA recebe esse
  resumo e precisa explicar mudanças grandes; mudança brusca sem motivo vira aviso, e as regras mantêm o nível de
  risco anterior quando a opção nova não é claramente melhor.
- **Títulos IPCA+:** simulados pelo IMA-B 5+ do Banco Central (2005-2023) emendado com o ETF IB5M11. Os ETFs de renda
  fixa do Yahoo (IMAB11, B5P211, IRFM11, FIXA11) ficaram com o preço parado de 2023 a 2025 e são marcados como não
  confiáveis.

## Testes

`sh testes/rodar_todos.sh` roda tudo sem internet. Veja `testes/LEIAME.md`. O contexto para quem for mexer no código
(pessoa ou IA) está em `CLAUDE.md`.

## Gastos, rentabilidade e fundamentos

- **Gastos do dia a dia** (aba Contas): lançamentos à mão ou importados do extrato do banco e da fatura do cartão (OFX
  ou CSV), com categoria automática pela descrição (iFood -> Alimentação fora, Uber -> Transporte...). Quando a pessoa
  corrige uma categoria, o app aprende e aplica aos parecidos. Limite por categoria com aviso ao passar de 80% e de
  100%, comparação com o mês anterior e com a média, e gráfico dos últimos meses. Pagamento de fatura e aplicações não
  contam como gasto (a fatura é a soma das compras; aplicar é guardar). Importar o mesmo extrato duas vezes não duplica.
- **Rentabilidade e proventos** (Resumo): a carteira contra CDI, Ibovespa e IPCA em 1, 3, 6, 12 e 24 meses, com
  gráfico e "% do CDI". Sem histórico, mede a carteira de hoje; com as compras e vendas importadas da B3, mostra o
  resultado real desde a primeira compra (Dietz modificado, mês a mês). Proventos dos últimos 12 meses por mês e por
  ativo, com retorno sobre o preço pago, e a projeção dos próximos 12 meses.
- **Importar da B3** (Ativos): planilhas da Área do Investidor (Posição, Negociação e Movimentação, em Excel ou CSV),
  reconhecidas pelo nome das colunas. Soma o mesmo ativo em corretoras diferentes, lê Tesouro Direto e CDB/LCI/LCA,
  calcula o preço médio e guarda os proventos recebidos. Não duplica ao importar de novo. A planilha é descartada.
- **Fundamentos e ranking** (Ativos e Mercado): P/L, P/VP, dividend yield, ROE, margens, dívida líquida/EBITDA, payout,
  crescimento da receita, valor de mercado e liquidez, cada um com a mediana do setor e uma explicação; proventos por
  ano (10 anos), dividend yield médio de 5 anos e crescimento dos proventos. Ranking das ações e dos FIIs da lista,
  ordenável e filtrável por setor. Os balanços vêm do Yahoo Finance, que tem falhas para empresas brasileiras: preço,
  dividend yield e liquidez são calculados pelo app, e o P/L só aparece quando duas contas independentes batem.

## Regras de gestão de risco

Valem com ou sem IA (e a IA recebe as mesmas regras e só os ativos que passam nelas):

- **Dados limpos:** cotações erradas do Yahoo são corrigidas antes de qualquer conta. Um salto de mais de 40% num dia que
  se desfaz em até 10 pregões sai da série; um salto de mais de 90% para baixo ou de 400% para cima num único dia é
  tratado como desdobramento ou grupamento não ajustado. Quedas reais, mesmo grandes, ficam.
- **Liquidez:** ativo novo só entra se negociar ao menos R$ 10 milhões por dia (ações) ou R$ 2 milhões (FIIs), pela
  mediana de 3 meses. Os que a pessoa já tem não são vendidos por isso, mas recebem alerta.
- **Histórico mínimo:** ativo novo precisa de 3 anos na bolsa.
- **Peso pelo risco:** nenhum papel individual passa de 10% da carteira; no máximo um novo por setor; quem oscila mais
  que o normal da classe (30% ao ano em ações, 15% em FIIs) entra com peso proporcionalmente menor (até a metade).
  Alerta quando ações e FIIs de um mesmo setor somam mais de 25% da carteira.
- **Armadilha de dividendos:** dividend yield muito acima do normal, ou alto porque o preço despencou, recebe aviso de
  que pode não se repetir. É só aviso: no teste com o passado, penalizar esses casos na escolha não melhorou o resultado.
- **Sem migalhas:** ativo novo que ficaria com menos de 1,5% da carteira vai para a renda fixa.

## Primeira conta

A primeira conta criada herda a carteira salva na época em que o app tinha uma senha única. Ativos que estavam só no
navegador de um aparelho são oferecidos para a pessoa que entrar nele (ela confirma se são dela).

## Quanto o app acerta

Nenhuma ferramenta acerta o mercado sempre. O app mede os próprios acertos e mostra o resultado na aba Mercado:

- **Teste com o passado:** as regras de indicadores são aplicadas no início de cada mês dos últimos 20 anos, só com os
  dados de cada data, e o resultado é medido 3, 6 e 12 meses depois contra o CDI (série 4391 do Banco Central). Um sinal
  de compra acerta quando o ativo rende mais que o CDI; um de venda, quando rende menos. A "taxa base" mostra com que
  frequência o ativo bate o CDI sem sinal nenhum. A IA não entra nesse teste, porque ela já sabe o que aconteceu depois.
- **Teste da escolha de ações e FIIs:** a regra que escolhe os complementos da carteira (retorno de 3 anos acima do CDI
  por unidade de risco, um papel por setor) é aplicada no fim de cada mês do passado e comparada com comprar todos os
  papéis da lista em partes iguais. Com os dados de novembro de 2026: nas ações, as escolhidas ganharam da lista em 55%
  dos meses, +2,3 p.p. ao ano em média (vantagem maior até 2014 do que depois); nos FIIs, escolher não ajudou. Por isso
  ações e FIIs individuais são só complemento (até 10% cada) e o núcleo fica em ETFs e fundos amplos. A lista só tem
  quem existe hoje (viés de sobrevivência), então a comparação justa é escolhidos x lista toda, não x Ibovespa.
- **Histórico real:** cada sinal de compra ou venda (da IA e das regras) é guardado com data e preço e conferido depois
  de 3, 6 e 12 meses, separado por quem deu o sinal: IA, regras ou as duas juntas.
- **Segunda opinião:** toda análise da IA é comparada com a das regras. Quando discordam, o app mostra "opiniões
  divergentes, confiança baixa" e não manda aviso de compra ou venda; o aviso só sai quando as duas concordam.
- **Checagem dos números:** cada número citado num texto da IA precisa existir nos dados que o app calculou ou recebeu.
  Se não existir, o texto é trocado pela explicação das regras, e a tela diz quantos textos foram conferidos e trocados.
