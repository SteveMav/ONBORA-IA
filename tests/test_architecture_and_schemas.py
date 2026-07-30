import ast
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from apps.ai_core.contracts import CompanyProfile


ROOT = Path(__file__).parents[1]


def imported_roots(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    roots = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".")[0])
    return roots


def test_domain_has_no_django_or_provider_sdk_dependency() -> None:
    for path in (ROOT / "apps" / "ai_core" / "domain").glob("*.py"):
        assert imported_roots(path).isdisjoint({"django", "google"}), path


def test_only_gemini_adapter_imports_google_sdk() -> None:
    offenders = []
    for path in (ROOT / "apps").rglob("*.py"):
        if "google" in imported_roots(path) and path.name != "gemini_adapter.py":
            offenders.append(path)
    assert offenders == []


def test_checked_in_valid_and_invalid_contract_examples() -> None:
    valid = json.loads(
        (ROOT / "contracts" / "examples" / "company-profile.valid.json").read_text(
            encoding="utf-8"
        )
    )
    invalid = json.loads(
        (ROOT / "contracts" / "examples" / "company-profile.invalid.json").read_text(
            encoding="utf-8"
        )
    )
    CompanyProfile.model_validate(valid)
    with pytest.raises(ValidationError):
        CompanyProfile.model_validate(invalid)
