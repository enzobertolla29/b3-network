import socket 
import threading
import time
import random
from datetime import datetime
from contextlib import suppress

# Escuta em todas as interfaces de rede disponíveis
HOST = "0.0.0.0" 
PORT = 9999


lock = threading.Lock()  

cotacoes = {
    "PETR4": 38.50,
    "VALE3": 65.20,
    "ITUB4": 28.90
}

usuarios = {}

estados = {}
clientes = []


def send(conn, msg):
    #Envia a mensagem ao cliente em bytes com brakeline
    conn.sendall((msg + "\n").encode())  

def safe_send(conn, msg):
    """Envia com proteção contra queda de conexão."""
    try:
        send(conn, msg)
        return True
    except OSError:
        return False

def broadcast(msg):
    with lock:
        copia = list(clientes)  
    for conn in copia:
        send(conn, msg)  

def format_prices():
    with lock:
        linhas = ["[FEED] Cotações:"] + [f"  {ativo}: R$ {preco:.2f}" for ativo, preco in cotacoes.items()]
    return "\n".join(linhas)  


def format_help_server():
    return "\n".join([
        "[INFO] Comandos disponíveis:",
        "  :register <USUARIO> <SENHA> -> registrar novo usuário",
        "  :login <USUARIO> <SENHA>    -> autenticar-se",
        "  :buy <ATIVO> <QTD>          -> ordem de compra",
        "  :sell <ATIVO> <QTD>         -> ordem de venda",
        "  :carteira                   -> exibe saldo e ativos",
        "  :exit                       -> encerra conexão"
    ])


def price_simulation_thread():
    while True:
        time.sleep(random.uniform(1.0, 2.0))  
        with lock:
            for ativo in cotacoes:
                variacao = round(random.uniform(-0.10, 0.10), 2)  
                novo_preco = round(cotacoes[ativo] + variacao, 2)
                cotacoes[ativo] = max(0.01, novo_preco) 

def feed_thread():
    while True:
        time.sleep(5)
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
    

def get_usuario_autenticado(conn):
    # Retorna o usuário logado na conexão
    with lock:
        sessao = estados.get(conn)

        if not sessao or not sessao["autenticado"] or not sessao["nome"]:
            return None, "[ERRO] Faça login com :login primeiro."

        nome = sessao["nome"]
        usuario = usuarios.get(nome)

        if usuario is None:
            return None, "[ERRO] Usuário não encontrado."

    return usuario, None

def usuario_ja_conectado(conn, nome):
    for outra_conn, sessao in estados.items():
        if outra_conn != conn and sessao["autenticado"] and sessao["nome"] == nome:
            return True
    return False

def handle_register(nome, senha):
    with lock:
        if nome in usuarios:
            return "[ERRO] Usuário já existe."

        usuarios[nome] = {
            "senha": senha,
            "saldo": 1000.0,
            "carteira": {}
        }

    return f"[OK] Usuário '{nome}' registrado com sucesso."

def handle_login(conn, nome, senha):
    with lock:
        if nome not in usuarios:
            return "[ERRO] Credenciais inválidas."

        if usuarios[nome]["senha"] != senha:
            return "[ERRO] Credenciais inválidas."

        if usuario_ja_conectado(conn, nome):
            return "[ERRO] Usuário já conectado em outra sessão."

        estados[conn]["nome"] = nome
        estados[conn]["autenticado"] = True

    return f"[OK] Login realizado com sucesso como '{nome}'."


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


def handle_client(conn, addr):
    with lock:
        clientes.append(conn)
        estados[conn] = {"nome": None, "autenticado": False}

    hora = datetime.now().strftime("%H:%M:%S")
    mensagem_inicial = "\n".join([
        f"{hora}: CONECTADO!!",
        format_prices(),
        format_help_server()
    ])

    if not safe_send(conn, mensagem_inicial):
        with lock:
            if conn in clientes:
                clientes.remove(conn)
            estados.pop(conn, None)
        with suppress(OSError):
            conn.close()
        return

    print(f"[+] Cliente conectado: {addr}")

    buf = ""

    try:
        while True:
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
                    return

                elif cmd == ":register":
                    if len(partes) != 3:
                        safe_send(conn, "[ERRO] Uso: :register <USUARIO> <SENHA>")
                        continue

                    nome = partes[1]
                    senha = partes[2]
                    resposta = handle_register(nome, senha)
                    safe_send(conn, resposta)

                elif cmd == ":login":
                    if len(partes) != 3:
                        safe_send(conn, "[ERRO] Uso: :login <USUARIO> <SENHA>")
                        continue

                    nome = partes[1]
                    senha = partes[2]
                    resposta = handle_login(conn, nome, senha)
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
        with lock:
            if conn in clientes:
                clientes.remove(conn)
            estados.pop(conn, None)

        with suppress(OSError):
            conn.close()

        print(f"[-] Cliente desconectado: {addr}")



def main():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server_sock:
        server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server_sock.bind((HOST, PORT))
        server_sock.listen(5)

        print(f"Servidor aguardando conexões em {HOST}:{PORT} ...")

        threading.Thread(target=price_simulation_thread, daemon=True).start()
        threading.Thread(target=feed_thread, daemon=True).start()

        with suppress(KeyboardInterrupt):
            while True:
                conn, addr = server_sock.accept()
                threading.Thread(
                    target=handle_client,
                    args=(conn, addr),
                    daemon=True
                ).start()

    print("Servidor encerrado.")

if __name__ == "__main__":
    main()
