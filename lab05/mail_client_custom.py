import argparse
import socket
import ssl
import base64


def send_recv(sock: socket.socket, cmd: str = None) -> str:
    if cmd:
        print(f"C: {cmd.strip()}")
        sock.sendall(cmd.encode('utf-8'))

    full_response = ""
    while True:
        chunk = sock.recv(4096).decode('utf-8')
        full_response += chunk

        lines = full_response.strip('\r\n').split('\r\n')
        last_line = lines[-1] if lines else ""

        if len(last_line) >= 4 and last_line[3] == ' ':
            break

    print(f"S:\n{full_response.strip()}")
    return full_response

def build_message(sender: str, recipient: str, subject: str, body: str, format: str) -> str:
    content_type = "text/html" if format == "html" else "text/plain"

    msg = (
        f"From: {sender}\r\n"
        f"To: {recipient}\r\n"
        f"Subject: {subject}\r\n"
        f"Content-Type: {content_type}; charset=utf-8\r\n"
        "\r\n"
        f"{body}"
    )
    return msg

def send_email():
    parser = argparse.ArgumentParser()
    parser.add_argument("recipient", help="recipient email address")
    parser.add_argument("--sender", required=True, help="sender email address")
    parser.add_argument("--username", required=True, help="auth username")
    parser.add_argument("--password", required=True, help="auth password")
    parser.add_argument("--format", choices=("txt", "html"), default="txt", help="message format")

    parser.add_argument("--subject", required=True, help="email subject")
    parser.add_argument("--body", help="email body")
    args = parser.parse_args()

    message = build_message(args.sender, args.recipient, args.subject, args.body, args.format)

    SMTP_SERVER = "smtp.gmail.com"
    SMTP_PORT = 587

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(15)

    try:
        sock.connect((SMTP_SERVER, SMTP_PORT))
        send_recv(sock)

        send_recv(sock, "EHLO localhost\r\n")
        send_recv(sock, "STARTTLS\r\n")

        context = ssl.create_default_context()
        secure_sock = context.wrap_socket(sock, server_hostname=SMTP_SERVER)

        send_recv(secure_sock, "EHLO localhost\r\n")
        send_recv(secure_sock, "AUTH LOGIN\r\n")

        user_b64 = base64.b64encode(args.username.encode()).decode() + "\r\n"
        send_recv(secure_sock, user_b64)

        pass_b64 = base64.b64encode(args.password.encode()).decode() + "\r\n"
        send_recv(secure_sock, pass_b64)

        send_recv(secure_sock, f"MAIL FROM:<{args.sender}>\r\n")
        send_recv(secure_sock, f"RCPT TO:<{args.recipient}>\r\n")

        send_recv(secure_sock, "DATA\r\n")
        send_recv(secure_sock, f"{message}\r\n.\r\n")
        send_recv(secure_sock, "QUIT\r\n")
    finally:
        if 'secure_sock' in locals():
            secure_sock.close()
        else:
            sock.close()


def main() -> None:
    try:
        send_email()
        print(f"\nSuccessfully sent an email!")
    except Exception as error:
        print(f"Error: {error}")

if __name__ == "__main__":
    main()

