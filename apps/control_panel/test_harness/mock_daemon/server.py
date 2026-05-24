"""Mock FEAT-011 daemon for FEAT-012 integration tests. T050 + research R-17.

Listens on a temp Unix socket and speaks the FEAT-011 `app.*` envelope
contract (`{ok, app_contract_version, result|error}`). Per-test process
spawn so there is no cross-test state pollution. Parameterized by a JSON
fixture file specifying which methods return which payloads (including
error codes from FEAT-011's 27-entry closed-set vocabulary).

Usage:
    python3 server.py --socket /tmp/agenttower-test.sock --fixture us1_happy_path.json

Fixture format:
    {
        "app_contract_version": "1.0",
        "daemon_version": "0.11.0",
        "session_token": "test-session-token",
        "responses": {
            "app.hello": {"ok": true, "result": {...}},
            "app.dashboard": {"ok": true, "result": {...}},
            "app.agent.register_from_pane": {"ok": true, "result": {...}},
            ...
        }
    }

If a request method is not in `responses`, returns
`{"ok": false, "error": {"code": "method_not_found", "message": "...", "details": {}}}`.

The harness enforces FEAT-011 FR-003a (1 MiB/8 MiB caps) and FR-003b
(UTF-8 + \\n + no \\r / \\x00) so client-side framing bugs surface
during tests.
"""

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

REQUEST_CAP = 1024 * 1024
RESPONSE_CAP = 8 * 1024 * 1024
APP_CONTRACT_VERSION_DEFAULT = "1.0"


async def handle_client(reader, writer, fixture):
    """One client connection: read newline-delimited JSON requests, write responses."""
    addr = writer.get_extra_info("peername")
    print(f"[mock_daemon] client connected: {addr}", file=sys.stderr)
    try:
        while True:
            line = await reader.readline()
            if not line:
                break
            if len(line) > REQUEST_CAP:
                err = {
                    "ok": False,
                    "app_contract_version": fixture.get(
                        "app_contract_version", APP_CONTRACT_VERSION_DEFAULT
                    ),
                    "error": {
                        "code": "payload_too_large",
                        "message": f"Request exceeds {REQUEST_CAP}-byte cap (FR-003a)",
                        "details": {"actual_bytes": len(line)},
                    },
                }
                writer.write((json.dumps(err) + "\n").encode("utf-8"))
                await writer.drain()
                continue

            # FR-003b strictness: reject \r or \x00 in the request line.
            stripped = line.rstrip(b"\n")
            if b"\r" in stripped or b"\x00" in stripped:
                err = {
                    "ok": False,
                    "app_contract_version": fixture.get(
                        "app_contract_version", APP_CONTRACT_VERSION_DEFAULT
                    ),
                    "error": {
                        "code": "malformed_request",
                        "message": "Request contains forbidden control character (FR-003b)",
                        "details": {},
                    },
                }
                writer.write((json.dumps(err) + "\n").encode("utf-8"))
                await writer.drain()
                continue

            try:
                req = json.loads(stripped.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as e:
                err = {
                    "ok": False,
                    "app_contract_version": fixture.get(
                        "app_contract_version", APP_CONTRACT_VERSION_DEFAULT
                    ),
                    "error": {
                        "code": "malformed_request",
                        "message": f"Failed to parse JSON: {e}",
                        "details": {},
                    },
                }
                writer.write((json.dumps(err) + "\n").encode("utf-8"))
                await writer.drain()
                continue

            method = req.get("method", "")
            req_id = req.get("id")

            # Look up fixture response; fall back to method_not_found.
            response_template = fixture.get("responses", {}).get(method)
            if response_template is None:
                response = {
                    "ok": False,
                    "app_contract_version": fixture.get(
                        "app_contract_version", APP_CONTRACT_VERSION_DEFAULT
                    ),
                    "error": {
                        "code": "method_not_found",
                        "message": f"Mock daemon has no fixture for {method}",
                        "details": {"method": method},
                    },
                }
            else:
                # Deep-copy + stamp contract version + correlate by id.
                response = dict(response_template)
                response.setdefault(
                    "app_contract_version",
                    fixture.get("app_contract_version", APP_CONTRACT_VERSION_DEFAULT),
                )

            if req_id is not None:
                response["id"] = req_id

            # Special-case app.hello to inject session_token.
            if method == "app.hello" and response.get("ok"):
                result = response.setdefault("result", {})
                result.setdefault(
                    "session_token", fixture.get("session_token", "mock-session-token")
                )
                result.setdefault(
                    "daemon_version", fixture.get("daemon_version", "0.0.0-mock")
                )

            line_out = (json.dumps(response) + "\n").encode("utf-8")
            if len(line_out) > RESPONSE_CAP:
                # Shouldn't happen in tests; fixtures should keep responses small.
                err = {
                    "ok": False,
                    "app_contract_version": fixture.get(
                        "app_contract_version", APP_CONTRACT_VERSION_DEFAULT
                    ),
                    "error": {
                        "code": "internal_error",
                        "message": "Mock-daemon response exceeds 8 MiB cap",
                        "details": {},
                    },
                }
                writer.write((json.dumps(err) + "\n").encode("utf-8"))
            else:
                writer.write(line_out)
            await writer.drain()
    except (ConnectionResetError, BrokenPipeError):
        pass
    finally:
        print(f"[mock_daemon] client disconnected: {addr}", file=sys.stderr)
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass


async def serve(socket_path: str, fixture: dict):
    """Listens on the Unix socket and serves clients until SIGINT."""
    if os.path.exists(socket_path):
        os.unlink(socket_path)
    server = await asyncio.start_unix_server(
        lambda r, w: handle_client(r, w, fixture),
        path=socket_path,
    )
    print(f"[mock_daemon] listening at {socket_path}", file=sys.stderr)
    async with server:
        await server.serve_forever()


def main():
    parser = argparse.ArgumentParser(description="FEAT-012 mock daemon harness (T050)")
    parser.add_argument(
        "--socket",
        required=True,
        help="Unix socket path the mock daemon will bind to",
    )
    parser.add_argument(
        "--fixture",
        required=True,
        type=Path,
        help="JSON fixture file specifying per-method responses",
    )
    args = parser.parse_args()

    with args.fixture.open() as f:
        fixture = json.load(f)

    try:
        asyncio.run(serve(args.socket, fixture))
    except KeyboardInterrupt:
        print("[mock_daemon] shutting down", file=sys.stderr)
    finally:
        if os.path.exists(args.socket):
            os.unlink(args.socket)


if __name__ == "__main__":
    main()
