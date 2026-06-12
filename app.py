import sys
import json
import os
from uuid import uuid4
from flask import Flask, request, session, jsonify
from flask_socketio import SocketIO, emit
from google import genai
from google.genai import types
from dotenv import load_dotenv

# Configuração do Gevent para ambientes não-Windows
if sys.platform != "win32":
    try:
        from gevent import monkey
        monkey.patch_all()
    except ImportError:
        print("Gevent não instalado!")

# Carrega as variáveis de ambiente (.env)
load_dotenv()

# Configuração do modelo do Gemini
MODELO = "gemini-3.5-flash"

# Carrega o System Prompt do arquivo JSON
with open("config.json", "r", encoding="utf-8") as f:
    dados = json.load(f)
    instrucoes = dados["system_prompt"]

# Inicializa o cliente da API do Gemini
client = genai.Client(api_key=os.getenv("GENAI_KEY"))

# Inicializa o Flask e configura o Socket.IO
app = Flask(__name__)
app.secret_key = "ch@tb07"
socketio = SocketIO(app, cors_allowed_origins="*")

# Dicionário para armazenar as sessões de chat ativas
active_chats = {}

def get_user_chat():
    """Recupera ou cria a sessão de chat do usuário baseada no ID de sessão."""
    session_id = request.args.get('session_id')
    
    # Valida e gera um session_id se necessário
    if not session_id or session_id in ['undefined', 'null'] or not session_id.strip():
        if 'session_id' not in session:
            session['session_id'] = str(uuid4())
        session_id = session['session_id']
    else:
        session_id = session_id.strip()

    # Cria um novo chat no Gemini caso não exista para esta sessão
    if session_id not in active_chats or active_chats[session_id] is None:
        try:
            chat_session = client.chats.create(
                model=MODELO,
                config=types.GenerateContentConfig(system_instruction=instrucoes)
            )
            active_chats[session_id] = chat_session
        except Exception as e:
            app.logger.error(f"Erro ao criar chat Gemini para {session_id}: {e}", exc_info=True)
            raise
    
    return active_chats[session_id], session_id

@app.route('/')
def root():
    """Rota de verificação de status do servidor."""
    return jsonify({
        "api-websocket": "chatbot",
        "status": "ok"
    })

# ------------------------------------------------------------------
# EVENTOS SOCKET.IO
# ------------------------------------------------------------------

@socketio.on('connect')
def handle_connect():
    """Trata a conexão inicial do usuário e vincula seu ID de sessão."""
    print(f"Cliente conectado: {request.sid}")
    try:
        _, user_session_id = get_user_chat()
        emit('status_conexao', {'data': 'Conectado com sucesso!', 'session_id': user_session_id})
    except Exception as e:
        app.logger.error(f"Erro no connect para {request.sid}: {e}", exc_info=True)
        emit('erro', {'erro': 'Falha ao inicializar a sessão de chat no servidor.'})

@socketio.on('enviar_mensagem')
def handle_enviar_mensagem(data):
    """Recebe a mensagem do front-end, envia ao Gemini e retorna a resposta."""
    try:
        mensagem_usuario = data.get("mensagem")

        if not mensagem_usuario:
            emit('erro', {"erro": "Mensagem não pode ser vazia."})
            return

        user_chat, user_session_id = get_user_chat()
        if user_chat is None:
            emit('erro', {"erro": "Sessão de chat não estabelecida."})
            return

        # Envia o input para o modelo e captura o texto retornado
        resposta_gemini = user_chat.send_message(mensagem_usuario)
        resposta_texto = resposta_gemini.text
        
        # Devolve a resposta estruturada para o front-end
        emit('nova_mensagem', {"remetente": "bot", "texto": resposta_texto, "session_id": user_session_id})

    except Exception as e:
        app.logger.error(f"Erro em 'enviar_mensagem': {e}", exc_info=True)
        emit('erro', {"erro": f"Ocorreu um erro no servidor: {str(e)}"})

@socketio.on('disconnect')
def handle_disconnect():
    """Trata a desconexão do cliente."""
    print(f"Cliente desconectado: {request.sid}")

if __name__ == "__main__":
    socketio.run(app)