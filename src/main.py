"""Main entry point for the Polymarket live data collector.

Usage:
    python -m src.main                  # Use default config.yaml
    python -m src.main -c config.yaml   # Use custom config
"""

import argparse
import asyncio
import logging
import signal
import sys
import time

from .config import load_config, get_enabled_targets
from .market_discovery import MarketDiscovery
from .ws_collector import WsCollector, JsonlWriter

logger = logging.getLogger("collector")


def setup_logging(level: str = "INFO"):
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


async def discovery_loop(discovery: MarketDiscovery, collector: WsCollector,
                         interval: int, stop_event: asyncio.Event):
    """Periodically discover new markets and subscribe."""
    while not stop_event.is_set():
        try:
            # Discover new markets
            new_markets = await asyncio.to_thread(discovery.discover_all)
            if new_markets:
                logger.info("Discovered %d new markets", len(new_markets))
                collector.add_markets(new_markets)

            # Handle expired markets
            expired = discovery.get_expired_markets()
            for m in expired:
                logger.info("Market expired: %s", m.question[:50])
                collector.remove_market(m)

            active = discovery.get_active_markets()
            logger.info(
                "Active markets: %d | Subscribed: %d",
                len(active), len(collector._subscribed),
            )

        except Exception as e:
            logger.error("Discovery error: %s", e)

        # Wait for next discovery cycle
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval)
        except asyncio.TimeoutError:
            pass


async def stats_loop(collector: WsCollector, stop_event: asyncio.Event):
    """Periodically log collector statistics."""
    while not stop_event.is_set():
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=60)
        except asyncio.TimeoutError:
            pass
        stats = collector.stats()
        logger.info(
            "Stats | msgs=%d rate=%.1f/s tokens=%d elapsed=%ds",
            stats["messages"], stats["rate"],
            stats["subscribed_tokens"], stats["elapsed_seconds"],
        )


async def main_async(config: dict):
    stop_event = asyncio.Event()

    # Setup signal handlers
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except NotImplementedError:
            # Windows doesn't support add_signal_handler
            pass

    # Initialize components
    data_dir = config.get("collector", {}).get("data_dir", "./data")
    writer = JsonlWriter(data_dir)

    enabled_targets = get_enabled_targets(config)
    discovery_config = {**config, "targets": enabled_targets}
    discovery = MarketDiscovery(discovery_config)
    collector = WsCollector(config, writer)

    discovery_interval = config.get("gamma", {}).get("discovery_interval", 300)

    logger.info(
        "Starting collector with %d targets, discovery every %ds",
        len(enabled_targets), discovery_interval,
    )

    # Initial discovery
    new_markets = await asyncio.to_thread(discovery.discover_all)
    if new_markets:
        logger.info("Initial discovery: %d markets", len(new_markets))
        collector.add_markets(new_markets)
    else:
        logger.warning("No markets found in initial discovery")

    # Run all tasks
    tasks = [
        asyncio.create_task(collector.run()),
        asyncio.create_task(
            discovery_loop(discovery, collector, discovery_interval, stop_event)
        ),
        asyncio.create_task(stats_loop(collector, stop_event)),
    ]

    # On Windows, handle Ctrl+C via polling
    if sys.platform == "win32":
        async def _win_signal_check():
            try:
                while not stop_event.is_set():
                    await asyncio.sleep(0.5)
            except KeyboardInterrupt:
                stop_event.set()
        tasks.append(asyncio.create_task(_win_signal_check()))

    try:
        await asyncio.gather(*tasks, return_exceptions=True)
    except KeyboardInterrupt:
        pass
    finally:
        await collector.stop()
        writer.close_all()
        logger.info("Collector shut down")


def main():
    parser = argparse.ArgumentParser(description="Polymarket Live Data Collector")
    parser.add_argument("-c", "--config", default=None, help="Config file path")
    args = parser.parse_args()

    config = load_config(args.config)
    setup_logging(config.get("collector", {}).get("log_level", "INFO"))

    logger.info("=" * 60)
    logger.info("Polymarket Live Data Collector")
    logger.info("=" * 60)

    asyncio.run(main_async(config))


if __name__ == "__main__":
    main()
