"""WebSocket collector for Polymarket CLOB orderbook data.

Connects to Polymarket WebSocket, subscribes to YES token orderbooks,
and writes raw WS messages to JSONL files.
"""

import asyncio
import gzip
import json
import logging
import os
import time
from datetime import datetime, timezone

import websockets

from .constants import WS_URL
from .market_discovery import Market

logger = logging.getLogger(__name__)


class JsonlWriter:
    """Writes WS messages to JSONL files, one per token per day."""

    def __init__(self, data_dir: str):
        self.data_dir = data_dir
        self._files: dict[str, object] = {}  # token_id -> file handle
        self._paths: dict[str, str] = {}     # token_id -> file path
        self._current_date: str = ""

    def _get_dir(self, market: Market) -> str:
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return os.path.join(
            self.data_dir, f"{market.asset}_{market.timeframe}", date_str,
        )

    def write(self, market: Market, msg: dict, local_ts: int):
        """Write a single WS message to the appropriate JSONL file."""
        token_id = market.yes_token_id
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        # Rotate files on date change
        if date_str != self._current_date:
            self.flush_all()
            self._current_date = date_str

        if token_id not in self._files:
            out_dir = self._get_dir(market)
            os.makedirs(out_dir, exist_ok=True)
            path = os.path.join(out_dir, f"{market.slug}.jsonl")
            self._paths[token_id] = path
            self._files[token_id] = open(path, "a", encoding="utf-8")

        msg["local_ts"] = local_ts
        line = json.dumps(msg, ensure_ascii=False, separators=(",", ":"))
        self._files[token_id].write(line + "\n")

    def close_market(self, market: Market):
        """Close and compress the JSONL file for a finished market."""
        token_id = market.yes_token_id
        if token_id in self._files:
            self._files[token_id].close()
            del self._files[token_id]

            path = self._paths.pop(token_id, None)
            if path and os.path.exists(path):
                self._compress(path)

    def _compress(self, path: str):
        """Gzip compress a JSONL file."""
        gz_path = path + ".gz"
        try:
            with open(path, "rb") as f_in:
                with gzip.open(gz_path, "wb") as f_out:
                    while chunk := f_in.read(1024 * 1024):
                        f_out.write(chunk)
            os.remove(path)
            logger.info("Compressed: %s", gz_path)
        except Exception as e:
            logger.error("Compression failed for %s: %s", path, e)

    def flush_all(self):
        """Flush all open file handles."""
        for fh in self._files.values():
            fh.flush()

    def close_all(self):
        """Close all open file handles."""
        for fh in self._files.values():
            fh.close()
        self._files.clear()
        self._paths.clear()


