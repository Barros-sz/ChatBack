import sys

if sys.platform != "win32":
    try:
        from gevent import monkey
        monkey.patch_all()
    except ImportError:
        print("Gevent não instalado!")

from flask import Flask, request, session, jsonify
from flask_socketio import SocketIO, emit
from google import genai
from google.genai import types
from dotenv import load_dotenv
from uuid import uuid4
import os

# Carrega as variáveis ocultas do arquivo .env (como a chave da API do Gemini)
load_dotenv()

# Define qual versão da IA vamos usar. O modelo "flash" é rápido e ideal para chatbots.
MODELO = "gemini-3.1-flash-lite"

# Aqui definimos o "Prompt de Sistema". É a personalidade e as regras que o bot deve seguir.
instrucoes = """
Você é o "Mano Peixe", um torcedor fanático, parceiro e casca-grossa do Santos Futebol Clube, diretamente das arquibancadas da Vila Belmiro (a Baixada Santista).
Sua personalidade e regras de comportamento são:
1. **Fidelidade ao Peixe:** Você respira Santos FC. Suas referências são Pelé (o Rei), Neymar (o Menino da Vila), a lendária Vila Belmiro (o Alçapão), a história dos Meninos da Vila e a glória de ser o único time com três Copas Libertadores e duas Intercontinentais no topo do futebol brasileiro.
2. **Linguajar da Baixada Santista:** Use gírias locais e típicas de torcida da Baixada. Exemplos: "tu" (ex: "tu é", "tu tá", "tu viu", "tu quer" com concordância coloquial), "parça", "mano", "mó da hora", "mó cara", "bolado", "papo reto", "cair caiçara", "canal" (como "lá nos canais de Santos"), "bagulho é o seguinte", "marrento", "baixar a bola".
3. **Relação com o Usuário:** 
   - Se o usuário for santista, trate-o como irmão, parceiro de arquibancada, com muita alegria e empolgação ("Aí sim, meu parça!", "Alvinegro praiano de coração!", "Cola na Vila com o bonde!").
   - Se o usuário disser ou der a entender que torce para outro time (especialmente rivais: Palmeiras, Corinthians, São Paulo), reaja com total desprezo, piadas ácidas, deboche e indignação.
     - Palmeiras: chame de "sem mundial", "porquinho", "sem copinha e sem mundial", zoe que eles choram na fila.
     - Corinthians: chame de "gambá", "curica", zoe o "itaquerão", as dívidas, e diga que freguês tem sempre razão.
     - São Paulo: chame de "bambi", "trikas", zoe que são torcedores "nutella" de panetone que não aguentam a pressão da Vila.
   - Se o usuário ofender você ou o Santos, responda com gíria pesada de torcida, mandando "baixar a bola", "respeita o octacampeão", "aqui é Vila, rapaz", mantendo a conversa sem palavrões de baixo calão.
4. **Estilo de Resposta:** Respostas diretas, sentimentais, informais, às vezes usando LETRAS MAIÚSCULAS para dar ênfase em gritos de torcida (ex: "SANTOS!", "VILA BELMIRO!", "PELÉ É REI!"). Mantenha as respostas curtas, rápidas e cheias de gírias, como se estivesse conversando antes de um jogo clássico na Vila Belmiro.
"""

# Inicializa a conexão com a inteligência artificial do Google usando a chave da API
client = genai.Client(api_key=os.getenv("GENAI_KEY"))

# Cria o nosso aplicativo web principal (o servidor)
app = Flask(__name__)

# A 'secret_key' funciona como uma senha interna do servidor para proteger 
# e criptografar os dados da sessão (as "lembranças" de quem é quem).
app.secret_key = "ch@tb07"

# Adiciona a funcionalidade de WebSockets (comunicação em tempo real) ao nosso app.
# O 'cors_allowed_origins="*"' é crucial: ele permite que o nosso front-end (HTML/JS) 
# consiga se conectar com esse back-end, mesmo que estejam em arquivos ou portas diferentes.
socketio = SocketIO(app, cors_allowed_origins="*")

# Dicionário que funciona como a "memória temporária" do servidor. 
# Ele guarda a conversa de cada aluno separadamente usando um ID único.
active_chats = {}

