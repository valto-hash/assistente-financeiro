"""Páginas públicas exigidas para publicar na Google Play: política de privacidade, termos de uso, exclusão de conta
pela web (sem precisar do app) e a página mostrada sem internet. Os dados do responsável vêm de variáveis de ambiente."""
import html
import os
from datetime import date


def _cfg():
    return {"app": os.getenv("APP_NOME", "Assistente Financeiro"),
            "resp": os.getenv("RESPONSAVEL", "o responsável pelo app"),
            "email": os.getenv("CONTATO_EMAIL", ""),
            "atualizado": os.getenv("POLITICA_DATA", date.today().strftime("%d/%m/%Y"))}


def _base(titulo, corpo, script=""):
    c = _cfg()
    return f"""<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{html.escape(titulo)} · {html.escape(c['app'])}</title>
<meta name="theme-color" content="#0b2a5b"><link rel="icon" href="/icone-192.png">
<style>
:root{{--bg:#f4f6fa;--sf:#fff;--ink:#14213d;--mut:#5b6478;--line:#e3e7ef;--acc:#2a78d6;--dn:#c2410c}}
@media (prefers-color-scheme:dark){{:root{{--bg:#0d1422;--sf:#151f33;--ink:#e8edf6;--mut:#9aa6bd;--line:#26324a;--acc:#6aa9ff;--dn:#ff8a5c}}}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:16px/1.6 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}}
header{{background:linear-gradient(160deg,#0b2a5b,#123f86);color:#fff;padding:28px 16px}}
header div,main{{max-width:760px;margin:0 auto}}header a{{color:#fff;opacity:.85;text-decoration:none;font-size:14px}}
h1{{margin:6px 0 0;font-size:26px;line-height:1.25}}main{{padding:20px 16px 48px}}
section{{background:var(--sf);border:1px solid var(--line);border-radius:14px;padding:4px 20px 16px;margin:0 0 14px}}
h2{{font-size:18px;margin:18px 0 6px}}p,li{{color:var(--ink)}}.mut{{color:var(--mut);font-size:14px}}a{{color:var(--acc)}}
label{{display:block;font-size:14px;font-weight:600;margin:12px 0 4px}}input{{width:100%;padding:11px 12px;border:1px solid var(--line);border-radius:10px;font:inherit;background:var(--bg);color:var(--ink)}}
button{{margin-top:16px;padding:12px 18px;border:0;border-radius:10px;font:inherit;font-weight:600;cursor:pointer;background:var(--dn);color:#fff}}
.msg{{margin-top:12px;font-weight:600}}
</style></head><body><header><div><a href="/">← {html.escape(c['app'])}</a><h1>{html.escape(titulo)}</h1></div></header>
<main>{corpo}</main>{script}</body></html>"""


