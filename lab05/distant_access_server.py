import socket
import threading
import subprocess
from distant_access_protocol import send_message, MSG_EXIT, MSG_ALIVE, MSG_OUTPUT, EXIT_CODE
import argparse

MAX_COMMAND = 4096

def read_command(buffer) -> str:
    raw = buffer.readline(MAX_COMMAND + 1)
    if raw == b"":
        raise ValueError("Got empty message")
    if not raw.endswith(b"\n"):
        raise ValueError("Command line is not terminated with \\n as it should have")

    try:
        command = raw.decode("utf-8").rstrip("\r\n")
    except UnicodeDecodeError:
        raise ValueError("Command could not be decoded via utf-8")

    if command.strip() == "":
        raise ValueError("Empty command")

    return command

def heartbeat_loop(conn: socket.socket, process: subprocess.Popen, send_lock: threading.Lock, interval: float, stop_event: threading.Event):
    while stop_event.wait(interval):
        if process.poll() is not None:
            return
        try:
            send_message(conn, MSG_ALIVE, lock=send_lock)
        except OSError:
            return

def handle_client(conn: socket.socket, addr, heartbeat_interval: float) -> None:
    with conn.makefile("rb") as buffer:
        command = read_command(buffer)

    print(f"[{addr[0]}:{addr[1]}] running: {command}")
    send_lock = threading.Lock()
    code = run_command(conn, command, send_lock, heartbeat_interval)

    code = (code + 2 ** 31) % 2 ** 32 - 2 ** 31 # unsigned int windows return code conversion to signed
    send_message(conn, MSG_EXIT, EXIT_CODE.pack(code), lock=send_lock)
    print(f"[{addr[0]}:{addr[1]} finished with code {code}]")

def serve_forever(listener: socket.socket, heartbeat_interval: float) -> None:
    host, port = listener.getsockname()[:2]
    print(f"Listening on {host}:{port}")
    while True:
        try:
            conn, addr = listener.accept()
        except TimeoutError:
            continue
        with conn:
            try:
                handle_client(conn, addr, heartbeat_interval)
            except (ValueError, OSError) as error:
                print(f"[{addr[0]}:{addr[1]}] error: {error}")

def create_listening_socket(host: str, port: int) -> socket.socket:
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind((host, port))
    listener.listen()
    listener.settimeout(1.0)  # иначе accept не прерывается по Ctrl+C
    return listener

def kill_process_tree(process: subprocess.Popen) -> None:
    subprocess.run(["taskkill", "/T", "/F", "/PID", str(process.pid)],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    process.wait()


def run_command(conn: socket.socket, command: str,
                send_lock: threading.Lock, heartbeat_interval: float) -> int:
    process = subprocess.Popen(command, shell=True, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="oem", errors="replace")

    stop_event = threading.Event()
    heartbeat = threading.Thread(target=heartbeat_loop, args=(conn, process, send_lock, heartbeat_interval, stop_event), daemon=True)
    heartbeat.start()

    try:
        for line in process.stdout:
            send_message(conn, MSG_OUTPUT, line.encode("utf-8"), lock=send_lock)
        return process.wait()
    finally:
        stop_event.set()
        if process.poll() is None:
            kill_process_tree(process)
        heartbeat.join()
        process.stdout.close()

def main() -> None:
    parser = argparse.ArgumentParser(description="Distant access command execute server")
    parser.add_argument("--host", default="127.0.0.1", help="Listening address")
    parser.add_argument("--port", type=int, default=9000, help="Port")
    parser.add_argument("--heartbeat", type=float, default=2.0, help="Interval in seconds")
    args = parser.parse_args()

    with create_listening_socket(args.host, args.port) as listener:
        try:
            serve_forever(listener, args.heartbeat)
        except KeyboardInterrupt:
            print("\nServer stopped")


if __name__ == "__main__":
    main()