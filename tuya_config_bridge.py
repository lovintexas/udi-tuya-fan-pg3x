import json
import os
import socket
import socketserver
import threading
from pathlib import Path

SOCKET_NAME = "tuya_config.sock"
MAX_REQUEST = 1024 * 1024


class BridgeHandler(socketserver.StreamRequestHandler):
    def handle(self):
        try:
            line = self.rfile.readline(MAX_REQUEST + 1)
            if len(line) > MAX_REQUEST or not line.endswith(b"\n"):
                raise ValueError("Invalid request size")

            request = json.loads(line)
            action = request.get("action")

            if action == "read":
                result = self.server.config_sync.snapshot(timeout=15)

            elif action == "write":
                params = request.get("params")
                result = self.server.config_sync.save(
                    self.server.polyglot, params, timeout=15
                )

            elif action == "restart_ns":
                if self.server.restart_callback is None:
                    raise RuntimeError("Restart callback unavailable")
                result = self.server.restart_callback()

            elif action == "delete_node":
                if self.server.delete_callback is None:
                    raise RuntimeError("Deletion callback unavailable")
                result = self.server.delete_callback(
                    request.get("address")
                )

            else:
                raise ValueError("Unsupported action")

            response = {"successful": True, "data": result}

        except Exception as exc:
            response = {
                "successful": False,
                "error": str(exc)
            }

        self.wfile.write((json.dumps(response) + "\n").encode())


class BridgeServer(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True
    allow_reuse_address = False


def start_bridge(
    base, config_sync, polyglot,
    delete_callback=None, restart_callback=None
):
    path = Path(base) / SOCKET_NAME

    if path.exists():
        if not path.is_socket():
            raise RuntimeError("Bridge path exists and is not a socket")
        path.unlink()

    server = BridgeServer(str(path), BridgeHandler)
    os.chmod(path, 0o600)

    server.config_sync = config_sync
    server.polyglot = polyglot
    server.delete_callback = delete_callback
    server.restart_callback = restart_callback

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    return server


def request_bridge(base, action, params=None, address=None, timeout=30):
    path = str(Path(base) / SOCKET_NAME)
    request = {"action": action}
    if params is not None:
        request["params"] = params
    if address is not None:
        request["address"] = address

    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(timeout)
        client.connect(path)
        client.sendall((json.dumps(request) + "\n").encode())

        response = bytearray()
        while not response.endswith(b"\n"):
            chunk = client.recv(65536)
            if not chunk:
                raise RuntimeError("Bridge connection closed")
            response.extend(chunk)
            if len(response) > MAX_REQUEST:
                raise ValueError("Bridge response too large")

    result = json.loads(response)
    if not result.get("successful"):
        raise RuntimeError(result.get("error", "Bridge request failed"))

    return result["data"]
