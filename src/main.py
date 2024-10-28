import os
import sys
import asyncio
import logging
from aiohttp import web
from .config import Config
from .monitor import TokenMonitor
from .web import create_web_app

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

async def main_async():
    config = None
    monitor = None
    runner = None
    
    try:
        # Load configuration
        config_path = os.getenv('CONFIG_PATH', 'config.yaml')
        config = Config(config_path)
        
        # Initialize monitor
        monitor = TokenMonitor(config)
        
        # Create and start web server
        app = await create_web_app(monitor)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, '0.0.0.0', config.port)
        await site.start()
        
        logger.info(f"Server started on port {config.port}")
        
        # Initialize Web3 connections and start collection
        await monitor.init_web3_connections()
        await monitor.collect_metrics()
        
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        if monitor:
            await monitor.shutdown()
        if runner:
            await runner.cleanup()
        sys.exit(1)

def main():
    try:
        asyncio.run(main_async())
    except KeyboardInterrupt:
        logger.info("Received shutdown signal")
    except Exception as e:
        logger.error(f"Fatal error in main: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()