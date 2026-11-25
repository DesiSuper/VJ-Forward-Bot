"""Minimal HTTP health service for container and platform probes."""

from __future__ import annotations

from flask import Flask, jsonify

app = Flask(__name__)
app.config["JSON_SORT_KEYS"] = False


@app.get("/")
def index():
    return jsonify(
        service="Forword Bot",
        status="running",
        health="/healthz",
    )


@app.get("/healthz")
def healthcheck():
    """Liveness check; intentionally does not disclose runtime secrets."""
    return jsonify(status="ok"), 200


if __name__ == "__main__":
    import os

    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "8000")))