def privacidade():
    c = _cfg()
    contato = f'<a href="mailto:{html.escape(c["email"])}">{html.escape(c["email"])}</a>' if c["email"] else "o e-mail de contato informado na loja de aplicativos"
    return _base("Política de privacidade", f"""
<p class="mut">Atualizada em {c['atualizado']}. Esta política explica, conforme a Lei Geral de Proteção de Dados (Lei 13.709/2018, LGPD),
quais dados o {html.escape(c['app'])} usa, para quê e como você controla seus dados. Responsável (controlador): {html.escape(c['resp'])}. Contato: {contato}.</p>
<section><h2>1. Dados que coletamos</h2><ul>
<li><b>Conta:</b> nome e e-mail. A senha é guardada apenas como um código irreversível (hash scrypt). Se você entrar com o Google, recebemos nome, e-mail e um identificador da sua conta Google; não recebemos sua senha do Google.</li>
<li><b>O que você informa no app:</b> ativos, quantidades e preços médios, saldos de renda fixa, perfil de investidor, respostas do teste de perfil, objetivo, renda mensal, contas do mês e alertas de preço.</li>
<li><b>Arquivos que você envia:</b> boletos, faturas e extratos são lidos para extrair nome, valor e vencimento das contas e não são guardados depois da leitura.</li>
<li><b>Dados técnicos:</b> endereço IP (só para proteger o login contra tentativas abusivas) e, se você ativar, o endereço de notificação do seu aparelho.</li>
<li><b>Assinatura:</b> a situação da sua assinatura (ativa, data de renovação). O pagamento é processado pelo Google Play ou pelo Mercado Pago; não recebemos dados do seu cartão.</li></ul></section>
<section><h2>2. Para que usamos</h2><ul>
<li>Prestar o serviço: mostrar sua carteira, calcular a carteira recomendada, simular o futuro, avisar de vencimentos e oportunidades (execução de contrato, art. 7º, V da LGPD).</li>
<li>Segurança da conta e prevenção de fraudes (legítimo interesse, art. 7º, IX).</li>
<li>Cobrança e controle da assinatura (execução de contrato).</li>
<li>Notificações no celular, só se você ativar (consentimento, art. 7º, I).</li></ul>
<p>Não vendemos seus dados, não mostramos anúncios e não usamos seus dados para publicidade.</p></section>
<section><h2>3. Com quem compartilhamos</h2><ul>
<li><b>Hospedagem e banco de dados</b>, onde o app funciona e seus dados ficam guardados.</li>
<li><b>Google</b>: login com o Google e cobrança pelo Google Play. <b>Mercado Pago</b>: cobrança de quem assina pelo site.</li>
<li><b>Inteligência artificial (Anthropic)</b>: no plano Premium, quando o servidor usa IA, os ativos, valores, perfil e objetivo da sua carteira são enviados para gerar as análises. Seu nome e e-mail não são enviados.</li>
<li><b>Fontes de cotações e notícias</b> (Yahoo Finance, Banco Central, Google Notícias): recebem apenas consultas públicas, como o código de um ativo; nenhum dado pessoal.</li>
<li>Serviços de notificação do seu navegador ou celular, quando você ativa os avisos.</li>
<li>Autoridades, quando a lei exigir.</li></ul></section>
<section><h2>4. Segurança e guarda</h2>
<p>Conexões criptografadas (HTTPS), senhas com hash, sessões com token de validade limitada e acesso restrito ao banco de dados.
Guardamos seus dados enquanto sua conta existir. Ao excluir a conta, apagamos na hora a conta e todos os dados dela, exceto o que a lei obrigar a manter.</p></section>
<section><h2>5. Seus direitos</h2>
<p>Você pode, a qualquer momento: ver e corrigir seus dados no próprio app; baixar uma cópia (menu da conta &gt; Backup);
excluir a conta e todos os dados (menu da conta &gt; Excluir minha conta, ou pela página <a href="/excluir-conta">excluir conta</a>);
revogar o consentimento das notificações; e pedir informações sobre o uso dos seus dados pelo contato acima (art. 18 da LGPD).
Você também pode reclamar à Autoridade Nacional de Proteção de Dados (ANPD).</p></section>
<section><h2>6. Avisos importantes</h2>
<p>O {html.escape(c['app'])} não é banco nem corretora: não guarda seu dinheiro e não executa ordens. As análises são automáticas, usam dados públicos
e não garantem resultado. Rentabilidade passada não garante rentabilidade futura. O app não é destinado a menores de 18 anos.</p>
<p>Podemos atualizar esta política; mudanças relevantes serão avisadas no app.</p></section>""")


def termos():
    c = _cfg()
    contato = f'<a href="mailto:{html.escape(c["email"])}">{html.escape(c["email"])}</a>' if c["email"] else "o e-mail de contato informado na loja de aplicativos"
    return _base("Termos de uso", f"""
<p class="mut">Atualizados em {c['atualizado']}. Ao criar uma conta você concorda com estes termos. Contato: {contato}.</p>
<section><h2>1. O serviço</h2><p>O {html.escape(c['app'])} organiza seus investimentos e contas, calcula uma carteira recomendada por regras
(e, no plano Premium, com inteligência artificial quando disponível), simula cenários futuros e envia avisos. Ele não é banco, corretora
ou gestora, não guarda dinheiro e não executa ordens: as decisões e operações são sempre suas.</p></section>
<section><h2>2. Sem garantia de resultado</h2><p>Investimentos têm riscos, inclusive de perda. Cotações e notícias vêm de fontes públicas
e podem ter atrasos ou erros. Simulações mostram possibilidades, não promessas. Rentabilidade passada não garante rentabilidade futura.</p></section>
<section><h2>3. Conta</h2><p>Você é responsável pelas informações que registra e por manter sua senha em segredo. Uma conta é pessoal.
Você pode excluir a conta a qualquer momento pelo app ou pela página <a href="/excluir-conta">excluir conta</a>.</p></section>
<section><h2>4. Planos e assinatura</h2><ul>
<li><b>Grátis:</b> funções limitadas, sem prazo. <b>Premium:</b> o app completo, por assinatura mensal ou anual, com renovação automática.</li>
<li>Novas contas podem ter um período de teste do Premium; ao fim dele, a conta volta ao plano grátis sem cobrança, a não ser que você assine.</li>
<li>Assinaturas feitas no app Android são cobradas e canceladas pelo Google Play (Play Store &gt; Pagamentos e assinaturas). As feitas pelo site,
pelo Mercado Pago. O cancelamento vale para a próxima renovação; o acesso continua até o fim do período pago.</li>
<li>Compras pela internet podem ser desistidas em até 7 dias (art. 49 do Código de Defesa do Consumidor); peça pelo contato acima ou pela loja.</li>
<li>Excluir a conta no app não cancela a assinatura na loja: cancele também por lá.</li></ul></section>
<section><h2>5. Uso adequado</h2><p>Não é permitido tentar acessar contas de outras pessoas, sobrecarregar o serviço ou usá-lo para fins ilegais.
Podemos suspender contas que violem estes termos.</p></section>
<section><h2>6. Disponibilidade e mudanças</h2><p>Buscamos manter o app disponível, mas podem ocorrer interrupções. Podemos mudar funções e preços;
mudanças de preço valem só a partir da renovação seguinte, com aviso prévio.</p></section>
<section><h2>7. Lei aplicável</h2><p>Estes termos seguem as leis do Brasil, inclusive o Código de Defesa do Consumidor e a LGPD.</p></section>""")


