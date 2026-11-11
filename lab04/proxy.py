import sys
import socket
import threading
from urllib.parse import urlparse
from pathlib import Path

LOG_FILE = Path(__file__).resolve().parent / "proxy.log"

HOP_BY_HOP_HEADERS = {
    "connection", "keep-alive", "proxy-authenticate",
    "proxy-authorization", "te", "trailers",
    "transfer-encoding", "upgrade"
}

def log_request(method: str, url: str, status_code: str):
    log_entry = f"{method} {url} - {status_code}\n"
    print(log_entry.strip())
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(log_entry)


def handle_client(client_socket: socket.socket):
    target_socket = None
    try:
        request_data = b""
        while b"\r\n\r\n" not in request_data:
            chunk = client_socket.recv(4096)
            if not chunk:
                break
            request_data += chunk

        if not request_data:
            return

        # HEADERS parse
        headers_end = request_data.find(b"\r\n\r\n") + 4
        headers_raw = request_data[:headers_end]
        body_raw = request_data[headers_end:]

        headers_text = headers_raw.decode("utf-8", errors="replace")
        lines = headers_text.split("\r\n")
        first_line = lines[0].split()

        if len(first_line) < 3:
            return

        method, raw_url, version = first_line[0], first_line[1], first_line[2]

        if method not in ["GET", "POST"]:
            return

        if raw_url.startswith("/"):
            clean_target = raw_url.lstrip("/")
            if clean_target.startswith(("http://", "https://")):
                target_url = clean_target
            elif clean_target:
                target_url = "http://" + clean_target
            else:
                return
        else:
            target_url = raw_url

        parsed_url = urlparse(target_url)
        host = parsed_url.hostname
        port = parsed_url.port or 80
        path = parsed_url.path or "/"
        if parsed_url.query:
            path += f"?{parsed_url.query}"

        headers_dict = {}
        for line in lines[1:]:
            if ":" in line:
                key, value = line.split(":", 1)
                key_lower = key.lower().strip()
                if key_lower not in HOP_BY_HOP_HEADERS:
                    headers_dict[key_lower] = value.strip()


        if method == "POST":
            content_length = int(headers_dict.get("content-length", 0))
            while len(body_raw) < content_length:
                body_raw += client_socket.recv(4096)

        headers_dict["host"] = f"{host}:{port}" if port != 80 else host
        headers_dict["connection"] = "close"

        modified_headers_list = [f"{method} {path} HTTP/1.1"]
        for k, v in headers_dict.items():
            modified_headers_list.append(f"{k.title()}: {v}")

        upstream_request = "\r\n".join(modified_headers_list).encode("utf-8") + b"\r\n\r\n" + body_raw

        try:
            # SEND MODIFIED
            target_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            target_socket.settimeout(3.0)
            target_socket.connect((host, port))
            target_socket.sendall(upstream_request)

            response_data = b""
            while True:
                try:
                    chunk = target_socket.recv(4096)
                    if not chunk:
                        break
                    response_data += chunk
                except socket.timeout:
                    break

            if response_data:
                status_line = response_data.split(b"\r\n")[0].decode("utf-8", errors="ignore")
                status_code = status_line.split()[1] if len(status_line.split()) > 1 else "Unknown"
                log_request(method, target_url, status_code)
                client_socket.sendall(response_data)

        # pure proxy errors (if destination does not exist or DNS resolvers throw an error)
        except socket.gaierror:
            error_body = "<html><body><h1>404 Proxy Error</h1><p>Target host not found.</p></body></html>"
            error_response = (
                "HTTP/1.1 404 Not Found\r\n"
                f"Content-Lenght: {len(error_body)}\r\n"
                "Content-Type: text/html\r\n"
                "Connection: close\r\n\r\n"
                f"{error_body}"
            )
            client_socket.sendall(error_response.encode("utf-8"))
            log_request(method, target_url, "404")

        except Exception as e:
            # basically any other error
            error_body = f"<html><body><h1>502 Bad Gateway</h1><p>Proxy encountered an error: {e}</p></body></html>"
            error_response = (
                "HTTP/1.1 502 Bad Gateway\r\n"
                f"Content-Length: {len(error_body)}\r\n"
                "Content-Type: text/html\r\n"
                "Connection: close\r\n\r\n"
                f"{error_body}"
            )
            client_socket.sendall(error_response.encode('utf-8'))
            log_request(method, target_url, "502")

    except Exception as e:
        print(f"Client parser error: {e}")
    finally:
        client_socket.close()
        if target_socket:
            target_socket.close()


def run_proxy():
    if len(sys.argv) != 2:
        print("Usage: python proxy.py <port>")
        sys.exit(1)

    port = int(sys.argv[1])

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as proxy_server:
        proxy_server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        proxy_server.bind(("0.0.0.0", port))
        proxy_server.listen(100)
        print(f"Proxy server listening to port {port}")

        while True:
            client_socket, _ = proxy_server.accept()
            threading.Thread(target=handle_client, args=(client_socket,), daemon=True).start()


if __name__ == "__main__":
    run_proxy()