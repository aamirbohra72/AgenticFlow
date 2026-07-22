from datetime import date, timedelta

from django.core.management.base import BaseCommand

from core.models import InventoryItem, Order, RefundPolicy


class Command(BaseCommand):
    help = "Seed demo Order, InventoryItem, and RefundPolicy rows"

    def handle(self, *args, **options):
        today = date.today()

        orders = [
            {
                "id": 1234,
                "customer_name": "Alice Johnson",
                "item_name": "Wireless Headphones",
                "item_category": "electronics",
                "status": Order.Status.SHIPPED,
                "order_date": today - timedelta(days=3),
                "tracking_number": "TRK-ABC-123456",
            },
            {
                "id": 5678,
                "customer_name": "Bob Smith",
                "item_name": "Running Shoes",
                "item_category": "apparel",
                "status": Order.Status.DELIVERED,
                "order_date": today - timedelta(days=10),
                "tracking_number": "TRK-XYZ-789012",
            },
            {
                "id": 9012,
                "customer_name": "Carol Davis",
                "item_name": "Smart Watch",
                "item_category": "electronics",
                "status": Order.Status.PLACED,
                "order_date": today - timedelta(days=1),
                "tracking_number": "",
            },
            {
                "id": 3333,
                "customer_name": "Dana Lee",
                "item_name": "Running Shoes",
                "item_category": "apparel",
                "status": Order.Status.DELIVERED,
                "order_date": today - timedelta(days=20),
                "tracking_number": "TRK-OUT-333333",
            },
        ]

        for data in orders:
            order_id = data.pop("id")
            Order.objects.update_or_create(id=order_id, defaults=data)

        inventory = [
            {"item_name": "Wireless Headphones", "quantity_available": 25, "restock_eta": None},
            {"item_name": "Running Shoes", "quantity_available": 0, "restock_eta": today + timedelta(days=14)},
            {"item_name": "Smart Watch", "quantity_available": 8, "restock_eta": None},
            {"item_name": "Laptop Stand", "quantity_available": 50, "restock_eta": None},
        ]

        for item in inventory:
            InventoryItem.objects.update_or_create(item_name=item["item_name"], defaults=item)

        policies = [
            {"item_category": "electronics", "refund_window_days": 30, "requires_manager_approval": False},
            {"item_category": "apparel", "refund_window_days": 14, "requires_manager_approval": False},
            {"item_category": "furniture", "refund_window_days": 7, "requires_manager_approval": True},
        ]

        for policy in policies:
            RefundPolicy.objects.update_or_create(
                item_category=policy["item_category"],
                defaults=policy,
            )

        self.stdout.write(self.style.SUCCESS("Demo data seeded successfully."))
