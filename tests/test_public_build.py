from __future__ import annotations

import unittest
from pathlib import Path

from src.analytics import build_weekly_readout
from src.evaluation import visible_evaluation_summary
from src.pipeline import load_bundled_dataset
from src.qa import evaluate_report_week
from src.trends import TREND_KPIS, build_trend_series


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class PublicBuildTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.dataset = load_bundled_dataset(PROJECT_ROOT)

    def test_bundle_is_healthcare_scope_and_has_eight_weeks(self) -> None:
        self.assertEqual(self.dataset.client_name, "Synthetic HealthCo")
        self.assertEqual(len(self.dataset.week_starts), 8)
        self.assertEqual({row["channel"] for row in self.dataset.rows}, {"Google", "Meta"})
        self.assertEqual(len(self.dataset.rows), 32)

    def test_latest_readout_exposes_exact_six_kpis(self) -> None:
        readout = build_weekly_readout(self.dataset, self.dataset.week_starts[-1])
        self.assertEqual(
            set(TREND_KPIS),
            {"Spend", "Qualified Leads", "CPQL", "Conversions", "Cost per Conversion", "Lead Qualification Rate"},
        )
        self.assertTrue(
            all(
                key in readout["current_metrics"]
                for key in (
                    "spend",
                    "qualified_leads",
                    "cost_per_qualified_lead",
                    "conversions",
                    "cost_per_conversion",
                    "lead_qualification_rate",
                )
            )
        )

    def test_public_quality_and_trend_paths_use_trusted_rows(self) -> None:
        latest = self.dataset.week_starts[-1]
        routing = evaluate_report_week(self.dataset, latest)
        self.assertEqual(routing.status, "PASS")
        summary = visible_evaluation_summary(self.dataset)
        self.assertTrue(summary["all_passed"])
        series = build_trend_series(self.dataset, self.dataset.week_starts[0], latest, "CPQL", "Overall", "4-week rolling")
        self.assertEqual(len(series), len(self.dataset.week_starts))
        self.assertTrue(all(item["trusted_row_count"] > 0 for item in series))

    def test_public_surface_keeps_readable_theme_and_colored_deltas(self) -> None:
        app_source = (PROJECT_ROOT / "app.py").read_text(encoding="utf-8")
        self.assertNotIn("--navy", app_source)
        self.assertNotIn("--gold", app_source)
        self.assertNotIn('delta_color="off"', app_source)
        self.assertIn('delta_color="normal"', app_source)
        self.assertIn('return "N/A" if percent is None else f"{float(percent):+.1%}"', app_source)
        self.assertNotIn('f"{float(percent):+.1%} WoW"', app_source)

    def test_public_surface_uses_healthcare_analytics_visual_system(self) -> None:
        app_source = (PROJECT_ROOT / "app.py").read_text(encoding="utf-8")
        self.assertIn("--readout-page: #f4f5f7", app_source)
        self.assertIn('page_title="Weekly Performance Readout"', app_source)
        self.assertIn('st.title("Weekly Performance Readout")', app_source)
        self.assertIn("--readout-focus: #374151", app_source)
        self.assertIn("--readout-positive: #15803d", app_source)
        self.assertIn("--readout-negative: #b91c1c", app_source)
        self.assertIn("--readout-table-bg: #ffffff", app_source)
        self.assertIn("--readout-table-header: #202124", app_source)
        self.assertIn("color-mix(in srgb, currentColor 22%, transparent)", app_source)
        self.assertIn('st.container(key=f"kpi-card-{key}")', app_source)
        self.assertIn('[data-testid="stMetricValue"] p', app_source)
        self.assertIn("SYNTHETIC DATA • FICTIONAL HEALTHCARE MARKETING ORGANIZATION • NO LIVE ACCOUNTS", app_source)
        self.assertIn("font-size: 1rem !important", app_source)
        self.assertIn('[data-testid="stTab"][aria-selected="true"]', app_source)
        self.assertIn("background: var(--readout-focus) !important", app_source)
        self.assertIn(".qa-card", app_source)
        self.assertIn(".readout-table th", app_source)
        self.assertIn("font-weight: 800", app_source)
        self.assertNotIn("--readout-accent", app_source)
        self.assertNotIn("--readout-warning", app_source)
        self.assertNotIn("212, 165, 74", app_source)
        self.assertNotIn("linear-gradient", app_source)
        self.assertNotIn("st.dataframe(", app_source)


if __name__ == "__main__":
    unittest.main()
