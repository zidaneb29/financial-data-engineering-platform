import re
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_source_scope_has_valid_identifiers_and_cadences():
    scope = tomllib.loads((ROOT / "config" / "source_scope.toml").read_text(encoding="utf-8"))
    series = scope["fred"]["series"]
    assert series
    assert set(series.values()) == {"daily", "monthly", "quarterly"}
    assert all(re.fullmatch(r"[A-Z][A-Z0-9_]*", series_id) for series_id in series)

    companies = scope["sec"]["companies"]
    assert 10 <= len(companies) <= 20
    assert len(set(companies.values())) == len(companies)
    assert all(re.fullmatch(r"[0-9]{10}", cik) for cik in companies.values())
    assert set(scope["sec"]["forms"]) == {"10-K", "10-K/A", "10-Q", "10-Q/A"}


def test_environment_template_leaves_credentials_blank():
    entries = dict(
        line.split("=", 1)
        for line in (ROOT / ".env.example").read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#")
    )
    assert entries["FRED_API_KEY"] == ""
    assert entries["SEC_USER_AGENT"] == ""
    data_dir = Path(entries["FIN_DATA_DIR"])
    assert data_dir.parts[0] == ".local"
    assert ".." not in data_dir.parts
