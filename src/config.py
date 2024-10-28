import yaml
import logging
from dataclasses import dataclass
from typing import Dict, List

logger = logging.getLogger(__name__)

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
    health_check_interval: int = 30

class Config:
    def __init__(self, config_path: str):
        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)
        
        self.networks: Dict[str, NetworkConfig] = {}
        self.scrape_interval = config['settings']['scrape_interval']
        self.port = config['settings']['port']
        self.health_check_interval = config['settings'].get('health_check_interval', 30)
        
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
