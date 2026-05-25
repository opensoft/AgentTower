"""Mock FEAT-011 daemon for FEAT-012 integration tests. T050 + research R-17.

Listens on a temp Unix socket and speaks the FEAT-011 `app.*` envelope
contract (`{ok, app_contract_version, result|error}`). Per-test process
spawn so there is no cross-test state pollution. Parameterized by a JSON
fixture file specifying which methods return which payloads (including
error codes from FEAT-011's 27-entry closed-set vocabulary in
`specs/011-app-backend-contract/contracts/error-codes.md`).

Usage:
    python3 server.py --socket /tmp/agenttower-test.sock --fixture us1_happy_path.json

Fixture format:
    {
        "app_contract_version": "1.0",
        "daemon_version": "0.11.0",
        "app_session_token": "<uuid-v4-hex-36-chars>",
        "app_session_id": 1,
        "host_user_id": "1000",
        "schema_version": 1,
        "responses": {
            "app.hello": {"ok": true, "result": {...}},
            "app.dashboard": {"ok": true, "result": {...}},
            "app.agent.register_from_pane": {"ok": true, "result": {...}},
            ...
        }
    }

If a request method is not in `responses`, returns the FEAT-011 closed-set
code `unknown_method` (FR-034b) with `details == {}`.

The harness enforces FEAT-011 FR-003a (1 MiB request / 8 MiB response caps)
and FR-003b (UTF-8 + \\n + no \\r / \\x00) so client-side framing bugs
surface during tests.
"""

import argparse
import asyncio
import copy
import json
import os
import sys
from pathlib import Path

REQUEST_CAP = 1024 * 1024
RESPONSE_CAP = 8 * 1024 * 1024
APP_CONTRACT_VERSION_DEFAULT = "1.0"


def _envelope_failure(fixture, code, message, details=None):
    """Build a FEAT-011 failure envelope with the canonical shape.

    Per `specs/011-app-backend-contract/contracts/error-codes.md`, every
    failure envelope is `{ok: false, app_contract_version, error: {code,
    message, details}}` and `details` is ALWAYS an object (never null).
    """
    return {
        "ok": False,
        "app_contract_version": fixture.get(
            "app_contract_version", APP_CONTRACT_VERSION_DEFAULT
        ),
        "error": {
            "code": code,
            "message": message,
            "details": details if details is not None else {},
        },
    }


def _envelope_app_contract_major_unsupported(fixture, client_major):
    """FR-036 — daemon emits a structured failure with both versions in details.

    Helper so tests that want to exercise the FR-002 banner path can
    inject a fixture entry like `{"ok": false, "_use_helper":
    "app_contract_major_unsupported"}` and the harness assembles the
    canonical `details` payload.
    """
    return _envelope_failure(
        fixture,
        "app_contract_major_unsupported",
        f"Daemon does not support app_contract major {client_major}",
        {
            "daemon_app_contract_version": fixture.get(
                "app_contract_version", APP_CONTRACT_VERSION_DEFAULT
            ),
            "client_app_contract_major": client_major,
        },
    )


