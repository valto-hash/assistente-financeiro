"""Servidor de teste da interface: dados de mercado simulados, Google simulado (token 'tok-<nome>')."""
import os, sys
os.environ.setdefault("APP_TOKEN", "")
os.environ.update(GOOGLE_CLIENT_ID=os.getenv("GOOGLE_CLIENT_ID", "cliente.apps.googleusercontent.com"), ADMIN_EMAILS="dono@ex.com",
                  CODIGOS_PREMIUM="AMIGOS30:30", SMTP_HOST="smtp.exemplo", SMTP_REMETENTE="app@ex.com", MERCADOPAGO_TOKEN="TEST-1")
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mocks, server, uvicorn
def fake_verificar(cred):
    nome = cred.replace("tok-", "")
    return {"sub": "g-" + nome, "email": f"{nome}@gmail.com", "email_verified": True, "name": nome.capitalize() + " Teste"}
server.verificar_google = fake_verificar
server.enviar_email = lambda para, assunto, texto: open(os.environ["DATA_DIR"] + "/ultimo_email.txt", "w").write(texto)
uvicorn.run(server.app, host="127.0.0.1", port=8765, log_level="warning")
