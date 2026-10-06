"""Entry-point / sink detection (phase 6) across the frameworks named in spec §10.3."""

import json
import subprocess
import sys
from pathlib import Path

import pytest
from attack_surface import build_surface
from build_graph import build
from entrypoints import normalize_callee, sink_category

TOOLS = Path(__file__).resolve().parents[2] / "hootpr_tools"

FILES = {
    "flask_app.py": """
from flask import Blueprint, Flask
from flask_login import login_required

app = Flask(__name__)
bp = Blueprint("admin", __name__, url_prefix="/admin")


@app.route("/login", methods=["GET", "POST"])
def login():
    return "ok"


@bp.route("/users")
@login_required
def users():
    return "ok"


if __name__ == "__main__":
    app.run()
""",
    "shop/urls.py": """
from django.urls import include, path
from shop import views

urlpatterns = [
    path("orders/", views.order_list),
    path("orders/<int:pk>/", views.OrderDetail.as_view()),
    path("api/", include("shop.api_urls")),
]
""",
    "shop/views.py": """
from rest_framework.decorators import api_view


def order_list(request):
    return render_orders()


class OrderDetail:
    def get(self, request, pk):
        return lookup(pk)


@api_view(["POST"])
def refund(request):
    return None
""",
    "jobs.py": """
import subprocess
from celery import shared_task
import click


@shared_task
def reindex(doc_id):
    subprocess.run(["reindex", str(doc_id)])


@click.command()
def cli():
    reindex(1)
""",
    "src/main/java/com/acme/UserController.java": """
package com.acme;

@RestController
@RequestMapping("/api/users")
@PreAuthorize("hasRole('USER')")
public class UserController {
    @GetMapping("/{id}")
    public User get(@PathVariable long id) { return repo.findById(id); }

    @PostMapping(value = "/import")
    public void importUsers() { }

    @KafkaListener(topics = "user-events")
    public void onEvent(String msg) { }

    public static void main(String[] args) { }
}
""",
    "cmd/server/main.go": """
package main

import "github.com/gin-gonic/gin"

func main() {
    r := gin.Default()
    r.GET("/ping", func(c *gin.Context) { pong(c) })
    r.POST("/admin", AuthRequired(), createAdmin)
    http.HandleFunc("GET /healthz", healthz)
}
""",
    "web/app/api/users/[id]/route.ts": """
export async function GET(req: Request) { return Response.json(await load()); }
export async function DELETE(req: Request) { return new Response(null); }
function helper() {}
""",
    "web/app/(marketing)/pages/api/hello.ts": """
export default function handler(req, res) { res.json({ hi: true }); }
""",
    "web/actions.ts": """'use server'
export async function saveNote(data: FormData) { await db.insert(data); }
""",
    "web/client.js": """
import axios from "axios";
axios.get("/api/users", { params: { q: 1 } });
router.get("env");
""",
    "web/consumer.js": """
const { Worker } = require("bullmq");
new Worker("emails", async (job) => { await send(job.data); });
consumer.run({ eachMessage: async ({ message }) => handle(message) });
""",
    "infra/main.tf": """
resource "aws_security_group" "web" {
  ingress {
    cidr_blocks = ["0.0.0.0/0"]
  }
}
resource "aws_db_instance" "db" {
  publicly_accessible = true
}
""",
    "k8s/svc.yaml": """apiVersion: v1
kind: Service
spec:
  type: LoadBalancer
""",
    "docker-compose.yml": """services:
  web:
    ports:
      - "8080:80"
""",
    "Dockerfile": "FROM python:3.12\nEXPOSE 8000\n",
    ".env": "SECRET_KEY=do-not-print-me\n",
    "settings.py": "import os\nSECRET = os.environ['DJANGO_SECRET_KEY']\nDEBUG = os.getenv('DEBUG')\n",
}


def git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    for rel, text in FILES.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    git(root, "init", "-q", "-b", "main")
    git(root, "add", "-A")
    return root


def names(g: dict) -> dict[str, dict]:
    return {e["name"]: e for e in g["entry_points"]}


