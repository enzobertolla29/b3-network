import socket
import threading
import time
import random
from datetime import datetime
from contextlib import suppress
import sys
import queue
import json
import os

# Escuta em todas as interfaces de rede disponíveis
HOST = "0.0.0.0"
PORT = 9999
USUARIOS_FILE = "usuarios.json"


lock = threading.RLock()
running = threading.Event()
running.set()  

cotacoes = {
    "PETR4": 38.50,
    "VALE3": 65.20,
    "ITUB4": 28.90
}

usuarios = {}

estados = {}
clientes = []
filas_envio = {}  # conn -> queue.Queue[str]


def carregar_usuarios():
    """Carrega usuarios.json se existir."""
    if not os.path.exists(USUARIOS_FILE):
        return
    try:
        with open(USUARIOS_FILE, "r", encoding="utf-8") as f:
            dados = json.load(f)
            with lock:
                usuarios.clear()
                usuarios.update(dados)
        print(f"[INFO] {len(dados)} usuário(s) carregado(s) de {USUARIOS_FILE}")
    except Exception as e:
        print(f"[ERRO] Falha ao carregar {USUARIOS_FILE}: {e}")


def salvar_usuarios():
    """Salva usuarios em usuarios.json."""
    try:
        with lock:
            copia = dict(usuarios)
        with open(USUARIOS_FILE, "w", encoding="utf-8") as f:
            json.dump(copia, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[ERRO] Falha ao salvar {USUARIOS_FILE}: {e}")


def send(conn, msg):
    #Envia a mensagem ao cliente em bytes com brakeline
    conn.sendall((msg + "\n").encode())     

def safe_send(conn, msg):
    """Enfileira mensagem para o cliente (proteção contra queda de conexão)."""
    with lock:
        q = filas_envio.get(conn)
    if q is None:
        return False

    try:
        q.put_nowait(msg)
        return True
    except Exception:
        return False

def broadcast(msg):
    with lock:
        copia = list(clientes)
    desconectados = []
    for conn in copia:
        if not safe_send(conn, msg):
            desconectados.append(conn)
    for conn in desconectados:
        cleanup_client(conn,save_first=False)  # Salva apenas no cleanup final para evitar múltiplas escritas simultâneas

def format_prices():
    with lock:
        linhas = ["[FEED] Cotações:"] + [f"  {ativo}: R$ {preco:.2f}" for ativo, preco in cotacoes.items()]
    return "\n".join(linhas)  


def format_help_server():
    return "\n".join([
        "[INFO] Comandos disponíveis:",
        "  :register <USUARIO> <SENHA> -> registrar novo usuário",
        "  :login <USUARIO> <SENHA>    -> autenticar-se",
        "  :logout                     -> encerra sessão (mantém conexão)",
        "  :quem                       -> exibe usuário logado",
        "  :buy <ATIVO> <QTD>          -> ordem de compra",
        "  :sell <ATIVO> <QTD>         -> ordem de venda",
        "  :carteira                   -> exibe saldo e ativos",
        "  :exit                       -> encerra conexão"
    ])


def price_simulation_thread():
    while running.is_set():
        time.sleep(random.uniform(1.0, 2.0))  
        with lock:
            for ativo in cotacoes:
                variacao = round(random.uniform(-0.10, 0.10), 2)  
                novo_preco = round(cotacoes[ativo] + variacao, 2)
                cotacoes[ativo] = max(0.01, novo_preco) 

def feed_thread():
    while running.is_set():
        time.sleep(5)
        if running.is_set():
            broadcast(format_prices())


def parse_qtd(valor):
    """Valida quantidade inteira positiva."""
    try:
        qtd = int(valor)
        if qtd <= 0:
            return None
        return qtd
    except ValueError:
        return None

def usuario_ja_conectado(conn, nome):
    #with lock:
    for outra_conn, sessao in estados.items():
            if outra_conn != conn and sessao["autenticado"] and sessao["nome"] == nome:
                return True
    return False

def handle_register(conn,nome, senha):
    with lock:
        sessao = estados.get(conn)
        if sessao is None:
            return "[ERRO] Sessão não encontrada."
        if sessao["autenticado"]:
            return f"[ERRO] Você já está logado como '{sessao['nome']}'. Faça :logout antes de registrar outro usuário."
        if nome in usuarios:
            return "[ERRO] Usuário já existe."

        usuarios[nome] = {
            "senha": senha,
            "saldo": 1000.0,
            "carteira": {}
        }

    salvar_usuarios()
    return f"[OK] Usuário '{nome}' registrado com sucesso."

def handle_login(conn, nome, senha):
    with lock:
        sessao = estados.get(conn)
        if sessao is None:
            return "[ERRO] Sessão não encontrada."
        
        if sessao["autenticado"]:
            return f"[ERRO] Você já está logado como '{sessao['nome']}'. Faça :logout antes de logar com outro usuário."

        if nome not in usuarios:
            return "[ERRO] Credenciais inválidas."

        if usuarios[nome]["senha"] != senha:
            return "[ERRO] Credenciais inválidas."

        if usuario_ja_conectado(conn, nome):
            return "[ERRO] Usuário já conectado em outra sessão."

          
        
        sessao["nome"] = nome
        sessao["autenticado"] = True

    return f"[OK] Login realizado com sucesso como '{nome}'."


def handle_logout(conn):
    """Encerra a sessão do usuário sem fechar a conexão TCP."""
    with lock:
        sessao = estados.get(conn)
        if not sessao or not sessao["autenticado"]:
            return "[ERRO] Você não está logado."

        nome = sessao["nome"]
        sessao["nome"] = None
        sessao["autenticado"] = False
    salvar_usuarios()
    return f"[OK] Logout realizado. Até logo, {nome}!"


def handle_quem(conn):
    """Retorna o nome do usuário autenticado na conexão atual."""
    with lock:
        sessao = estados.get(conn)
        if not sessao or not sessao["autenticado"] or not sessao["nome"]:
            return "[INFO] Você não está logado."

        nome = sessao["nome"]

    return f"[INFO] Você está logado como '{nome}'."


def handle_buy(conn, ativo, qtd):
    with lock:
        sessao = estados.get(conn)
        if not sessao or not sessao["autenticado"] or not sessao["nome"]:
            return "[ERRO] Faça login com :login primeiro."

        nome = sessao["nome"]

        if nome not in usuarios:
            return "[ERRO] Usuário não encontrado."

        if ativo not in cotacoes:
            return "[ERRO] Ativo inválido."

        usuario = usuarios[nome]
        preco = cotacoes[ativo]
        total = round(preco * qtd, 2)

        if usuario["saldo"] < total:
            return f"[ERRO] Saldo insuficiente. Necessário: R$ {total:.2f}"

        usuario["saldo"] = round(usuario["saldo"] - total, 2)
        usuario["carteira"][ativo] = usuario["carteira"].get(ativo, 0) + qtd
        saldo_atual = usuario["saldo"]

    salvar_usuarios()
    return (
        f"[OK] Você executou: COMPRA de {qtd}x {ativo} "
        f"@ R$ {preco:.2f} = R$ {total:.2f} | Saldo: R$ {saldo_atual:.2f}"
    )

def handle_sell(conn, ativo, qtd):
    with lock:
        sessao = estados.get(conn)
        if not sessao or not sessao["autenticado"] or not sessao["nome"]:
            return "[ERRO] Faça login com :login primeiro."

        nome = sessao["nome"]

        if nome not in usuarios:
            return "[ERRO] Usuário não encontrado."

        if ativo not in cotacoes:
            return "[ERRO] Ativo inválido."

        usuario = usuarios[nome]
        quantidade_atual = usuario["carteira"].get(ativo, 0)

        if quantidade_atual < qtd:
            return f"[ALERTA] Você possui apenas {quantidade_atual}x {ativo}."

        preco = cotacoes[ativo]
        total = round(preco * qtd, 2)

        usuario["saldo"] = round(usuario["saldo"] + total, 2)
        usuario["carteira"][ativo] -= qtd

        if usuario["carteira"][ativo] == 0:
            del usuario["carteira"][ativo]

        saldo_atual = usuario["saldo"]

    salvar_usuarios()
    return (
        f"[OK] Você executou: VENDA de {qtd}x {ativo} "
        f"@ R$ {preco:.2f} = R$ {total:.2f} | Saldo: R$ {saldo_atual:.2f}"
    )


def handle_carteira(conn):
    # Exibe carteira do usuário logado
    with lock:
        sessao = estados.get(conn)
        if not sessao or not sessao["autenticado"] or not sessao["nome"]:
            return "[ERRO] Faça login com :login primeiro."

        nome = sessao["nome"]

        if nome not in usuarios:
            return "[ERRO] Usuário não encontrado."

        usuario = usuarios[nome]

        linhas = [
            f"[INFO] Carteira de {nome}",
            f"Saldo: R$ {usuario['saldo']:.2f}",
            "Ativos:"
        ]

        if not usuario["carteira"]:
            linhas.append("  (vazia)")
        else:
            for ativo, qtd in usuario["carteira"].items():
                preco_atual = cotacoes.get(ativo, 0.0)
                linhas.append(f"  {ativo}: {qtd} ações @ R$ {preco_atual:.2f}")

    return "\n".join(linhas)


def cleanup_client(conn, save_first=True):
    with lock:
        sessao = estados.get(conn)
        autenticado=bool(sessao and sessao.get("autenticado"))
        
        if conn in clientes:
            clientes.remove(conn)

        estados.pop(conn, None)
        q=filas_envio.pop(conn, None)
    if save_first and autenticado:
        salvar_usuarios()
    if q is not None:
        with suppress(Exception):
            q.put_nowait(None)  # Sinaliza para a thread de envio encerrar  

    with suppress(OSError):
        conn.shutdown(socket.SHUT_RDWR)
    with suppress(OSError):
        conn.close()


def client_sender(conn):
    while running.is_set():
        with lock:
            q = filas_envio.get(conn)

        if q is None:
            return

        try:
            msg = q.get(timeout=1)  # Espera por mensagens para enviar, mas verifica periodicamente se deve encerrar
        except queue.Empty:
            continue

        if msg is None:
            return
        
        try:
            send(conn, msg)
        except OSError:
            cleanup_client(conn, save_first=False)
            return


def client_receiver(conn, addr):
    hora = datetime.now().strftime("%H:%M:%S")
    mensagem_inicial = "\n".join([
        f"{hora}: CONECTADO!!",
        "[INFO] Faça :register ou :login antes de operar.",
        format_prices(),
        format_help_server()
    ])

    if not safe_send(conn, mensagem_inicial):
        cleanup_client(conn, save_first=False)
        return

    print(f"[+] Cliente conectado: {addr}")

    buf = ""

    try:
        while running.is_set():
            dados = conn.recv(1024)
            if not dados:
                break

            buf += dados.decode("utf-8", errors="ignore")

            while "\n" in buf:
                linha, buf = buf.split("\n", 1)
                linha = linha.strip()

                if not linha:
                    continue

                partes = linha.split()
                cmd = partes[0].lower()

                if cmd == ":exit":
                    safe_send(conn, "[INFO] Até logo!")
                    time.sleep(0.5)  # Dá tempo do cliente receber a mensagem antes de fechar
                    return

                elif cmd == ":register":
                    if len(partes) != 3:
                        safe_send(conn, "[ERRO] Uso: :register <USUARIO> <SENHA>")
                        continue

                    nome = partes[1]
                    senha = partes[2]
                    resposta = handle_register(conn,nome, senha)
                    safe_send(conn, resposta)

                elif cmd == ":login":
                    if len(partes) != 3:
                        safe_send(conn, "[ERRO] Uso: :login <USUARIO> <SENHA>")
                        continue

                    nome = partes[1]
                    senha = partes[2]
                    resposta = handle_login(conn, nome, senha)
                    safe_send(conn, resposta)

                elif cmd == ":logout":
                    resposta = handle_logout(conn)
                    safe_send(conn, resposta)

                elif cmd == ":quem":
                    resposta = handle_quem(conn)
                    safe_send(conn, resposta)

                elif cmd == ":buy":
                    if len(partes) != 3:
                        safe_send(conn, "[ERRO] Uso: :buy <ATIVO> <QTD>")
                        continue

                    ativo = partes[1].upper()
                    qtd = parse_qtd(partes[2])

                    if qtd is None:
                        safe_send(conn, "[ERRO] Quantidade inválida. Use um inteiro positivo.")
                        continue

                    resposta = handle_buy(conn, ativo, qtd)
                    safe_send(conn, resposta)

                elif cmd == ":sell":
                    if len(partes) != 3:
                        safe_send(conn, "[ERRO] Uso: :sell <ATIVO> <QTD>")
                        continue

                    ativo = partes[1].upper()
                    qtd = parse_qtd(partes[2])

                    if qtd is None:
                        safe_send(conn, "[ERRO] Quantidade inválida. Use um inteiro positivo.")
                        continue

                    resposta = handle_sell(conn, ativo, qtd)
                    safe_send(conn, resposta)

                elif cmd == ":carteira":
                    resposta = handle_carteira(conn)
                    safe_send(conn, resposta)

                else:
                    safe_send(conn, f"[ERRO] Comando desconhecido: '{cmd}'")

    except OSError:
        pass
    finally:
        cleanup_client(conn)
        print(f"[-] Cliente desconectado: {addr}")


def handle_client(conn, addr):
    with lock:
        clientes.append(conn)
        estados[conn] = {"nome": None, "autenticado": False}
        filas_envio[conn] = queue.Queue()

    t_send = threading.Thread(target=client_sender, args=(conn,), daemon=True)
    t_recv = threading.Thread(target=client_receiver, args=(conn, addr), daemon=True)

    t_send.start()
    t_recv.start()


def parse_max_conexoes():
    if len(sys.argv) < 2:
        return 5

    try:
        valor = int(sys.argv[1])
        if valor <= 0:
            raise ValueError
        return valor
    except ValueError:
        print("[ERRO] MAX_CONEXOES inválido. Use inteiro positivo. Exemplo: python server.py 5")
        raise SystemExit(1)

def shutdown_server(server_sock=None):
    print("\n[INFO] Encerrando servidor...")
    running.clear()
    salvar_usuarios()
    with lock:
        conexoes = list(clientes)

    for conn in conexoes:
        cleanup_client(conn,save_first=False)

    if server_sock is not None:
        with suppress(OSError):
            server_sock.close()    


def main():
    carregar_usuarios()
    max_conexoes = parse_max_conexoes()

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server_sock:
        server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server_sock.bind((HOST, PORT))
        server_sock.listen(5)
        
        print(f"Servidor aguardando conexões em {HOST}:{PORT} ...")
        print(f"Limite de conexões simultâneas: {max_conexoes}")

        threading.Thread(target=price_simulation_thread, daemon=True).start()
        threading.Thread(target=feed_thread, daemon=True).start()

        try:
            while running.is_set():
                try:
                    conn, addr = server_sock.accept()
                except OSError:
                    break

                with lock:
                    lotado = len(clientes) >= max_conexoes

                if lotado:
                    with suppress(OSError):
                        send(conn, "[ERRO] Servidor cheio. Tente novamente mais tarde.")
                    with suppress(OSError):
                        conn.close()
                    continue

                handle_client(conn, addr)
        except KeyboardInterrupt:
            print("\n[INFO] Encerrando servidor...")
        finally:
            shutdown_server(server_sock)
    print("Servidor encerrado.")

if __name__ == "__main__":
    main()
