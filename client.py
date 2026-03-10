import socket
import sys

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 9999


def main() -> None:
    host = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_HOST  #verifica se o host foi passado como argumento, se não usa o default
    port = int(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_PORT #verifica se a porta foi passada como argumento, se não usa o default

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock: # parametros: AF_INET = IPv4  |  SOCK_STREAM = TCP  |  with = garante que o socket seja fechado corretamente e automaticamente
        try:
            sock.connect((host, port))
        except ConnectionRefusedError:
            print("Erro: nao foi possivel conectar a", host, ":", port)
            return

        print("Conectado a", host, ":", port)
        print(sock.recv(1024).decode("utf-8"), end="") # recebe a mensagem de entrada do servidor

        while True:
            msg = input("> ").strip() # le a mensagem do usuario e remove espaços em branco
            if not msg:
                continue

            sock.sendall((msg + "\n").encode("utf-8")) # envia a mensagem para o servidor
            resposta = sock.recv(1024).decode("utf-8")
            print(resposta, end="") # imprime a resposta do servidor sem adicionar nova linha (end="")

            if msg == ":exit":
                break


if __name__ == "__main__":
    main()
