"""VulnTell COSV 模块测试。"""

from __future__ import annotations

import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

from apps.vulntell.cosv.models import (
    Affected,
    COSVDocument,
    Package,
    Reference,
    ReferenceType,
    Severity,
    SeverityType,
    VersionEvent,
    VersionRange,
)
from apps.vulntell.cosv.schema import validate_cosv_file, validate_cosv_record
from apps.vulntell.cosv.serializer import (
    content_hash,
    deserialize_cosv,
    read_cosv_file,
    serialize_cosv,
    serialize_cosv_to_file,
)
from apps.vulntell.cosv.mapper import observation_to_cosv, batch_observations_to_cosv
from apps.vulntell.domain.models import SourceObservation


class TestCOSVModels:
    """COSV 模型测试。"""

    def test_cosv_document_minimal(self):
        """测试最小 COSV 文档。"""
        doc = COSVDocument(
            id="CVE-2024-0001",
            modified="2024-01-01T00:00:00Z",
        )
        assert doc.schema_version == "1.0"
        assert doc.id == "CVE-2024-0001"
        assert doc.modified == "2024-01-01T00:00:00Z"

    def test_cosv_document_full(self):
        """测试完整 COSV 文档。"""
        doc = COSVDocument(
            id="CVE-2024-0001",
            modified="2024-01-01T00:00:00Z",
            published="2024-01-01T00:00:00Z",
            aliases=["GHSA-xxxx"],
            summary="Test vulnerability",
            details="Full description",
            affected=[
                Affected(
                    package=Package(name="test-pkg", ecosystem="npm"),
                    ranges=[
                        VersionRange(
                            type="semver",
                            events=[
                                VersionEvent(introduced="0.0.0", fixed="1.0.0"),
                            ],
                        )
                    ],
                )
            ],
            severity=[
                Severity(type=SeverityType.CVSS_V31, score="9.8", vector="CVSS:3.1/AV:N")
            ],
            references=[
                Reference(type=ReferenceType.ADVISORY, url="https://example.com/advisory"),
            ],
            credits=["Test User"],
        )
        assert doc.aliases == ["GHSA-xxxx"]
        assert len(doc.affected) == 1
        assert doc.affected[0].package.name == "test-pkg"

    def test_cosv_document_validation_error(self):
        """测试 COSV 文档验证错误。"""
        with pytest.raises(Exception):
            COSVDocument(id="", modified="2024-01-01T00:00:00Z")

    def test_cosv_document_modified_validation(self):
        """测试 modified 时间格式验证。"""
        with pytest.raises(Exception):
            COSVDocument(id="CVE-2024-0001", modified="invalid-date")


