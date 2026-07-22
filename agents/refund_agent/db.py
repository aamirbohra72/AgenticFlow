import os
from contextlib import contextmanager
from datetime import date

import psycopg2
import psycopg2.extras


@contextmanager
def get_connection():
    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    try:
        yield conn
    finally:
        conn.close()


def get_order_by_id(order_id: str | int) -> dict | None:
    with get_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT id, customer_name, item_name, item_category, status, order_date
                FROM core_order WHERE id = %s
                """,
                (int(order_id),),
            )
            row = cur.fetchone()
            return dict(row) if row else None


def get_refund_policy(category: str) -> dict | None:
    with get_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT item_category, refund_window_days, requires_manager_approval
                FROM core_refundpolicy WHERE LOWER(item_category) = LOWER(%s)
                """,
                (category,),
            )
            row = cur.fetchone()
            return dict(row) if row else None


def get_inventory_status(item_name: str) -> dict:
    with get_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT item_name, quantity_available, restock_eta
                FROM core_inventoryitem WHERE LOWER(item_name) = LOWER(%s)
                """,
                (item_name,),
            )
            row = cur.fetchone()
            if not row:
                return {"in_stock": False, "quantity_available": 0}
            return {
                "item_name": row["item_name"],
                "in_stock": row["quantity_available"] > 0,
                "quantity_available": row["quantity_available"],
                "restock_eta": str(row["restock_eta"]) if row["restock_eta"] else None,
            }