def excluir_conta(google_client_id=""):
    c = _cfg()
    google = (f"""<div id="g_id_onload" data-client_id="{html.escape(google_client_id)}" data-callback="porGoogle"></div>
<p class="mut">Se você entra com o Google:</p><div class="g_id_signin" data-type="standard" data-text="continue_with"></div>
<script src="https://accounts.google.com/gsi/client" async></script>""" if google_client_id else "")
    corpo = f"""
<section><h2>Excluir sua conta do {html.escape(c['app'])}</h2>
<p>Isto apaga <b>para sempre</b> sua conta e todos os dados dela: carteira, objetivo e perfil, contas do mês, avisos e preferências.
Não dá para desfazer. Se você tem assinatura, cancele também no Google Play (Play Store &gt; Pagamentos e assinaturas) ou no Mercado Pago:
excluir a conta não cancela a cobrança na loja.</p>
<form id="f" autocomplete="on"><label for="e">E-mail da conta</label><input id="e" type="email" required autocomplete="email">
<label for="s">Senha</label><input id="s" type="password" required autocomplete="current-password">
<button type="submit">Excluir minha conta e meus dados</button></form>
{google}
<p id="m" class="msg" role="status"></p>
<p class="mut">Também é possível excluir pelo próprio app: menu da conta &gt; Excluir minha conta.
{f'Dúvidas: <a href="mailto:{html.escape(c["email"])}">{html.escape(c["email"])}</a>.' if c['email'] else ''}</p></section>"""
    script = """<script>
const m = document.getElementById('m');
async function apagar(token, confirmacao) {
  const r = await fetch('/api/conta', {method: 'DELETE', headers: {'Content-Type': 'application/json', Authorization: 'Bearer ' + token}, body: JSON.stringify({senha: confirmacao})});
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || 'Não foi possível excluir.');
  m.textContent = 'Pronto: sua conta e todos os seus dados foram excluídos.'; document.getElementById('f').remove();
}
document.getElementById('f').onsubmit = async e => {
  e.preventDefault(); m.textContent = 'Conferindo…';
  const email = document.getElementById('e').value, senha = document.getElementById('s').value;
  if (!confirm('Excluir para sempre a conta ' + email + '?')) { m.textContent = ''; return; }
  try {
    const r = await fetch('/api/conta/entrar', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({email, senha})});
    const j = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(j.detail || 'E-mail ou senha incorretos.');
    await apagar(j.token, senha);
  } catch (er) { m.textContent = er.message; }
};
async function porGoogle(resp) {
  try {
    const r = await fetch('/api/conta/google', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({credencial: resp.credential, somente_entrar: true})});
    const j = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(j.detail || 'Não encontrei uma conta para este Google.');
    if (!confirm('Excluir para sempre a conta ' + j.usuario.email + '?')) return;
    await apagar(j.token, j.usuario.tem_senha ? prompt('Digite a senha da conta para confirmar:') || '' : 'EXCLUIR');
  } catch (er) { m.textContent = er.message; }
}
</script>"""
    return _base("Excluir conta", corpo, script)


OFFLINE = """<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Sem conexão</title><meta name="theme-color" content="#0b2a5b"><style>body{margin:0;min-height:100vh;display:grid;place-items:center;
background:linear-gradient(160deg,#0b2a5b,#123f86);color:#fff;font:16px/1.5 system-ui,sans-serif;text-align:center;padding:24px}
button{margin-top:16px;padding:12px 20px;border:0;border-radius:10px;font:inherit;font-weight:600;background:#fff;color:#0b2a5b}</style></head>
<body><div><h1 style="font-size:22px">Sem conexão com a internet</h1><p>As cotações e a sua carteira precisam de internet.<br>Confira a conexão e tente de novo.</p>
<button onclick="location.reload()">Tentar de novo</button></div></body></html>"""
