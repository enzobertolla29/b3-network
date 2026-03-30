import socket
import sys
import threading
from contextlib import suppress

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 9999

run = threading.Event()
run.set()


def receber(sock):
    buf = ""
    try:
        while run.is_set():
            dados = sock.recv(4096) # 4096 qtd maxima de bytes a receber
            if not dados:
                print("\n[INFO]Servidor encerrou a conexão]")
                run.clear()
                break
            buf = buf + dados.decode("utf-8",errors="ignore")
            while "\n" in buf:
                linha, buf = buf.split("\n", 1)
                if linha:
                    print(f"\r{linha}\n> ", end="", flush=True)
    except OSError:
        pass
    finally:
        run.clear()

def loop_entrada(sock):
    doc()
    try:
        while run.is_set():
            try:
                cmd = input("> ").strip()
            except EOFError:
                cmd = ":exit"
            if not cmd:
                continue
            try:
                sock.sendall((cmd + "\n").encode("utf-8"))
            except OSError:
                print("\n[INFO] Não foi possível enviar o comando, conexão encerrada.")
                run.clear()
                break
            if cmd.lower() == ":exit":
                break

    except EOFError:
        pass
    finally:
        run.clear()
        with suppress(OSError):
            sock.shutdown(socket.SHUT_RDWR)
        with suppress(OSError):
            sock.close()

def doc():
    print("─" * 45)
    print("Comandos disponíveis:")
    print("  :register <USUARIO> <SENHA> — registrar")
    print("  :login <USUARIO> <SENHA>    — autenticar")
    print("  :logout                     — encerrar sessão")
    print("  :quem                       — usuário logado")
    print("  :buy <ATIVO> <QTD>          — ordem de compra")
    print("  :sell <ATIVO> <QTD>         — ordem de venda")
    print("  :carteira                   — saldo e ativos")
    print("  :exit                       — encerrar conexão")
    print("─" * 45)

def main():
    host = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_HOST  #verifica se o host foi passado como argumento, se não usa o default
    port = int(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_PORT #verifica se a porta foi passada como argumento, se não usa o default

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM) # parametros: AF_INET = IPv4  |  SOCK_STREAM = TCP
    try:
        sock.connect((host, port))
    except ConnectionRefusedError:
        print("Erro: nao foi possivel conectar a", host, ":", port)
        sys.exit(1)
    except OSError as e:
        print("Erro de conexao:", e)
        sys.exit(1)

    print("Conectado a", host, ":", port)

    threading.Thread(target=receber, args=(sock,), daemon=True).start()

    loop_entrada(sock)


if __name__ == "__main__":
    main()
