"""
Self-test for the scheduling engine - no pytest needed, just:

    python test_scheduler.py

Covers the Order model, the heapq priority queue (including lazy deletion),
metric arithmetic and the greedy sequencing loop.
"""

from __future__ import annotations

import unittest

from scheduler.engine import compare_strategies, compute_metrics, schedule_orders
from scheduler.models import SAMPLE_ORDERS, Order, ValidationError, parse_orders
from scheduler.queueing import KitchenPriorityQueue
from scheduler.strategies import STRATEGY_KEYS, atc_breakdown


def make_orders():
    return [Order.from_dict(o) for o in SAMPLE_ORDERS]


class TestOrderModel(unittest.TestCase):
    def test_valid_order(self):
        o = Order(id=1, name="Dosa", prep_time=9, urgency=3, promised_time=23)
        self.assertEqual((o.prep_time, o.urgency, o.promised_time), (9, 3, 23))

    def test_rejects_bad_urgency(self):
        with self.assertRaises(ValidationError):
            Order(id=1, name="X", prep_time=5, urgency=9, promised_time=10)

    def test_rejects_zero_prep(self):
        with self.assertRaises(ValidationError):
            Order(id=1, name="X", prep_time=0, urgency=2, promised_time=10)

    def test_rejects_negative_deadline(self):
        with self.assertRaises(ValidationError):
            Order(id=1, name="X", prep_time=5, urgency=2, promised_time=-1)

    def test_parse_orders_rejects_duplicates(self):
        with self.assertRaises(ValidationError):
            parse_orders(
                [
                    {"id": 1, "name": "A", "prep_time": 3, "urgency": 1, "promised_time": 9},
                    {"id": 1, "name": "B", "prep_time": 3, "urgency": 1, "promised_time": 9},
                ]
            )


class TestPriorityQueue(unittest.TestCase):
    def test_pops_in_priority_order(self):
        pq = KitchenPriorityQueue()
        for prio, oid in [(3, "c"), (1, "a"), (2, "b")]:
            pq.push((prio,), Order(id=oid, name=oid, prep_time=1, urgency=1, promised_time=5))
        self.assertEqual([pq.pop().id for _ in range(3)], ["a", "b", "c"])
        self.assertIsNone(pq.pop())

    def test_lazy_deletion_discards_stale_entries(self):
        pq = KitchenPriorityQueue()
        o = Order(id="x", name="X", prep_time=1, urgency=1, promised_time=5)
        pq.push((1,), o)
        pq.invalidate()          # generation bumped -> the entry above is now stale
        self.assertEqual(len(pq), 0)
        self.assertEqual(pq.heap_size, 1)   # still physically present in the list
        pq.push((2,), o)                     # re-push with a fresh score
        self.assertEqual(pq.pop().id, "x")   # stale entry skipped, live one returned

    def test_peek_sorted_is_non_destructive(self):
        pq = KitchenPriorityQueue()
        o = Order(id="x", name="X", prep_time=1, urgency=1, promised_time=5)
        pq.push((1,), o)
        self.assertEqual(len(pq.peek_sorted()), 1)
        self.assertEqual(len(pq), 1)


class TestScoring(unittest.TestCase):
    def test_atc_ratio_and_saturation(self):
        o = Order(id=1, name="X", prep_time=10, urgency=5, promised_time=100)
        b = atc_breakdown(o, now=0, avg_prep=10.0, k=1.5)
        self.assertAlmostEqual(b["ratio"], 0.5)
        self.assertTrue(0 < b["deadline_factor"] < 1)
        self.assertAlmostEqual(b["score"], b["ratio"] * b["deadline_factor"], places=5)

    def test_atc_saturates_when_at_risk(self):
        # slack = 5 - 10 - 0 = -5  -> already late -> exponential term must be 1.0
        o = Order(id=1, name="X", prep_time=10, urgency=5, promised_time=5)
        b = atc_breakdown(o, now=0, avg_prep=10.0, k=1.5)
        self.assertTrue(b["at_risk"])
        self.assertAlmostEqual(b["deadline_factor"], 1.0)
        self.assertAlmostEqual(b["score"], 0.5)

    def test_shorter_prep_beats_longer_prep_at_equal_urgency(self):
        short = Order(id=1, name="S", prep_time=4, urgency=4, promised_time=30)
        long_ = Order(id=2, name="L", prep_time=20, urgency=4, promised_time=30)
        avg = 12.0
        self.assertGreater(
            atc_breakdown(short, 0, avg)["score"], atc_breakdown(long_, 0, avg)["score"]
        )


