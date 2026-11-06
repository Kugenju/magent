"""COSV-Schema 1.0.0 规范约束测试。"""
from apps.vulntell.cosv.models import COSVDocument, VersionEvent
from apps.vulntell.cosv.schema import validate_cosv_record
import pytest


def test_v100_minimal_record():
    ok, errors = validate_cosv_record({
        "schema_version": "1.0.0", "id": "CNVD-2023-12345",
        "modified": "2023-07-20T00:00:00Z",
    })
    assert ok, errors


def test_range_event_has_exactly_one_endpoint():
    with pytest.raises(ValueError):
        VersionEvent(introduced="1.0", fixed="2.0")


def test_v100_full_record_and_confirmation():
    doc = COSVDocument(
        id="CVE-2023-1", modified="2023-07-20T00:00:00Z",
        schema_version="1.0.0", confirm_type="double_confirmed",
        time_line=[{"type": "found", "value": "2023-07-19T00:00:00Z"}],
        affected=[{"package": {"ecosystem": "PyPI", "name": "demo"},
                   "ranges": [{"type": "SEMVER", "events": [{"introduced": "0"}, {"fixed": "1.2.0"}]}]}],
    )
    assert doc.affected[0].ranges[0].events[1].fixed == "1.2.0"


def test_rejects_legacy_schema_version():
    ok, errors = validate_cosv_record({
        "schema_version": "1.0", "id": "CVE-2023-1",
        "modified": "2023-07-20T00:00:00Z",
    })
    assert not ok
    assert any("schema_version" in error for error in errors)
