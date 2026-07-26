import uuid

from django.db import models


class Order(models.Model):
    class Status(models.TextChoices):
        PLACED = "placed", "Placed"
        SHIPPED = "shipped", "Shipped"
        DELIVERED = "delivered", "Delivered"
        REFUND_REQUESTED = "refund_requested", "Refund Requested"

    customer_name = models.CharField(max_length=255)
    item_name = models.CharField(max_length=255)
    item_category = models.CharField(max_length=100, default="electronics")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PLACED)
    order_date = models.DateField()
    tracking_number = models.CharField(max_length=100, blank=True, default="")

    class Meta:
        ordering = ["-order_date"]

    def __str__(self):
        return f"Order #{self.pk} — {self.customer_name}"


class InventoryItem(models.Model):
    item_name = models.CharField(max_length=255, unique=True)
    quantity_available = models.IntegerField(default=0)
    restock_eta = models.DateField(null=True, blank=True)

    def __str__(self):
        return f"{self.item_name} ({self.quantity_available} in stock)"


class RefundPolicy(models.Model):
    item_category = models.CharField(max_length=100, unique=True)
    refund_window_days = models.IntegerField(default=30)
    requires_manager_approval = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.item_category} — {self.refund_window_days}d window"


class ConversationLog(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        IN_PROGRESS = "in_progress", "In Progress"
        RESOLVED = "resolved", "Resolved"
        ESCALATED = "escalated", "Escalated"
        FAILED = "failed", "Failed"

    conversation_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    query_text = models.TextField()
    intent = models.CharField(max_length=50, blank=True, default="")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    final_response = models.TextField(blank=True, null=True)
    error_message = models.TextField(blank=True, null=True)
    last_agent_name = models.CharField(max_length=100, blank=True, default="")
    confidence_score = models.FloatField(null=True, blank=True)
    was_escalated = models.BooleanField(default=False)
    agents_involved = models.JSONField(default=list, blank=True)
    request_id = models.CharField(max_length=64, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.conversation_id} — {self.status}"
