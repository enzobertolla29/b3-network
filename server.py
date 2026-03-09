import socket
#trabalhar smp com bytes

HOST = "0.0.0.0"
PORT = 9999


def main() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server_sock:  # parametros: AF_INET = IPv4  |  SOCK_STREAM = TCP  |  with = garante que o socket seja fechado corretamente e automaticamente
        server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1) # para reutilizar a mesma porta 
        server_sock.bind((HOST, PORT)) # vincula o socket a um endereço e porta específicos
        server_sock.listen(1)
        print("Servidor ouvindo em", HOST, ":", PORT, "...")

        while True:
            conn, addr = server_sock.accept() # conn = socket do cliente  |  addr = endereço do cliente
            print("[+] Cliente conectado:", addr)

            with conn:
                conn.sendall(b"Bem-vindo ao servidor!\n") # mandamos mensagem com o "conn" para o client

                while True:
                    data = conn.recv(1024)
                    if not data:
                        break

                    msg = data.decode("utf-8") # decodifica os bytes recebidos para string
                    if msg == ":exit":
                        conn.sendall(b"Ate logo!\n")
                        break

                    conn.sendall(f"[eco] {msg}\n".encode("utf-8")) #se não for exit, ecoa a msg

            print("[-] Cliente desconectado:", addr)


if __name__ == "__main__":
    main()
