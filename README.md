# Assistente Financeiro

Carteira de investimentos com recomendações explicadas, simulação do futuro, contas do mês e avisos.
Cada pessoa tem a própria conta: carteira, contas e avisos ficam separados.

## Rodar

```bash
docker build -t assistente . && docker run -p 8000:8000 --env-file .env assistente
```

## Configuração (variáveis de ambiente)

| Variável | Para quê |
|---|---|
| `CODIGO_CONVITE` (ou `APP_TOKEN`) | Código exigido para criar conta. Compartilhe só com quem pode usar o app. Sem nenhum dos dois, o cadastro fica aberto a qualquer pessoa. |
| `DATABASE_URL` | PostgreSQL onde ficam contas, carteiras e avisos (recomendado). Sem ele, os dados ficam em arquivos em `DATA_DIR`. |
| `DATA_DIR` | Pasta dos arquivos de dados quando não há `DATABASE_URL`. Precisa ser um disco persistente, senão tudo some no próximo deploy. |
| `ANTHROPIC_API_KEY` | Opcional. Com ela, a IA (Claude) lê notícias, explica decisões e lê fotos de boletos. Sem ela, o app usa o motor de regras. `USAR_IA=nao` desliga a IA mesmo com a chave. |
| `MODEL` | Modelo do Claude nas análises de cada ativo, no panorama e na leitura de boletos (padrão `claude-sonnet-5-5`). |
| `MODELO_DECISOES`, `EFFORT_DECISOES` | Modelo e nível de raciocínio da carteira recomendada, onde saem as decisões de comprar, manter e vender (padrão `claude-opus-5-5` com `high`). Se o modelo não estiver disponível na conta, o app usa `MODEL`. |
| `CRON_CHAVE` | Opcional. Se o servidor desliga quando ninguém usa (planos gratuitos), configure esta chave e um agendador externo para chamar `POST /api/cron/avisos` com o cabeçalho `X-Cron-Chave` a cada 30 minutos. |
| `AVISOS_INTERVALO_MIN` | Intervalo da verificação de avisos em minutos (padrão 30). `AVISOS_AUTOMATICOS=nao` desliga a verificação interna. |
| `VAPID_CHAVE_PRIVADA`, `VAPID_CONTATO` | Opcionais. Chave das notificações push (se não definida, é gerada uma vez e guardada no armazenamento) e contato (`mailto:` ou `https:`) enviado aos serviços de push. |

Notificações no celular exigem o app servido por HTTPS. No iPhone, só funcionam com o app adicionado à Tela de Início
(Compartilhar → Adicionar à Tela de Início).

## Primeira conta

A primeira conta criada herda a carteira salva na época em que o app tinha uma senha única. Ativos que estavam só no
navegador de um aparelho são oferecidos para a pessoa que entrar nele (ela confirma se são dela).

## Quanto o app acerta

Nenhuma ferramenta acerta o mercado sempre. O app mede os próprios acertos e mostra o resultado na aba Mercado:

- **Teste com o passado:** as regras de indicadores são aplicadas no início de cada mês dos últimos 20 anos, só com os
  dados de cada data, e o resultado é medido 3, 6 e 12 meses depois contra o CDI (série 4391 do Banco Central). Um sinal
  de compra acerta quando o ativo rende mais que o CDI; um de venda, quando rende menos. A "taxa base" mostra com que
  frequência o ativo bate o CDI sem sinal nenhum. A IA não entra nesse teste, porque ela já sabe o que aconteceu depois.
- **Histórico real:** cada sinal de compra ou venda (da IA e das regras) é guardado com data e preço e conferido depois
  de 3, 6 e 12 meses, separado por quem deu o sinal: IA, regras ou as duas juntas.
- **Segunda opinião:** toda análise da IA é comparada com a das regras. Quando discordam, o app mostra "opiniões
  divergentes, confiança baixa" e não manda aviso de compra ou venda; o aviso só sai quando as duas concordam.
- **Checagem dos números:** cada número citado num texto da IA precisa existir nos dados que o app calculou ou recebeu.
  Se não existir, o texto é trocado pela explicação das regras, e a tela diz quantos textos foram conferidos e trocados.
