from __future__ import annotations

from django.core.exceptions import ValidationError
from django.db import models
from pydantic import ValidationError as PydanticValidationError

from .contracts import CompanyProfile, RecommendationResult, TurnResult


class Conversation(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        COMPLETED = "completed", "Completed"

    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE)
    state_version = models.PositiveIntegerField(default=0)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class Message(models.Model):
    class Role(models.TextChoices):
        USER = "user", "User"
        ASSISTANT = "assistant", "Assistant"

    class Status(models.TextChoices):
        PROCESSING = "processing", "Processing"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"

    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name="messages")
    role = models.CharField(max_length=16, choices=Role.choices)
    content = models.TextField(max_length=20_000)
    idempotency_key = models.CharField(max_length=100)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PROCESSING)
    attempt_count = models.PositiveSmallIntegerField(default=0)
    error_code = models.CharField(max_length=80, blank=True)
    result_data = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["conversation", "idempotency_key"], name="unique_message_idempotency_key"
            )
        ]
        ordering = ["created_at", "id"]

    def clean(self) -> None:
        if self.status == self.Status.COMPLETED and self.role == self.Role.USER:
            try:
                TurnResult.model_validate(self.result_data)
            except PydanticValidationError as exc:
                raise ValidationError({"result_data": str(exc)}) from exc

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class CompanyProfileSnapshot(models.Model):
    conversation = models.ForeignKey(
        Conversation, on_delete=models.CASCADE, related_name="profile_snapshots"
    )
    version = models.PositiveIntegerField()
    schema_version = models.CharField(max_length=20, default="1.0")
    data = models.JSONField()
    content_hash = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["conversation", "version"], name="unique_profile_snapshot_version"
            )
        ]
        ordering = ["version"]

    def clean(self) -> None:
        try:
            profile = CompanyProfile.model_validate(self.data)
        except PydanticValidationError as exc:
            raise ValidationError({"data": str(exc)}) from exc
        if profile.schema_version != self.schema_version:
            raise ValidationError({"schema_version": "does not match profile data"})

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class RecommendationRecord(models.Model):
    conversation = models.ForeignKey(
        Conversation, on_delete=models.CASCADE, related_name="recommendation_records"
    )
    profile_snapshot = models.ForeignKey(
        CompanyProfileSnapshot, on_delete=models.CASCADE, related_name="recommendation_records"
    )
    catalog_version = models.CharField(max_length=64)
    input_fingerprint = models.CharField(max_length=64)
    data = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["profile_snapshot", "input_fingerprint"],
                name="unique_recommendation_fingerprint",
            )
        ]

    def clean(self) -> None:
        try:
            result = RecommendationResult.model_validate(self.data)
        except PydanticValidationError as exc:
            raise ValidationError({"data": str(exc)}) from exc
        if result.catalog_version != self.catalog_version:
            raise ValidationError({"catalog_version": "does not match recommendation data"})

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class AIExecution(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        SUCCEEDED = "succeeded", "Succeeded"
        FAILED = "failed", "Failed"

    conversation = models.ForeignKey(
        Conversation, on_delete=models.CASCADE, related_name="ai_executions"
    )
    message = models.ForeignKey(
        Message, on_delete=models.CASCADE, related_name="ai_executions", null=True, blank=True
    )
    purpose = models.CharField(max_length=50)
    provider = models.CharField(max_length=80)
    model_name = models.CharField(max_length=160)
    prompt_version = models.CharField(max_length=64)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    latency_ms = models.PositiveIntegerField(null=True, blank=True)
    input_tokens = models.PositiveIntegerField(null=True, blank=True)
    output_tokens = models.PositiveIntegerField(null=True, blank=True)
    error_code = models.CharField(max_length=80, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=["conversation", "purpose", "created_at"])]