class TestCOSVSchema:
    """COSV Schema 校验测试。"""

    def test_validate_valid_record(self):
        """测试有效记录校验。"""
        record = {
            "schema_version": "1.0",
            "id": "CVE-2024-0001",
            "modified": "2024-01-01T00:00:00Z",
        }
        is_valid, errors = validate_cosv_record(record)
        assert is_valid
        assert errors == []

    def test_validate_missing_required_field(self):
        """测试缺少必填字段。"""
        record = {"id": "CVE-2024-0001", "modified": "2024-01-01T00:00:00Z"}
        is_valid, errors = validate_cosv_record(record)
        assert not is_valid
        assert any("schema_version" in e for e in errors)

    def test_validate_invalid_modified_format(self):
        """测试无效的 modified 格式。"""
        record = {
            "schema_version": "1.0",
            "id": "CVE-2024-0001",
            "modified": "2024-01-01",
        }
        is_valid, errors = validate_cosv_record(record)
        assert not is_valid
        assert any("modified" in e for e in errors)

    def test_validate_file_not_found(self):
        """测试文件不存在。"""
        is_valid, results = validate_cosv_file("/nonexistent/file.jsonl")
        assert not is_valid
        assert len(results) == 1

    def test_validate_valid_file(self):
        """测试有效 JSONL 文件。"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            f.write('{"schema_version":"1.0","id":"CVE-2024-0001","modified":"2024-01-01T00:00:00Z"}\n')
            f.write('{"schema_version":"1.0","id":"CVE-2024-0002","modified":"2024-01-02T00:00:00Z"}\n')
            temp_path = f.name

        try:
            is_valid, results = validate_cosv_file(temp_path)
            assert is_valid
            assert len(results) == 2
        finally:
            Path(temp_path).unlink()


class TestCOSVSerializer:
    """COSV 序列化测试。"""

    def test_serialize_cosv(self):
        """测试 serialize_cosv 函数。"""
        doc = COSVDocument(
            id="CVE-2024-0001",
            modified="2024-01-01T00:00:00Z",
        )
        serialized = serialize_cosv(doc)
        assert "CVE-2024-0001" in serialized
        assert "2024-01-01T00:00:00Z" in serialized

    def test_content_hash_consistency(self):
        """测试内容哈希一致性。"""
        doc = COSVDocument(
            id="CVE-2024-0001",
            modified="2024-01-01T00:00:00Z",
        )
        hash1 = content_hash(doc)
        hash2 = content_hash(doc)
        assert hash1 == hash2

    def test_content_hash_change_on_field_update(self):
        """测试字段更新后哈希变化。"""
        doc1 = COSVDocument(
            id="CVE-2024-0001",
            modified="2024-01-01T00:00:00Z",
        )
        doc2 = COSVDocument(
            id="CVE-2024-0001",
            modified="2024-01-02T00:00:00Z",
        )
        assert content_hash(doc1) != content_hash(doc2)

    def test_serialize_to_file(self):
        """测试序列化到文件。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "test.cosv.jsonl"
            doc = COSVDocument(
                id="CVE-2024-0001",
                modified="2024-01-01T00:00:00Z",
            )
            file_hash = serialize_cosv_to_file(doc, file_path)
            assert file_hash
            assert file_path.exists()

    def test_deserialize_cosv(self):
        """测试反序列化。"""
        line = '{"schema_version":"1.0","id":"CVE-2024-0001","modified":"2024-01-01T00:00:00Z"}'
        doc = deserialize_cosv(line)
        assert doc is not None
        assert doc.id == "CVE-2024-0001"

    def test_read_cosv_file(self):
        """测试读取 COSV 文件。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "test.cosv.jsonl"
            doc = COSVDocument(
                id="CVE-2024-0001",
                modified="2024-01-01T00:00:00Z",
            )
            serialize_cosv_to_file(doc, file_path)
            docs = read_cosv_file(file_path)
            assert len(docs) == 1
            assert docs[0].id == "CVE-2024-0001"


class TestCOSVMapper:
    """COSV 映射器测试。"""

    def _make_observation(self, **kwargs) -> SourceObservation:
        """创建测试用 SourceObservation。"""
        defaults = {
            "source": "nvd",
            "source_record_id": "CVE-2024-0001",
            "cve_id": "CVE-2024-0001",
            "observed_at": datetime.now(timezone.utc),
            "raw_payload_hash": "abc123",
            "normalized_fields": {
                "title": "Test vulnerability",
                "description": "Full description",
                "references": [
                    {"url": "https://example.com", "ref_type": "advisory"},
                ],
            },
        }
        defaults.update(kwargs)
        return SourceObservation(**defaults)

    def test_observation_to_cosv(self):
        """测试 SourceObservation 到 COSVDocument 映射。"""
        obs = self._make_observation()
        doc = observation_to_cosv(obs)
        assert doc.id == "CVE-2024-0001"
        assert doc.summary == "Test vulnerability"

    def test_observation_to_cosv_no_cve(self):
        """测试无 CVE 的 SourceObservation 映射。"""
        obs = self._make_observation(cve_id=None, source_record_id="nvd:12345")
        doc = observation_to_cosv(obs)
        assert doc.id == "nvd:nvd:12345"

    def test_batch_observations_to_cosv(self):
        """测试批量映射。"""
        obs1 = self._make_observation(source_record_id="CVE-2024-0001")
        obs2 = self._make_observation(source_record_id="CVE-2024-0002")
        docs, issues = batch_observations_to_cosv([obs1, obs2])
        assert len(docs) == 2
        assert len(issues) == 0


class TestCredentialLeakage:
    """凭据泄露测试。"""

    def test_no_api_key_in_serialized_cosv(self):
        """测试序列化 COSV 不包含 API key。"""
        doc = COSVDocument(
            id="CVE-2024-0001",
            modified="2024-01-01T00:00:00Z",
        )
        serialized = serialize_cosv(doc)
        assert "api_key" not in serialized.lower()
        assert "apikey" not in serialized.lower()

    def test_no_cookie_in_serialized_cosv(self):
        """测试序列化 COSV 不包含 Cookie。"""
        doc = COSVDocument(
            id="CVE-2024-0001",
            modified="2024-01-01T00:00:00Z",
        )
        serialized = serialize_cosv(doc)
        assert "cookie" not in serialized.lower()
