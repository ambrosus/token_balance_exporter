import os
import yaml
import logging
from web3 import Web3
from web3.providers import AsyncHTTPProvider
from prometheus_client import Gauge, Counter, generate_latest
import asyncio
from aiohttp import web
import time
from web3.middleware import async_geth_poa_middleware
from typing import Dict, List, Optional
from dataclasses import dataclass
import sys

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Add new metrics
health_gauge = Gauge('exporter_health', 'Health status of the exporter (1 = healthy, 0 = unhealthy)')
last_successful_scrape = Gauge('exporter_last_successful_scrape_timestamp', 'Timestamp of the last successful scrape')
scrape_failures_total = Counter('exporter_scrape_failures_total', 'Total number of scrape failures', ['network'])
rpc_health = Gauge('exporter_rpc_health', 'RPC endpoint health status (1 = healthy, 0 = unhealthy)', ['network'])


# USDC Contract ABI - only including balanceOf function
TOKEN_ABI = [
    {
        "inputs": [{"name": "account", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function"
    }
]

@dataclass
class TokenConfig:
    address: str
    decimals: int

@dataclass
class AddresConfig:
    alias: str
    address: str

@dataclass
class NetworkConfig:
    rpc_url: str
    tokens: Dict[str, TokenConfig]
    addresses: List[AddresConfig]

@dataclass
class Settings:
    scrape_interval: int
    port: int
    health_check_interval: int = 30  # default to 30 seconds

class Config:
    def __init__(self, config_path: str):
        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)
        
        self.networks: Dict[str, NetworkConfig] = {}
        self.scrape_interval = config['settings']['scrape_interval']
        self.port = config['settings']['port']
        self.health_check_interval = config['settings'].get('health_check_interval', 30)

        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)
        
        self.networks: Dict[str, NetworkConfig] = {}
        self.scrape_interval = config['settings']['scrape_interval']
        self.port = config['settings']['port']
        
        # Parse network configurations
        for network_name, network_data in config['networks'].items():
            logger.info(f"Loading config for network: {network_name}")
            logger.info(f"RPC URL: {network_data['rpc_url']}")
            
            tokens = {
                token_name: TokenConfig(
                    address=token_data['address'],
                    decimals=token_data['decimals']
                )
                for token_name, token_data in network_data['tokens'].items()
            }
            
            addresses = [
                AddresConfig(
                    alias=address_data['alias'],
                    address=address_data['address']
                )
                for address_data in network_data['addresses']
            ]
            
            self.networks[network_name] = NetworkConfig(
                rpc_url=network_data['rpc_url'],
                tokens=tokens,
                addresses=addresses
            )

# Single Gauge metric with labels
token_balance = Gauge(
    'token_balance',
    'Token balance for a address',
    ['network', 'token', 'token_address', 'alias', 'address']
)

