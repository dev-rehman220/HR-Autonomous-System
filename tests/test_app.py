from pathlib import Path

import streamlit as st
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parent.parent
APP_PATH = ROOT / "src" / "app.py"


def _run_app() -> AppTest:
    st.cache_resource.clear()
    app = AppTest.from_file(str(APP_PATH), default_timeout=120)
    app.run()
    assert not app.exception, f"Streamlit raised: {[e.value for e in app.exception]}"
    return app


def test_app_renders_three_tabs_without_error():
    app = _run_app()
    assert app.title[0].value == "TalentAgent: Autonomous Technical Recruiter"
    assert len(app.tabs) == 3


def test_roster_tab_reports_empty_state(tmp_path, monkeypatch):
    import src.config

    monkeypatch.setattr(src.config, "ROSTER_DB_PATH", str(tmp_path / "roster.db"))
    app = _run_app()
    labels = [info.value for info in app.info]
    assert any("No applicants yet" in text for text in labels)
    assert any("Upload a resume" in text for text in labels)


def test_inbox_tab_shows_roster_count_metric():
    app = _run_app()
    assert "Applicants in roster" in [metric.label for metric in app.metric]


def test_roster_tab_lists_existing_applicants():
    app = _run_app()
    assert len(app.dataframe) >= 1
