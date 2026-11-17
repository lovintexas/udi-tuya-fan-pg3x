"""Same-port HTTP redirect and transparent HTTPS forwarding."""

import asyncio
import ipaddress
import re
from contextlib import suppress

PUBLIC_PORT = 8767
BACKEND_PORT = 18767


async def relay(reader, writer):
    try:
        while data := await reader.read(65536):
            writer.write(data)
            await writer.drain()
    except (OSError, ConnectionError):
        pass
    finally:
        writer.close()


async def handle_client(reader, writer):
    backend = None

    try:
        # Timeout applies to this connection, not the listening server.
        first = await asyncio.wait_for(reader.read(1), timeout=5)

        if not first:
            return

        if first == b"\x16":
            # TLS handshake: forward encrypted bytes unchanged.
            backend_reader, backend = await asyncio.open_connection(
                "127.0.0.1", BACKEND_PORT
            )

            backend.write(first)
            await backend.drain()

            upstream = asyncio.create_task(relay(reader, backend))
            downstream = asyncio.create_task(relay(backend_reader, writer))

            done, pending = await asyncio.wait(
                (upstream, downstream),
                return_when=asyncio.FIRST_COMPLETED,
            )

            for task in pending:
                task.cancel()

            await asyncio.gather(
                upstream, downstream, return_exceptions=True
            )

        else:
            # Plain HTTP: read headers, then redirect to HTTPS.
            request = first + await asyncio.wait_for(
                reader.readuntil(b"\r\n\r\n"),
                timeout=5
            )

            lines = request.split(b"\r\n")
            request_line = lines[0].decode("ascii", "replace").split()

            if len(request_line) != 3 or not request_line[2].startswith("HTTP/"):
                return

            path = request_line[1]
            if not path.startswith("/") or path.startswith("//"):
                path = "/"

            host = None
            for line in lines[1:]:
                if line.lower().startswith(b"host:"):
                    host = line[5:].strip().decode("ascii", "replace")
                    break

            # Validate the Host header before constructing a redirect.
            valid_host = False

            if host and host.endswith(f":{PUBLIC_PORT}"):
                hostname = host[:-(len(str(PUBLIC_PORT)) + 1)]

                try:
                    ipaddress.ip_address(hostname.strip("[]"))
                    valid_host = True
                except ValueError:
                    valid_host = bool(
                        re.fullmatch(
                            r"[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?",
                            hostname
                        )
                    )

            if not valid_host:
                response = (
                    b"HTTP/1.1 400 Bad Request\r\n"
                    b"Content-Length: 0\r\nConnection: close\r\n\r\n"
                )
            else:
                location = f"https://{host}{path}"
                response = (
                    "HTTP/1.1 308 Permanent Redirect\r\n"
                    f"Location: {location}\r\n"
                    "Content-Length: 0\r\n"
                    "Connection: close\r\n\r\n"
                ).encode("ascii", "replace")

            writer.write(response)
            await writer.drain()

    except (OSError, ConnectionError, asyncio.TimeoutError,
            asyncio.IncompleteReadError, asyncio.LimitOverrunError):
        pass
    finally:
        if backend is not None:
            backend.close()
            with suppress(Exception):
                await backend.wait_closed()

        writer.close()
        with suppress(Exception):
            await writer.wait_closed()


async def serve():
    server = await asyncio.start_server(
        handle_client, "0.0.0.0", PUBLIC_PORT
    )
    async with server:
        await server.serve_forever()
