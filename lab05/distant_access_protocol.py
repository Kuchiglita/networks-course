import socket
import struct
import threading
from contextlib import nullcontext
from typing import BinaryIO
# header format = "!BI", type, length

MSG_OUTPUT = 1
MSG_ALIVE = 2
MSG_EXIT = 3

KNOWN_TYPES = {MSG_OUTPUT, MSG_ALIVE, MSG_EXIT}

HEADER = struct.Struct("!BI")
EXIT_CODE = struct.Struct("!i")

MAX_PAYLOAD = 1024 * 1024

def send_message(sock: socket.socket, msg_type: int, payload: bytes = b"", lock: threading.Lock | None = None) -> None:
    if len(payload) > MAX_PAYLOAD:
        raise ValueError(f"payload too large: {len(payload)} bytes")

    data = HEADER.pack(msg_type, len(payload)) + payload
    with lock if lock is not None else nullcontext():
        sock.sendall(data)

def recv_exact(buffer: BinaryIO, n: int) -> bytes:
    data = buffer.read(n)
    if len(data) != n:
        raise ValueError(f"connection closed: received only {len(data)} out of {n} bytes")
    return data

def recv_message(buffer) -> tuple[int, bytes]:
    msg_type, length = HEADER.unpack(recv_exact(buffer, HEADER.size))

    if msg_type not in KNOWN_TYPES:
        raise ValueError(f"incorrect type int the received message: {msg_type}")
    if length > MAX_PAYLOAD:
        raise ValueError(f"too large payload: {length} bytes")

    payload = recv_exact(buffer, length)
    return msg_type, payload
