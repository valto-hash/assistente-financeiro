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