class TestSequencer(unittest.TestCase):
    def test_timeline_is_contiguous_and_starts_at_zero(self):
        for key in STRATEGY_KEYS:
            res = schedule_orders(make_orders(), key)
            clock = 0
            for slot in res.timeline:
                self.assertEqual(slot["start_time"], clock, f"{key}: gap before {slot['name']}")
                self.assertEqual(slot["completion_time"], clock + slot["prep_time"])
                clock = slot["completion_time"]
            self.assertEqual(res.metrics["makespan"], clock)

    def test_every_order_scheduled_exactly_once(self):
        orders = make_orders()
        for key in STRATEGY_KEYS:
            res = schedule_orders(orders, key)
            self.assertEqual(len(res.timeline), len(orders))
            self.assertEqual({s["id"] for s in res.timeline}, {o.id for o in orders})

    def test_delay_arithmetic(self):
        res = schedule_orders(make_orders(), "edf")
        for slot in res.timeline:
            expected = max(0, slot["completion_time"] - slot["promised_time"])
            self.assertEqual(slot["delay"], expected)
            self.assertEqual(slot["on_time"], expected == 0)

    def test_deterministic(self):
        a = schedule_orders(make_orders(), "greedy_min_delay").to_dict()
        b = schedule_orders(make_orders(), "greedy_min_delay").to_dict()
        self.assertEqual(a, b)

    def test_fifo_preserves_input_order(self):
        res = schedule_orders(make_orders(), "fifo")
        self.assertEqual([s["id"] for s in res.timeline], [o["id"] for o in SAMPLE_ORDERS])

    def test_edf_sorts_by_deadline(self):
        orders = make_orders()
        res = schedule_orders(orders, "edf")
        emitted = [s["promised_time"] for s in res.timeline]
        self.assertEqual(emitted, sorted(o.promised_time for o in orders))

    def test_decision_log_shape(self):
        res = schedule_orders(make_orders(), "greedy_min_delay")
        self.assertEqual(len(res.decision_log), len(res.timeline))
        for step in res.decision_log:
            self.assertIn("rationale", step)
            self.assertIn("queue_event", step)
            self.assertIn("candidates", step)
            self.assertIn("arithmetic", step)
            self.assertTrue(step["rationale"].startswith("Picked #"))

    def test_dynamic_strategy_rescores_every_tick(self):
        res = schedule_orders(make_orders(), "greedy_min_delay")
        self.assertTrue(all(s["queue_event"]["type"] == "recompute" for s in res.decision_log))
        edf = schedule_orders(make_orders(), "edf").decision_log
        self.assertEqual(edf[0]["queue_event"]["type"], "build")
        self.assertTrue(all(s["queue_event"]["type"] == "reuse" for s in edf[1:]))

    def test_metrics_arithmetic(self):
        res = schedule_orders(make_orders(), "greedy_min_delay")
        m = res.metrics
        self.assertEqual(m["total_delay"], sum(s["delay"] for s in res.timeline))
        self.assertEqual(m["on_time_count"] + m["delayed_count"], m["total_orders"])
        self.assertAlmostEqual(m["on_time_percentage"], 100 * m["on_time_count"] / m["total_orders"], places=4)
        self.assertEqual(
            m["total_cost"],
            round(sum(s["delay"] * s["urgency"] for s in res.timeline) + 10 * m["delayed_count"], 2),
        )

    def test_empty_metrics_are_safe(self):
        self.assertEqual(compute_metrics([])["on_time_percentage"], 0.0)

    def test_greedy_beats_fifo_on_sample(self):
        orders = make_orders()
        greedy = schedule_orders(orders, "greedy_min_delay").metrics
        fifo = schedule_orders(orders, "fifo").metrics
        self.assertLess(greedy["total_cost"], fifo["total_cost"])
        self.assertGreaterEqual(greedy["on_time_percentage"], fifo["on_time_percentage"])

    def test_lookahead_k_is_threaded_through(self):
        res = schedule_orders(make_orders(), "greedy_min_delay", k=5.0)
        self.assertEqual(res.lookahead, 5.0)
        self.assertEqual(res.to_dict()["lookahead_k"], 5.0)


class TestComparison(unittest.TestCase):
    def test_comparison_ranks_all_strategies(self):
        out = compare_strategies(make_orders())
        self.assertEqual(len(out["rows"]), len(STRATEGY_KEYS))
        self.assertEqual(out["rows"][0]["total_cost"], min(r["total_cost"] for r in out["rows"]))
        self.assertTrue(out["rows"][0]["is_best"])
        self.assertIn("cost_formula", out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
