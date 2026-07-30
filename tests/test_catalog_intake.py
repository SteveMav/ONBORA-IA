import json
from copy import deepcopy
from pathlib import Path

import pytest
from pydantic import ValidationError

from apps.ai_core.catalog import load_catalog
from catalog.intake.validate_intake import (
    export_approved_catalog,
    prepare_catalog_review_package,
    validate_intake_package,
)


ROOT = Path(__file__).parents[1]
TEMPLATE_PATH = ROOT / "catalog" / "intake" / "template.json"


def _template() -> dict:
    return json.loads(TEMPLATE_PATH.read_text(encoding="utf-8"))


def _approved_package() -> dict:
    package = deepcopy(_template())
    package["catalog"].update(
        {
            "catalog_version": "test-approved-1.0",
            "status": "approved",
            "source_name": "Catalogue officiel de test",
            "source_url": "https://example.org/catalogue",
            "source_checked_on": "2026-07-26",
        }
    )
    service = package["catalog"]["services"][0]
    service.update(
        {
            "service_id": "synthetic_service",
            "name": "Service synthétique",
            "category": "Test",
            "description": "Service utilisé uniquement pour vérifier le processus d’import.",
            "allowed_benefits": ["Répondre à un besoin synthétique"],
            "target_customers": ["Entreprises de test"],
            "commercial_terms": ["Conditions disponibles sur demande"],
            "prerequisites": ["Vérification technique"],
            "exclusions": ["Aucun usage réel"],
            "source_url": "https://example.org/offre",
            "source_checked_on": "2026-07-26",
            "match": {
                "need_keywords": ["besoin synthétique"],
                "sectors": [],
                "excluded_sectors": [],
                "required_profile_fields": ["locations"],
            },
        }
    )

    review = package["service_reviews"][0]
    review.update(
        {
            "service_id": "synthetic_service",
            "provenance": [
                {
                    "verification_status": "verified",
                    "title": "Source officielle de test",
                    "publisher": "Éditeur de test",
                    "url": "https://example.org/offre",
                    "checked_on": "2026-07-26",
                    "supports": ["name", "description", "allowed_benefits"],
                    "notes": "Fixture synthétique; ne représente aucune offre réelle.",
                }
            ],
            "eligibility_criteria": ["Entreprise située dans une zone éligible"],
            "coverage": {
                "status": "case_by_case",
                "areas": [],
                "verification_required": True,
                "notes": "Éligibilité technique vérifiée au cas par cas.",
            },
            "pricing": {
                "status": "quote_required",
                "price_terms": [],
                "currency": None,
                "billing_period": None,
                "source_url": "",
                "checked_on": None,
                "notes": "Un devis est requis; aucun prix public n’est enregistré.",
            },
            "validation": {
                "status": "approved",
                "reviewed_by": "Responsable métier de test",
                "reviewed_on": "2026-07-26",
                "notes": "Validation synthétique.",
            },
            "review_checklist": {
                key: True for key in review["review_checklist"]
            },
        }
    )
    return package


def test_intake_template_is_structurally_valid_but_not_approved() -> None:
    package = validate_intake_package(TEMPLATE_PATH)

    assert package.catalog.status == "draft"
    assert package.catalog.services[0].service_id == "offer_to_replace"
    with pytest.raises(ValueError, match="not approved"):
        validate_intake_package(TEMPLATE_PATH, require_approved=True)


def test_intake_requires_one_review_per_catalog_service(tmp_path: Path) -> None:
    raw = _template()
    raw["service_reviews"] = []
    path = tmp_path / "missing-review.json"
    path.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(ValidationError, match="at least 1 item"):
        validate_intake_package(path)


def test_approved_intake_exports_through_catalog_loader(tmp_path: Path) -> None:
    intake_path = tmp_path / "approved.intake.json"
    intake_path.write_text(
        json.dumps(_approved_package(), ensure_ascii=False), encoding="utf-8"
    )
    output_path = tmp_path / "new-version" / "catalog.json"

    exported = export_approved_catalog(intake_path, output_path)
    catalog = load_catalog(exported, require_approved=True)

    assert catalog.catalog_version == "test-approved-1.0"
    assert catalog.services[0].service_id == "synthetic_service"
    with pytest.raises(FileExistsError, match="overwrite"):
        export_approved_catalog(intake_path, output_path)


def test_published_pricing_requires_dated_source(tmp_path: Path) -> None:
    raw = _approved_package()
    raw["service_reviews"][0]["pricing"].update(
        {
            "status": "published",
            "price_terms": ["100 unités par mois"],
            "currency": "CDF",
            "source_url": "",
            "checked_on": None,
        }
    )
    path = tmp_path / "unsourced-price.json"
    path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(ValueError, match="published pricing requires a dated source URL"):
        validate_intake_package(path, require_approved=True)


def test_prepare_catalog_review_keeps_every_decision_pending(tmp_path: Path) -> None:
    catalog_path = ROOT / "catalog" / "versions" / "v1" / "catalog.json"
    output_path = tmp_path / "catalog-review.json"

    prepared = prepare_catalog_review_package(catalog_path, output_path)
    package = validate_intake_package(prepared)

    assert package.catalog.status == "draft"
    assert len(package.service_reviews) == len(package.catalog.services)
    assert all(
        review.validation.status == "needs_review"
        for review in package.service_reviews
    )
    assert all(
        not any(review.review_checklist.model_dump().values())
        for review in package.service_reviews
    )
    with pytest.raises(ValueError, match="not approved"):
        validate_intake_package(prepared, require_approved=True)
    with pytest.raises(FileExistsError, match="overwrite"):
        prepare_catalog_review_package(catalog_path, output_path)
