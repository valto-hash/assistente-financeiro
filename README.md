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
| `MODEL` | Modelo do Claude (padrão `claude-sonnet-5-5`). |
| `CRON_CHAVE` | Opcional. Se o servidor desliga quando ninguém usa (planos gratuitos), configure esta chave e um agendador externo para chamar `POST /api/cron/avisos` com o cabeçalho `X-Cron-Chave` a cada 30 minutos. |
| `AVISOS_INTERVALO_MIN` | Intervalo da verificação de avisos em minutos (padrão 30). `AVISOS_AUTOMATICOS=nao` desliga a verificação interna. |
| `VAPID_CHAVE_PRIVADA`, `VAPID_CONTATO` | Opcionais. Chave das notificações push (se não definida, é gerada uma vez e guardada no armazenamento) e contato (`mailto:` ou `https:`) enviado aos serviços de push. |

Notificações no celular exigem o app servido por HTTPS. No iPhone, só funcionam com o app adicionado à Tela de Início
(Compartilhar → Adicionar à Tela de Início).

## Primeira conta

A primeira conta criada herda a carteira salva na época em que o app tinha uma senha única. Ativos que estavam só no
navegador de um aparelho são oferecidos para a pessoa que entrar nele (ela confirma se são dela).