def get_user_chat():
    """
    Função principal de gerenciamento de usuários.
    Ela recupera a conversa correta baseada no 'session_id' enviado pelo cliente.
    """
    # Passo 1: Busca o session_id nos argumentos do handshake do Socket.IO ou na sessão normal
    session_id = request.args.get('session_id')
    
    if not session_id or session_id == 'undefined' or session_id == 'null' or session_id.strip() == '':
        if 'session_id' not in session:
            session['session_id'] = str(uuid4())
            print(f"Nova sessão Flask HTTP criada: {session['session_id']}")
        session_id = session['session_id']
    else:
        session_id = session_id.strip()

    # Passo 2: Se o usuário já tem um ID, mas ainda não tem uma conversa aberta com o Gemini...
    if session_id not in active_chats or active_chats[session_id] is None:
        print(f"Criando/Recriando chat Gemini para session_id: {session_id}")
        try:
            # ...nós criamos uma nova conversa e passamos as instruções (personalidade).
            chat_session = client.chats.create(
                model=MODELO,
                config=types.GenerateContentConfig(system_instruction=instrucoes)
            )
            # Guardamos essa conversa no nosso dicionário (memória).
            active_chats[session_id] = chat_session
            print(f"Novo chat Gemini criado e armazenado para {session_id}")
        except Exception as e:
            app.logger.error(f"Erro ao criar chat Gemini para {session_id}: {e}", exc_info=True)
            raise  # Se der erro aqui, repassa para o sistema avisar que falhou
    
    # Retorna o histórico de mensagens exato daquele usuário e seu session_id correspondente.
    return active_chats[session_id], session_id

# Rota simples para verificar se o servidor está rodando.
# Ao acessar o localhost no navegador, o aluno verá este aviso em formato JSON.
@app.route('/')
def root():
    return jsonify({
        "api-websocket": "chatbot",
        "status": "ok"
    })


# ------------------------------------------------------------------
# EVENTOS SOCKET.IO (Onde a mágica do tempo real acontece)
# ------------------------------------------------------------------

@socketio.on('connect')
def handle_connect():
    """
    EVENTO: Disparado no momento exato em que o Front-end (navegador) se conecta ao servidor.
    """
    print(f"Cliente conectado: {request.sid}")
    
    try:
        # Tenta obter ou criar a sessão do usuário assim que ele entra
        _, user_session_id = get_user_chat()
        print(f"Sessão para {request.sid} usa session_id: {user_session_id}")
        
        # O comando 'emit' serve para enviar um pacote de dados do servidor PARA o front-end.
        emit('status_conexao', {'data': 'Conectado com sucesso!', 'session_id': user_session_id})
    except Exception as e:
        app.logger.error(f"Erro durante o evento connect para {request.sid}: {e}", exc_info=True)
        emit('erro', {'erro': 'Falha ao inicializar a sessão de chat no servidor.'})


@socketio.on('enviar_mensagem')
def handle_enviar_mensagem(data):
    """
    EVENTO: O Front-end mandou uma mensagem (ex: o usuário clicou em 'Enviar' no chat).
    A variável 'data' traz os dados enviados pelo HTML (o texto que o usuário digitou).
    """
    try:
        # Pega o texto de dentro do dicionário enviado pelo JS
        mensagem_usuario = data.get("mensagem")

        # Validação básica: não deixa enviar mensagens vazias
        if not mensagem_usuario:
            emit('erro', {"erro": "Mensagem não pode ser vazia."})
            return

        # Puxa o histórico de conversa desse aluno específico
        user_chat, user_session_id = get_user_chat()
        if user_chat is None:
            emit('erro', {"erro": "Sessão de chat não pôde ser estabelecida."})
            return

        app.logger.info(f"Mensagem recebida de {user_session_id}: {mensagem_usuario}")

        # ==========================================
        # COMUNICAÇÃO COM O GOOGLE GEMINI
        # ==========================================
        # Aqui o nosso servidor repassa a pergunta para a IA do Google...
        resposta_gemini = user_chat.send_message(mensagem_usuario)

        # ... e aqui extraímos apenas o texto da resposta que o Gemini devolveu.
        resposta_texto = (
            resposta_gemini.text
            if hasattr(resposta_gemini, 'text')
            else resposta_gemini.candidates[0].content.parts[0].text
        )
        
        # O servidor usa o 'emit' para devolver a resposta final do bot lá para a tela do Front-end.
        emit('nova_mensagem', {"remetente": "bot", "texto": resposta_texto, "session_id": user_session_id})
        app.logger.info(f"Resposta enviada para {user_session_id}: {resposta_texto}")

    except Exception as e:
        app.logger.error(f"Erro ao processar 'enviar_mensagem': {e}", exc_info=True)
        # Se algo quebrar (ex: falha de internet), avisamos o front-end educadamente.
        emit('erro', {"erro": f"Ocorreu um erro no servidor: {str(e)}"})


@socketio.on('disconnect')
def handle_disconnect():
    """
    EVENTO: Disparado quando o usuário fecha a aba do navegador ou perde a conexão.
    """
    print(f"Cliente desconectado: {request.sid}")


# Inicia o servidor local. A porta padrão do Flask costuma ser a 5000.
if __name__ == "__main__":
    socketio.run(app)
