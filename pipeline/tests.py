from __future__ import annotations

from django.test import TestCase
from rest_framework.test import APIClient

from pipeline.ingest.engine import training_vector
from pipeline.ingest.features import OrderBook, RealTimeTradeImbalance, RealTimeVPIN
from pipeline.models import FeatureBar, TrainingJob
from pipeline.trading.markets import btc_15m_slug, current_window_start


class FeatureMathTests(TestCase):
    def test_trade_flow_imbalance_window(self) -> None:
        meter = RealTimeTradeImbalance(window_seconds=10)
        meter.process_tick(2.0, is_buyer_maker=False, now=0.0)
        meter.process_tick(1.0, is_buyer_maker=True, now=1.0)
        self.assertAlmostEqual(meter.current_imbalance, 1.0)
        meter.process_tick(0.0, is_buyer_maker=False, now=11.5)
        self.assertAlmostEqual(meter.current_imbalance, 0.0)
        self.assertIsNone(meter.ratio)

    def test_tfi_ratio_is_scale_free(self) -> None:
        meter = RealTimeTradeImbalance(window_seconds=10)
        meter.process_tick(100.0, is_buyer_maker=False, now=0.0)
        meter.process_tick(50.0, is_buyer_maker=True, now=1.0)
        self.assertAlmostEqual(meter.ratio or 0.0, 50.0 / 150.0)

    def test_vpin_splits_oversized_tick(self) -> None:
        vpin = RealTimeVPIN(bucket_volume=10.0, window_size=2)
        self.assertIsNone(vpin.process_tick(10.0, is_buyer_maker=False))
        value = vpin.process_tick(10.0, is_buyer_maker=True)
        self.assertIsNotNone(value)
        self.assertAlmostEqual(value or 0.0, 1.0)
        value = vpin.process_tick(25.0, is_buyer_maker=False)
        self.assertIsNotNone(value)
        self.assertGreaterEqual(value or 0.0, 0.0)
        self.assertLessEqual(value or 0.0, 1.0)

    def test_order_book_imbalance_and_wmp(self) -> None:
        book = OrderBook()
        book.apply_snapshot([[100.0, 8.0], [99.0, 2.0]], [[101.0, 2.0], [102.0, 2.0]])
        obi = book.imbalance(2)
        self.assertIsNotNone(obi)
        self.assertGreater(obi or 0.0, 0.0)
        wmp = book.weighted_mid()
        self.assertIsNotNone(wmp)
        self.assertGreater(wmp or 0.0, book.mid() or 0.0)

    def test_vpin_rejects_negative_size(self) -> None:
        vpin = RealTimeVPIN(bucket_volume=5.0, window_size=2)
        with self.assertRaises(ValueError):
            vpin.process_tick(-1.0, True)


class LabelAndVectorTests(TestCase):
    def test_training_vector_drops_raw_prices(self) -> None:
        vec = training_vector(
            {
                "mid": 64000.0,
                "binance_spot_last": 64001.0,
                "ret_60s": 0.001,
                "binance_spot_obi5": 0.2,
                "poly_yes_mid": 0.57,
            }
        )
        self.assertNotIn("mid", vec)
        self.assertNotIn("binance_spot_last", vec)
        self.assertIn("ret_60s", vec)
        self.assertIn("poly_yes_mid", vec)

    def test_forward_label_from_bars(self) -> None:
        FeatureBar.objects.create(ts=1_000, interval_seconds=5, mid_price=100.0, features={"ret_5s": 0.0})
        FeatureBar.objects.create(ts=1_900, interval_seconds=5, mid_price=101.0, features={"ret_5s": 0.01})
        from pipeline.ingest.supervisor import label_ready_bars

        labeled = label_ready_bars(horizon=900, limit=10)
        self.assertEqual(labeled, 1)
        bar = FeatureBar.objects.get(ts=1_000)
        self.assertTrue(bar.label_up_15m)

    def test_labels_do_not_mix_assets(self) -> None:
        FeatureBar.objects.create(asset="BTC", ts=1_000, interval_seconds=60, mid_price=100.0, features={})
        FeatureBar.objects.create(asset="BTC", ts=1_900, interval_seconds=60, mid_price=90.0, features={})
        FeatureBar.objects.create(asset="ETH", ts=1_000, interval_seconds=60, mid_price=100.0, features={})
        FeatureBar.objects.create(asset="ETH", ts=1_900, interval_seconds=60, mid_price=130.0, features={})
        from pipeline.ingest.supervisor import label_ready_bars

        label_ready_bars(horizon=900, limit=20)
        btc = FeatureBar.objects.get(asset="BTC", ts=1_000)
        eth = FeatureBar.objects.get(asset="ETH", ts=1_000)
        self.assertFalse(btc.label_up_15m)
        self.assertTrue(eth.label_up_15m)

    def test_next_bar_label(self) -> None:
        FeatureBar.objects.create(asset="XRP", ts=1_000, interval_seconds=60, mid_price=1.0, features={})
        FeatureBar.objects.create(asset="XRP", ts=1_060, interval_seconds=60, mid_price=1.2, features={})
        from pipeline.ingest.supervisor import label_ready_bars

        labeled = label_ready_bars(horizon=900, limit=20)
        self.assertGreaterEqual(labeled, 1)
        first = FeatureBar.objects.get(asset="XRP", ts=1_000)
        self.assertTrue(first.label_up_next)
        self.assertIsNone(first.label_up_15m)


