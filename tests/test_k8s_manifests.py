"""
Structural validation tests for Kubernetes manifests (k8s/).

These tests run offline — no cluster required.
They verify YAML syntax, document counts, required fields,
namespace labels, and Stage-8-specific invariants.
"""

import pytest
from k8s.validate import validate_all


def test_k8s_manifests_are_structurally_valid():
    """All k8s/ manifests pass structural validation."""
    errors, ok_count = validate_all()
    assert errors == [], "Kubernetes manifest errors:\n" + "\n".join(f"  {e}" for e in errors)
    assert ok_count > 0, "No manifest documents were checked"


def test_k8s_manifest_count():
    """Expected number of total manifest documents is present."""
    _, ok_count = validate_all()
    # 1+1+1+2+3+3+2 = 13 documents across 7 files
    assert ok_count == 13
