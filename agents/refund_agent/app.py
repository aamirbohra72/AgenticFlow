import logging
import os
import sys
import threading

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import common.env  # noqa: F401
from flask import Flask, jsonify

from consumer import main as start_consumer_loop

logging.basicConfig(level=logging.INFO)
app = Flask(__name__)


@app.route("/health")
def health():
    return jsonify({"status": "ok", "agent": "refund_agent"})


if __name__ == "__main__":
    thread = threading.Thread(target=start_consumer_loop, daemon=True)
    thread.start()
    port = int(os.getenv("REFUND_AGENT_PORT", "5003"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
