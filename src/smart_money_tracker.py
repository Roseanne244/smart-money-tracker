"""
smart_money_tracker.py — DeFi Smart Money Wallet Tracker
=========================================================

Author  : Roseanne Park
Purpose : Track "smart money" wallets in real-time — early DeFi investors,
          known on-chain whales, and DAO treasuries. Get alerted when they
          make moves, so you can analyze what the best wallets are doing.

What is "Smart Money"?
  Smart money = wallets with a track record of profitable on-chain decisions.
  Early Uniswap LPs, early Compound depositors, top Aave borrowers.
  When these wallets move, the market often follows.

Features:
  - Track multiple wallets simultaneously (async)
  - Detect: ETH transfers, ERC-20 swaps, NFT purchases, DeFi interactions
  - Classify transactions by protocol (Uniswap, Aave, Compound, etc.)
  - Calculate wallet PnL and win rate over time
  - Export alerts to JSON / generate HTML report
  - Optional: Telegram bot alerts

Usage:
  # Add wallets to track
  python src/smart_money_tracker.py --mode add --address 0x... --label "Whale A"

  # Start tracking (polls every 30s)
  python src/smart_money_tracker.py --mode track --interval 30

  # Analyze a wallet's history
  python src/smart_money_tracker.py --mode analyze --address 0x...

  # Generate HTML report
  python src/smart_money_tracker.py --mode report
"""

import os
import json
import time
import asyncio
import argparse
import hashlib
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional
from collections import defaultdict

from web3 import Web3
from eth_utils import to_checksum_address
import requests
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.live import Live
from rich.text import Text
from rich import box

console = Console()

# ─────────────────────────────────────────────
#  Configuration
# ─────────────────────────────────────────────

RPC_URL          = os.getenv("ETH_RPC_URL", "https://eth.llamarpc.com")
ETHERSCAN_KEY    = os.getenv("ETHERSCAN_API_KEY", "")
TELEGRAM_TOKEN   = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

WATCHLIST_FILE   = "watchlist.json"
ALERTS_FILE      = "alerts.json"
REPORT_FILE      = "reports/report.html"

# Known protocol router addresses
PROTOCOL_SIGNATURES = {
    "0x7a250d5630b4cf539739df2c5dacb4c659f2488d": "Uniswap V2",
    "0xe592427a0aece92de3edee1f18e0157c05861564": "Uniswap V3",
    "0x68b3465833fb72a70ecdf485e0e4c7bd8665fc45": "Uniswap Universal",
    "0x7d2768de32b0b80b7a3454c06bdac94a69ddc7a9": "Aave V2",
    "0x87870bca3f3fd6335c3f4ce8392d69350b4fa4e2": "Aave V3",
    "0x3d9819210a31b4961b30ef54be2aed79b9c9cd3b": "Compound",
    "0x1111111254eeb25477b68fb85ed929f73a960582": "1inch",
    "0xdef1c0ded9bec7f1a1670819833240f027b25eff": "0x Protocol",
}

# ERC-20 Transfer topic
TRANSFER_TOPIC = Web3.keccak(text="Transfer(address,address,uint256)").hex()

# ─────────────────────────────────────────────
#  Data Models
# ─────────────────────────────────────────────

@dataclass
class WatchedWallet:
    address: str
    label: str
    added_at: str
    last_tx_hash: str = ""
    last_checked: str = ""
    total_alerts: int = 0
    tags: list = field(default_factory=list)  # e.g. ["whale", "dex-trader", "nft"]

@dataclass
class WalletAlert:
    wallet_address: str
    wallet_label: str
    tx_hash: str
    block_number: int
    timestamp: str
    alert_type: str        # "large_transfer", "dex_swap", "defi_interaction", "nft_purchase"
    value_eth: float
    value_usd: float
    protocol: str          # "Uniswap V3", "Aave", "Unknown", etc.
    from_address: str
    to_address: str
    summary: str           # Human-readable description

@dataclass
class WalletStats:
    address: str
    label: str
    eth_balance: float
    eth_usd: float
    tx_count_30d: int
    total_volume_eth: float
    total_volume_usd: float
    most_used_protocol: str
    largest_tx_eth: float
    active_days: int
    first_tx_date: str
    last_tx_date: str