class UniverseTests(TestCase):
    def test_symbol_maps(self) -> None:
        from pipeline.universe import asset_from_binance, normalize_assets, poly_slug

        self.assertEqual(normalize_assets(["eth", "BTC", "ETH", "zzz"]), ["ETH", "BTC"])
        self.assertEqual(asset_from_binance("ethusdt@trade"), "ETH")
        self.assertEqual(poly_slug("ETH", 900), "eth-updown-15m-900")



class MarketSlugTests(TestCase):
    def test_slug_aligns_to_900s(self) -> None:
        start = current_window_start(1_768_824_123)
        self.assertEqual(start % 900, 0)
        self.assertEqual(btc_15m_slug(start), f"btc-updown-15m-{start}")


class ApiTests(TestCase):
    def test_health_and_bootstrap(self) -> None:
        client = APIClient()
        health = client.get("/api/health")
        self.assertEqual(health.status_code, 200)
        self.assertTrue(health.json()["ok"])
        boot = client.get("/api/bootstrap")
        self.assertEqual(boot.status_code, 200)
        body = boot.json()
        self.assertIn("sources", body)
        self.assertGreaterEqual(len(body["architectures"]), 10)
        self.assertIn("universe", body)
        self.assertGreaterEqual(len(body["universe"]["assets"]), 6)
        self.assertGreaterEqual(len(body["universe"]["timeframes"]), 3)

    def test_setup_saves_assets_and_timeframes(self) -> None:
        client = APIClient()
        resp = client.post(
            "/api/setup",
            {
                "dry_run": True,
                "enabled_assets": ["BTC", "ETH", "XRP"],
                "bar_timeframes": ["1m", "5m"],
                "enabled_sources": ["binance_spot"],
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        settings = resp.json()["settings"]
        self.assertEqual(settings["enabled_assets"], ["BTC", "ETH", "XRP"])
        self.assertEqual(settings["bar_timeframes"], ["1m", "5m"])

    def test_setup_saves_non_secret_settings(self) -> None:
        client = APIClient()
        resp = client.post(
            "/api/setup",
            {"dry_run": True, "min_edge": 0.05, "order_size": 12, "enabled_sources": ["binance_spot", "polymarket_gamma"]},
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["settings"]["setup_complete"])
        self.assertEqual(resp.json()["settings"]["min_edge"], 0.05)

    def test_spa_serves_built_frontend(self) -> None:
        from django.test import Client

        response = Client().get("/")
        self.assertEqual(response.status_code, 200)
        body = b"".join(response.streaming_content)
        self.assertIn(b"BTC 15m Pipeline", body)


class TrainJobTests(TestCase):
    def test_logistic_walk_forward(self) -> None:
        for i in range(280):
            x = (i % 17) / 17.0
            FeatureBar.objects.create(
                ts=1_700_000_000 + i * 60,
                interval_seconds=60,
                mid_price=100.0 + i * 0.01,
                features={
                    "ret_60s": x,
                    "poly_yes_mid": 0.4 + 0.2 * x,
                    "binance_spot_obi5": x - 0.5,
                },
                label_up_15m=x > 0.5,
                label_up_next=x > 0.4,
            )
        job = TrainingJob.objects.create(
            status="pending",
            config={
                "architectures": ["logistic_regression", "random_forest"],
                "min_rows": 200,
                "folds": 2,
                "interval_seconds": 60,
                "label": "next",
                "assets": ["BTC", "ETH"],
            },
        )
        from pipeline.ml.train import run_training_job

        run_training_job(job.id)
        job.refresh_from_db()
        self.assertEqual(job.status, "completed")
        self.assertGreaterEqual(job.artifacts.count(), 1)
