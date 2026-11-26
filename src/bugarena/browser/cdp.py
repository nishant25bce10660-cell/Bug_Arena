"""Pure-stdlib RFC 6455 async WebSocket CDP client (127.0.0.1 loopback only)."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import struct
from collections import defaultdict
from typing import Any
from urllib.parse import urlparse

import httpx

_WS_MAGIC = b"258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
_MAX_FRAME_BYTES = 32 * 1024 * 1024


class CDPError(RuntimeError):
    """Raised when CDP returns a protocol error or WebSocket fails."""


class CDPClient:
    """Async Chrome DevTools Protocol client speaking RFC 6455 WebSocket over loopback TCP."""

    def __init__(self, ws_url: str):
        if any(ch in ws_url for ch in ("\r", "\n", "\x00")):
            raise ValueError(f"CDPClient rejects control characters in ws_url: {ws_url!r}")
        parsed = urlparse(ws_url)
        if parsed.scheme != "ws" or parsed.hostname not in ("127.0.0.1", "localhost"):
            raise ValueError(f"CDPClient permits loopback ws:// only, got {ws_url!r}")
        self.ws_url = ws_url
        self.host = parsed.hostname
        self.port = parsed.port or 80
        self.path = parsed.path or "/"
        if parsed.query:
            self.path = f"{self.path}?{parsed.query}"

        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._recv_task: asyncio.Task[None] | None = None
        self._next_id = 0
        self._pending: dict[int, asyncio.Future[dict[str, Any]]] = {}
        self.events: dict[str, list[dict[str, Any]]] = defaultdict(list)

    @classmethod
    async def from_port(cls, port: int, *, prefer_page_target: bool = True) -> CDPClient:
        """Discover WebSocket debugger URL from 127.0.0.1:<port> and connect."""
        async with httpx.AsyncClient(timeout=5.0, trust_env=False) as client:
            if prefer_page_target:
                resp = await client.get(f"http://127.0.0.1:{port}/json/list")
                resp.raise_for_status()
                targets = resp.json()
                for t in targets:
                    if t.get("type") == "page" and t.get("webSocketDebuggerUrl"):
                        inst = cls(t["webSocketDebuggerUrl"])
                        try:
                            await inst.connect()
                        except BaseException:
                            await inst.close()
                            raise
                        return inst
            ver = await client.get(f"http://127.0.0.1:{port}/json/version")
            ver.raise_for_status()
            ws_url = ver.json()["webSocketDebuggerUrl"]
            inst = cls(ws_url)
            try:
                await inst.connect()
            except BaseException:
                await inst.close()
                raise
            return inst

    async def connect(self) -> None:
        self._reader, self._writer = await asyncio.wait_for(
            asyncio.open_connection(self.host, self.port, limit=16 * 1024 * 1024),
            timeout=5.0,
        )
        try:
            key = base64.b64encode(os.urandom(16)).decode("ascii")
            handshake = (
                f"GET {self.path} HTTP/1.1\r\n"
                f"Host: {self.host}:{self.port}\r\n"
                "Upgrade: websocket\r\n"
                "Connection: Upgrade\r\n"
                f"Sec-WebSocket-Key: {key}\r\n"
                "Sec-WebSocket-Version: 13\r\n\r\n"
            )
            self._writer.write(handshake.encode("ascii"))
            await self._writer.drain()

            status_line = await asyncio.wait_for(self._reader.readline(), timeout=5.0)
            if b"101" not in status_line:
                raise CDPError(f"WebSocket handshake failed: {status_line!r}")

            accept_expected = base64.b64encode(hashlib.sha1(key.encode("ascii") + _WS_MAGIC).digest()).decode("ascii")
            headers: dict[str, str] = {}
            while True:
                line = await asyncio.wait_for(self._reader.readline(), timeout=5.0)
                if line in (b"\r\n", b"\n", b""):
                    break
                if b":" in line:
                    k, v = line.decode("latin1").split(":", 1)
                    headers[k.strip().lower()] = v.strip()
            if headers.get("sec-websocket-accept") != accept_expected:
                raise CDPError("Invalid Sec-WebSocket-Accept from CDP endpoint.")

            self._recv_task = asyncio.create_task(self._recv_loop())
        except BaseException:
            await self.close()
            raise

    async def _send_frame(self, opcode: int, payload: bytes) -> None:
        if not self._writer:
            raise CDPError("CDPClient not connected")
        mask = os.urandom(4)
        header = bytearray([0x80 | opcode])
        n = len(payload)
        if n < 126:
            header.append(0x80 | n)
        elif n <= 0xFFFF:
            header.append(0x80 | 126)
            header.extend(struct.pack("!H", n))
        else:
            header.append(0x80 | 127)
            header.extend(struct.pack("!Q", n))
        header.extend(mask)
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        self._writer.write(bytes(header) + masked)
        await self._writer.drain()

    async def _read_frame(self) -> tuple[int, bytes]:
        assert self._reader is not None
        b1, b2 = await self._reader.readexactly(2)
        fin = (b1 & 0x80) != 0
        opcode = b1 & 0x0F
        masked = (b2 & 0x80) != 0
        length = b2 & 0x7F
        if length == 126:
            (length,) = struct.unpack("!H", await self._reader.readexactly(2))
        elif length == 127:
            (length,) = struct.unpack("!Q", await self._reader.readexactly(8))
        if length > _MAX_FRAME_BYTES:
            raise CDPError(f"WebSocket frame too large ({length} > {_MAX_FRAME_BYTES})")
        mask = await self._reader.readexactly(4) if masked else b""
        data = await self._reader.readexactly(length)
        if masked:
            data = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
        if not fin:
            # Accumulate continuation frames
            chunks = [data]
            total = len(data)
            while True:
                nb1, nb2 = await self._reader.readexactly(2)
                nfin = (nb1 & 0x80) != 0
                nlen = nb2 & 0x7F
                if nlen == 126:
                    (nlen,) = struct.unpack("!H", await self._reader.readexactly(2))
                elif nlen == 127:
                    (nlen,) = struct.unpack("!Q", await self._reader.readexactly(8))
                total += nlen
                if total > _MAX_FRAME_BYTES:
                    raise CDPError(f"Fragmented WebSocket frame exceeds {_MAX_FRAME_BYTES}")
                nmask = await self._reader.readexactly(4) if (nb2 & 0x80) else b""
                ndata = await self._reader.readexactly(nlen)
                if nmask:
                    ndata = bytes(b ^ nmask[i % 4] for i, b in enumerate(ndata))
                chunks.append(ndata)
                if nfin:
                    break
            data = b"".join(chunks)
        return opcode, data

    async def _recv_loop(self) -> None:
        try:
            while self._reader is not None:
                opcode, data = await self._read_frame()
                if opcode == 0x8:
                    break
                if opcode == 0x9:
                    await self._send_frame(0xA, data)
                    continue
                if opcode not in (0x1, 0x2):
                    continue
                msg = json.loads(data.decode("utf-8", errors="replace"))
                if "id" in msg:
                    fut = self._pending.pop(msg["id"], None)
                    if fut and not fut.done():
                        if "error" in msg:
                            fut.set_exception(CDPError(str(msg["error"])))
                        else:
                            fut.set_result(msg.get("result", {}))
                elif "method" in msg:
                    self.events[msg["method"]].append(msg.get("params", {}))
        except asyncio.CancelledError:
            raise
        except (asyncio.IncompleteReadError, OSError, ValueError, CDPError):
            pass
        finally:
            for fut in list(self._pending.values()):
                if not fut.done():
                    fut.set_exception(CDPError("CDP WebSocket disconnected"))
            self._pending.clear()

    async def send(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        *,
        timeout: float = 15.0,
    ) -> dict[str, Any]:
        self._next_id += 1
        cmd_id = self._next_id
        loop = asyncio.get_running_loop()
        fut: asyncio.Future[dict[str, Any]] = loop.create_future()
        self._pending[cmd_id] = fut
        try:
            payload = json.dumps({"id": cmd_id, "method": method, "params": params or {}}).encode("utf-8")
            await self._send_frame(0x1, payload)
            return await asyncio.wait_for(fut, timeout=timeout)
        finally:
            self._pending.pop(cmd_id, None)

    async def close(self) -> None:
        if self._recv_task and not self._recv_task.done():
            self._recv_task.cancel()
            try:
                await self._recv_task
            except asyncio.CancelledError:
                pass
        if self._writer is not None:
            try:
                self._writer.close()
                await self._writer.wait_closed()
            except OSError:
                pass
        self._writer = None
        self._reader = None