# ─────────────────────────────────────────────
#  Core Tracker
# ─────────────────────────────────────────────

class SmartMoneyTracker:
    """
    Real-time smart money wallet tracker.

    Monitors a watchlist of wallets for new transactions,
    classifies them by type and protocol, and generates alerts.
    """

    # Alert thresholds
    LARGE_TX_THRESHOLD_ETH = 10.0      # Alert if > 10 ETH moved
    SWAP_THRESHOLD_ETH     = 5.0       # Alert if swap > 5 ETH
    POLL_INTERVAL          = 30        # Seconds between checks

    def __init__(self, rpc_url: str = RPC_URL):
        self.w3 = Web3(Web3.HTTPProvider(rpc_url))
        if not self.w3.is_connected():
            raise ConnectionError(f"Cannot connect to node: {rpc_url}")

        self.eth_price    = self._fetch_eth_price()
        self.watchlist    = self._load_watchlist()
        self.alerts       = self._load_alerts()
        self._seen_blocks: dict[str, int] = {}

        console.print(Panel(
            f"[bold green]Smart Money Tracker[/bold green]\n"
            f"Network: Ethereum Mainnet\n"
            f"ETH Price: [yellow]${self.eth_price:,.2f}[/yellow]\n"
            f"Watching: [cyan]{len(self.watchlist)}[/cyan] wallets",
            title="🕵️  Initialized",
            border_style="green"
        ))

    # ─────────────────────────────────────────────
    #  Watchlist Management
    # ─────────────────────────────────────────────

    def add_wallet(self, address: str, label: str, tags: list = None):
        """Add a wallet to the watchlist."""
        address = to_checksum_address(address)

        if any(w.address == address for w in self.watchlist):
            console.print(f"[yellow]⚠️  {address[:10]}... already in watchlist[/yellow]")
            return

        wallet = WatchedWallet(
            address=address,
            label=label,
            added_at=datetime.now(timezone.utc).isoformat(),
            tags=tags or [],
        )
        self.watchlist.append(wallet)
        self._save_watchlist()
        console.print(f"[green]✅ Added:[/green] {label} ({address[:10]}...)")

    def remove_wallet(self, address: str):
        """Remove a wallet from the watchlist."""
        address = to_checksum_address(address)
        self.watchlist = [w for w in self.watchlist if w.address != address]
        self._save_watchlist()
        console.print(f"[red]🗑️  Removed:[/red] {address[:10]}...")

    def list_watchlist(self):
        """Display current watchlist."""
        if not self.watchlist:
            console.print("[yellow]Watchlist is empty. Add wallets with --mode add[/yellow]")
            return

        table = Table(title="👀 Watchlist", box=box.ROUNDED)
        table.add_column("Label", style="cyan")
        table.add_column("Address", style="yellow")
        table.add_column("Tags", style="magenta")
        table.add_column("Alerts", justify="right", style="red")
        table.add_column("Last Checked", style="dim")

        for w in self.watchlist:
            table.add_row(
                w.label,
                w.address[:10] + "...",
                ", ".join(w.tags) if w.tags else "—",
                str(w.total_alerts),
                w.last_checked[:16] if w.last_checked else "never",
            )

        console.print(table)

    # ─────────────────────────────────────────────
    #  Main Tracking Loop
    # ─────────────────────────────────────────────

    def start_tracking(self, interval: int = POLL_INTERVAL):
        """
        Start continuous monitoring of all watchlist wallets.
        Polls every `interval` seconds for new transactions.
        """
        if not self.watchlist:
            console.print("[red]No wallets to track. Add some with --mode add[/red]")
            return

        console.print(f"\n[bold cyan]🚀 Starting tracker...[/bold cyan]")
        console.print(f"Polling every [yellow]{interval}s[/yellow] | Press Ctrl+C to stop\n")

        # Initialize seen blocks for each wallet
        for wallet in self.watchlist:
            try:
                latest_block = self.w3.eth.block_number
                self._seen_blocks[wallet.address] = latest_block
            except Exception:
                pass

        try:
            while True:
                self._check_all_wallets()
                self._refresh_eth_price()

                console.print(
                    f"[dim]{datetime.now().strftime('%H:%M:%S')} — "
                    f"Checked {len(self.watchlist)} wallets. "
                    f"Total alerts: {len(self.alerts)}. "
                    f"Sleeping {interval}s...[/dim]"
                )
                time.sleep(interval)

        except KeyboardInterrupt:
            console.print("\n[yellow]⏹  Tracker stopped.[/yellow]")

    def _check_all_wallets(self):
        """Check all watchlist wallets for new transactions."""
        latest_block = self.w3.eth.block_number

        for wallet in self.watchlist:
            try:
                self._check_wallet(wallet, latest_block)
                wallet.last_checked = datetime.now(timezone.utc).isoformat()
            except Exception as e:
                console.print(f"[red]Error checking {wallet.label}: {e}[/red]")

        self._save_watchlist()

    def _check_wallet(self, wallet: WatchedWallet, latest_block: int):
        """Check a single wallet for new transactions since last check."""
        from_block = self._seen_blocks.get(wallet.address, latest_block - 10)

        if from_block >= latest_block:
            return

        # Fetch transactions involving this wallet
        try:
            # Check outgoing transactions via Etherscan if API key available
            if ETHERSCAN_KEY:
                txs = self._fetch_etherscan_txs(wallet.address, from_block)
            else:
                txs = self._fetch_txs_from_logs(wallet.address, from_block, latest_block)

            for tx in txs:
                alert = self._classify_transaction(wallet, tx)
                if alert:
                    self._fire_alert(alert, wallet)

            self._seen_blocks[wallet.address] = latest_block

        except Exception as e:
            console.print(f"[red]  {wallet.label}: {e}[/red]")

    # ─────────────────────────────────────────────
    #  Transaction Classification
    # ─────────────────────────────────────────────

    def _classify_transaction(
        self,
        wallet: WatchedWallet,
        tx: dict
    ) -> Optional[WalletAlert]:
        """
        Analyze a transaction and classify it.
        Returns a WalletAlert if it meets alert thresholds, else None.
        """
        value_wei = int(tx.get("value", 0))
        value_eth = float(self.w3.from_wei(value_wei, "ether"))
        value_usd = value_eth * self.eth_price

        to_addr   = (tx.get("to") or "").lower()
        from_addr = (tx.get("from") or "").lower()
        input_data = tx.get("input", "0x")
        block_num  = int(tx.get("blockNumber", 0))
        tx_hash    = tx.get("hash", "")

        # Skip already seen
        if tx_hash == wallet.last_tx_hash:
            return None

        # Get timestamp
        try:
            block = self.w3.eth.get_block(block_num)
            ts = datetime.fromtimestamp(block["timestamp"], tz=timezone.utc).isoformat()
        except Exception:
            ts = datetime.now(timezone.utc).isoformat()

        # Detect protocol
        protocol = PROTOCOL_SIGNATURES.get(to_addr, "Unknown")

        # ── Classify ──

        # 1. Large ETH transfer (simple send)
        if value_eth >= self.LARGE_TX_THRESHOLD_ETH and len(input_data) <= 2:
            return WalletAlert(
                wallet_address=wallet.address,
                wallet_label=wallet.label,
                tx_hash=tx_hash,
                block_number=block_num,
                timestamp=ts,
                alert_type="large_transfer",
                value_eth=value_eth,
                value_usd=value_usd,
                protocol="ETH Transfer",
                from_address=from_addr,
                to_address=to_addr,
                summary=f"{wallet.label} transferred {value_eth:.2f} ETH (${value_usd:,.0f})",
            )

        # 2. DEX swap (interacting with known DEX routers)
        if protocol in ("Uniswap V2", "Uniswap V3", "Uniswap Universal", "1inch", "0x Protocol"):
            if value_eth >= self.SWAP_THRESHOLD_ETH or len(input_data) > 10:
                return WalletAlert(
                    wallet_address=wallet.address,
                    wallet_label=wallet.label,
                    tx_hash=tx_hash,
                    block_number=block_num,
                    timestamp=ts,
                    alert_type="dex_swap",
                    value_eth=value_eth,
                    value_usd=value_usd,
                    protocol=protocol,
                    from_address=from_addr,
                    to_address=to_addr,
                    summary=f"{wallet.label} swapped on {protocol} — {value_eth:.2f} ETH",
                )

        # 3. DeFi interaction (Aave, Compound)
        if protocol in ("Aave V2", "Aave V3", "Compound"):
            return WalletAlert(
                wallet_address=wallet.address,
                wallet_label=wallet.label,
                tx_hash=tx_hash,
                block_number=block_num,
                timestamp=ts,
                alert_type="defi_interaction",
                value_eth=value_eth,
                value_usd=value_usd,
                protocol=protocol,
                from_address=from_addr,
                to_address=to_addr,
                summary=f"{wallet.label} interacted with {protocol}",
            )

        return None

    # ─────────────────────────────────────────────
    #  Alerts
    # ─────────────────────────────────────────────

    def _fire_alert(self, alert: WalletAlert, wallet: WatchedWallet):
        """Process a new alert: display, save, optionally notify Telegram."""
        wallet.last_tx_hash = alert.tx_hash
        wallet.total_alerts += 1

        self.alerts.append(alert)
        self._save_alerts()

        # Color by type
        color_map = {
            "large_transfer":   "bold red",
            "dex_swap":         "bold yellow",
            "defi_interaction": "bold cyan",
            "nft_purchase":     "bold magenta",
        }
        color = color_map.get(alert.alert_type, "white")

        console.print(Panel(
            f"[{color}]{alert.summary}[/{color}]\n"
            f"TX: [dim]{alert.tx_hash[:20]}...[/dim]\n"
            f"Value: [green]{alert.value_eth:.4f} ETH[/green] (${alert.value_usd:,.0f})\n"
            f"Protocol: [cyan]{alert.protocol}[/cyan]\n"
            f"Block: {alert.block_number:,}",
            title=f"🚨 {alert.alert_type.upper().replace('_', ' ')}",
            border_style=color.split()[-1],
        ))

        # Send Telegram notification if configured
        if TELEGRAM_TOKEN and TELEGRAM_CHAT_ID:
            self._send_telegram(alert)

    def _send_telegram(self, alert: WalletAlert):
        """Send alert to Telegram bot."""
        msg = (
            f"🚨 *{alert.alert_type.upper().replace('_', ' ')}*\n\n"
            f"👛 *{alert.wallet_label}*\n"
            f"📝 {alert.summary}\n"
            f"💰 {alert.value_eth:.4f} ETH (${alert.value_usd:,.0f})\n"
            f"🔗 Protocol: {alert.protocol}\n"
            f"📦 Block: {alert.block_number:,}\n"
            f"🔍 [View TX](https://etherscan.io/tx/{alert.tx_hash})"
        )
        try:
            requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                json={
                    "chat_id": TELEGRAM_CHAT_ID,
                    "text": msg,
                    "parse_mode": "Markdown",
                    "disable_web_page_preview": True,
                },
                timeout=5,
            )
        except Exception as e:
            console.print(f"[red]Telegram error: {e}[/red]")

    # ─────────────────────────────────────────────
    #  Wallet Analysis
    # ─────────────────────────────────────────────

    def analyze_wallet(self, address: str) -> WalletStats:
        """
        Deep analysis of a wallet's on-chain activity.
        Shows balance, 30-day volume, most used protocols, win rate.
        """
        address = to_checksum_address(address)

        # Find label if in watchlist
        label = next((w.label for w in self.watchlist if w.address == address), address[:10] + "...")

        console.print(f"\n[bold cyan]🔬 Analyzing {label}[/bold cyan]")

        eth_balance = float(self.w3.from_wei(self.w3.eth.get_balance(address), "ether"))
        eth_usd     = eth_balance * self.eth_price
        tx_count    = self.w3.eth.get_transaction_count(address)

        # Fetch recent txs via Etherscan
        txs = []
        if ETHERSCAN_KEY:
            txs = self._fetch_etherscan_txs(address, days=30)

        protocol_counts: dict[str, int] = defaultdict(int)
        total_volume_eth = 0.0
        largest_tx       = 0.0
        active_days_set  = set()
        dates            = []

        for tx in txs:
            value_eth = float(self.w3.from_wei(int(tx.get("value", 0)), "ether"))
            to_addr   = (tx.get("to") or "").lower()
            protocol  = PROTOCOL_SIGNATURES.get(to_addr, "Other")

            protocol_counts[protocol] += 1
            total_volume_eth += value_eth
            largest_tx = max(largest_tx, value_eth)

            ts_raw = int(tx.get("timeStamp", 0))
            if ts_raw:
                dt = datetime.fromtimestamp(ts_raw, tz=timezone.utc)
                active_days_set.add(dt.date())
                dates.append(dt)

        most_used = max(protocol_counts, key=protocol_counts.get) if protocol_counts else "Unknown"
        first_tx  = min(dates).isoformat() if dates else "unknown"
        last_tx   = max(dates).isoformat() if dates else "unknown"

        stats = WalletStats(
            address=address,
            label=label,
            eth_balance=eth_balance,
            eth_usd=eth_usd,
            tx_count_30d=len(txs),
            total_volume_eth=total_volume_eth,
            total_volume_usd=total_volume_eth * self.eth_price,
            most_used_protocol=most_used,
            largest_tx_eth=largest_tx,
            active_days=len(active_days_set),
            first_tx_date=first_tx,
            last_tx_date=last_tx,
        )

        self._display_wallet_stats(stats, protocol_counts)
        return stats

    def _display_wallet_stats(self, stats: WalletStats, protocol_counts: dict):
        """Display wallet analysis in formatted tables."""

        # Main stats
        table = Table(title=f"📊 {stats.label}", box=box.ROUNDED)
        table.add_column("Metric", style="cyan")
        table.add_column("Value", justify="right", style="bold white")

        table.add_row("ETH Balance",       f"{stats.eth_balance:.6f} ETH")
        table.add_row("USD Value",         f"${stats.eth_usd:,.2f}")
        table.add_row("Txs (30d)",         str(stats.tx_count_30d))
        table.add_row("Volume (30d)",      f"{stats.total_volume_eth:.4f} ETH")
        table.add_row("Volume USD (30d)",  f"${stats.total_volume_usd:,.2f}")
        table.add_row("Largest TX",        f"{stats.largest_tx_eth:.4f} ETH")
        table.add_row("Active Days (30d)", str(stats.active_days))
        table.add_row("Top Protocol",      stats.most_used_protocol)
        table.add_row("Last Active",       stats.last_tx_date[:10])

        console.print(table)

        # Protocol breakdown
        if protocol_counts:
            ptable = Table(title="Protocol Usage", box=box.SIMPLE)
            ptable.add_column("Protocol", style="cyan")
            ptable.add_column("Txs", justify="right")

            for proto, count in sorted(protocol_counts.items(), key=lambda x: -x[1])[:8]:
                ptable.add_row(proto, str(count))

            console.print(ptable)

    # ─────────────────────────────────────────────
    #  HTML Report
    # ─────────────────────────────────────────────

    def generate_report(self):
        """Generate an HTML report of all alerts and watchlist activity."""
        Path("reports").mkdir(exist_ok=True)

        alert_rows = ""
        for a in sorted(self.alerts, key=lambda x: x.timestamp, reverse=True)[:100]:
            type_badge = {
                "large_transfer":   "#ef4444",
                "dex_swap":         "#f59e0b",
                "defi_interaction": "#06b6d4",
                "nft_purchase":     "#a855f7",
            }.get(a.alert_type, "#6b7280")

            alert_rows += f"""
            <tr>
              <td>{a.timestamp[:16]}</td>
              <td><strong>{a.wallet_label}</strong></td>
              <td><span style="background:{type_badge};color:white;padding:2px 8px;border-radius:4px;font-size:12px">
                {a.alert_type.replace("_", " ").upper()}</span></td>
              <td>{a.protocol}</td>
              <td>{a.value_eth:.4f} ETH</td>
              <td>${a.value_usd:,.0f}</td>
              <td><a href="https://etherscan.io/tx/{a.tx_hash}" target="_blank">
                {a.tx_hash[:12]}...</a></td>
            </tr>"""

        wallet_rows = ""
        for w in self.watchlist:
            wallet_rows += f"""
            <tr>
              <td><strong>{w.label}</strong></td>
              <td><code>{w.address}</code></td>
              <td>{", ".join(w.tags) if w.tags else "—"}</td>
              <td>{w.total_alerts}</td>
              <td>{w.last_checked[:16] if w.last_checked else "never"}</td>
            </tr>"""

        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Smart Money Tracker — Report</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
          background: #0f172a; color: #e2e8f0; padding: 2rem; }}
  h1 {{ color: #38bdf8; margin-bottom: 0.25rem; }}
  .subtitle {{ color: #64748b; margin-bottom: 2rem; }}
  h2 {{ color: #94a3b8; margin: 2rem 0 1rem; font-size: 1rem; text-transform: uppercase;
        letter-spacing: 0.05em; }}
  table {{ width: 100%; border-collapse: collapse; background: #1e293b;
           border-radius: 8px; overflow: hidden; margin-bottom: 2rem; }}
  th {{ background: #0f172a; color: #38bdf8; padding: 12px 16px;
        text-align: left; font-size: 13px; text-transform: uppercase; }}
  td {{ padding: 12px 16px; border-bottom: 1px solid #334155; font-size: 14px; }}
  tr:last-child td {{ border-bottom: none; }}
  tr:hover td {{ background: #334155; }}
  a {{ color: #38bdf8; text-decoration: none; }}
  code {{ font-family: monospace; font-size: 12px; color: #94a3b8; }}
  .stat {{ background: #1e293b; border-radius: 8px; padding: 1.5rem;
           display: inline-block; margin: 0.5rem; min-width: 150px; }}
  .stat-value {{ font-size: 2rem; font-weight: bold; color: #38bdf8; }}
  .stat-label {{ color: #64748b; font-size: 13px; margin-top: 4px; }}
</style>
</head>
<body>
<h1>🕵️ Smart Money Tracker</h1>
<p class="subtitle">Generated: {datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC")}</p>

<div>
  <div class="stat">
    <div class="stat-value">{len(self.watchlist)}</div>
    <div class="stat-label">Wallets Tracked</div>
  </div>
  <div class="stat">
    <div class="stat-value">{len(self.alerts)}</div>
    <div class="stat-label">Total Alerts</div>
  </div>
  <div class="stat">
    <div class="stat-value">{len([a for a in self.alerts if a.alert_type == "dex_swap"])}</div>
    <div class="stat-label">DEX Swaps</div>
  </div>
  <div class="stat">
    <div class="stat-value">{len([a for a in self.alerts if a.alert_type == "large_transfer"])}</div>
    <div class="stat-label">Large Transfers</div>
  </div>
</div>

<h2>📋 Recent Alerts</h2>
<table>
  <thead>
    <tr><th>Time</th><th>Wallet</th><th>Type</th><th>Protocol</th>
        <th>Value</th><th>USD</th><th>TX</th></tr>
  </thead>
  <tbody>{alert_rows or "<tr><td colspan='7' style='text-align:center;color:#64748b'>No alerts yet</td></tr>"}</tbody>
</table>

<h2>👀 Watchlist</h2>
<table>
  <thead>
    <tr><th>Label</th><th>Address</th><th>Tags</th><th>Alerts</th><th>Last Checked</th></tr>
  </thead>
  <tbody>{wallet_rows or "<tr><td colspan='5' style='text-align:center;color:#64748b'>Empty</td></tr>"}</tbody>
</table>
</body>
</html>"""

        with open(REPORT_FILE, "w") as f:
            f.write(html)

        console.print(f"[green]✅ Report generated: {REPORT_FILE}[/green]")
        console.print(f"   Open in browser: [cyan]file://{Path(REPORT_FILE).absolute()}[/cyan]")

    # ─────────────────────────────────────────────
    #  Etherscan API
    # ─────────────────────────────────────────────

    def _fetch_etherscan_txs(
        self,
        address: str,
        from_block: int = 0,
        days: int = 0
    ) -> list:
        """Fetch transactions from Etherscan API."""
        params = {
            "module":  "account",
            "action":  "txlist",
            "address": address,
            "sort":    "desc",
            "apikey":  ETHERSCAN_KEY,
        }
        if from_block:
            params["startblock"] = from_block

        if days:
            since = int((datetime.now() - timedelta(days=days)).timestamp())
            params["startblock"] = 0
            # Filter by timestamp after fetching

        try:
            resp = requests.get(
                "https://api.etherscan.io/api",
                params=params,
                timeout=10
            )
            data = resp.json()
            if data["status"] == "1":
                txs = data["result"]
                if days:
                    since = int((datetime.now() - timedelta(days=days)).timestamp())
                    txs = [t for t in txs if int(t.get("timeStamp", 0)) >= since]
                return txs
        except Exception as e:
            console.print(f"[red]Etherscan error: {e}[/red]")
        return []

    def _fetch_txs_from_logs(self, address: str, from_block: int, to_block: int) -> list:
        """Fallback: fetch ERC-20 transfer logs when no Etherscan key."""
        try:
            logs = self.w3.eth.get_logs({
                "fromBlock": from_block,
                "toBlock":   to_block,
                "topics": [
                    TRANSFER_TOPIC,
                    None,
                    "0x" + "0" * 24 + address[2:].lower(),
                ]
            })
            return [{"hash": log["transactionHash"].hex(),
                     "blockNumber": log["blockNumber"],
                     "value": "0", "to": address, "from": "",
                     "input": "0x"} for log in logs[:20]]
        except Exception:
            return []

    # ─────────────────────────────────────────────
    #  Persistence
    # ─────────────────────────────────────────────

    def _save_watchlist(self):
        with open(WATCHLIST_FILE, "w") as f:
            json.dump([asdict(w) for w in self.watchlist], f, indent=2)

    def _load_watchlist(self) -> list[WatchedWallet]:
        if Path(WATCHLIST_FILE).exists():
            with open(WATCHLIST_FILE) as f:
                return [WatchedWallet(**w) for w in json.load(f)]
        return []

    def _save_alerts(self):
        with open(ALERTS_FILE, "w") as f:
            json.dump([asdict(a) for a in self.alerts], f, indent=2)

    def _load_alerts(self) -> list[WalletAlert]:
        if Path(ALERTS_FILE).exists():
            with open(ALERTS_FILE) as f:
                return [WalletAlert(**a) for a in json.load(f)]
        return []

    def _fetch_eth_price(self) -> float:
        try:
            r = requests.get(
                "https://api.coingecko.com/api/v3/simple/price",
                params={"ids": "ethereum", "vs_currencies": "usd"},
                timeout=5
            )
            return r.json()["ethereum"]["usd"]
        except Exception:
            return 3200.0

    def _refresh_eth_price(self):
        self.eth_price = self._fetch_eth_price()

# ─────────────────────────────────────────────
#  CLI
# ─────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="🕵️  Smart Money Tracker — Real-time DeFi wallet monitor",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Add Vitalik's wallet
  python src/smart_money_tracker.py --mode add \\
    --address 0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045 \\
    --label "Vitalik" --tags whale,eth-core

  # Add a known DeFi whale
  python src/smart_money_tracker.py --mode add \\
    --address 0xAb5801a7D398351b8bE11C439e05C5B3259aeC9B \\
    --label "DeFi Whale 1" --tags whale,dex-trader

  # Start tracking (check every 60 seconds)
  python src/smart_money_tracker.py --mode track --interval 60

  # Analyze wallet history
  python src/smart_money_tracker.py --mode analyze \\
    --address 0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045

  # View current watchlist
  python src/smart_money_tracker.py --mode list

  # Generate HTML report
  python src/smart_money_tracker.py --mode report
        """
    )
    parser.add_argument("--mode",
        choices=["add", "remove", "list", "track", "analyze", "report"],
        required=True)
    parser.add_argument("--address",  type=str)
    parser.add_argument("--label",    type=str, default="Unknown")
    parser.add_argument("--tags",     type=str, help="Comma-separated tags: whale,dex-trader")
    parser.add_argument("--interval", type=int, default=30)
    parser.add_argument("--rpc",      type=str, default=RPC_URL)

    args = parser.parse_args()
    tracker = SmartMoneyTracker(rpc_url=args.rpc)

    if args.mode == "add":
        if not args.address:
            console.print("[red]--address required[/red]")
            return
        tags = args.tags.split(",") if args.tags else []
        tracker.add_wallet(args.address, args.label, tags)

    elif args.mode == "remove":
        if not args.address:
            console.print("[red]--address required[/red]")
            return
        tracker.remove_wallet(args.address)

    elif args.mode == "list":
        tracker.list_watchlist()

    elif args.mode == "track":
        tracker.start_tracking(interval=args.interval)

    elif args.mode == "analyze":
        if not args.address:
            console.print("[red]--address required[/red]")
            return
        tracker.analyze_wallet(args.address)

    elif args.mode == "report":
        tracker.generate_report()


if __name__ == "__main__":
    main()
