import argparse
import socket
import sys

from distant_access_protocol import MSG_ALIVE, MSG_OUTPUT, MSG_EXIT, EXIT_CODE, recv_message

def run_remote(host: str, port: int, command: str, timeout: float) -> int:
    with socket.create_connection((host, port), timeout=timeout) as sock:
        sock.sendall(command.encode("utf-8") + b"\n")

        with sock.makefile("rb") as buffer:
            while True:
                msg_type, payload = recv_message(buffer)

                if msg_type == MSG_OUTPUT:
                    print(payload.decode("utf-8", errors="replace"), end="", flush=True)
                elif msg_type == MSG_ALIVE:
                    continue
                elif msg_type == MSG_EXIT:
                    if len(payload) != EXIT_CODE.size:
                        raise ValueError(f"bad EXIT payload length: {len(payload)}")
                    return EXIT_CODE.unpack(payload)[0]


def main() -> None:
    parser = argparse.ArgumentParser(description="Distant access command execute client")
    parser.add_argument("--host", default="127.0.0.1", help="server address")
    parser.add_argument("--port", type=int, default=9000, help="server port")
    parser.add_argument("--timeout", type=float, default=10.0, help="timeout time")
    parser.add_argument("command", nargs="+", help="command to be executed on server")
    args = parser.parse_args()

    command = " ".join(args.command)
    if "\r" in command or "\n" in command:
        parser.error("command must not contain line breaks")

    try:
        code = run_remote(args.host, args.port, command, args.timeout)
    except ConnectionRefusedError:
        print(f"Error: nothing is listening on {args.host}:{args.port}", file=sys.stderr)
        sys.exit(1)
    except TimeoutError:
        print(f"\nError: server was silent for {args.timeout} s, assuming it is dead",
              file=sys.stderr)
        sys.exit(1)
    except ValueError as error:
        print(f"\nError: {error}", file=sys.stderr)
        sys.exit(1)
    except OSError as error:
        print(f"\nError: {error}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nInterrupted", file=sys.stderr)
        sys.exit(130)

    print(f"\n[remote command finished with exit code {code}]")
    sys.exit(code)


if __name__ == "__main__":
    main()