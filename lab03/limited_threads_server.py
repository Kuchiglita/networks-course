import sys
import socket
import threading
import mimetypes
from pathlib import Path

STATIC_DIR = Path(__file__).resolve().parent


def handle_client(client_socket: socket.socket, client_address: tuple, semaphore: threading.Semaphore):
    try:
        raw_request = client_socket.recv(4096)
        if not raw_request:
            return

        request_text = raw_request.decode("utf-8", errors="replace")
        first_line = request_text.split("\r\n")[0]
        parts = first_line.split()

        if len(parts) < 2 or parts[0] != "GET":
            return

        requested_path = parts[1]
        clean_path = requested_path.split("?")[0].lstrip("/")
        if not clean_path:
            clean_path = "index.html"

        target_file = (STATIC_DIR / clean_path).resolve()

        if target_file.is_file() and str(target_file).startswith(str(STATIC_DIR)):
            content_type, _ = mimetypes.guess_type(target_file)
            content_type = content_type or "application/octet-stream"

            with open(target_file, "rb") as f:
                body = f.read()

            headers = (
                "HTTP/1.1 200 OK\r\n"
                f"Content-Type: {content_type}\r\n"
                f"Content-Length: {len(body)}\r\n"
                "Connection: close\r\n"
                "\r\n"
            )
            client_socket.sendall(headers.encode("utf-8") + body)

        else:
            not_found_body = b"<html><body><h1>404 Not Found</h1></body></html>"
            headers = (
                "HTTP/1.1 404 Not Found\r\n"
                "Content-Type: text/html; charset=utf-8\r\n"
                f"Content-Length: {len(not_found_body)}\r\n"
                "Connection: close\r\n"
                "\r\n"
            )
            client_socket.sendall(headers.encode("utf-8") + not_found_body)

    except Exception as e:
        print(f"Error handling {client_address}: {e}")
    finally:
        client_socket.close()
        semaphore.release()


def run_server():
    if len(sys.argv) != 3:
        print("Usage: python server.py <server_port> <concurrency_level>")
        sys.exit(1)

    port = int(sys.argv[1])
    concurrency_level = int(sys.argv[2])

    semaphore = threading.Semaphore(concurrency_level)

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server_socket:
        server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server_socket.bind(("0.0.0.0", port))

        server_socket.listen(100) # let the limit be 100 or whatever
        print(f"Server runs on port {port}, max ports in parallel: {concurrency_level}")

        while True:
            semaphore.acquire()

            try:
                client_socket, client_address = server_socket.accept()
                print(f"Client connected {client_address}")

                client_thread = threading.Thread(
                    target=handle_client,
                    args=(client_socket, client_address, semaphore),
                    daemon=True
                )
                client_thread.start()
            except Exception as e:
                semaphore.release()
                print(f"Error while trying to accept(): {e}")


if __name__ == "__main__":
    run_server()