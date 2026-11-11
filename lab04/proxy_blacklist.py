import sys
import socket
import threading
from urllib.parse import urlparse
from pathlib import Path
import json
import hashlib

BASE_DIR = Path(__file__).resolve().parent
LOG_FILE = BASE_DIR / "proxy.log"
BLACKLIST_FILE = BASE_DIR / "blacklist.txt"
CACHE_DIR = BASE_DIR / "cache"
CACHE_DIR.mkdir(exist_ok=True)
CACHE_META_FILE = CACHE_DIR / "metadata.json"

HOP_BY_HOP_HEADERS = {
    "connection", "keep-alive", "proxy-authenticate",
    "proxy-authorization", "te", "trailers",
    "transfer-encoding", "upgrade"
}

CACHE_LOCK = threading.Lock()

def load_cache_meta():
    if CACHE_META_FILE.exists():
        with open(CACHE_META_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_cache_meta(meta):
    with open(CACHE_META_FILE, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=4)

cache_metadata = load_cache_meta()

def log_request(method: str, url: str, status_code: str, note: str = ""):
    note_str = f" ({note})" if note else ""
    log_entry = f"{method} {url} - {status_code}{note_str}\n"
    print(log_entry.strip())
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(log_entry)

def send_proxy_error(client_socket, status_code, status_msg, description):
    try:
        error_body = f"<html><body><h1>{status_code} {status_msg}</h1><p>{description}</p></body></html>".encode("utf-8")
        response = (
            f"HTTP/1.1 {status_code} {status_msg}\r\n"
            f"Content-Length: {len(error_body)}\r\n"
            "Content-Type: text/html; charset=utf-8\r\n"
            "Connection: close\r\n\r\n"
        ).encode("utf-8") + error_body
        client_socket.sendall(response)
    except:
        pass

def recv_headers(sock: socket.socket, timeout: float = 3.0) -> bytes:
    sock.settimeout(timeout)
    data = bytearray()
    while b"\r\n\r\n" not in data:
        try:
            chunk = sock.recv(4096)
            if not chunk:
                break
            data.extend(chunk)
        except socket.timeout:
            break
        except Exception as e:
            print(f"Network error while reading body: {e}")
            break
    return bytes(data)

def recv_exactly(sock: socket.socket, length: int, timeout: float = 3.0) -> bytes:
    sock.settimeout(timeout)
    data = bytearray()
    while len(data) < length:
        try:
            chunk = sock.recv(min(4096, length - len(data)))
            if not chunk:
                break
            data.extend(chunk)
        except socket.timeout:
            break
        except Exception as e:
            print(f"Network error while reading body: {e}")
            break
    return bytes(data)

def recv_all(sock: socket.socket, timeout: float = 3.0) -> bytes:
    sock.settimeout(timeout)
    data = bytearray()
    while True:
        try:
            chunk = sock.recv(4096)
            if not chunk:
                break
            data.extend(chunk)
        except socket.timeout:
            break
        except Exception as e:
            print(f"Network error while reading body: {e}")
            break
    return bytes(data)

def parse_client_request(request_data: bytes):
    """
    Разбирает сырые байты запроса на искомые параметры. В случае ошибки кидает исключения ValueError.
    :param request_data: Полный запрос
    :return: Кортеж параметров (method, target_url, host, port, path, headers_dict, body_raw)
    """
    headers_end = request_data.find(b"\r\n\r\n") + 4
    headers_raw = request_data[:headers_end]
    body_raw = request_data[headers_end:]

    headers_text = headers_raw.decode("utf-8", errors="replace")
    lines = headers_text.split("\r\n")

    if not lines or not lines[0]:
        raise ValueError("Empty starting line of the request")

    first_line = lines[0].split()

    if len(first_line) < 3:
        raise ValueError(f"Wrong HTTP-line format: {lines[0]}")

    method, raw_url, version = first_line[0], first_line[1], first_line[2]

    if method not in ["GET", "POST"]:
        raise ValueError(f"Unsupported HTTP-method: {method}")

    if raw_url.startswith("/"):
        clean_target = raw_url.lstrip("/")
        if clean_target.startswith(("http://", "https://")):
            target_url = clean_target
        elif clean_target:
            target_url = "http://" + clean_target
        else:
            raise ValueError("Couldn't extract target URL from path")
    else:
        target_url = raw_url

    parsed_url = urlparse(target_url)
    host = parsed_url.hostname
    port = parsed_url.port or 80
    path = parsed_url.path or "/"
    if parsed_url.query:
        path += f"?{parsed_url.query}"

    if not host:
        raise ValueError(f"Host is not found in the url: {target_url}")

    headers_dict = {}
    for line in lines[1:]:
        if ":" in line:
            key, value = line.split(":", 1)
            key_lower = key.lower().strip()
            if key_lower not in HOP_BY_HOP_HEADERS:
                headers_dict[key_lower] = value.strip()

    return method, target_url, host, port, path, headers_dict, body_raw

def parse_server_response(response_data: bytes):
    resp_headers_end = response_data.find(b"\r\n\r\n") + 4
    resp_headers_raw = response_data[:resp_headers_end]
    status_line = resp_headers_raw.split(b"\r\n")[0].decode("utf-8", errors="ignore")
    status_code = status_line.split()[1] if len(status_line.split()) > 1 else "Unknown"

    resp_headers_text_lower = resp_headers_raw.decode("utf-8", errors="ignore").lower()
    has_body_indicators = "content-length:" in resp_headers_text_lower or "transfer-encoding: chunked" in resp_headers_text_lower

    return status_code, has_body_indicators, resp_headers_raw


def load_blacklist(filepath):
    if filepath.exists():
        with open(filepath, "r", encoding="utf-8") as f:
            return set(line.strip().lower() for line in f if line.strip())
    return set()

def check_blacklist(host, blacklist):
    if host.lower() in blacklist:
        raise PermissionError("Access Denied")

blacklist_domains = load_blacklist(BLACKLIST_FILE)


def handle_client(client_socket: socket.socket):
    target_socket = None
    try:

        # CLIENT REQUEST PROCESSING
        request_data = recv_headers(client_socket)

        if not request_data or b"\r\n\r\n" not in request_data:
            return

        try:
            parsed_data = parse_client_request(request_data)
            method, target_url, host, port, path, headers_dict, body_raw = parsed_data

            # BLACKLIST
            check_blacklist(host, blacklist_domains)
        except ValueError as e:
            print(f"Incorrect request declined: {e}")
            send_proxy_error(client_socket, 400, "Bad Request", str(e))
            return
        except PermissionError:
            print(f"Denying access to the domain: {host}")
            send_proxy_error(client_socket, 403, "Forbidden", "Page is in a blacklist, not accessible")
            return

        # CACHE
        is_cached = target_url in cache_metadata
        if method == "GET" and is_cached:
            cached_data = cache_metadata[target_url]
            if cached_data.get("etag"):
                headers_dict["if-none-match"] = cached_data["etag"]
            if cached_data.get("last_modified"):
                headers_dict["if-modified-since"] = cached_data["last_modified"]

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
            target_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            target_socket.settimeout(3.0)
            target_socket.connect((host, port))
            target_socket.sendall(upstream_request)
        except socket.gaierror:
            send_proxy_error(client_socket, 502, "Bad Gateway", f"DNS resolution failed for {host}")
            log_request(method, target_url, "502", "DNS Error")
            return
        except Exception as e:
            send_proxy_error(client_socket, 502, "Bad Gateway", f"Failed to connect to {host}: {e}")
            log_request(method, target_url, "502", "Connection Error")
            return

        response_data = recv_all(target_socket)
        if not response_data:
            send_proxy_error(client_socket, 502, "Bad Gateway", "For some reason no response came back.")
            log_request(method, target_url, "502", "Empty Response")
            return

        status_code, has_body_indicators, resp_headers_raw = parse_server_response(response_data)
        resp_headers_text_lower = resp_headers_raw.decode("utf-8", errors="ignore").lower()
        has_body_indicators = "content-length:" in resp_headers_text_lower or "transfer-encoding: chunked" in resp_headers_text_lower

        if status_code.startswith("1") or status_code in ["204", "304"] and not has_body_indicators:
            pass
        else:
            response_data += recv_all(target_socket)

        if method == "GET":
            if status_code == "304" and is_cached:
                cache_file = CACHE_DIR / cache_metadata[target_url]["file"]
                if cache_file.exists():
                    with open(cache_file, "rb") as f:
                        cached_response = f.read()
                    client_socket.sendall(cached_response)
                    log_request(method, target_url, "304", "Cache Hit")
                    return
                else:
                    send_proxy_error(client_socket, 500, "Internal Proxy Error", "Cache file is missing locally")
                    return

            if status_code == "200":
                etag = None
                last_modified = None
                original_headers_text = resp_headers_raw.decode("utf-8", errors="ignore")
                for line in original_headers_text.split("\r\n")[1:]:
                    line_lower = line.lower()
                    if line_lower.startswith("etag:"):
                        etag = line.split(":", 1)[1].strip()
                        if not etag.startswith('"'):
                            etag = f'"{etag}"'
                    elif line_lower.startswith("last-modified:"):
                        last_modified = line.split(":", 1)[1].strip()

                if etag or last_modified:
                    file_hash = hashlib.md5(target_url.encode("utf-8")).hexdigest() + ".bin"
                    cache_file = CACHE_DIR / file_hash
                    with CACHE_LOCK:
                        with open(cache_file, "wb") as f:
                            f.write(response_data)
                        cache_metadata[target_url] = {
                            "file": file_hash,
                            "etag": etag,
                            "last_modified": last_modified
                        }
                        save_cache_meta(cache_metadata)
                    log_request(method, target_url, "200", "Saved to Cache")
                else:
                    log_request(method, target_url, "200")

            client_socket.sendall(response_data)

    except Exception as e:
        print(f"Client error: {e}")
        send_proxy_error(client_socket, 500, "Internal Server Error", str(e))
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