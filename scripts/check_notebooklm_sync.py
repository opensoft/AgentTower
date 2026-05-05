#!/usr/bin/env python3
"""Check or refresh Markdown sources in an AgentTower NotebookLM notebook."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shlex
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ZERO_SHA = "0000000000000000000000000000000000000000"


@dataclass(frozen=True)
class SourceMapping:
    path: str
    title: str
    source_id: str | None = None
    content_sha256: str | None = None


@dataclass(frozen=True)
class NotebookSource:
    source_id: str
    title: str


@dataclass
class CheckResult:
    notebook_id: str
    notebook_title: str | None
    checked_markdown: list[str]
    needs_refresh: list[SourceMapping]
    missing_sources: list[SourceMapping]
    unmapped_markdown: list[str]
    verified_sources: list[SourceMapping]

    @property
    def ok(self) -> bool:
        return not (self.needs_refresh or self.missing_sources or self.unmapped_markdown)


@dataclass
class RefreshResult:
    notebook_id: str
    notebook_title: str | None
    refreshed: list[SourceMapping]
    skipped: list[SourceMapping]
    verified: list[SourceMapping]
    unmapped_markdown: list[str]

    @property
    def ok(self) -> bool:
        return not self.unmapped_markdown


def run_git(args: list[str], cwd: Path) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"git {' '.join(args)} failed: {completed.stderr.strip()}"
        )
    return completed.stdout


def repo_root() -> Path:
    output = run_git(["rev-parse", "--show-toplevel"], Path.cwd())
    return Path(output.strip())


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_config(path: Path) -> tuple[dict[str, Any], str, str | None, list[SourceMapping]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    notebook_id = data["notebook_id"]
    notebook_title = data.get("notebook_title")
    sources = [
        SourceMapping(
            path=item["path"],
            source_id=item.get("source_id"),
            title=item["title"],
            content_sha256=item.get("content_sha256"),
        )
        for item in data.get("sources", [])
    ]
    return data, notebook_id, notebook_title, sources


def write_config(
    path: Path,
    data: dict[str, Any],
    refreshed: list[SourceMapping],
    root: Path,
) -> None:
    refreshed_by_path = {item.path: item for item in refreshed}
    for item in data.get("sources", []):
        refreshed_item = refreshed_by_path.get(item["path"])
        if refreshed_item is None:
            continue
        item["source_id"] = refreshed_item.source_id
        item["content_sha256"] = sha256_file(root / refreshed_item.path)
        item["synced_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def changed_markdown_files(
    root: Path, base: str | None, head: str | None, include_all: bool
) -> list[str]:
    if include_all or not (base and head) or base == ZERO_SHA or head == ZERO_SHA:
        output = run_git(["ls-files", "*.md"], root)
        return sorted(line for line in output.splitlines() if line.endswith(".md"))

    output = run_git(["diff", "--name-only", base, head, "--", "*.md"], root)
    return sorted(line for line in output.splitlines() if line.endswith(".md"))


def parse_tool_text(result: Any) -> str:
    texts: list[str] = []
    for item in getattr(result, "content", []):
        text = getattr(item, "text", None)
        if text:
            texts.append(text)
    raw = "\n".join(texts).strip()
    if not raw:
        raise RuntimeError("NotebookLM MCP returned an empty response.")
    return raw


def parse_tool_json(result: Any, *, allow_text: bool = False) -> dict[str, Any]:
    raw = parse_tool_text(result)
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        if allow_text:
            return {"raw": raw}
        raise RuntimeError(f"NotebookLM MCP returned non-JSON output: {raw}") from exc


def extract_source_id(payload: dict[str, Any]) -> str | None:
    candidates: list[Any] = [
        payload.get("source_id"),
        payload.get("id"),
        payload.get("uuid"),
    ]
    for key in ("source", "result", "data"):
        value = payload.get(key)
        if isinstance(value, dict):
            candidates.extend([value.get("source_id"), value.get("id"), value.get("uuid")])
    sources = payload.get("sources")
    if isinstance(sources, list):
        for source in sources:
            if isinstance(source, dict):
                candidates.extend([source.get("source_id"), source.get("id"), source.get("uuid")])
    for candidate in candidates:
        if isinstance(candidate, str) and candidate:
            return candidate
    return None


def nested_source_id(value: Any) -> str | None:
    if isinstance(value, str) and value:
        return value
    if isinstance(value, list) and value:
        return nested_source_id(value[0])
    return None


def parse_notebook_source(source: Any) -> NotebookSource | None:
    if isinstance(source, dict):
        source_id = source.get("id") or source.get("source_id")
        title = source.get("title") or source.get("name")
        if isinstance(source_id, str) and isinstance(title, str):
            return NotebookSource(source_id=source_id, title=title)
        return None

    # notebooklm-mcp-server currently returns NotebookLM's raw array payload:
    # [[source_id], title, ...]. Keep this parser isolated so the rest of the
    # sync code can work with stable objects.
    if isinstance(source, list) and len(source) >= 2:
        source_id = nested_source_id(source[0])
        title = source[1]
        if source_id and isinstance(title, str):
            return NotebookSource(source_id=source_id, title=title)
    return None


def extract_notebook_sources(payload: dict[str, Any]) -> list[NotebookSource]:
    source_groups: list[Any] = []
    if isinstance(payload.get("sources"), list):
        source_groups.append(payload["sources"])

    notebook = payload.get("notebook")
    if isinstance(notebook, dict) and isinstance(notebook.get("sources"), list):
        source_groups.append(notebook["sources"])
    elif isinstance(notebook, list):
        for notebook_row in notebook:
            if isinstance(notebook_row, dict) and isinstance(notebook_row.get("sources"), list):
                source_groups.append(notebook_row["sources"])
            elif (
                isinstance(notebook_row, list)
                and len(notebook_row) > 1
                and isinstance(notebook_row[1], list)
            ):
                source_groups.append(notebook_row[1])

    sources: list[NotebookSource] = []
    seen: set[str] = set()
    for group in source_groups:
        if not isinstance(group, list):
            continue
        for raw_source in group:
            source = parse_notebook_source(raw_source)
            if source and source.source_id not in seen:
                sources.append(source)
                seen.add(source.source_id)
    return sources


class NotebookMcpClient:
    def __init__(self, command: str, url: str | None = None) -> None:
        self.command = command
        self.url = url
        self.session: Any = None
        self._stdio_context: Any = None
        self._session_context: Any = None
        self.tool_names: set[str] = set()

    async def __aenter__(self) -> "NotebookMcpClient":
        try:
            from mcp import ClientSession, StdioServerParameters
            from mcp.client.streamable_http import streamablehttp_client
            from mcp.client.stdio import stdio_client
        except ImportError as exc:
            raise RuntimeError(
                "Missing Python package 'mcp'. Install it with: python -m pip install mcp"
            ) from exc

        try:
            if self.url:
                self._stdio_context = streamablehttp_client(self.url)
                read_stream, write_stream, _ = await self._stdio_context.__aenter__()
            else:
                parts = shlex.split(self.command)
                if not parts:
                    raise RuntimeError("NOTEBOOKLM_MCP_COMMAND is empty.")

                server = StdioServerParameters(
                    command=parts[0],
                    args=parts[1:],
                    env=dict(os.environ),
                )
                self._stdio_context = stdio_client(server)
                read_stream, write_stream = await self._stdio_context.__aenter__()
            self._session_context = ClientSession(read_stream, write_stream)
            self.session = await self._session_context.__aenter__()
            await self.session.initialize()
            tools = await self.session.list_tools()
            self.tool_names = {tool.name for tool in tools.tools}
            return self
        except BaseException:
            await self._close_after_failed_enter(*sys.exc_info())
            raise

    async def _close_after_failed_enter(
        self, exc_type: Any, exc: Any, tb: Any
    ) -> None:
        close_errors: list[BaseException] = []
        if self._session_context is not None:
            try:
                await self._session_context.__aexit__(exc_type, exc, tb)
            except BaseException as close_exc:
                close_errors.append(close_exc)
        if self._stdio_context is not None:
            try:
                await self._stdio_context.__aexit__(exc_type, exc, tb)
            except BaseException as close_exc:
                close_errors.append(close_exc)
        if close_errors:
            print(
                "NotebookLM MCP cleanup after initialization failure also failed: "
                + "; ".join(str(error) for error in close_errors),
                file=sys.stderr,
            )

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        if self._session_context is not None:
            await self._session_context.__aexit__(exc_type, exc, tb)
        if self._stdio_context is not None:
            await self._stdio_context.__aexit__(exc_type, exc, tb)

    async def call_tool(
        self, name: str, args: dict[str, Any], *, allow_text: bool = False
    ) -> dict[str, Any]:
        if name not in self.tool_names:
            raise RuntimeError(f"NotebookLM MCP server does not expose {name}.")
        result = await self.session.call_tool(name, args)
        if getattr(result, "isError", False):
            raise RuntimeError(f"{name} failed: {parse_tool_text(result)}")
        payload = parse_tool_json(result, allow_text=allow_text)
        if payload.get("status") not in (None, "success"):
            raise RuntimeError(f"{name} failed: {payload}")
        return payload

    async def notebook_sources(self, notebook_id: str) -> list[NotebookSource]:
        if "notebook_get" not in self.tool_names:
            available = ", ".join(sorted(self.tool_names))
            raise RuntimeError(
                "NotebookLM MCP server does not expose notebook_get. "
                f"Available tools: {available}"
            )
        payload = await self.call_tool("notebook_get", {"notebook_id": notebook_id})
        return extract_notebook_sources(payload)

    async def delete_source(self, source_id: str) -> None:
        if "source_delete" in self.tool_names:
            await self.call_tool(
                "source_delete",
                {"source_id": source_id, "confirm": True},
                allow_text=True,
            )
            return
        if "delete_source" in self.tool_names:
            await self.call_tool(
                "delete_source",
                {"source_id": source_id, "confirm": True},
                allow_text=True,
            )
            return
        raise RuntimeError(
            "Refreshing an existing source requires source_delete or delete_source, "
            "but neither tool is exposed by the NotebookLM MCP server."
        )

    async def add_text_source(self, notebook_id: str, title: str, text: str) -> str | None:
        candidates: list[tuple[str, dict[str, Any]]] = []
        if "source_add" in self.tool_names:
            candidates.append(
                (
                    "source_add",
                    {
                        "notebook_id": notebook_id,
                        "source_type": "text",
                        "title": title,
                        "text": text,
                        "wait": True,
                        "wait_timeout": 180,
                    },
                )
            )
        if "notebook_add_text" in self.tool_names:
            candidates.extend(
                [
                    ("notebook_add_text", {"notebook_id": notebook_id, "title": title, "text": text}),
                    ("notebook_add_text", {"notebook_id": notebook_id, "title": title, "content": text}),
                ]
            )
        if "source_add_text" in self.tool_names:
            candidates.extend(
                [
                    ("source_add_text", {"notebook_id": notebook_id, "title": title, "text": text}),
                    ("source_add_text", {"notebook_id": notebook_id, "title": title, "content": text}),
                ]
            )

        errors: list[str] = []
        for name, args in candidates:
            try:
                payload = await self.call_tool(name, args, allow_text=True)
                return extract_source_id(payload)
            except Exception as exc:
                errors.append(f"{name}: {exc}")

        available = ", ".join(sorted(self.tool_names))
        raise RuntimeError(
            "NotebookLM MCP server does not expose a compatible text source add tool. "
            f"Available tools: {available}. Tried: {'; '.join(errors)}"
        )


def sources_matching(mapping: SourceMapping, rows: list[NotebookSource]) -> list[NotebookSource]:
    matches: list[NotebookSource] = []
    for row in rows:
        if mapping.source_id and row.source_id == mapping.source_id:
            matches.append(row)
        elif row.title == mapping.title:
            matches.append(row)
    seen: set[str] = set()
    unique: list[NotebookSource] = []
    for match in matches:
        if match.source_id not in seen:
            unique.append(match)
            seen.add(match.source_id)
    return unique


def content_is_synced(root: Path, mapping: SourceMapping) -> bool:
    file_path = root / mapping.path
    return bool(
        mapping.content_sha256
        and file_path.exists()
        and sha256_file(file_path) == mapping.content_sha256
    )


def evaluate(
    root: Path,
    notebook_id: str,
    notebook_title: str | None,
    mappings: list[SourceMapping],
    checked: list[str],
    notebook_rows: list[NotebookSource],
) -> CheckResult:
    by_path = {mapping.path: mapping for mapping in mappings}
    verified: list[SourceMapping] = []
    missing: list[SourceMapping] = []
    needs_refresh: list[SourceMapping] = []
    unmapped: list[str] = []

    for mapping in mappings:
        if sources_matching(mapping, notebook_rows):
            verified.append(mapping)
        else:
            missing.append(mapping)

    for path in checked:
        mapping = by_path.get(path)
        if mapping is None:
            unmapped.append(path)
        elif not content_is_synced(root, mapping):
            needs_refresh.append(mapping)

    return CheckResult(
        notebook_id=notebook_id,
        notebook_title=notebook_title,
        checked_markdown=checked,
        needs_refresh=needs_refresh,
        missing_sources=missing,
        unmapped_markdown=unmapped,
        verified_sources=verified,
    )


async def wait_for_source(
    client: NotebookMcpClient,
    notebook_id: str,
    mapping: SourceMapping,
    timeout_seconds: int,
) -> NotebookSource:
    import anyio

    deadline = time.monotonic() + timeout_seconds
    last_matches: list[NotebookSource] = []
    while time.monotonic() < deadline:
        rows = await client.notebook_sources(notebook_id)
        last_matches = sources_matching(mapping, rows)
        if len(last_matches) == 1:
            return last_matches[0]
        await anyio.sleep(5)
    if not last_matches:
        raise RuntimeError(f"Could not verify refreshed source for {mapping.path}.")
    raise RuntimeError(
        f"Could not verify refreshed source for {mapping.path}: "
        f"found {len(last_matches)} sources titled {mapping.title!r}."
    )


async def refresh_sources(
    root: Path,
    config_path: Path,
    data: dict[str, Any],
    notebook_id: str,
    notebook_title: str | None,
    mappings: list[SourceMapping],
    checked: list[str],
    command: str,
    url: str | None,
    verify_timeout: int,
) -> RefreshResult:
    by_path = {mapping.path: mapping for mapping in mappings}
    checked_mappings: list[SourceMapping] = []
    unmapped: list[str] = []
    for path in checked:
        mapping = by_path.get(path)
        if mapping is None:
            unmapped.append(path)
        else:
            checked_mappings.append(mapping)

    if unmapped:
        return RefreshResult(
            notebook_id=notebook_id,
            notebook_title=notebook_title,
            refreshed=[],
            skipped=[],
            verified=[],
            unmapped_markdown=unmapped,
        )

    refreshed: list[SourceMapping] = []
    skipped: list[SourceMapping] = []
    verified: list[SourceMapping] = []

    async with NotebookMcpClient(command, url) as client:
        rows = await client.notebook_sources(notebook_id)
        targets: list[SourceMapping] = []
        for mapping in mappings:
            is_checked = mapping in checked_mappings
            missing = not sources_matching(mapping, rows)
            unsynced = not content_is_synced(root, mapping)
            if is_checked or missing or unsynced:
                targets.append(mapping)
            else:
                skipped.append(mapping)

        for mapping in targets:
            file_path = root / mapping.path
            if not file_path.exists():
                raise RuntimeError(f"Mapped Markdown file does not exist: {mapping.path}")

            current_rows = await client.notebook_sources(notebook_id)
            old_sources = sources_matching(mapping, current_rows)
            if old_sources and not (
                "source_delete" in client.tool_names or "delete_source" in client.tool_names
            ):
                raise RuntimeError(
                    "Cannot refresh existing NotebookLM source because the MCP server "
                    "does not expose source_delete or delete_source."
                )

            text = file_path.read_text(encoding="utf-8")
            new_source_id = await client.add_text_source(notebook_id, mapping.title, text)

            for old_source in old_sources:
                await client.delete_source(old_source.source_id)

            refreshed_mapping = SourceMapping(
                path=mapping.path,
                title=mapping.title,
                source_id=new_source_id,
                content_sha256=sha256_file(file_path),
            )
            verified_source = await wait_for_source(
                client,
                notebook_id,
                refreshed_mapping,
                verify_timeout,
            )
            refreshed_mapping = SourceMapping(
                path=mapping.path,
                title=mapping.title,
                source_id=verified_source.source_id,
                content_sha256=sha256_file(file_path),
            )
            refreshed.append(refreshed_mapping)
            verified.append(refreshed_mapping)

        final_rows = await client.notebook_sources(notebook_id)
        final_result = evaluate(
            root,
            notebook_id,
            notebook_title,
            [*mappings, *refreshed],
            [mapping.path for mapping in mappings],
            final_rows,
        )
        if final_result.missing_sources:
            missing_paths = ", ".join(mapping.path for mapping in final_result.missing_sources)
            raise RuntimeError(f"Final verification failed; missing sources: {missing_paths}")

    if refreshed:
        write_config(config_path, data, refreshed, root)

    return RefreshResult(
        notebook_id=notebook_id,
        notebook_title=notebook_title,
        refreshed=refreshed,
        skipped=skipped,
        verified=verified,
        unmapped_markdown=[],
    )


def render_check_summary(result: CheckResult) -> str:
    lines = [
        "# NotebookLM sync check",
        "",
        f"Notebook: `{result.notebook_title or result.notebook_id}`",
        "",
    ]

    if result.ok:
        lines.append("All checked Markdown files are mapped and content hashes match the last recorded NotebookLM refresh.")
        return "\n".join(lines) + "\n"

    if result.checked_markdown:
        lines.extend(["## Checked Markdown", ""])
        lines.extend(f"- `{path}`" for path in result.checked_markdown)
        lines.append("")

    if result.needs_refresh:
        lines.extend(["## Needs NotebookLM Refresh", ""])
        for mapping in result.needs_refresh:
            lines.append(f"- `{mapping.path}` -> `{mapping.title}`")
        lines.append("")

    if result.missing_sources:
        lines.extend(["## Missing NotebookLM Sources", ""])
        for mapping in result.missing_sources:
            expected = mapping.source_id or mapping.title
            lines.append(f"- `{mapping.path}` expected `{expected}`")
        lines.append("")

    if result.unmapped_markdown:
        lines.extend(["## Markdown Without Source Mapping", ""])
        lines.extend(f"- `{path}`" for path in result.unmapped_markdown)
        lines.append("")

    lines.append("Run the NotebookLM refresh workflow or update the notebook manually.")
    return "\n".join(lines) + "\n"


def render_refresh_summary(result: RefreshResult) -> str:
    lines = [
        "# NotebookLM refresh",
        "",
        f"Notebook: `{result.notebook_title or result.notebook_id}`",
        "",
    ]

    if result.unmapped_markdown:
        lines.extend(["## Markdown Without Source Mapping", ""])
        lines.extend(f"- `{path}`" for path in result.unmapped_markdown)
        lines.append("")
        return "\n".join(lines) + "\n"

    if result.refreshed:
        lines.extend(["## Refreshed Sources", ""])
        for mapping in result.refreshed:
            lines.append(f"- `{mapping.path}` -> `{mapping.title}` (`{mapping.source_id}`)")
        lines.append("")
    else:
        lines.append("No sources needed refresh.")
        lines.append("")

    lines.extend(["## Verification", ""])
    if result.verified:
        for mapping in result.verified:
            lines.append(f"- verified `{mapping.title}` is visible in NotebookLM")
    else:
        lines.append("- all configured sources were already visible in NotebookLM")
    lines.append("")

    return "\n".join(lines)


def append_github_summary(summary: str) -> None:
    summary_path = os.getenv("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return
    with Path(summary_path).open("a", encoding="utf-8") as handle:
        handle.write(summary)
        if not summary.endswith("\n"):
            handle.write("\n")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        default=".notebooklm/sources.json",
        help="NotebookLM source mapping JSON file.",
    )
    parser.add_argument(
        "--mode",
        choices=("check", "refresh"),
        default="check",
        help="Check mappings or refresh NotebookLM sources.",
    )
    parser.add_argument("--base", default=os.getenv("GIT_BASE_SHA"))
    parser.add_argument("--head", default=os.getenv("GIT_HEAD_SHA"))
    parser.add_argument(
        "--all",
        action="store_true",
        help="Check or refresh all tracked Markdown files instead of the git diff.",
    )
    parser.add_argument(
        "--mcp-command",
        default=os.getenv("NOTEBOOKLM_MCP_COMMAND", "notebooklm-mcp"),
        help="Command used to start the NotebookLM MCP server.",
    )
    parser.add_argument(
        "--mcp-url",
        default=os.getenv("NOTEBOOKLM_MCP_URL"),
        help="HTTP URL for an already-running NotebookLM MCP server.",
    )
    parser.add_argument(
        "--verify-timeout",
        type=int,
        default=120,
        help="Seconds to wait for refreshed sources to appear in NotebookLM.",
    )
    parser.add_argument(
        "--github-summary",
        action="store_true",
        help="Append the report to GITHUB_STEP_SUMMARY when available.",
    )
    parser.add_argument(
        "--warn-only",
        action="store_true",
        help="Print findings without exiting non-zero.",
    )
    return parser.parse_args()


async def main() -> int:
    args = parse_args()
    root = repo_root()
    config_path = (root / args.config).resolve()
    data, notebook_id, notebook_title, mappings = load_config(config_path)
    checked = changed_markdown_files(root, args.base, args.head, args.all)

    if args.mode == "refresh":
        refresh_result = await refresh_sources(
            root,
            config_path,
            data,
            notebook_id,
            notebook_title,
            mappings,
            checked,
            args.mcp_command,
            args.mcp_url,
            args.verify_timeout,
        )
        summary = render_refresh_summary(refresh_result)
        print(summary)
        if args.github_summary:
            append_github_summary(summary)
        if refresh_result.ok or args.warn_only:
            return 0
        return 1

    async with NotebookMcpClient(args.mcp_command, args.mcp_url) as client:
        rows = await client.notebook_sources(notebook_id)
    check_result = evaluate(root, notebook_id, notebook_title, mappings, checked, rows)
    summary = render_check_summary(check_result)
    print(summary)
    if args.github_summary:
        append_github_summary(summary)
    if check_result.ok or args.warn_only:
        return 0
    return 1


if __name__ == "__main__":
    try:
        try:
            import anyio
        except ImportError:
            import asyncio

            raise SystemExit(asyncio.run(main()))
        raise SystemExit(anyio.run(main))
    except Exception as exc:
        print(f"NotebookLM sync failed: {exc}", file=sys.stderr)
        raise SystemExit(2)
