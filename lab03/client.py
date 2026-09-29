import sys
import socket

def run_client():
    if len(sys.argv) != 4:
        print("Usage: python client.py <server_host> <server_port> <filename>")
        sys.exit(1)

    host = sys.argv[1]
    port = int(sys.argv[2])
    filename = sys.argv[3]

    if not filename.startswith("/"):
        filename = f"/{filename}"

    http_request = (
        f"GET {filename} HTTP/1.1\r\n"
        f"Host: {host}:{port}\r\n"
        "Connection: close\r\n"
        "\r\n"
    )

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client_socket:
        try:
            client_socket.connect((host, port))
            client_socket.sendall(http_request.encode("utf-8"))

            response_chunks = []
            while True:
                chunk = client_socket.recv(4096)
                if not chunk:
                    break
                response_chunks.append(chunk)

            full_response = b"".join(response_chunks).decode("utf-8", errors="replace")
            print(full_response)

        except ConnectionRefusedError:
            print(f"Error: server {host}:{port} is unavailable.")
        except Exception as e:
            print(f"Some other error: {e}")

if __name__ == "__main__":
    run_client()