def _stamp_app_hello_result(result, fixture):
    """Fill in the FEAT-011 contract-required fields on an `app.hello` success.

    Per `contracts/app-methods.md` §app.hello, the success `result` MUST
    contain: app_session_token, app_session_id, daemon_version,
    schema_version, app_contract_version, supported_minor_range,
    host_user_id, capability_flags, state.
    """
    result.setdefault(
        "app_session_token",
        fixture.get("app_session_token", "00000000-0000-4000-8000-000000000001"),
    )
    result.setdefault("app_session_id", fixture.get("app_session_id", 1))
    result.setdefault(
        "daemon_version", fixture.get("daemon_version", "0.0.0-mock")
    )
    result.setdefault("schema_version", fixture.get("schema_version", 1))
    contract_version = fixture.get(
        "app_contract_version", APP_CONTRACT_VERSION_DEFAULT
    )
    result.setdefault("app_contract_version", contract_version)
    result.setdefault(
        "supported_minor_range",
        fixture.get(
            "supported_minor_range",
            {"min": contract_version, "max": contract_version},
        ),
    )
    result.setdefault("host_user_id", fixture.get("host_user_id", "1000"))
    result.setdefault("capability_flags", fixture.get("capability_flags", {}))
    result.setdefault("state", "ok")


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
                err = _envelope_failure(
                    fixture,
                    "payload_too_large",
                    f"Request exceeds {REQUEST_CAP}-byte cap (FR-003a)",
                    {
                        "size_limit_bytes": REQUEST_CAP,
                        "actual_size_bytes": len(line),
                    },
                )
                writer.write((json.dumps(err) + "\n").encode("utf-8"))
                await writer.drain()
                continue

            # FR-003b strictness: reject \r or \x00 in the request line.
            stripped = line.rstrip(b"\n")
            if b"\r" in stripped:
                err = _envelope_failure(
                    fixture,
                    "malformed_request",
                    "Request contains stray carriage return (FR-003b)",
                    {"reason": "stray_carriage_return"},
                )
                writer.write((json.dumps(err) + "\n").encode("utf-8"))
                await writer.drain()
                continue
            if b"\x00" in stripped:
                err = _envelope_failure(
                    fixture,
                    "malformed_request",
                    "Request contains embedded NUL byte (FR-003b)",
                    {"reason": "embedded_nul"},
                )
                writer.write((json.dumps(err) + "\n").encode("utf-8"))
                await writer.drain()
                continue
            if not stripped:
                err = _envelope_failure(
                    fixture,
                    "malformed_request",
                    "Empty request line (FR-003b)",
                    {"reason": "empty_line"},
                )
                writer.write((json.dumps(err) + "\n").encode("utf-8"))
                await writer.drain()
                continue

            try:
                req = json.loads(stripped.decode("utf-8"))
            except UnicodeDecodeError as e:
                err = _envelope_failure(
                    fixture,
                    "malformed_request",
                    f"Request is not valid UTF-8: {e}",
                    {"reason": "invalid_utf8"},
                )
                writer.write((json.dumps(err) + "\n").encode("utf-8"))
                await writer.drain()
                continue
            except json.JSONDecodeError as e:
                err = _envelope_failure(
                    fixture,
                    "malformed_request",
                    f"Failed to parse JSON: {e}",
                    {"reason": "json_decode_error"},
                )
                writer.write((json.dumps(err) + "\n").encode("utf-8"))
                await writer.drain()
                continue

            method = req.get("method", "")
            req_id = req.get("id")

            # Look up fixture response; fall back to unknown_method per FR-034b.
            response_template = fixture.get("responses", {}).get(method)
            if response_template is None:
                response = _envelope_failure(
                    fixture,
                    "unknown_method",
                    f"Mock daemon has no fixture for {method}",
                )
            else:
                # Deep-copy so tests that mutate response_template via setdefault
                # below don't corrupt the next call's template.
                response = copy.deepcopy(response_template)
                # If a fixture explicitly opts into the helper-built failure,
                # rebuild it now so client_app_contract_major is plumbed through.
                if (
                    response.get("ok") is False
                    and response.get("_use_helper")
                    == "app_contract_major_unsupported"
                ):
                    client_major = (
                        req.get("params", {}).get("client_app_contract_major")
                    )
                    response = _envelope_app_contract_major_unsupported(
                        fixture, client_major
                    )
                response.setdefault(
                    "app_contract_version",
                    fixture.get(
                        "app_contract_version", APP_CONTRACT_VERSION_DEFAULT
                    ),
                )

            if req_id is not None:
                response["id"] = req_id

            # Special-case app.hello to inject the full FEAT-011 success shape.
            if method == "app.hello" and response.get("ok"):
                result = response.setdefault("result", {})
                _stamp_app_hello_result(result, fixture)

            # T174(b) — mirror the submitted `generated_prompt_text` into
            # the `app.handoff.submit` response row so the daemon
            # round-trip is observable from the test side (closes the
            # non-tautological half of T169's SC-004 assertion). The
            # mock daemon is otherwise stateless / fixture-templated;
            # this is the narrowest splice that makes the submit echo
            # what the client actually sent without persisting the
            # row across calls.
            if method == "app.handoff.submit" and response.get("ok"):
                submitted_prompt_text = (
                    req.get("params", {})
                    .get("draft", {})
                    .get("generated_prompt_text")
                )
                if submitted_prompt_text is not None:
                    result = response.setdefault("result", {})
                    row = result.setdefault("row", {})
                    row["generated_prompt_text"] = submitted_prompt_text

            line_out = (json.dumps(response) + "\n").encode("utf-8")
            if len(line_out) > RESPONSE_CAP:
                # Shouldn't happen in tests; fixtures should keep responses small.
                err = _envelope_failure(
                    fixture,
                    "internal_error",
                    "Mock-daemon response exceeds 8 MiB cap",
                )
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
