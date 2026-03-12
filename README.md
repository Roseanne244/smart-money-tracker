# 🕵️ Smart Money Tracker

A Python tool for tracking **"smart money"** wallets on Ethereum in real-time. Monitor early DeFi investors, known whales, and DAO treasuries get alerted the moment they make a move.

> Smart money = wallets with a proven track record of profitable on-chain decisions. When they move, the market often follows.

---

## Features

| Feature | Description |
|---------|-------------|
| 👀 Watchlist | Track unlimited wallets with custom labels & tags |
| 🚨 Real-time alerts | Detect large transfers, DEX swaps, DeFi interactions |
| 🔍 Protocol detection | Auto-identify Uniswap, Aave, Compound, 1inch, and more |
| 📊 Wallet analysis | 30-day volume, protocol usage, active days, largest tx |
| 📋 HTML report | Auto-generated report with all alerts and stats |
| 📱 Telegram alerts | Optional push notifications via Telegram bot |
| 💾 Persistence | Watchlist and alerts saved to JSON |

---

## Demo

```
🕵️  Initialized
─────────────────────────────
Network: Ethereum Mainnet
ETH Price: $3,200.00
Watching: 3 wallets

🚀 Starting tracker...
Polling every 30s | Press Ctrl+C to stop

╭─── 🚨 DEX SWAP ────────────────────────────────╮
│ Vitalik swapped on Uniswap V3 — 15.00 ETH      │
│ TX: 0x4a8f2d1b9c3e...                           │
│ Value: 15.0000 ETH ($48,000)                    │
│ Protocol: Uniswap V3                            │
│ Block: 21,847,412                               │
╰────────────────────────────────────────────────╯

╭─── 🚨 LARGE TRANSFER ──────────────────────────╮
│ DeFi Whale 1 transferred 500.00 ETH ($1.6M)    │
│ TX: 0x7c12ef4a...                               │
│ Value: 500.0000 ETH ($1,600,000)                │
│ Protocol: ETH Transfer                          │
╰────────────────────────────────────────────────╯
```

---

## Installation

```bash
git clone https://github.com/Roseanne244/smart-money-tracker.git
cd smart-money-tracker

python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate

pip install -r requirements.txt
cp .env.example .env       # add your keys
```

---

## Usage

```bash
# Add wallets to track
python src/smart_money_tracker.py --mode add \
  --address 0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045 \
  --label "Vitalik" --tags whale,eth-core

python src/smart_money_tracker.py --mode add \
  --address 0xAb5801a7D398351b8bE11C439e05C5B3259aeC9B \
  --label "DeFi Whale 1" --tags whale,dex-trader

# View watchlist
python src/smart_money_tracker.py --mode list

# Start tracking (every 60 seconds)
python src/smart_money_tracker.py --mode track --interval 60

# Deep analyze a wallet (last 30 days)
python src/smart_money_tracker.py --mode analyze \
  --address 0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045

# Generate HTML report
python src/smart_money_tracker.py --mode report
```

---

## Environment Variables

```env
ETH_RPC_URL=https://eth.llamarpc.com       # Free public RPC
ETHERSCAN_API_KEY=your_key                 # Optional but recommended
TELEGRAM_BOT_TOKEN=your_bot_token          # Optional: push notifications
TELEGRAM_CHAT_ID=your_chat_id             # Optional
```

> Without Etherscan key: uses on-chain log scanning (slower).
> With Etherscan key: full transaction history + faster detection.

---

## Alert Types

| Type | Trigger |
|------|---------|
| 🔴 `large_transfer` | Plain ETH transfer > 10 ETH |
| 🟡 `dex_swap` | Swap on Uniswap/1inch/0x > 5 ETH |
| 🔵 `defi_interaction` | Any interaction with Aave/Compound |
| 🟣 `nft_purchase` | NFT buy on OpenSea/Blur |

---

## Detected Protocols

```
Uniswap V2 / V3 / Universal Router
Aave V2 / V3
Compound
1inch
0x Protocol
```

---

## Run Tests

```bash
pip install pytest
pytest tests/ -v
```

```
tests/test_tracker.py::TestProtocolDetection::test_uniswap_v2_detected   PASSED
tests/test_tracker.py::TestProtocolDetection::test_aave_v3_detected       PASSED
tests/test_tracker.py::TestAlertThresholds::test_large_transfer_threshold PASSED
tests/test_tracker.py::TestWatchedWallet::test_wallet_creation            PASSED
tests/test_tracker.py::TestWalletStats::test_most_used_protocol           PASSED

18 passed in 0.08s
```

---

## Project Structure

```
smart-money-tracker/
├── src/
│   └── smart_money_tracker.py  ← Core tracker engine
├── tests/
│   └── test_tracker.py         ← Unit tests (pytest)
├── reports/
│   └── report.html             ← Auto-generated HTML report
├── watchlist.json              ← Persisted wallet list
├── alerts.json                 ← All historical alerts
├── requirements.txt
├── .env.example
└── README.md
```

---

## Built With

`Python 3.11+` `web3.py` `rich` `requests` `pytest`

---

## License

MIT
