import argparse
import socket
import ssl
import base64
import io
from email.utils import formatdate
import secrets
import mimetypes
import os
import sys

CRLF = "\r\n"
bCRLF = b"\r\n"
_MAXLINE = 8192
_MAXCHALLANGE = 5

class SMTPClientError(Exception):
    """Базовый класс для всех исключений."""

class SMTPProtocolError(SMTPClientError):
    def __init__(self, message: str, received: list[bytes]):
        self.received = received
        details = "\n".join(f"  {line!r}" for line in received)
        super().__init__(f"{message}\nReceived so far:\n{details}")


class SMTPConnectionClosed(SMTPProtocolError):
    """Сервер закрыл соединение посреди ответа."""


class SMTPReplyError(SMTPClientError):
    def __init__(self, expected: set[int], code: int, text: str):
        self.expected = expected
        self.code = code
        self.text = text
        super().__init__(f"expected {expected}, got {code}: {text}")

def send_msg(sock: socket.socket, cmd: str = None):
    pass

# line = raw.rstrip(b"\r\n").decode("utf-8", errors="replace")
# code_part, sep, text = line[:3], line[3:4], line[4:]

def recv_reply(buffer: io.BufferedReader) -> tuple[int, str]:
    raw_lines = []
    lines = []
    code = None
    while True:
        raw = buffer.readline()
        raw_lines.append(raw)
        if raw == b"":
            raise SMTPConnectionClosed("unexpected connection loss", raw_lines)
        if not raw.endswith(b"\r\n"):
            raise SMTPProtocolError(f"received line not ending with CRLF", raw_lines)
        line = raw.rstrip(b"\r\n").decode("utf-8", errors="backslashreplace")
        code_part, sep, text = line[:3], line[3:4], line[4:]

        if len(code_part) != 3 or not code_part.isdigit():
            raise SMTPProtocolError(f"code part incorrect format: {line}", raw_lines)

        if code is None:
            code = code_part
        elif code != code_part:
            raise SMTPProtocolError(f"code parts change throughout the message from {code} to {code_part}", raw_lines)

        lines.append(text)
        if len(sep) == 0 or sep == " ":
            break
        elif sep == "-":
            continue
        else: raise SMTPProtocolError(f"incorrect separator format: {line}", raw_lines)

    return int(code), "\n".join(lines)


def send_command(sock: socket.socket, buffer: io.BufferedReader, command: str, expected: set[int]) -> str:
    if "\n" in command or "\r" in command:
        raise ValueError("\\n and \\r symbols are forbidden in commands!")

    sock.sendall(command.encode("ascii") + b"\r\n")

    response_code, response_text = recv_reply(buffer)

    if response_code not in expected:
        raise SMTPReplyError(expected, response_code, response_text)

    return response_text

def send_data(sock: socket.socket, buffer: io.BufferedReader, body: bytes) -> str:
    send_command(sock, buffer, "DATA", {354})

    lines = body.splitlines()
    lines = [b"." + line if line.startswith(b".") else line for line in lines]

    proper_body = b"\r\n".join(lines) + b"\r\n.\r\n"
    sock.sendall(proper_body)

    response_code, response_text = recv_reply(buffer)
    expected_code = 250

    if response_code != expected_code:
        raise SMTPReplyError({expected_code}, response_code, response_text)

    return response_text


def encode_header_value(value: str) -> str:
    """ASCII-значение оставляем как есть, остальное упаковываем в =?utf-8?B?...?=."""
    if value.isascii():
        return value
    encoded = base64.b64encode(value.encode("utf-8")).decode("ascii")
    return f"=?utf-8?B?{encoded}?="


def build_text_message(sender: str, recipient: str, subject: str, text: str) -> bytes:
    for name, value in (("sender", sender), ("recipient", recipient), ("subject", subject)):
        if "\r" in value or "\n" in value:
            raise ValueError(f"{name} must not contain line breaks")

    headers = [
        f"From: {sender}",
        f"To: {recipient}",
        f"Subject: {encode_header_value(subject)}",
        f"Date: {formatdate(localtime=True)}",
        "MIME-Version: 1.0",
        "Content-Type: text/plain; charset=utf-8",
        "Content-Transfer-Encoding: base64",
    ]

    body_b64 = base64.b64encode(text.encode("utf-8")).decode("ascii")
    body_lines = [body_b64[i:i + 76] for i in range(0, len(body_b64), 76)]

    message = "\r\n".join(headers + [""] + body_lines) + "\r\n"
    return message.encode("ascii")


