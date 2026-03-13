import urllib.request
import urllib.parse
import smtplib
import threading
from email.message import EmailMessage
from app.state import state

# --- MOTORES DE NOTIFICACIÓN PUSH ---
# Se utiliza el hilo de Python ("Threading") para cada mensaje enviado, 
# asegurando que si la red tarda en responder, el "Control Loop" térmico nunca se bloquee.

def _send_telegram(msg):
    """Envia mensajes utilizando la API nativa de un Bot de Telegram para mayor seguridad (Sin dependencias costosas)"""
    token, chat_id = state.get("telegram_token", "").strip(), state.get("telegram_chat_id", "").strip()
    if token and chat_id:
        try: 
            # Parse_mode = Markdown ayuda a darle formato bonito a las alertas de temperatura/S.M.A.R.T.
            data = urllib.parse.urlencode({'chat_id': chat_id, 'text': msg, 'parse_mode': 'Markdown'}).encode()
            urllib.request.urlopen(f"https://api.telegram.org/bot{token}/sendMessage", data=data, timeout=5)
        except: pass

def _send_email(sub, body):
    """Protocolo estándar SMTP para servidores de correo corporativo / NAS"""
    s_srv, s_user, s_pass, s_dest = state.get("smtp_server"), state.get("smtp_user"), state.get("smtp_pass"), state.get("smtp_dest")
    if s_srv and s_user and s_pass and s_dest:
        try:
            msg = EmailMessage()
            msg.set_content(body)
            msg['Subject'] = sub
            msg['From'] = s_user
            msg['To'] = s_dest
            port, s_tls = int(state.get("smtp_port", 587)), state.get("smtp_tls", "starttls")

            if s_tls == "tls" or port == 465:
                # Servidores Modernos / Cloud / SSL por defecto
                with smtplib.SMTP_SSL(s_srv, port, timeout=10) as s: 
                    s.login(s_user, s_pass)
                    s.send_message(msg)
            else:
                # Legacy StartTLS o Puerto 587 Estándar
                with smtplib.SMTP(s_srv, port, timeout=10) as s:
                    if s_tls == "starttls": 
                        s.ehlo()
                        s.starttls()
                    s.login(s_user, s_pass)
                    s.send_message(msg)
        except Exception as e: 
            print(f"Email err: {e}")

def send_alert(tg_msg, email_sub, email_body):
    """Envoltorio principal: Lanza Múltiples Demonios No-Bloqueantes ('Daemon Threads') hacia redes externas"""
    threading.Thread(target=lambda: _send_telegram(tg_msg), daemon=True).start()
    threading.Thread(target=lambda: _send_email(email_sub, email_body), daemon=True).start()
