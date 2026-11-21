# Onde hospedar (fora do Render)

O app é um contêiner Docker comum: roda em qualquer lugar que rode Docker. O que importa é **guardar os dados num
lugar permanente**. No Render (plano grátis), o disco do servidor é apagado a cada atualização: sem `DATABASE_URL`,
as contas e carteiras somem. O app avisa isso no menu da conta (para os administradores) e nos logs.

## Banco de dados permanente e gratuito
- **Neon** (https://neon.tech): PostgreSQL gratuito, sem prazo de validade. Crie um projeto e copie a "connection
  string" para `DATABASE_URL` (ela termina com `?sslmode=require`).
- Alternativas: Supabase (o grátis pausa após 1 semana sem uso) ou o PostgreSQL do próprio
  servidor (docker-compose abaixo).

## Opção 1: servidor próprio com docker-compose (mais controle, a partir de ~R$ 25/mês ou grátis na Oracle Cloud)
Qualquer VPS (Hetzner, DigitalOcean, Contabo, Magalu Cloud, Oracle Cloud "Always Free"...):
```bash
git clone https://github.com/SEU-USUARIO/assistente-financeiro && cd assistente-financeiro
cp .env.example .env && nano .env     # DOMINIO, POSTGRES_SENHA e o resto
docker compose up -d --build          # app + PostgreSQL + HTTPS automático (Caddy)
```
Atualizar: `git pull && docker compose up -d --build`. Os dados ficam no volume `banco`.
Backup diário: `docker compose exec banco pg_dump -U app app > backup.sql` (agende no cron).

## Opção 2: Google Cloud Run + Neon (paga só pelo uso; costuma sair de graça para poucos usuários)
```bash
gcloud run deploy financeiro --source . --region southamerica-east1 --allow-unauthenticated \
  --set-env-vars DATABASE_URL=...,ADMIN_EMAILS=...,AVISOS_AUTOMATICOS=nao,CRON_CHAVE=um-segredo
```
O Cloud Run desliga o servidor quando ninguém usa, então os avisos automáticos não rodam sozinhos: crie no
Cloud Scheduler uma chamada a cada 30 min para `POST https://SEU-SERVICO/api/cron/avisos` com o cabeçalho
`X-Cron-Chave: um-segredo`.

## Opção 3: Fly.io ou Railway + Neon
- Fly.io: `fly launch` (usa o Dockerfile) e `fly secrets set DATABASE_URL=... ADMIN_EMAILS=...`.
- Railway: "Deploy from GitHub repo" e adicione as variáveis; ele também oferece PostgreSQL.

## Mudar do Render sem perder dados
1. Ainda no Render, entre no app com um e-mail listado em `ADMIN_EMAILS` e use *menu da conta > Exportar todos os
   dados* (ou `GET /api/admin/exportar`). Isso baixa um arquivo `.jsonl` com tudo.
2. No servidor novo (com `DATABASE_URL` configurado): `python armazem.py importar backup.jsonl`
   (ou envie o arquivo para `POST /api/admin/importar` logado como administrador).
3. Aponte o domínio para o servidor novo.

Mesmo sem o backup, quem usava o app não perde a carteira: ela também fica guardada no aparelho, e ao criar a conta
de novo com o mesmo e-mail (ou entrar com o Google) o app recupera a conta com o mesmo identificador e reenvia os dados.

## Conferir
`https://SEU-DOMINIO/api/saude` mostra se o servidor está no ar e se o armazenamento é permanente.
