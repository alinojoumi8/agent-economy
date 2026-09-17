"""Exercise real Prometheus -> Alertmanager -> disposable webhook delivery.

Only evaluation/grouping delays are accelerated. Production alert expressions
and receiver routing are used. No public notification endpoint is contacted.
"""
from __future__ import annotations

import argparse
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from pathlib import Path
import shutil
import subprocess
import time
from uuid import uuid4

import yaml


def fixture(directory):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            down = (directory / "down").exists()
            self.send_response(503 if down else 200)
            self.send_header("Content-Type", "text/plain; version=0.0.4")
            self.end_headers()
            self.wfile.write(f"agent_economy_catalog_backup_last_success_seconds {time.time()}\n".encode())

        def do_POST(self):
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size <= 100000:
                self.send_error(413)
                return
            payload = json.loads(self.rfile.read(size))
            with (directory / "received.jsonl").open("a") as stream:
                stream.write(json.dumps(payload) + "\n")
            self.send_response(200)
            self.end_headers()

        def log_message(self, *args):
            pass

    HTTPServer(("0.0.0.0", 9081), Handler).serve_forever()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", action="store_true")
    parser.add_argument("--image", default="ae-ops-test:local")
    parser.add_argument("--output", type=Path, default=Path("tmp/alert-drill"))
    args = parser.parse_args(argv)
    output = args.output.resolve()
    if args.fixture:
        fixture(output)
        return 0
    from scripts.docker_preflight import ensure_ready
    docker = shutil.which("docker")
    if not docker or ensure_ready(docker, wait_seconds=0)["status"] != "ready":
        raise SystemExit("Docker is unavailable; no resources changed")
    output.mkdir(parents=True, exist_ok=True)
    if (output / "received.jsonl").exists():
        raise SystemExit("Use a fresh output directory")
    root = Path(__file__).resolve().parents[1]
    deployment = root / "deploy/hostinger"
    rules = yaml.safe_load((deployment / "storage-alerts.yml").read_text())
    for group in rules["groups"]:
        for rule in group["rules"]:
            rule["for"] = "0s"
    (output / "rules.yml").write_text(yaml.safe_dump(rules))
    alerts = yaml.safe_load((deployment / "alertmanager.yml").read_text())
    alerts["route"].update(group_wait="1s", group_interval="1s", repeat_interval="1m")
    alerts["receivers"][0]["webhook_configs"][0]["url_file"] = "/evidence/url"
    (output / "alerts.yml").write_text(yaml.safe_dump(alerts))
    (output / "url").write_text("http://fixture:9081/alerts\n")
    config = yaml.safe_load((deployment / "prometheus.yml").read_text())
    config["global"] = {"scrape_interval": "1s", "evaluation_interval": "1s"}
    config["rule_files"] = ["/evidence/rules.yml"]
    for job in config["scrape_configs"]:
        job["static_configs"] = [{"targets": ["alertmanager:9093" if job["job_name"] == "alertmanager" else "fixture:9081"]}]
    (output / "prometheus.yml").write_text(yaml.safe_dump(config))
    prefix = "ae-alert-drill-" + uuid4().hex[:12]
    containers = []
    network_created = False
    with (output / "drill.log").open("w") as log:
        def run(*command, timeout=120, check=True):
            result = subprocess.run([docker, *command], stdout=log, stderr=log, timeout=timeout)
            if check and result.returncode:
                raise RuntimeError("Alert drill failed; inspect private drill.log")

        def start(alias, image, *command, entrypoint=None):
            name = prefix + "-" + alias
            containers.append(name)
            options = ["run", "-d", "--name", name, "--network", prefix, "--network-alias", alias,
                "--mount", f"type=bind,source={output},target=/evidence",
                "--mount", f"type=bind,source={root},target=/app,readonly"]
            if entrypoint:
                options += ["--entrypoint", entrypoint]
            run(*options, image, *command)

        def wait_status(status):
            deadline = time.monotonic() + 75
            while time.monotonic() < deadline:
                path = output / "received.jsonl"
                if path.exists():
                    for line in path.read_text().splitlines():
                        try:
                            payload = json.loads(line)
                        except ValueError:
                            continue
                        if any(a["labels"]["alertname"] == "HostedAppUnavailable" and a["status"] == status for a in payload["alerts"]):
                            return
                time.sleep(1)
            raise RuntimeError(f"No {status} notification received")

        try:
            run("run", "--rm", "--mount", f"type=bind,source={output},target=/evidence,readonly",
                "--entrypoint", "/bin/promtool", "prom/prometheus:v3.5.0", "check", "rules", "/evidence/rules.yml")
            run("run", "--rm", "--mount", f"type=bind,source={output},target=/evidence,readonly",
                "--entrypoint", "/bin/amtool", "prom/alertmanager:v0.28.1", "check-config", "/evidence/alerts.yml")
            run("network", "create", prefix)
            network_created = True
            start("fixture", args.image, "-m", "scripts.alert_delivery_drill", "--fixture", "--output", "/evidence", entrypoint="python")
            start("alertmanager", "prom/alertmanager:v0.28.1", "--config.file=/evidence/alerts.yml", "--cluster.listen-address=")
            start("prometheus", "prom/prometheus:v3.5.0", "--config.file=/evidence/prometheus.yml", "--storage.tsdb.retention.time=1h")
            time.sleep(5)
            (output / "down").write_text("disposable failure injection")
            wait_status("firing")
            (output / "down").unlink()
            wait_status("resolved")
            receipt = {"status": "passed", "firing_delivered": True, "resolved_delivered": True,
                "scope": "local-disposable-webhook", "timers_accelerated": True}
            (output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
            print(json.dumps(receipt))
        finally:
            for name in reversed(containers):
                run("rm", "--force", "--volumes", name, check=False, timeout=45)
            if network_created:
                run("network", "rm", prefix, check=False, timeout=45)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
