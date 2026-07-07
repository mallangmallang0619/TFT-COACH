"""
Backend Entry Point

Starts the screen capture pipeline and WebSocket server.

Usage:
    python backend/main.py
    python backend/main.py --debug        (verbose logging + frame saves)
    python backend/main.py --demo         (demo mode with simulated data)
"""

import asyncio
import argparse
import logging
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from config import LOG_LEVEL, LogLevel


def setup_logging(debug: bool = False):
    """Configure logging output."""
    level = logging.DEBUG if debug else getattr(logging, LOG_LEVEL.value, logging.INFO)

    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    # Quiet down noisy libraries
    logging.getLogger("websockets").setLevel(logging.WARNING)
    logging.getLogger("PIL").setLevel(logging.WARNING)


def main():
    parser = argparse.ArgumentParser(description="TFT Coach Backend")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    parser.add_argument(
        "--demo", action="store_true",
        help="Run in demo mode with simulated game data (no screen capture)"
    )
    parser.add_argument(
        "--sim", action="store_true",
        help="Run the real detector+coach pipeline on synthesized board frames "
             "(no screen capture), cycling through comps for the frontend"
    )
    parser.add_argument(
        "--sim-comps", default=None,
        help="Comma-separated comp slugs for --sim (default: a built-in rotation)"
    )
    parser.add_argument(
        "--sim-dwell", type=float, default=6.0,
        help="Seconds to show each board in --sim mode (default: 6)"
    )
    parser.add_argument("--port", type=int, default=None, help="WebSocket port override")
    args = parser.parse_args()

    setup_logging(debug=args.debug)
    logger = logging.getLogger("tft-coach")

    if args.port:
        import config
        config.WEBSOCKET_PORT = args.port

    logger.info("=" * 60)
    logger.info("  TFT COACH — Desktop Overlay Backend")
    logger.info("=" * 60)

    if args.sim:
        logger.info("Running in SIM MODE (synthesized frames → real detector+coach)")
        from sim_server import SimulationServer
        comps = (
            [s.strip() for s in args.sim_comps.split(",") if s.strip()]
            if args.sim_comps else None
        )
        server = SimulationServer(comps=comps, dwell_seconds=args.sim_dwell)
    elif args.demo:
        logger.info("Running in DEMO MODE (simulated game data)")
        # Lazy import — demo_server only needs websockets + pydantic, not opencv/mss
        from demo_server import DemoServer
        server = DemoServer()
    else:
        logger.info("Running in LIVE MODE (screen capture)")
        try:
            from websocket_server import TFTCoachServer
        except ImportError as e:
            logger.error(
                f"Missing dependency for live mode: {e}\n"
                f"Install all deps with: pip install -r requirements.txt --break-system-packages\n"
                f"Or run in demo mode: python backend/main.py --demo"
            )
            sys.exit(1)
        server = TFTCoachServer()

    try:
        asyncio.run(server.start())
    except KeyboardInterrupt:
        logger.info("Shutting down...")
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
