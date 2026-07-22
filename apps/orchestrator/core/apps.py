from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "core"

    def ready(self):
        # Start background RabbitMQ result consumer only when serving requests
        import sys

        if "runserver" not in sys.argv:
            return

        import threading

        from core.rabbitmq_client import consume_results_loop

        thread = threading.Thread(target=consume_results_loop, daemon=True, name="rmq-result-consumer")
        thread.start()
