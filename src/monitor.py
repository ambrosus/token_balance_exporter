import logging
import asyncio
from aiohttp import web
from prometheus_client import generate_latest
from .config import Config
import time
from web3 import Web3
from web3.providers import AsyncHTTPProvider
from web3.middleware import async_geth_poa_middleware
from typing import Dict, Optional
from .metrics import (
    health_gauge, last_successful_scrape, scrape_failures_total,
    rpc_health, token_balance, TOKEN_ABI
)

logger = logging.getLogger(__name__)

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
        
        logger.info("Metrics collection stopped")
    
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
        if self.app:
            self.app.freeze()
            await self.app.shutdown()
            await self.app.cleanup()
        else:
            logger.warning("App is not initialized, skipping shutdown steps.")
