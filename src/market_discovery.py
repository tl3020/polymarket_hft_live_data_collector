"""Market discovery via Gamma API.

Discovers active Polymarket Up-or-Down markets and extracts
YES (UP) token_ids for WebSocket subscription.
"""

import json
import logging
import time
from datetime import datetime, timezone
from dataclasses import dataclass, field

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .constants import GAMMA_BASE_URL, CLOB_BASE_URL

logger = logging.getLogger(__name__)

# Map config asset name to Gamma API tag slug
ASSET_TAG_MAP = {
    "btc": "bitcoin",
    "eth": "ethereum",
    "sol": "solana",
    "xrp": "xrp",
}


@dataclass
class Market:
    """A single Polymarket Up-or-Down market."""
    condition_id: str
    yes_token_id: str
    no_token_id: str
    question: str
    slug: str
    end_date: str          # ISO format
    end_ts: float          # unix timestamp
    asset: str             # btc, eth, sol, xrp
    timeframe: str         # 1h, 4h, 1d
    series_slug: str
    tick_size: float = 0.01
    active: bool = True


class MarketDiscovery:
    """Discovers and manages active markets via Gamma API."""

    def __init__(self, config: dict):
        self.gamma_url = config.get("gamma", {}).get("base_url", GAMMA_BASE_URL)
        self.clob_url = config.get("clob", {}).get("base_url", CLOB_BASE_URL)
        self.request_delay = config.get("gamma", {}).get("request_delay", 0.2)
        self.targets = config.get("targets", [])

        self.session = requests.Session()
        retry = Retry(total=3, backoff_factor=1, status_forcelist=[429, 500, 502, 503])
        self.session.mount("https://", HTTPAdapter(max_retries=retry))

        # All known markets: condition_id -> Market
        self.markets: dict[str, Market] = {}

    def discover_all(self) -> list[Market]:
        """Discover active markets for all enabled targets."""
        new_markets = []
        for target in self.targets:
            if not target.get("enabled", True):
                continue
            found = self._discover_series(
                series_slug=target["series_slug"],
                asset=target["asset"],
                timeframe=target["timeframe"],
            )
            new_markets.extend(found)
        return new_markets

    def _discover_series(self, series_slug: str, asset: str, timeframe: str) -> list[Market]:
        """Discover active markets for a single series via tag-based filtering."""
        new_markets = []
        asset_tag = ASSET_TAG_MAP.get(asset, asset)
        try:
            resp = self.session.get(
                f"{self.gamma_url}/events",
                params=[
                    ("tag_slug", "up-or-down"),
                    ("tag_slug", asset_tag),
                    ("closed", "false"),
                    ("limit", "100"),
                ],
                timeout=15,
            )
            resp.raise_for_status()
            events = resp.json()

            if not isinstance(events, list):
                events = [events] if events else []

            for event in events:
                # Match only events belonging to the target series
                if event.get("seriesSlug") != series_slug:
                    continue

                for mkt in event.get("markets", []):
                    if mkt.get("closed"):
                        continue
                    cid = mkt.get("conditionId", "")
                    if not cid or cid in self.markets:
                        continue

                    # clobTokenIds is a JSON-encoded string in the API response
                    raw_ids = mkt.get("clobTokenIds", "[]")
                    if isinstance(raw_ids, str):
                        token_ids = json.loads(raw_ids)
                    else:
                        token_ids = raw_ids
                    if len(token_ids) < 2:
                        continue

                    end_date = mkt.get("endDate", "")
                    end_ts = 0.0
                    if end_date:
                        try:
                            dt = datetime.fromisoformat(end_date.replace("Z", "+00:00"))
                            end_ts = dt.timestamp()
                        except ValueError:
                            pass

                    # Skip already expired
                    if end_ts > 0 and end_ts < time.time():
                        continue

                    slug = mkt.get("slug", cid[:16])
                    market = Market(
                        condition_id=cid,
                        yes_token_id=token_ids[0],
                        no_token_id=token_ids[1],
                        question=mkt.get("question", ""),
                        slug=slug,
                        end_date=end_date,
                        end_ts=end_ts,
                        asset=asset,
                        timeframe=timeframe,
                        series_slug=series_slug,
                    )

                    # Query tick_size
                    market.tick_size = self._get_tick_size(token_ids[0])

                    self.markets[cid] = market
                    new_markets.append(market)
                    logger.info(
                        "Discovered: %s | %s_%s | ends %s | tick=%.4f",
                        market.question[:50], asset, timeframe,
                        end_date[:16], market.tick_size,
                    )
                    time.sleep(self.request_delay)

        except Exception as e:
            logger.error("Discovery failed for %s: %s", series_slug, e)

        return new_markets

    def _get_tick_size(self, token_id: str) -> float:
        """Query tick_size from CLOB API."""
        try:
            resp = self.session.get(
                f"{self.clob_url}/tick-size",
                params={"token_id": token_id},
                timeout=10,
            )
            if resp.status_code == 200:
                data = resp.json()
                ts = float(data) if isinstance(data, (int, float, str)) else 0.01
                return ts if ts > 0 else 0.01
        except Exception:
            pass
        return 0.01

    def get_active_markets(self) -> list[Market]:
        """Return currently active (not expired) markets."""
        now = time.time()
        active = []
        for m in self.markets.values():
            if m.end_ts > 0 and m.end_ts < now:
                m.active = False
            if m.active:
                active.append(m)
        return active

    def get_expired_markets(self) -> list[Market]:
        """Return markets that have expired since last check."""
        now = time.time()
        expired = []
        for m in self.markets.values():
            if m.active and m.end_ts > 0 and m.end_ts < now:
                m.active = False
                expired.append(m)
        return expired

    def get_yes_token_ids(self) -> list[str]:
        """Return YES token_ids of all active markets."""
        return [m.yes_token_id for m in self.get_active_markets()]

    def find_market_by_token(self, token_id: str) -> Market | None:
        """Find market by YES token_id."""
        for m in self.markets.values():
            if m.yes_token_id == token_id:
                return m
        return None