class WsCollector:
    """Manages WebSocket connections to Polymarket CLOB."""

    def __init__(self, config: dict, writer: JsonlWriter):
        ws_cfg = config.get("websocket", {})
        self.ws_url = ws_cfg.get("url", WS_URL)
        self.heartbeat_interval = ws_cfg.get("heartbeat_interval", 8)
        self.reconnect_base = ws_cfg.get("reconnect_base_delay", 3)
        self.reconnect_max = ws_cfg.get("reconnect_max_delay", 30)
        self.max_tokens_per_conn = ws_cfg.get("max_tokens_per_connection", 25)

        self.writer = writer

        # token_id -> Market mapping
        self._token_market: dict[str, Market] = {}
        # Currently subscribed token_ids
        self._subscribed: set[str] = set()
        # Active WebSocket connections
        self._connections: list[asyncio.Task] = []
        # Tokens pending subscription
        self._pending_tokens: list[str] = []
        # Event to signal new subscriptions needed
        self._new_sub_event = asyncio.Event()
        # Global stop event
        self._stop = asyncio.Event()

        self._msg_count = 0
        self._start_time = 0.0

    def add_markets(self, markets: list[Market]):
        """Add markets for WebSocket subscription."""
        for m in markets:
            tid = m.yes_token_id
            if tid not in self._token_market:
                self._token_market[tid] = m
                if tid not in self._subscribed:
                    self._pending_tokens.append(tid)

        if self._pending_tokens:
            self._new_sub_event.set()

    def remove_market(self, market: Market):
        """Remove a market (after expiry). Close its JSONL file."""
        tid = market.yes_token_id
        self._subscribed.discard(tid)
        self._token_market.pop(tid, None)
        self.writer.close_market(market)

    async def run(self):
        """Main loop: manage WS connections and subscriptions."""
        self._start_time = time.time()
        logger.info("WsCollector started")

        while not self._stop.is_set():
            # Wait for tokens to subscribe
            if not self._pending_tokens and not self._subscribed:
                try:
                    await asyncio.wait_for(self._new_sub_event.wait(), timeout=10)
                except asyncio.TimeoutError:
                    continue
                self._new_sub_event.clear()

            # Launch connections for pending tokens
            if self._pending_tokens:
                await self._launch_connections()

            await asyncio.sleep(1)

    async def _launch_connections(self):
        """Launch WebSocket connections for pending tokens."""
        while self._pending_tokens:
            batch = []
            while self._pending_tokens and len(batch) < self.max_tokens_per_conn:
                batch.append(self._pending_tokens.pop(0))

            task = asyncio.create_task(self._ws_loop(batch))
            self._connections.append(task)

    async def _ws_loop(self, token_ids: list[str]):
        """Single WebSocket connection loop with auto-reconnect."""
        delay = self.reconnect_base
        while not self._stop.is_set():
            # Filter out tokens for markets that are no longer active
            active_ids = [t for t in token_ids if t in self._token_market]
            if not active_ids:
                logger.info("No active tokens left for this connection, exiting")
                return

            try:
                async with websockets.connect(
                    self.ws_url,
                    ping_interval=None,  # We handle heartbeat manually
                    close_timeout=5,
                    max_size=10 * 1024 * 1024,  # 10MB max message
                ) as ws:
                    logger.info(
                        "WS connected, subscribing to %d tokens", len(active_ids)
                    )

                    # Subscribe
                    sub_msg = json.dumps({
                        "assets_ids": active_ids,
                        "type": "market",
                        "custom_feature_enabled": True,
                    })
                    await ws.send(sub_msg)
                    self._subscribed.update(active_ids)

                    delay = self.reconnect_base  # Reset delay on success

                    # Run heartbeat and message receiver concurrently
                    hb_task = asyncio.create_task(self._heartbeat(ws))
                    try:
                        await self._receive_loop(ws)
                    finally:
                        hb_task.cancel()
                        try:
                            await hb_task
                        except asyncio.CancelledError:
                            pass

            except asyncio.CancelledError:
                return
            except Exception as e:
                logger.warning("WS error: %s, reconnecting in %ds", e, delay)
                self._subscribed -= set(active_ids)
                await asyncio.sleep(delay)
                delay = min(delay * 2, self.reconnect_max)

    async def _heartbeat(self, ws):
        """Send PING every heartbeat_interval seconds."""
        while True:
            await asyncio.sleep(self.heartbeat_interval)
            try:
                await ws.send("PING")
            except Exception:
                return

    async def _receive_loop(self, ws):
        """Receive and write WS messages."""
        async for raw_msg in ws:
            local_ts = time.time_ns()

            if raw_msg == "PONG":
                continue

            try:
                msgs = json.loads(raw_msg)
            except json.JSONDecodeError:
                continue

            if not isinstance(msgs, list):
                msgs = [msgs]

            for msg in msgs:
                asset_id = msg.get("asset_id")
                if not asset_id:
                    continue

                market = self._token_market.get(asset_id)
                if not market:
                    continue

                event_type = msg.get("event_type")
                if event_type not in ("book", "price_change", "last_trade_price"):
                    continue

                self.writer.write(market, msg, local_ts)
                self._msg_count += 1

                if self._msg_count % 10000 == 0:
                    elapsed = time.time() - self._start_time
                    logger.info(
                        "Messages: %d | Rate: %.1f/s | Tokens: %d",
                        self._msg_count, self._msg_count / max(elapsed, 1),
                        len(self._subscribed),
                    )

    async def stop(self):
        """Stop all connections gracefully."""
        self._stop.set()
        for task in self._connections:
            task.cancel()
        self.writer.flush_all()
        logger.info("WsCollector stopped. Total messages: %d", self._msg_count)

    def stats(self) -> dict:
        """Return collector statistics."""
        elapsed = time.time() - self._start_time if self._start_time else 0
        return {
            "messages": self._msg_count,
            "rate": self._msg_count / max(elapsed, 1),
            "subscribed_tokens": len(self._subscribed),
            "elapsed_seconds": int(elapsed),
        }
