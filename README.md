# Token Balance Exporter

A Prometheus exporter that monitors USDC token (or any specified token by contact addr) balances across multiple blockchain networks (Ethereum, BSC, etc.). It provides real-time metrics about token balances and network health.

## Features

- Monitors USDC token balances across multiple addresses and networks
- Provides Prometheus metrics for monitoring and alerting
- Health checks for each RPC endpoint
- Built-in HTTP server for metrics and health endpoints
- Configurable scrape intervals
- Docker support with health checking

## Metrics

The exporter provides the following metrics:

- `token_balance{network, token, token_address, alias, address}` - Token balance for each monitored address
- `exporter_health` - Overall health status of the exporter (1 = healthy, 0 = unhealthy)
- `exporter_last_successful_scrape_timestamp` - Timestamp of the last successful scrape
- `exporter_scrape_failures_total{network}` - Counter of scrape failures by network
- `exporter_rpc_health{network}` - RPC endpoint health status by network (1 = healthy, 0 = unhealthy)

## Configuration

Create a `config.yaml` file:

```yaml
networks:
  ethereum:
    rpc_url: "https://mainnet.infura.io/v3/YOUR-PROJECT-ID"
    tokens:
      USDC:
        address: "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48"
        decimals: 6
    addresses:
      - alias: "bridge_eth"
        address: "<YOUR-ADDRESS>"

  bsc:
    rpc_url: "https://bsc-dataseed1.binance.org"
    tokens:
      USDC:
        address: "0x8AC76a51cc950d9822D68b83fE1Ad97B32Cd580d"
        decimals: 18
    addresses:
      - alias: "bridge_bsc"
        address: "<YOUR-ADDRESS>"

settings:
  scrape_interval: 60  # in seconds
  port: 4200
  health_check_interval: 30
```

## Installation

### Prerequisites

- Python 3.11 or higher
- Docker (optional)

### Local Installation

1. Clone the repository:
```bash
git clone https://github.com/ambrosus/token_balance_exporter.git
cd token_balance_exporter
```

2. Create and activate virtual environment:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

4. Configure your `config.yaml` and run:
```bash
python -m src.main
```

### Docker Installation

1. Build the Docker image:
```bash
docker build -t token-monitor .
```

or pull the image from github registry: 
```bash
docker pull ghcr.io/ambrosus/token_balance_exporter:latest
```

2. Run the container:
```bash
docker run -d \
    --name token-monitor \
    -p 4200:4200 \
    -v $(pwd)/config/config.yaml:/app/config/config.yaml \
    token-monitor:latest
```

## Usage

### Endpoints

- Metrics: `http://localhost:4200/metrics`
- Health Check: `http://localhost:4200/health`

### Prometheus Configuration

Add the following to your `prometheus.yml`:

```yaml
scrape_configs:
  - job_name: 'token_monitor'
    static_configs:
      - targets: ['localhost:4200']
    scrape_interval: 1m
```

### Example Grafana Queries

1. Token Balance by Address:
```
token_balance{alias="bridge_eth"}
```

2. RPC Health Status:
```
exporter_rpc_health
```

## Development

Project structure:
```
token-monitor/
├── config/
│   └── config.yaml
├── src/
│   ├── __init__.py
│   ├── main.py
│   ├── config.py
│   ├── metrics.py
│   ├── monitor.py
│   └── web.py
├── requirements.txt
├── README.md
└── Dockerfile
```

## Contributing

1. Fork the repository
2. Create a feature branch
3. Commit your changes
4. Push to the branch
5. Create a Pull Request

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Acknowledgments

- Web3.py for blockchain interaction
- Prometheus for metrics collection
- aiohttp for async HTTP server