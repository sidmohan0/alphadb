# AlphaDB 📈

A self-hosted **TimescaleDB + Grafana** stack for real-time cryptocurrency market data analysis and visualization.

![License](https://img.shields.io/badge/license-MIT-blue.svg)
![Docker](https://img.shields.io/badge/docker-compose-blue.svg)
![TimescaleDB](https://img.shields.io/badge/timescaledb-2.15-green.svg)
![Grafana](https://img.shields.io/badge/grafana-12.1-orange.svg)

## 🚀 Quick Start

1. **Clone and setup**
   ```bash
   git clone <your-repo-url>
   cd alphadb
   cp .env.example .env
   # Edit .env with your preferred passwords
   ```

2. **Launch the stack**
   ```bash
   docker compose up -d
   ```

3. **Initialize database**
   ```bash
   docker exec -i tsdb psql -U trader -d market < init.sql
   ```

4. **Install Python dependencies**
   ```bash
   pip install -r requirements.txt
   ```

5. **Backfill historical data** (choose one method):

   **Option A: CoinGecko Pro API (Recommended for 90 days)**
   ```bash
   export COINGECKO_API_KEY=your_api_key_here
   ./scripts/run_coingecko_backfill.sh
   ```
   
   **Option B: Kraken API (Limited to ~19 hours)**
   ```bash
   ./scripts/run_backfill.sh
   ```

6. **Start real-time data collection**:
   ```bash
   python scripts/ingest.py  # OHLCV bars via REST API
   # WebSocket tick data runs automatically via Docker
   ```

7. **Access Grafana**
   - URL: http://localhost:3000
   - Login: `admin` / `[your GF_SECURITY_ADMIN_PASSWORD]`

## 📊 Features

- **Real-time WebSocket data** - Live tick-by-tick trade feeds from Kraken
- **REST API ingestion** - OHLCV bars for BTC/USDT and ETH/USDT 
- **Historical backfill** - 90 days of data via CoinGecko Pro API
- **TimescaleDB hypertables** - Efficient time-series storage with automatic partitioning
- **Continuous aggregates** - Real-time 5-minute OHLCV views
- **Professional dashboards** - Bitcoin, Ethereum, and performance monitoring
- **Tick-level analysis** - Candlestick charts built from live trade data
- **Performance monitoring** - WebSocket latency, throughput, and SLA tracking
- **Persistent storage** - Named Docker volumes for data retention
- **Auto-provisioned setup** - Grafana dashboards and datasources ready-to-go

## 🏗️ Architecture

```mermaid
flowchart LR
    subgraph Docker_Network
        tsdb[(TimescaleDB<br/>Postgres 16 + TS 2.15)]
        grafana[[Grafana OSS 12<br/>dashboards]]
    end
    user((Host<br/>localhost:5432/3000)) --- grafana
    script[[Python Scripts<br/>data-ingestors]] --> tsdb
    grafana --> tsdb
```

## 📁 Project Structure

```
alphadb/
├── README.md                    # This file
├── docker-compose.yml           # Docker services configuration
├── init.sql                     # Database schema initialization
├── .env.example                 # Environment variables template
├── .gitignore                   # Git ignore rules
├── requirements.txt             # Python dependencies
├── scripts/
│   └── ingest.py               # Data ingestion script
├── grafana/
│   ├── dashboards/             # Grafana dashboard definitions
│   │   ├── btc-dashboard.json
│   │   └── dashboard.yml
│   └── datasources/            # Grafana datasource configuration
│       └── ds.yml
├── .github/
│   ├── ISSUE_TEMPLATE/         # GitHub issue templates
│   └── pull_request_template.md
└── docs/
    ├── SETUP.md                # Detailed setup instructions
    ├── API.md                  # Database schema and API docs
    └── TROUBLESHOOTING.md      # Common issues and solutions
```

## 🛠️ Requirements

- **Docker** & **Docker Compose**
- **Python 3.8+** (for data ingestion)
- **8GB RAM** recommended
- **10GB disk space** minimum

## 📈 Dashboard Features

- **Candlestick Chart**: Professional OHLCV visualization
- **Price Monitoring**: Real-time BTC price tracking  
- **Volume Analysis**: Trading volume with proper BTC units
- **Data Health**: Collection statistics and freshness monitoring
- **Custom Time Ranges**: From minutes to hours of historical data

## 🔧 Configuration

### Environment Variables

Copy `.env.example` to `.env` and customize:

```bash
# Database Configuration
POSTGRES_USER=trader
POSTGRES_PASSWORD=your_secure_password_here
POSTGRES_DB=market

# Grafana Configuration  
GF_SECURITY_ADMIN_PASSWORD=your_grafana_admin_password_here
```

### Database Schema

- **`ohlcv_1m`**: 1-minute OHLCV hypertable
- **`ohlcv_5m`**: 5-minute continuous aggregate
- **Automatic partitioning** by time (1-day chunks)
- **Optimized for time-series** queries and analytics

## 📚 Documentation

- [Setup Guide](docs/SETUP.md) - Detailed installation and configuration
- [API Documentation](docs/API.md) - Database schema and query examples  
- [Troubleshooting](docs/TROUBLESHOOTING.md) - Common issues and solutions

## 🤝 Contributing

We welcome contributions! Please see [CONTRIBUTING.md](CONTRIBUTING.md) for details.

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## ⚠️ Disclaimer

This software is for educational and research purposes only. Not financial advice. Trade at your own risk.

## 🙏 Acknowledgments

- [TimescaleDB](https://www.timescale.com/) for excellent time-series database
- [Grafana](https://grafana.com/) for powerful visualization platform
- [CCXT](https://github.com/ccxt/ccxt) for cryptocurrency exchange integration