class TokenMonitor:
    def __init__(self, config: Config):
        self.config = config
        self.web3_instances: Dict[str, Optional[Web3]] = {}
        self.running = True
        self.last_successful_scrape_time = 0
        self.last_health_check = {}
        self.app = web.Application()
        self.setup_routes()

    def setup_routes(self):
        self.app.router.add_get("/health", self.health_check_handler)
        self.app.router.add_get("/metrics", self.metrics_handler)
        
    async def metrics_handler(self, request):
        metrics_data = generate_latest()
        return web.Response(
            body=metrics_data,
            content_type='text/plain; version=0.0.4'
        )

    async def health_check_handler(self, request):
        # Check if we have at least one working RPC connection
        has_working_rpc = any(w3 is not None for w3 in self.web3_instances.values())
        
        # Check if we had a successful scrape in the last 2 intervals
        last_scrape_ok = time.time() - last_successful_scrape._value.get() < (self.config.scrape_interval * 2)
        
        is_healthy = has_working_rpc and last_scrape_ok
        health_gauge.set(1 if is_healthy else 0)
        
        if is_healthy:
            return web.Response(text="healthy", status=200)
        else:
            return web.Response(text="unhealthy", status=500)

    async def check_rpc_health(self, network_name: str, w3: Web3) -> bool:
        try:
            request = w3.provider.make_request("eth_blockNumber", [])
            response = await request
            if "result" in response:
                self.last_health_check[network_name] = time.time()
                rpc_health.labels(network=network_name).set(1)
                return True
        except Exception as e:
            logger.error(f"Health check failed for {network_name}: {str(e)}")
        
        rpc_health.labels(network=network_name).set(0)
        return False
    
    async def setup_web3(self, network_name: str, rpc_url: str) -> Optional[Web3]:
        """Setup and test a Web3 connection"""
        logger.info(f"Attempting to connect to {network_name} at {rpc_url}")
        try:
            # Create async provider
            provider = AsyncHTTPProvider(rpc_url, request_kwargs={'timeout': 30})
            w3 = Web3(provider)
            
            logger.info(f"{network_name} Web3 instance created. Testing connection...")
            
            try:
                # Use the async version directly
                request = w3.provider.make_request("eth_blockNumber", [])
                response = await request
                block_number = int(response["result"], 16)  # Convert hex to int
                logger.info(f"Successfully connected to {network_name} (block: {block_number})")
                return w3
            except Exception as e:
                logger.error(f"Failed to get block number from {network_name}: {str(e)}")
                logger.error(f"Error type: {type(e).__name__}")
                logger.error(f"Full error details: {str(e)}")
                return None

        except Exception as e:
            logger.error(f"Failed to initialize Web3 for {network_name}: {str(e)}")
            logger.error(f"Error type: {type(e).__name__}")
            logger.error(f"Full error details: {str(e)}")
            return None
    
    async def get_token_balance(self, w3: Web3, token_address: str, address: str, decimals: int) -> float:
        try:
            contract = w3.eth.contract(
                address=Web3.to_checksum_address(token_address), 
                abi=TOKEN_ABI
            )
            
            # Encode the function call
            func = contract.encodeABI(
                fn_name='balanceOf',
                args=[Web3.to_checksum_address(address)]
            )
            
            # Make the eth_call request
            request = w3.provider.make_request(
                "eth_call",
                [
                    {
                        "to": Web3.to_checksum_address(token_address),
                        "data": func,
                    },
                    "latest"
                ]
            )
            response = await request
            
            # Decode the response
            if "result" in response and response["result"]:
                balance = int(response["result"], 16)
                return balance / (10 ** decimals)
            else:
                logger.error(f"Invalid response format: {response}")
                return 0.0
        except Exception as e:
            logger.error(f"Error getting balance for {address} from {token_address}: {str(e)}")
            logger.error(f"Error type: {type(e).__name__}")
            logger.error(f"Full error details: {str(e)}")
            return 0.0

    async def collect_metrics(self):
        logger.info("Starting metrics collection...")
        
        while self.running:
            try:
                tasks = []
                labels_list = []
                
                # Check RPC health first
                health_checks = []
                for network_name, w3 in self.web3_instances.items():
                    if w3:
                        health_checks.append(self.check_rpc_health(network_name, w3))
                
                # Wait for health checks to complete
                await asyncio.gather(*health_checks)
                
                for network_name, network_config in self.config.networks.items():
                    w3 = self.web3_instances.get(network_name)
                    if not w3:
                        logger.warning(f"No Web3 connection for {network_name}, skipping...")
                        scrape_failures_total.labels(network=network_name).inc()
                        continue

                    for token_name, token_config in network_config.tokens.items():
                        for address in network_config.addresses:
                            tasks.append(
                                self.get_token_balance(
                                    w3,
                                    token_config.address,
                                    address.address,
                                    token_config.decimals
                                )
                            )
                            labels_list.append({
                                'network': network_name,
                                'token': token_name,
                                'token_address': token_config.address,
                                'alias': address.alias,
                                'address': address.address
                            })

                if tasks:
                    balances = await asyncio.gather(*tasks, return_exceptions=True)
                    update_count = 0

                    for balance, labels in zip(balances, labels_list):
                        if isinstance(balance, Exception):
                            logger.error(f"Error getting balance for {labels}: {balance}")
                            scrape_failures_total.labels(network=labels['network']).inc()
                            continue
                        token_balance.labels(**labels).set(balance)
                        update_count += 1

                    logger.info(f"Updated {update_count} metrics successfully")
                    
                    if update_count > 0:
                        last_successful_scrape.set(time.time())
                else:
                    logger.warning("No metrics to collect, check your configuration and connections")

            except Exception as e:
                logger.error(f"Error in collection loop: {e}")

            await asyncio.sleep(self.config.scrape_interval)
    
    async def init_web3_connections(self):
        """Initialize Web3 connections and verify them"""
        for network_name, network_config in self.config.networks.items():
            logger.info(f"Initializing connection for {network_name}...")
            w3 = await self.setup_web3(network_name, network_config.rpc_url)
            if w3:
                w3.middleware_onion.inject(async_geth_poa_middleware, layer=0)
                self.web3_instances[network_name] = w3
            else:
                self.web3_instances[network_name] = None

    async def shutdown(self):
        """Graceful shutdown"""
        logger.info("Shutting down token monitor...")
        self.running = False
        # Add a small delay to allow pending operations to complete
        await asyncio.sleep(1)


