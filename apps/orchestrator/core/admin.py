from django.contrib import admin

from .models import ConversationLog, InventoryItem, Order, RefundPolicy


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ("id", "customer_name", "item_name", "status", "order_date", "tracking_number")
    list_filter = ("status", "item_category")
    search_fields = ("customer_name", "item_name", "tracking_number")


@admin.register(InventoryItem)
class InventoryItemAdmin(admin.ModelAdmin):
    list_display = ("id", "item_name", "quantity_available", "restock_eta")
    search_fields = ("item_name",)


@admin.register(RefundPolicy)
class RefundPolicyAdmin(admin.ModelAdmin):
    list_display = ("id", "item_category", "refund_window_days", "requires_manager_approval")


@admin.register(ConversationLog)
class ConversationLogAdmin(admin.ModelAdmin):
    list_display = ("conversation_id", "intent", "status", "created_at")
    list_filter = ("status", "intent")
    search_fields = ("query_text", "final_response")
    readonly_fields = ("conversation_id", "created_at", "updated_at")
