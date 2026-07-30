from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from datetime import date
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from apps.ai_core.catalog import CatalogDefinition, load_catalog  # noqa: E402


class IntakeModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class EvidenceSource(IntakeModel):
    verification_status: Literal["to_collect", "verified", "rejected"] = "to_collect"
    title: str = Field(default="", max_length=200)
    publisher: str = Field(default="", max_length=160)
    url: str = Field(default="", max_length=500, pattern=r"^$|^https://")
    checked_on: date | None = None
    supports: list[str] = Field(min_length=1, max_length=30)
    notes: str = Field(default="", max_length=1_000)


class CoverageReview(IntakeModel):
    status: Literal[
        "unknown", "national", "international", "limited", "case_by_case"
    ] = "unknown"
    areas: list[str] = Field(default_factory=list, max_length=100)
    verification_required: bool = True
    notes: str = Field(min_length=1, max_length=1_000)


class PricingReview(IntakeModel):
    status: Literal["not_collected", "not_public", "quote_required", "published"] = (
        "not_collected"
    )
    price_terms: list[str] = Field(default_factory=list, max_length=20)
    currency: str | None = Field(default=None, max_length=12)
    billing_period: str | None = Field(default=None, max_length=80)
    source_url: str = Field(default="", max_length=500, pattern=r"^$|^https://")
    checked_on: date | None = None
    notes: str = Field(min_length=1, max_length=1_000)


class BusinessReviewChecklist(IntakeModel):
    official_name_verified: bool = False
    description_verified: bool = False
    benefits_verified: bool = False
    eligibility_verified: bool = False
    prerequisites_verified: bool = False
    exclusions_verified: bool = False
    coverage_verified: bool = False
    pricing_verified_without_invention: bool = False
    matching_terms_verified: bool = False
    sources_are_current: bool = False


class BusinessValidation(IntakeModel):
    status: Literal["draft", "needs_review", "approved", "rejected"] = "draft"
    reviewed_by: str = Field(default="", max_length=160)
    reviewed_on: date | None = None
    notes: str = Field(default="", max_length=1_000)


class ServiceReviewRecord(IntakeModel):
    service_id: str = Field(pattern=r"^[a-z][a-z0-9_]{2,63}$")
    provenance: list[EvidenceSource] = Field(min_length=1, max_length=20)
    eligibility_criteria: list[str] = Field(min_length=1, max_length=30)
    coverage: CoverageReview
    pricing: PricingReview
    validation: BusinessValidation
    review_checklist: BusinessReviewChecklist


class CatalogIntakePackage(IntakeModel):
    intake_schema_version: Literal["1.0"] = "1.0"
    catalog: CatalogDefinition
    service_reviews: list[ServiceReviewRecord] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def reviews_match_services(self) -> "CatalogIntakePackage":
        service_ids = [service.service_id for service in self.catalog.services]
        review_ids = [review.service_id for review in self.service_reviews]
        if len(review_ids) != len(set(review_ids)):
            raise ValueError("service review service_id values must be unique")
        if set(service_ids) != set(review_ids):
            missing = sorted(set(service_ids) - set(review_ids))
            unknown = sorted(set(review_ids) - set(service_ids))
            raise ValueError(
                "service reviews must match catalog services exactly "
                f"(missing={missing}, unknown={unknown})"
            )
        return self


PLACEHOLDER_MARKERS = (
    "à confirmer",
    "a confirmer",
    "à remplacer",
    "a remplacer",
    "non renseigné",
    "non renseigne",
    "todo",
    "tbd",
)


def _is_placeholder(value: str) -> bool:
    normalized = value.casefold()
    return any(marker in normalized for marker in PLACEHOLDER_MARKERS)


