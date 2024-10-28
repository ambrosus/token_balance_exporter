from prometheus_client import Gauge, Counter

# Define metrics
health_gauge = Gauge('exporter_health', 'Health status of the exporter (1 = healthy, 0 = unhealthy)')
last_successful_scrape = Gauge('exporter_last_successful_scrape_timestamp', 'Timestamp of the last successful scrape')
scrape_failures_total = Counter('exporter_scrape_failures_total', 'Total number of scrape failures', ['network'])
rpc_health = Gauge('exporter_rpc_health', 'RPC endpoint health status (1 = healthy, 0 = unhealthy)', ['network'])
token_balance = Gauge(
    'token_balance',
    'Token balance for a address',
    ['network', 'token', 'token_address', 'alias', 'address']
)

# Contract ABI
TOKEN_ABI = [
    {
        "inputs": [{"name": "account", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function"
    }
]
