#!/usr/bin/env python3
"""Dev-only TCP proxy: expose a localhost CDP port to the WSL vEthernet address.

Chromium binds --remote-debugging-port to 127.0.0.1 even when asked to bind
0.0.0.0. In NAT mode WSL cannot reach Windows localhost, so this tiny proxy
listens on the Windows vEthernet IP and forwards to 127.0.0.1. On the Windows
target (brain and bridge on the same machine) the proxy is not needed.
"""
from __future__ import annotations

import argparse
import socket
import threading


def relay(src: socket.socket, dst: socket.socket) -> None:
    try:
        while True:
            data = src.recv(65536)
            if not data:
                break
            dst.sendall(data)
    except OSError:
        pass
    finally:
        for sock in (src, dst):
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            sock.close()


def handle(client: socket.socket, target: tuple[str, int]) -> None:
    try:
        upstream = socket.create_connection(target, timeout=5)
    except OSError:
        client.close()
        return
    threading.Thread(target=relay, args=(client, upstream), daemon=True).start()
    threading.Thread(target=relay, args=(upstream, client), daemon=True).start()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--listen-host", default="172.23.112.1")
    parser.add_argument("--listen-port", type=int, default=9222)
    parser.add_argument("--target-host", default="127.0.0.1")
    parser.add_argument("--target-port", type=int, default=9222)
    args = parser.parse_args()
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((args.listen_host, args.listen_port))
    server.listen(16)
    print(
        f"cdp proxy {args.listen_host}:{args.listen_port} "
        f"-> {args.target_host}:{args.target_port}",
        flush=True,
    )
    while True:
        client, _ = server.accept()
        threading.Thread(
            target=handle,
            args=(client, (args.target_host, args.target_port)),
            daemon=True,
        ).start()


if __name__ == "__main__":
    raise SystemExit(main())