async def main_async():
    config = None
    monitor = None
    runner = None
    
    try:
        # Load configuration
        config_path = os.getenv('CONFIG_PATH', 'config.yaml')
        try:
            config = Config(config_path)
            logger.info(f"Configuration loaded from {config_path}")
        except Exception as e:
            logger.error(f"Failed to load configuration: {e}")
            return

        # Initialize monitor
        monitor = TokenMonitor(config)
        
        # Create and start the web server
        runner = web.AppRunner(monitor.app)
        await runner.setup()
        site = web.TCPSite(runner, '0.0.0.0', config.port)
        await site.start()
        logger.info(f"Server started on port {config.port}")
        logger.info(f"Metrics endpoint: http://0.0.0.0:{config.port}/metrics")
        logger.info(f"Health endpoint: http://0.0.0.0:{config.port}/health")
        
        # Initialize Web3 connections
        await monitor.init_web3_connections()
        
        # Start metrics collection
        await monitor.collect_metrics()
        
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        if monitor:
            await monitor.shutdown()
        if runner:
            await runner.cleanup()
        sys.exit(1)
        
    except KeyboardInterrupt:
        logger.info("Received shutdown signal")
        if monitor:
            await monitor.shutdown()
        if runner:
            await runner.cleanup()
        sys.exit(0)    # Load configuration
    config_path = os.getenv('CONFIG_PATH', 'config.yaml')
    try:
        config = Config(config_path)
        logger.info(f"Configuration loaded from {config_path}")
    except Exception as e:
        logger.error(f"Failed to load configuration: {e}")
        return

    # Initialize monitor
    monitor = TokenMonitor(config)
    
    # Create and start the web server
    runner = web.AppRunner(monitor.app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', config.port)
    await site.start()
    logger.info(f"Server started on port {config.port}")
    logger.info(f"Metrics endpoint: http://0.0.0.0:{config.port}/metrics")
    logger.info(f"Health endpoint: http://0.0.0.0:{config.port}/health")
    
    try:
        # Initialize Web3 connections
        await monitor.init_web3_connections()
        
        # Start metrics collection
        await monitor.collect_metrics()
    except KeyboardInterrupt:
        logger.info("Received shutdown signal")
        await monitor.shutdown()
        await runner.cleanup()
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        await monitor.shutdown()
        await runner.cleanup()

def main():
    try:
        asyncio.run(main_async())
    except Exception as e:
        logger.error(f"Fatal error in main: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()