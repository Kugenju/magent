from datetime import datetime, timezone, timedelta

from apps.vulntell.config import VulnTellConfig, SOURCE_AVAILABILITY
from apps.vulntell.sources.live_adapter import create_live_adapter


def test_default_live_window_is_two_years():
    cfg = VulnTellConfig(live=True, source="nvd")
    delta = cfg.window_end - cfg.window_start
    assert 729 <= delta.days <= 730


def test_all_registered_sources_have_live_adapter():
    sources = ["nvd", "cisa_kev", "cnvd", "osv", "github_advisory", "euvd", "msrc",
               "redhat", "ubuntu", "debian", "jvn", "certcc", "cisco", "fortinet",
               "paloalto", "exploitdb"]
    for source in sources:
        assert SOURCE_AVAILABILITY[source] == "available"
        assert create_live_adapter(VulnTellConfig(live=True, source=source)) is not None