def _approved_errors(package: CatalogIntakePackage) -> list[str]:
    errors: list[str] = []
    today = date.today()

    if package.catalog.status != "approved":
        errors.append("catalog.status must be approved")
    if (
        not package.catalog.source_name
        or _is_placeholder(package.catalog.source_name)
        or not package.catalog.source_url
    ):
        errors.append("catalog source_name and source_url are required")
    if package.catalog.source_checked_on is None:
        errors.append("catalog source_checked_on is required")
    elif package.catalog.source_checked_on > today:
        errors.append("catalog source_checked_on cannot be in the future")

    service_by_id = {service.service_id: service for service in package.catalog.services}
    for review in package.service_reviews:
        prefix = f"service {review.service_id}:"
        service = service_by_id[review.service_id]

        required_texts = [
            service.service_id,
            service.name,
            service.category,
            service.description,
            *service.allowed_benefits,
            *service.target_customers,
            *(variant.name for variant in service.variants),
            *(detail for variant in service.variants for detail in variant.details),
            *service.commercial_terms,
            *service.prerequisites,
            *service.exclusions,
            *service.match.need_keywords,
            *service.match.sectors,
            *service.match.excluded_sectors,
            *review.eligibility_criteria,
        ]
        if any(_is_placeholder(value) for value in required_texts):
            errors.append(f"{prefix} placeholder text remains in required business fields")
        if not service.source_url or service.source_checked_on is None:
            errors.append(f"{prefix} source_url and source_checked_on are required")
        elif service.source_checked_on > today:
            errors.append(f"{prefix} source_checked_on cannot be in the future")

        verified_sources = [
            source for source in review.provenance if source.verification_status == "verified"
        ]
        if not verified_sources:
            errors.append(f"{prefix} at least one verified provenance source is required")
        for source in verified_sources:
            if not source.title or not source.publisher or not source.url or source.checked_on is None:
                errors.append(f"{prefix} every verified source must be fully documented")
            elif source.checked_on > today:
                errors.append(f"{prefix} source checked_on cannot be in the future")

        if review.coverage.status == "unknown":
            errors.append(f"{prefix} coverage status must be reviewed")
        if review.coverage.status == "limited" and not review.coverage.areas:
            errors.append(f"{prefix} limited coverage requires at least one area")
        if _is_placeholder(review.coverage.notes):
            errors.append(f"{prefix} coverage notes still contain a placeholder")

        pricing = review.pricing
        if pricing.status == "not_collected":
            errors.append(f"{prefix} pricing status must be reviewed")
        if pricing.status == "published":
            if not pricing.price_terms or not pricing.currency:
                errors.append(f"{prefix} published pricing requires price_terms and currency")
            if not pricing.source_url or pricing.checked_on is None:
                errors.append(f"{prefix} published pricing requires a dated source URL")
        elif pricing.price_terms:
            errors.append(
                f"{prefix} price_terms must stay empty unless pricing status is published"
            )
        if pricing.checked_on is not None and pricing.checked_on > today:
            errors.append(f"{prefix} pricing checked_on cannot be in the future")
        if _is_placeholder(pricing.notes) or any(
            _is_placeholder(term) for term in pricing.price_terms
        ):
            errors.append(f"{prefix} pricing fields still contain a placeholder")

        validation = review.validation
        if validation.status != "approved":
            errors.append(f"{prefix} business validation must be approved")
        if not validation.reviewed_by or validation.reviewed_on is None:
            errors.append(f"{prefix} reviewer and review date are required")
        elif validation.reviewed_on > today:
            errors.append(f"{prefix} review date cannot be in the future")

        checklist = review.review_checklist.model_dump()
        unchecked = [name for name, checked in checklist.items() if not checked]
        if unchecked:
            errors.append(f"{prefix} unchecked review items: {', '.join(unchecked)}")

    return errors


def validate_intake_package(
    path: str | Path, *, require_approved: bool = False
) -> CatalogIntakePackage:
    intake_path = Path(path).resolve()
    if not intake_path.is_file():
        raise FileNotFoundError(f"intake package not found: {intake_path}")
    with intake_path.open("r", encoding="utf-8") as stream:
        package = CatalogIntakePackage.model_validate(json.load(stream))

    if require_approved:
        errors = _approved_errors(package)
        if errors:
            raise ValueError("intake package is not approved:\n- " + "\n- ".join(errors))
    return package