def build_message_with_image(sender: str, recipient: str, subject: str,
                             text: str, image_path: str) -> bytes:
    for name, value in (("sender", sender), ("recipient", recipient), ("subject", subject)):
        if "\r" in value or "\n" in value:
            raise ValueError(f"{name} must not contain line breaks")

    filename = os.path.basename(image_path)
    if not filename.isascii() or '"' in filename:
        raise ValueError("image file name must be ASCII and contain no quotes")

    with open(image_path, "rb") as f:
        image_data = f.read()

    content_type, _ = mimetypes.guess_type(image_path)
    if content_type is None:
        content_type = "application/octet-stream"

    text_b64 = base64.b64encode(text.encode("utf-8")).decode("ascii")
    text_lines = [text_b64[i:i + 76] for i in range(0, len(text_b64), 76)]

    image_b64 = base64.b64encode(image_data).decode("ascii")
    image_lines = [image_b64[i:i + 76] for i in range(0, len(image_b64), 76)]

    boundary = "==" + secrets.token_hex(16) + "=="

    lines = [
        f"From: {sender}",
        f"To: {recipient}",
        f"Subject: {encode_header_value(subject)}",
        f"Date: {formatdate(localtime=True)}",
        "MIME-Version: 1.0",
        f'Content-Type: multipart/mixed; boundary="{boundary}"',
        "",
        f"--{boundary}", # text part
        "Content-Type: text/plain; charset=utf-8",
        "Content-Transfer-Encoding: base64",
        "",
        *text_lines,
        f"--{boundary}", # image part
        f'Content-Type: {content_type}; name="{filename}"',
        "Content-Transfer-Encoding: base64",
        f'Content-Disposition: attachment; filename="{filename}"',
        "",
        *image_lines,
        f"--{boundary}--",
    ]
    return ("\r\n".join(lines) + "\r\n").encode("ascii")

def send_mail(host: str, port: int, username: str, password: str, sender: str, recipient: str, body: bytes) -> str:
    hostname = socket.gethostname()
    if not hostname.isascii() or " " in hostname:
        hostname = "localhost"

    sock = socket.create_connection((host, port), timeout=30)
    buffer = sock.makefile("rb")
    try:
        code, text = recv_reply(buffer)
        if code != 220:
            raise SMTPReplyError({220}, code, text)

        send_command(sock, buffer, f"EHLO {hostname}", {250})

        send_command(sock, buffer, "STARTTLS", {220})
        buffer.close()
        context = ssl.create_default_context()
        sock = context.wrap_socket(sock, server_hostname=host)
        buffer = sock.makefile("rb")
        send_command(sock, buffer, f"EHLO {hostname}", {250})

        credentials = f"\0{username}\0{password}".encode("utf-8")
        token = base64.b64encode(credentials).decode("ascii")
        send_command(sock, buffer, f"AUTH PLAIN {token}", {235})

        send_command(sock, buffer, f"MAIL FROM:<{sender}>", {250})
        send_command(sock, buffer, f"RCPT TO:<{recipient}>", {250, 251})
        result = send_data(sock, buffer, body)
        send_command(sock, buffer, "QUIT", {221})
        return result
    finally:
        buffer.close()
        sock.close()

def main() -> None:
    parser = argparse.ArgumentParser(description="Простой SMTP-клиент на сокетах")
    parser.add_argument("recipient", help="адрес получателя")
    parser.add_argument("--username", required=True, help="логин на SMTP-сервере (ваш адрес)")
    parser.add_argument("--password", required=True, help="пароль приложения")
    parser.add_argument("--subject", default="Lab 5", help="тема письма")
    parser.add_argument("--text", default="Hello from my SMTP client!", help="текст письма")
    parser.add_argument("--image", help="путь к картинке для вложения")
    parser.add_argument("--host", default="smtp.gmail.com", help="SMTP-сервер")
    parser.add_argument("--port", type=int, default=587, help="порт SMTP-сервера")

    args = parser.parse_args()

    sender = args.username

    try:
        if args.image is None:
            body = build_text_message(sender, args.recipient, args.subject, args.text)
        else:
            body = build_message_with_image(sender, args.recipient, args.subject, args.text, args.image)

        result = send_mail(args.host, args.port, args.username, args.password, sender, args.recipient, body)
        print(f"Success! Sent an email! Server reply: {result}")
    except (SMTPClientError, OSError, ValueError) as error:
        print(f"Error: {error}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()

