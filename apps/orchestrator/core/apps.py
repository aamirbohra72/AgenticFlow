import os
import sys
import threading

from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "core"
    _consumer_started = False

    def ready(self):
        # Skip management commands that should not open a long-lived AMQP consumer
        if any(
            cmd in sys.argv
            for cmd in ("migrate", "makemigrations", "seed_demo_data", "shell", "check", "createsuperuser")
        ):
            return

        # Django autoreloader: parent has no RUN_MAIN, child has RUN_MAIN=true.
        # With --noreload there is only one process (RUN_MAIN unset) — must start there.
        using_reloader = "runserver" in sys.argv and "--noreload" not in sys.argv
        if using_reloader and os.environ.get("RUN_MAIN") != "true":
            return

        if CoreConfig._consumer_started:
            return
        CoreConfig._consumer_started = True

        from core.rabbitmq_client import consume_results_loop

        print("[orchestrator] Starting RabbitMQ result consumer thread", flush=True)
        thread = threading.Thread(
            target=consume_results_loop,
            daemon=True,
            name="rmq-result-consumer",
        )
        thread.start()
