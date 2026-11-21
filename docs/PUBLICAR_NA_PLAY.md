# Publicar o app na Google Play

O app é um site instalável (PWA). Na Play Store ele vai como uma **Trusted Web Activity (TWA)**: um app Android
pequeno que abre o site em tela cheia, sem barra do navegador, com notificações e cobrança pelo Google Play.
Toda atualização feita no servidor chega na hora para quem tem o app, sem publicar nova versão na loja.

## 1. Antes de começar
- **Domínio próprio com HTTPS** (ex.: `app.seudominio.com.br`). Veja [HOSPEDAGEM.md](HOSPEDAGEM.md).
- **Banco de dados permanente** (`DATABASE_URL`). Sem ele, contas e carteiras somem a cada atualização do servidor.
- Preencha no servidor: `APP_NOME`, `RESPONSAVEL`, `CONTATO_EMAIL`, `ADMIN_EMAILS` e, se quiser, `GOOGLE_CLIENT_ID` e `SMTP_*`.
- Confira as páginas que a loja exige: `https://SEU-DOMINIO/privacidade`, `/termos` e `/excluir-conta`.
- **Leia a seção "Regras para vender" no fim deste guia antes de cobrar.**

## 2. Conta de desenvolvedor
- Crie em https://play.google.com/console (taxa única de US$ 25).
- Conta **pessoal** criada depois de nov/2023: antes de publicar, faça um **teste fechado com pelo menos 12 testadores
  por 14 dias seguidos**. Conta de **organização** (com CNPJ e número D-U-N-S) não tem essa exigência.

## 3. Gerar o app Android (Bubblewrap)
Precisa de Node.js 18+ (o Bubblewrap baixa sozinho o Java e o Android SDK na primeira vez).
```bash
npm i -g @bubblewrap/cli
cd android
# edite twa-manifest.json: troque "seudominio" pelo seu domínio e escolha o packageId (não dá para mudar depois)
bubblewrap init --manifest https://SEU-DOMINIO/manifest.webmanifest   # ou use o twa-manifest.json desta pasta
bubblewrap build        # gera app-release-bundle.aab, assinado com a chave de upload
```
Guarde a chave (`chave-de-upload.keystore`) e as senhas num lugar seguro: sem elas não dá para atualizar o app.
O `twa-manifest.json` já liga a cobrança pelo Google Play (`features.playBilling`).

Alternativa sem linha de comando: https://www.pwabuilder.com gera o pacote Android a partir do endereço do site
(confira se a opção de cobrança pelo Google Play está ligada; se não estiver, use o Bubblewrap).

## 4. Ligar o app ao site (some a barra do navegador)
```bash
bubblewrap fingerprint list     # impressão digital SHA-256 da chave de upload
```
No Play Console, em *Teste e lançamento > Configuração > Integridade do app*, copie também a SHA-256 da
**chave de assinatura do app** (a Google assina o app final). Coloque as duas no servidor:
```
ANDROID_PACKAGE=br.com.seudominio.financeiro
ANDROID_SHA256=AA:BB:...(upload),CC:DD:...(Play)
```
Teste em `https://SEU-DOMINIO/.well-known/assetlinks.json`.

## 5. Assinaturas (Google Play Billing)
1. Play Console > *Monetizar > Produtos > Assinaturas*: crie `premium_mensal` e `premium_anual` (com um plano base
   de renovação automática cada; o teste grátis pode ser uma oferta).
2. Google Cloud: crie uma **conta de serviço**, ative a *Google Play Android Developer API* e, no Play Console
   (*Usuários e permissões*), dê a ela acesso para ver dados financeiros e gerenciar pedidos.
   Coloque o JSON dela em `GOOGLE_PLAY_CONTA_SERVICO`.
3. Notificações em tempo real (renovação, cancelamento, reembolso): crie um tópico no Pub/Sub, ligue-o em
   *Monetizar > Configuração de monetização* e faça uma assinatura **push** para
   `https://SEU-DOMINIO/api/assinatura/google/notificacao?chave=UM_SEGREDO` (o mesmo valor em `RTDN_CHAVE`).
4. Adicione contas de teste em *Configuração > Teste de licença* para comprar sem ser cobrado.

O app só oferece a compra pelo Google Play quando aberto pelo app Android; no site, oferece o Mercado Pago
(`MERCADOPAGO_TOKEN`). Dentro do app da Play Store não há link para pagar fora, como exige a política da loja.

## 6. Ficha da loja
- Ícone 512x512 e imagem de destaque 1024x500: pasta `loja/`.
- Capturas de tela: `static/tela-celular-*.png` (geradas a partir do app).
- Categoria: **Finanças**. Classificação de conteúdo: questionário no Play Console.
- **Declaração de recursos financeiros** (*Conteúdo do app*): informe que o app oferece recomendações/planejamento
  de investimentos e não é banco, corretora nem empréstimo.
- **Segurança dos dados**: o app coleta nome, e-mail, dados financeiros informados pela pessoa (carteira, renda,
  contas) e identificadores do aparelho para notificações; dados criptografados em trânsito; a pessoa pode pedir
  a exclusão (link: `https://SEU-DOMINIO/excluir-conta`). Dados compartilhados com: Google (login e cobrança),
  Mercado Pago (cobrança) e, se houver IA, Anthropic (dados da carteira, sem nome ou e-mail).
- Política de privacidade: `https://SEU-DOMINIO/privacidade`.

## 7. Regras para vender (importante)
Recomendar a compra ou venda de ativos específicos para uma pessoa, considerando o perfil dela, é **consultoria de
valores mobiliários** (Resolução CVM 19/2021), e a CVM diz que robôs de consultoria seguem as mesmas regras, inclusive
o registro. Antes de cobrar por recomendações personalizadas, converse com um advogado de mercado de capitais sobre:
(1) registrar-se como consultor na CVM (exige certificação aprovada pela CVM); (2) vender o app para consultores,
assessores e gestoras registrados, que o usam com os clientes deles; ou (3) oferecer ao público só as funções de
organização, simulação e educação, sem indicar ativos específicos.
