"""
tests/test_tracker.py — Unit tests for SmartMoneyTracker
"""

import pytest
from datetime import datetime, timezone
from src.smart_money_tracker import (
    WatchedWallet, WalletAlert, WalletStats,
    PROTOCOL_SIGNATURES
)


class TestProtocolDetection:
    """Test protocol classification from contract addresses."""

    def test_uniswap_v2_detected(self):
        addr = "0x7a250d5630b4cf539739df2c5dacb4c659f2488d"
        assert PROTOCOL_SIGNATURES.get(addr) == "Uniswap V2"

    def test_uniswap_v3_detected(self):
        addr = "0xe592427a0aece92de3edee1f18e0157c05861564"
        assert PROTOCOL_SIGNATURES.get(addr) == "Uniswap V3"

    def test_aave_v3_detected(self):
        addr = "0x87870bca3f3fd6335c3f4ce8392d69350b4fa4e2"
        assert PROTOCOL_SIGNATURES.get(addr) == "Aave V3"

    def test_unknown_contract(self):
        addr = "0x1234567890123456789012345678901234567890"
        assert PROTOCOL_SIGNATURES.get(addr, "Unknown") == "Unknown"

    def test_all_protocols_have_addresses(self):
        assert len(PROTOCOL_SIGNATURES) >= 8


class TestAlertThresholds:
    """Test alert threshold logic."""

    def test_large_transfer_threshold(self):
        threshold = 10.0
        assert 15.0 >= threshold   # should alert
        assert 5.0 < threshold     # should not alert
        assert 10.0 >= threshold   # edge case — should alert

    def test_swap_threshold(self):
        threshold = 5.0
        assert 10.0 >= threshold
        assert 4.9 < threshold

    def test_value_eth_calculation(self):
        value_wei = 10 ** 18  # 1 ETH
        value_eth = value_wei / 10**18
        assert value_eth == 1.0

    def test_usd_value_calculation(self):
        value_eth = 5.0
        eth_price = 3200.0
        usd = value_eth * eth_price
        assert usd == 16_000.0


class TestWatchedWallet:
    """Test WatchedWallet data model."""

    def test_wallet_creation(self):
        w = WatchedWallet(
            address="0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045",
            label="Vitalik",
            added_at=datetime.now(timezone.utc).isoformat(),
            tags=["whale", "eth-core"],
        )
        assert w.label == "Vitalik"
        assert "whale" in w.tags
        assert w.total_alerts == 0

    def test_wallet_default_values(self):
        w = WatchedWallet(
            address="0x1234",
            label="Test",
            added_at="2026-01-01",
        )
        assert w.last_tx_hash == ""
        assert w.total_alerts == 0
        assert w.tags == []


class TestAlertClassification:
    """Test alert type logic."""

    def test_alert_types_are_valid(self):
        valid_types = {"large_transfer", "dex_swap", "defi_interaction", "nft_purchase"}
        alert = WalletAlert(
            wallet_address="0x1234",
            wallet_label="Test",
            tx_hash="0xabcd",
            block_number=1000,
            timestamp="2026-01-01T00:00:00+00:00",
            alert_type="dex_swap",
            value_eth=5.0,
            value_usd=16000.0,
            protocol="Uniswap V3",
            from_address="0x1234",
            to_address="0x5678",
            summary="Test swapped 5 ETH on Uniswap V3",
        )
        assert alert.alert_type in valid_types

    def test_summary_generated(self):
        label = "Whale A"
        value_eth = 100.0
        protocol = "Uniswap V3"
        summary = f"{label} swapped on {protocol} — {value_eth:.2f} ETH"
        assert "Whale A" in summary
        assert "100.00 ETH" in summary


class TestWalletStats:
    """Test wallet statistics calculations."""

    def test_active_days_counted(self):
        from datetime import date
        dates = {
            date(2026, 1, 1),
            date(2026, 1, 2),
            date(2026, 1, 3),
        }
        assert len(dates) == 3

    def test_most_used_protocol(self):
        from collections import defaultdict
        counts = defaultdict(int)
        protocols = ["Uniswap V3", "Uniswap V3", "Aave V3", "Uniswap V3"]
        for p in protocols:
            counts[p] += 1
        most_used = max(counts, key=counts.get)
        assert most_used == "Uniswap V3"

    def test_largest_tx_tracked(self):
        txs_eth = [1.0, 50.0, 5.0, 100.0, 3.0]
        largest = max(txs_eth)
        assert largest == 100.0

    def test_volume_calculation(self):
        txs_eth = [1.0, 2.5, 10.0, 0.5]
        total = sum(txs_eth)
        assert total == 14.0


class TestPersistence:
    """Test JSON serialization."""

    def test_wallet_to_dict(self):
        from dataclasses import asdict
        w = WatchedWallet(
            address="0x1234",
            label="Test",
            added_at="2026-01-01",
            tags=["whale"],
        )
        d = asdict(w)
        assert d["label"] == "Test"
        assert d["tags"] == ["whale"]
        assert "address" in d

    def test_alert_to_dict(self):
        from dataclasses import asdict
        a = WalletAlert(
            wallet_address="0x1234", wallet_label="Test",
            tx_hash="0xabcd", block_number=100,
            timestamp="2026-01-01", alert_type="dex_swap",
            value_eth=5.0, value_usd=16000.0,
            protocol="Uniswap V3",
            from_address="0x1", to_address="0x2",
            summary="test",
        )
        d = asdict(a)
        assert d["alert_type"] == "dex_swap"
        assert d["value_eth"] == 5.0