def prepare_catalog_review_package(
    catalog_path: str | Path, destination: str | Path
) -> Path:
    """Create a pending, one-review-per-service business approval package.

    Source metadata is copied as a convenience, but every review remains explicitly
    unverified.  The function never upgrades the catalog or a service to approved.
    """

    catalog = load_catalog(catalog_path)
    output_path = Path(destination).resolve()
    if output_path.exists():
        raise FileExistsError(f"refusing to overwrite existing review package: {output_path}")

    catalog_data = catalog.model_dump(mode="json")
    catalog_data["status"] = "draft"
    service_reviews: list[dict[str, object]] = []
    for service in catalog.services:
        source_checked_on = (
            service.source_checked_on.isoformat() if service.source_checked_on else None
        )
        service_reviews.append(
            {
                "service_id": service.service_id,
                "provenance": [
                    {
                        "verification_status": "to_collect",
                        "title": service.name,
                        "publisher": service.provider_name,
                        "url": service.source_url,
                        "checked_on": source_checked_on,
                        "supports": [
                            "name",
                            "description",
                            "allowed_benefits",
                            "eligibility",
                            "coverage",
                            "pricing",
                        ],
                        "notes": (
                            "Source préremplie depuis le catalogue draft; le relecteur "
                            "doit vérifier son authenticité, son actualité et sa portée."
                        ),
                    }
                ],
                "eligibility_criteria": list(service.target_customers),
                "coverage": {
                    "status": "unknown",
                    "areas": [],
                    "verification_required": True,
                    "notes": (
                        "La couverture et la disponibilité doivent être confirmées "
                        "par le relecteur métier."
                    ),
                },
                "pricing": {
                    "status": "not_collected",
                    "price_terms": [],
                    "currency": None,
                    "billing_period": None,
                    "source_url": "",
                    "checked_on": None,
                    "notes": (
                        "La politique tarifaire doit être revue; aucun prix n’est "
                        "déduit automatiquement."
                    ),
                },
                "validation": {
                    "status": "needs_review",
                    "reviewed_by": "",
                    "reviewed_on": None,
                    "notes": "",
                },
                "review_checklist": {
                    field_name: False
                    for field_name in BusinessReviewChecklist.model_fields
                },
            }
        )

    package = CatalogIntakePackage.model_validate(
        {
            "intake_schema_version": "1.0",
            "catalog": catalog_data,
            "service_reviews": service_reviews,
        }
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("x", encoding="utf-8") as stream:
        json.dump(package.model_dump(mode="json"), stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    return output_path


def export_approved_catalog(intake_path: str | Path, destination: str | Path) -> Path:
    package = validate_intake_package(intake_path, require_approved=True)
    output_path = Path(destination).resolve()
    if output_path.exists():
        raise FileExistsError(f"refusing to overwrite existing catalog: {output_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    handle, temporary_name = tempfile.mkstemp(
        prefix=f".{output_path.stem}-", suffix=".json", dir=output_path.parent
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(
                package.catalog.model_dump(mode="json"),
                stream,
                ensure_ascii=False,
                indent=2,
            )
            stream.write("\n")
        load_catalog(temporary_path, require_approved=True)
        temporary_path.replace(output_path)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise
    return output_path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Valide un paquet de collecte Orange Business RDC ou international."
    )
    parser.add_argument("intake_file", type=Path)
    parser.add_argument(
        "--require-approved",
        action="store_true",
        help="exige les preuves et la revue métier complètes",
    )
    parser.add_argument(
        "--export",
        type=Path,
        help="exporte un nouveau catalog.json approuvé sans écraser un fichier existant",
    )
    args = parser.parse_args()

    try:
        if args.export:
            output_path = export_approved_catalog(args.intake_file, args.export)
            print(f"Catalogue approuvé exporté vers {output_path}")
        else:
            package = validate_intake_package(
                args.intake_file, require_approved=args.require_approved
            )
            print(
                f"Paquet valide: {len(package.catalog.services)} offre(s), "
                f"statut {package.catalog.status}."
            )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"Validation échouée: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