def test_frameworks_detected(repo: Path) -> None:
    eps = names(build(repo, [], 3000, 20000))
    # Flask: methods list, Blueprint url_prefix, login_required
    assert eps["GET/POST /login"]["framework"] == "flask"
    assert eps["GET /admin/users"]["auth"] is True
    assert eps["python flask_app.py"]["kind"] == "cli"
    # Django urls.py + CBV + DRF
    assert eps["ANY /orders/"]["framework"] == "django"
    assert "ANY /orders/<int:pk>/" in eps
    assert not any(e["path"] == "shop/urls.py" and "/api/" in e["name"] for e in eps.values())  # include()
    assert eps["POST refund"]["framework"] == "django-rest"
    # Celery + click
    assert eps["celery reindex"]["kind"] == "message"
    assert eps["click cli"]["kind"] == "cli"
    # Spring: class prefix, class-level auth, listener, main
    assert eps["GET /api/users/{id}"]["auth"] is True
    assert "POST /api/users/import" in eps
    assert eps["listener user-events"]["kind"] == "message"
    assert any(e["kind"] == "cli" and e["framework"] == "java" for e in eps.values())
    # Gin + net/http 1.22 pattern + Go main
    assert eps["GET /ping"]["framework"] == "gin" and eps["GET /ping"]["auth"] is False
    assert eps["POST /admin"]["auth"] is True
    assert "GET /healthz" in eps
    assert any(n.startswith("go main") for n in eps)
    # Next.js route handlers, pages/api, server actions
    assert eps["GET /api/users/[id]"]["framework"] == "nextjs"
    assert "DELETE /api/users/[id]" in eps
    assert "ANY /api/hello" in eps
    assert eps["server action saveNote"]["kind"] == "server_action"
    # JS consumers; HTTP clients and app settings are not routes
    assert "queue emails" in eps and "consumer eachMessage" in eps
    assert not any(e.get("route") == "/api/users" and e["path"] == "web/client.js" for e in eps.values())


def test_django_cbv_and_gin_inline_handlers_get_edges(repo: Path) -> None:
    g = build(repo, [], 3000, 20000)
    ids = {s["id"]: s["qualified_name"] for s in g["symbols"]}
    calls = {(ids[e["from"]], ids[e["to"]]) for e in g["edges"] if e["kind"] == "calls"}
    assert ("ANY /orders/<int:pk>/", "OrderDetail") in calls
    assert ("ANY /orders/", "order_list") in calls


def test_sink_categories() -> None:
    assert sink_category("subprocess.run") == "exec"
    assert sink_category("hashlib.sha256") == "crypto"
    assert sink_category("requests.post") == "network"
    assert sink_category("self.db.execute") == "db"
    assert sink_category("query") is None  # too generic without a receiver
    assert sink_category("open") == "file"
    assert sink_category("authenticate") == "auth"
    assert sink_category("format") is None
    assert normalize_callee("this . client\n.get") == "client.get"


def test_attack_surface_map(repo: Path) -> None:
    doc = build_surface(repo, 3000)
    assert doc["stats"]["http_endpoints"] >= 10
    assert doc["stats"]["unauthenticated_endpoints"] < doc["stats"]["http_endpoints"]
    rules = {(i["kind"], i["rule"]) for i in doc["iac"]}
    assert {
        ("terraform", "open-cidr"),
        ("terraform", "public-db"),
        ("kubernetes", "exposed-service"),
        ("compose", "published-port"),
        ("dockerfile", "expose"),
    } <= rules
    secrets = {(s["name"], s["source"]) for s in doc["secrets"]}
    assert ("DJANGO_SECRET_KEY", "env") in secrets and (".env", "committed_env_file") in secrets
    assert not any(s["name"] == "DEBUG" for s in doc["secrets"])
    assert "do-not-print-me" not in json.dumps(doc)
    assert doc["sinks"]["counts"]["exec"] >= 1


def test_attack_surface_cli(repo: Path) -> None:
    r = subprocess.run(
        [sys.executable, str(TOOLS / "attack_surface.py"), "--repo", str(repo)],
        capture_output=True,
        text=True,
        check=True,
    )
    assert json.loads(r.stdout)["version"] == 1
