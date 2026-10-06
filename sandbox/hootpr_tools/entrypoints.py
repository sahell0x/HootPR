"""Entry-point and sensitive-sink detection for the code graph (spec §10.3, phase 6).

Imported by build_graph.py INSIDE the sandbox (stdlib only; tree-sitter nodes come from the caller).
Best effort and name based, like the rest of the graph: it finds

- HTTP routes: FastAPI / Flask / aiohttp / DRF decorators (+ APIRouter / Blueprint prefixes),
  Django ``urls.py``, Express / Koa / Fastify / Hono registrations, Next.js ``app/**/route.ts`` and
  ``pages/api/**``, Spring ``@*Mapping`` (+ class ``@RequestMapping`` prefix), Gin / Echo / chi /
  net/http registrations;
- CLI mains (``if __name__ == "__main__"``, ``require.main === module``, Go/Java ``main``,
  click/typer commands) and message handlers (Celery/Dramatiq/Faust, Kafka/Rabbit/JMS/SQS
  listeners, JS consumers);
- sinks: calls into auth, crypto, command execution, files, databases and the network.

Handlers registered by a call (``app.get("/x", (req, res) => ...)``) have no symbol of their own, so
the builder turns the registration into a *synthetic* ``entry`` symbol that scopes the calls inside
it and calls the named handler arguments.
"""

from __future__ import annotations

import posixpath
import re
from dataclasses import dataclass, field

HTTP_VERBS = ("GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS")
JS_ROUTE_METHODS = {"get", "post", "put", "delete", "patch", "all", "options", "head", "del"}
GO_ROUTE_METHODS = {
    "GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS", "Any", "Handle", "HandleFunc",
    "Get", "Post", "Put", "Delete", "Patch", "Head", "Options", "Match",
}  # fmt: skip
# Receivers that are HTTP *clients*, never servers (``axios.get("/api/x", fn)`` is not a route).
CLIENT_NAMES = {
    "axios", "http", "https", "fetch", "request", "client", "api", "$http", "superagent",
    "supertest", "got", "ky", "agent", "httpClient", "apiClient", "cy", "page", "$",
}  # fmt: skip
JS_HANDLER_TYPES = {
    "arrow_function", "function_expression", "function", "identifier", "member_expression",
    "call_expression", "generator_function",
}  # fmt: skip
GO_HANDLER_TYPES = {"func_literal", "identifier", "selector_expression", "call_expression"}
AUTH_RX = re.compile(
    r"(?i)(auth(?!or)|login_required|log_in_required|permission|jwt|token_required|"
    r"requires?_?(user|role|scope|login|admin)|protect|guard|verify_?token|current_?user|"
    r"is_?authenticated|ensure_?logged|secured|roles_?allowed|preauthorize|session_required|"
    r"admin_required|staff_member_required|api_?key)"
)
PUBLIC_RX = re.compile(r"(?i)(permitall|allowany|anonymous|public_route|skip_?auth)")
_STR = re.compile(r"""[rbfu]{0,2}(["'`])((?:\\.|(?!\1).)*)\1""", re.S)

# (category, pattern over the normalized callee text) — first match wins.
SINKS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "exec",
        re.compile(
            r"^(subprocess\.\w+|os\.(system|popen|exec\w*|spawn\w*)|eval|exec|execSync|execFile\w*|"
            r"spawnSync|spawn|child_process\.\w+|exec\.Command\w*|Runtime\.getRuntime\(\)\.exec|"
            r"ProcessBuilder|vm\.runIn\w+|new Function|Function|shell_exec|system|popen|passthru)$"
        ),
    ),
    (
        "crypto",
        re.compile(
            r"(^|\.)(hashlib\.\w+|hmac\.\w+|bcrypt\.\w+|argon2\.\w+|scrypt\w*|pbkdf2\w*|Fernet|"
            r"AES\.new|createHash|createHmac|createCipher\w*|createDecipher\w*|createSign|"
            r"createVerify|randomBytes|jwt\.(encode|decode|sign|verify)|jsonwebtoken\.\w+|"
            r"MessageDigest\.getInstance|Cipher\.getInstance|KeyGenerator\.\w+|secrets\.\w+|"
            r"md5|sha1|sha256|sha512|encrypt|decrypt|hashpw|checkpw|gensalt)$"
        ),
    ),
    (
        "auth",
        re.compile(
            r"(?i)(^|\.)(\w*authenticat\w*|\w*authoriz\w*|login\w*|logout\w*|\w*check_password|"
            r"\w*verify_password|set_password|make_password|\w*verify_token|decode_token|"
            r"has_perms?|check_permissions?|require_role|get_current_user|current_user|"
            r"passport\.\w+|signIn\w*|signOut|getServerSession|getSession|compare_digest)$"
        ),
    ),
    (
        "network",
        re.compile(
            r"^(requests\.\w+|httpx\.\w+|urllib\.request\.\w+|urllib3\.\w+|urlopen|"
            r"aiohttp\.\w+|ClientSession|fetch|axios(\.\w+)?|got(\.\w+)?|ky(\.\w+)?|"
            r"http\.(get|request|Get|Post|PostForm|Head|NewRequest\w*)|https\.(get|request)|"
            r"superagent\.\w+|new RestTemplate|RestTemplate|WebClient\.\w+|HttpClient\.\w+|"
            r"socket\.\w+|net\.Dial\w*|net\.connect|smtplib\.\w+|boto3\.client|boto3\.resource)$"
        ),
    ),
    (
        "db",
        re.compile(
            r"(^|\.)(execute|executemany|executescript|raw|rawQuery|query|Query|QueryRow|"
            r"QueryContext|Exec|ExecContext|createQuery|createNativeQuery|prepareStatement|"
            r"\$queryRaw\w*|\$executeRaw\w*|text)$"
        ),
    ),
    (
        "file",
        re.compile(
            r"^(open|io\.open|os\.(remove|unlink|rename|makedirs|rmdir|chmod)|shutil\.\w+|"
            r"fs\.\w+|fsPromises\.\w+|os\.(Open|OpenFile|Create|WriteFile|ReadFile|Remove\w*)|"
            r"ioutil\.\w+|Files\.\w+|send_file|send_from_directory|res\.sendFile|res\.download|"
            r"tarfile\.open|zipfile\.ZipFile|pickle\.loads?|yaml\.load|FileResponse)$"
        ),
    ),
)
_DB_NEEDS_RECEIVER = {"text", "raw", "query", "Query", "execute", "Exec"}


def normalize_callee(text: str) -> str:
    t = re.sub(r"\s+", "", text)
    t = re.sub(r"^(this|self|cls)\.", "", t)
    t = re.sub(r"<[^<>()]*>", "", t)  # generics
    return t[:120]


def sink_category(callee: str) -> str | None:
    c = normalize_callee(callee)
    if not c:
        return None
    for cat, rx in SINKS:
        if rx.search(c):
            if cat == "db" and "." not in c and c in _DB_NEEDS_RECEIVER:
                return None  # a bare ``query(...)`` / ``text(...)`` is too generic
            return cat
    return None


def sensitive_name(name: str) -> str | None:
    """auth / crypto for a symbol whose own name says what it does."""
    if re.search(r"(?i)(authenticat|authoriz|login|logout|password|passwd|credential|session|"
                 r"permission|jwt|token|oauth|saml|csrf|acl|rbac)", name):  # fmt: skip
        return "auth"
    if re.search(r"(?i)(encrypt|decrypt|cipher|hash|hmac|signature|sign_|_sign|verify_sig|"
                 r"crypto|nonce|salt|keypair|private_key)", name):  # fmt: skip
        return "crypto"
    return None


def _strings(text: str) -> list[str]:
    return [m.group(2) for m in _STR.finditer(text)]


def _join(prefix: str, route: str) -> str:
    if not prefix:
        return route
    return "/" + "/".join(p for p in (prefix.strip("/"), route.strip("/")) if p)


def _last_ident(text: str) -> str:
    found = re.findall(r"[A-Za-z_$][\w$]*", text)
    return found[-1] if found else ""


@dataclass
class Synthetic:
    """A registration call that becomes an ``entry`` symbol scoping its inline handler."""

    name: str
    entry: dict
    handler_refs: list[str] = field(default_factory=list)


class Detector:
    def __init__(self, lang: str, path: str, raw: bytes) -> None:
        self.lang, self.path, self.raw = lang, path, raw
        self.text = raw.decode(errors="replace")
        low = self.text.lower()
        self.prefixes: dict[str, str] = {}
        if lang == "python":
            for m in re.finditer(r"(\w+)\s*=\s*(?:\w+\.)?(APIRouter|Blueprint)\s*\(([^)]*)\)", self.text, re.S):
                pm = re.search(r"(?:url_)?prefix\s*=\s*[rbf]?[\"']([^\"']*)[\"']", m.group(3))
                if pm:
                    self.prefixes[m.group(1)] = pm.group(1)
            self.framework = next(
                (f for f in ("fastapi", "flask", "aiohttp", "sanic", "quart", "starlette", "django")
                 if re.search(rf"^\s*(from|import)\s+{f}\b", self.text, re.M)),
                "python",
            )  # fmt: skip
        elif lang in ("javascript", "typescript", "tsx"):
            self.framework = next(
                (f for f in ("express", "fastify", "koa", "hono", "restify")
                 if re.search(rf"""(from\s+|require\s*\(\s*)["'](@?{f}[\w/-]*)["']""", self.text)),
                "node",
            )  # fmt: skip
        elif lang == "go":
            self.framework = next(
                (name for key, name in (("gin-gonic/gin", "gin"), ("labstack/echo", "echo"),
                 ("go-chi/chi", "chi"), ("gofiber/fiber", "fiber"), ("gorilla/mux", "gorilla"))
                 if key in self.text),
                "net/http",
            )  # fmt: skip
        elif lang in ("java", "kotlin"):
            self.framework = "spring" if "springframework" in low else lang
        else:
            self.framework = lang
        self.use_server = bool(re.match(r"""\s*(//[^\n]*\n\s*)*["']use server["']""", self.text))
        dm = re.search(r"export\s+default\s+(?:async\s+)?(?:function\s*\*?\s*)?([A-Za-z_$][\w$]*)",
                       self.text)  # fmt: skip
        self.default_export = dm.group(1) if dm else None

    # --- helpers ------------------------------------------------------------------------------
    def t(self, node) -> str:  # type: ignore[no-untyped-def]
        return self.raw[node.start_byte : node.end_byte].decode(errors="replace")

    def _entry(self, kind: str, name: str, **kw: object) -> dict:
        e = {"kind": kind, "framework": self.framework, "method": None, "route": None, "name": name,
             "auth": False, "auth_evidence": None}  # fmt: skip
        e.update(kw)
        return e

    def _first_string(self, node) -> str | None:  # type: ignore[no-untyped-def]
        if node is None:
            return None
        if node.type in ("string", "string_literal", "interpreted_string_literal",
                         "raw_string_literal", "template_string"):  # fmt: skip
            s = _strings(self.t(node))
            return s[0] if s else self.t(node).strip("`\"'")
        return None

    # --- synthetic registrations --------------------------------------------------------------
    def synthetic(self, node) -> Synthetic | None:  # type: ignore[no-untyped-def]
        t = node.type
        if t == "if_statement":
            cond = node.child_by_field_name("condition")
            ct = self.t(cond) if cond is not None else ""
            if self.lang == "python" and re.search(r"__name__\s*==\s*[\"']__main__[\"']", ct):
                return Synthetic("__main__", self._entry("cli", f"python {self.path}", framework="python"))
            if self.lang in ("javascript", "typescript", "tsx") and re.search(r"require\.main\s*===?\s*module", ct):
                return Synthetic("__main__", self._entry("cli", f"node {self.path}", framework="node"))
            return None
        if self.lang == "python" and t == "call":
            return self._django_url(node)
        if self.lang in ("javascript", "typescript", "tsx") and t in ("call_expression", "new_expression"):
            return self._js_call(node)
        if self.lang == "go" and t == "call_expression":
            return self._go_call(node)
        return None

    def _django_url(self, node) -> Synthetic | None:  # type: ignore[no-untyped-def]
        if posixpath.basename(self.path) != "urls.py":
            return None
        fn = node.child_by_field_name("function")
        if fn is None or self.t(fn) not in ("path", "re_path", "url"):
            return None
        args = node.child_by_field_name("arguments")
        items = [a for a in (args.named_children if args is not None else []) if a.type != "keyword_argument"]
        if len(items) < 2:
            return None
        route = self._first_string(items[0])
        view = self.t(items[1])
        if route is None or view.startswith("include("):
            return None
        m = re.search(r"([A-Za-z_]\w*)\s*\.\s*as_view", view)
        ref = m.group(1) if m else _last_ident(view)
        route = route if route.startswith(("/", "^")) else "/" + route
        entry = self._entry("http", f"ANY {route}", method="ANY", route=route, framework="django")
        return Synthetic(f"ANY {route}", entry, [ref] if ref else [])

    def _handler_refs(self, args: list, handler_types: set[str]) -> tuple[list[str], bool, str | None]:  # type: ignore[type-arg]
        refs: list[str] = []
        auth, evidence = False, None
        for i, a in enumerate(args):
            txt = self.t(a)
            if a.type in ("identifier", "member_expression", "selector_expression"):
                refs.append(_last_ident(txt))
            elif a.type == "call_expression":
                fn = a.child_by_field_name("function")
                if fn is not None:
                    refs.append(_last_ident(self.t(fn)))
            if i < len(args) - 1 and a.type in handler_types:
                head = txt.split("(", 1)[0] if a.type == "call_expression" else txt
                if AUTH_RX.search(head[:120]):
                    auth, evidence = True, head[:80]
        return [r for r in refs if r], auth, evidence

    def _js_call(self, node) -> Synthetic | None:  # type: ignore[no-untyped-def]
        if node.type == "new_expression":
            ctor = node.child_by_field_name("constructor")
            args_node = node.child_by_field_name("arguments")
            args = args_node.named_children if args_node is not None else []
            if ctor is not None and self.t(ctor) == "Worker" and args and self._first_string(args[0]):
                q = self._first_string(args[0])
                return Synthetic(f"worker {q}", self._entry("message", f"queue {q}", framework="bullmq"))
            return None
        fn = node.child_by_field_name("function")
        if fn is None or fn.type != "member_expression":
            return None
        prop_n, obj = fn.child_by_field_name("property"), fn.child_by_field_name("object")
        if prop_n is None or obj is None:
            return None
        prop = self.t(prop_n)
        args_node = node.child_by_field_name("arguments")
        args = [a for a in (args_node.named_children if args_node is not None else []) if a.type != "comment"]
        receiver = _last_ident(self.t(obj).split("(")[0]) if obj.type != "call_expression" else ""
        route: str | None = None
        handlers = args
        if prop.lower() in JS_ROUTE_METHODS:
            if obj.type == "call_expression":  # router.route("/x").get(handler)
                inner = obj.child_by_field_name("function")
                inner_args = obj.child_by_field_name("arguments")
                if (inner is not None and inner.type == "member_expression"
                        and self.t(inner).endswith(".route") and inner_args is not None
                        and inner_args.named_children):  # fmt: skip
                    route = self._first_string(inner_args.named_children[0])
            elif len(args) >= 2 and receiver not in CLIENT_NAMES:
                route = self._first_string(args[0])
                handlers = args[1:]
            if route is not None and (route.startswith("/") or route == "*") and handlers \
                    and handlers[-1].type in JS_HANDLER_TYPES:  # fmt: skip
                method = "ANY" if prop.lower() == "all" else ("DELETE" if prop == "del" else prop.upper())
                refs, auth, ev = self._handler_refs(handlers, JS_HANDLER_TYPES)
                name = f"{method} {route}"
                return Synthetic(name, self._entry("http", name, method=method, route=route,
                                                   auth=auth, auth_evidence=ev), refs)  # fmt: skip
            return None
        fn_types = ("arrow_function", "function_expression", "function", "identifier", "member_expression")
        first = self._first_string(args[0]) if args else None
        if prop in ("on", "once") and first in ("message", "data") and args[-1].type in fn_types:
            refs, _, _ = self._handler_refs(args[1:], JS_HANDLER_TYPES)
            return Synthetic(f"on {first}", self._entry("message", f"{receiver or 'consumer'} on '{first}'"), refs)
        if prop == "subscribe" and first and len(args) >= 2:
            refs, _, _ = self._handler_refs(args[1:], JS_HANDLER_TYPES)
            return Synthetic(f"subscribe {first}", self._entry("message", f"subscribe '{first}'"), refs)
        if prop == "process" and args and args[-1].type in fn_types[:3] and re.search(r"(?i)queue", receiver):
            return Synthetic(f"process {receiver}", self._entry("message", f"{receiver}.process"))
        if prop == "run" and args and "eachMessage" in self.t(args[0]):
            return Synthetic(f"run {receiver}", self._entry("message", f"{receiver} eachMessage", framework="kafkajs"))
        return None

    def _go_call(self, node) -> Synthetic | None:  # type: ignore[no-untyped-def]
        fn = node.child_by_field_name("function")
        if fn is None or fn.type != "selector_expression":
            return None
        field_n = fn.child_by_field_name("field")
        if field_n is None or self.t(field_n) not in GO_ROUTE_METHODS:
            return None
        verb = self.t(field_n)
        args_node = node.child_by_field_name("arguments")
        args = args_node.named_children if args_node is not None else []
        if len(args) < 2:
            return None
        route = self._first_string(args[0])
        method = verb.upper() if verb.upper() in HTTP_VERBS else "ANY"
        if route is not None and verb in ("Handle", "HandleFunc", "Match"):  # "GET /path" (1.22+)
            m = re.match(r"^(GET|POST|PUT|DELETE|PATCH|HEAD|OPTIONS)\s+(/.*)$", route)
            if m:
                method, route = m.group(1), m.group(2)
        if route is None or not route.startswith("/") or args[-1].type not in GO_HANDLER_TYPES:
            return None
        refs, auth, ev = self._handler_refs(args[1:], GO_HANDLER_TYPES)
        name = f"{method} {route}"
        return Synthetic(name, self._entry("http", name, method=method, route=route, auth=auth,
                                           auth_evidence=ev), refs)  # fmt: skip

    # --- definitions --------------------------------------------------------------------------
    def for_definition(self, node, name: str, kind: str) -> dict | None:  # type: ignore[no-untyped-def]
        if self.lang == "python":
            return self._py_def(node, name, kind)
        if self.lang in ("javascript", "typescript", "tsx"):
            return self._js_def(node, name, kind)
        if self.lang == "java":
            return self._java_def(node, name, kind)
        if (
            self.lang == "go"
            and kind == "function"
            and name == "main"
            and re.search(r"^\s*package\s+main\b", self.text, re.M)
        ):
            return self._entry("cli", f"go main ({posixpath.dirname(self.path) or '.'})", framework="go")
        if self.lang == "kotlin" and name == "main" and kind == "function":
            return self._entry("cli", f"kotlin main ({self.path})")
        return None

    def _py_def(self, node, name: str, kind: str) -> dict | None:  # type: ignore[no-untyped-def]
        parent = node.parent
        decos = [self.t(c).lstrip("@").strip() for c in (parent.named_children if parent is not None
                 and parent.type == "decorated_definition" else []) if c.type == "decorator"]  # fmt: skip
        if not decos:
            return None
        entry: dict | None = None
        auth, evidence = False, None
        for d in decos:
            head = d.split("(", 1)[0]
            m = re.match(r"([\w.]+?)\.(get|post|put|delete|patch|options|head|route|api_route|websocket|view)$", head)
            if m and entry is None:
                strings = _strings(d)
                route = next((s for s in strings if s.startswith("/") or s == ""), None)
                if route is None:
                    continue
                verb = m.group(2)
                if verb in ("route", "api_route", "view"):
                    mm = re.search(r"methods\s*=\s*[\[(]([^\])]*)", d)
                    methods = [s.upper() for s in _strings(mm.group(1))] if mm else []
                    method = "/".join(methods) if methods else ("ANY" if verb == "view" else "GET")
                else:
                    method = "WS" if verb == "websocket" else verb.upper()
                route = _join(self.prefixes.get(m.group(1), ""), route) or "/"
                entry = self._entry("http", f"{method} {route}", method=method, route=route)
                dm = re.search(r"dependencies\s*=\s*\[([^\]]*)\]", d)
                if dm and AUTH_RX.search(dm.group(1)):
                    auth, evidence = True, dm.group(1).strip()[:80]
                continue
            if re.match(r"(?:[\w.]+\.)?api_view$", head) and entry is None:
                methods = [s.upper() for s in _strings(d)] or ["GET"]
                method = "/".join(methods)
                entry = self._entry("http", f"{method} {name}", method=method, framework="django-rest")
                continue
            if re.match(r"(?:[\w.]+\.)?(task|shared_task|periodic_task|actor|agent|subscriber|"
                        r"on_message|consumer|job|listener)$", head) and entry is None:  # fmt: skip
                fw = next((f for f in ("celery", "dramatiq", "faust", "rq", "kombu") if f in self.text), "python")
                entry = self._entry("message", f"{fw} {name}", framework=fw)
                continue
            if re.match(r"(?:[\w.]+\.)?(command|group)$", head) and entry is None:
                fw = "typer" if "typer" in self.text else ("click" if "click" in self.text else "python")
                entry = self._entry("cli", f"{fw} {name}", framework=fw)
                continue
            if PUBLIC_RX.search(head):
                continue
            if AUTH_RX.search(head):
                auth, evidence = True, "@" + head[:80]
        if entry is None:
            return None
        params = node.child_by_field_name("parameters")
        ptxt = self.t(params) if params is not None else ""
        for pm in re.finditer(r"(Depends|Security)\s*\(\s*([\w.]*)", ptxt):
            if pm.group(1) == "Security" or AUTH_RX.search(pm.group(2)):
                auth, evidence = True, f"{pm.group(1)}({pm.group(2)})"
                break
        if auth:
            entry["auth"], entry["auth_evidence"] = True, evidence
        return entry

    def _exported(self, node) -> bool:  # type: ignore[no-untyped-def]
        p, depth = node.parent, 0
        while p is not None and depth < 3:
            if p.type == "export_statement":
                return True
            p, depth = p.parent, depth + 1
        return False

    def _js_def(self, node, name: str, kind: str) -> dict | None:  # type: ignore[no-untyped-def]
        if kind not in ("function", "method"):
            return None
        p = self.path
        app = re.search(r"(?:^|/)app/(.*?)/?route\.(?:ts|js|tsx|jsx|mjs)$", p)
        if app is not None and name in HTTP_VERBS and self._exported(node):
            segs = [s for s in app.group(1).split("/") if s and not s.startswith(("(", "@"))]
            route = "/" + "/".join(segs)
            return self._entry("http", f"{name} {route}", method=name, route=route, framework="nextjs")
        pages = re.search(r"(?:^|/)pages/(api/.*)\.(?:ts|js|tsx|jsx)$", p)
        if pages is not None and (name == self.default_export or (
                self._exported(node) and "default" in self.t(node.parent)[:40])):  # fmt: skip
            route = "/" + re.sub(r"/index$", "", pages.group(1))
            return self._entry("http", f"ANY {route}", method="ANY", route=route, framework="nextjs")
        if self.use_server and self._exported(node):
            return self._entry("server_action", f"server action {name}", framework="nextjs")
        return None

    def _java_def(self, node, name: str, kind: str) -> dict | None:  # type: ignore[no-untyped-def]
        if kind != "method":
            return None
        mods = next((c for c in node.children if c.type == "modifiers"), None)
        mtxt = self.t(mods) if mods is not None else ""
        cls = node.parent.parent if node.parent is not None else None
        cmods = next((c for c in cls.children if c.type == "modifiers"), None) if cls is not None else None
        ctxt = self.t(cmods) if cmods is not None else ""
        entry: dict | None = None
        m = re.search(r"@(Get|Post|Put|Delete|Patch|Request)Mapping\b\s*(\((.*?)\))?", mtxt, re.S)
        if m:
            args = m.group(3) or ""
            vm = re.search(r"(?:value|path)\s*=\s*\{?\s*\"([^\"]*)\"", args)
            strings = _strings(args)
            route = vm.group(1) if vm else (strings[0] if strings and "=" not in args.split('"')[0] else "")
            method = m.group(1).upper()
            if method == "REQUEST":
                rm = re.findall(r"RequestMethod\.(\w+)", args)
                method = "/".join(rm) if rm else "ANY"
            cm = re.search(r"@RequestMapping\s*\((.*?)\)", ctxt, re.S)
            prefix = ""
            if cm:
                cvm = re.search(r"(?:value|path)\s*=\s*\{?\s*\"([^\"]*)\"", cm.group(1))
                cs = _strings(cm.group(1))
                prefix = cvm.group(1) if cvm else (cs[0] if cs else "")
            route = _join(prefix, route) or "/"
            entry = self._entry("http", f"{method} {route}", method=method, route=route)
        elif re.search(r"@(KafkaListener|RabbitListener|JmsListener|SqsListener|StreamListener|"
                       r"EventListener|MessageMapping)\b", mtxt):  # fmt: skip
            topics = _strings(mtxt)
            entry = self._entry("message", f"listener {topics[0] if topics else name}")
        elif name == "main" and "static" in mtxt:
            return self._entry("cli", f"java main ({self.path})", framework="java")
        if entry is None:
            return None
        both = mtxt + "\n" + ctxt
        am = re.search(r"@(PreAuthorize|PostAuthorize|Secured|RolesAllowed)\b[^\n@]*", both)
        if am and not re.search(r"@PermitAll\b", mtxt):
            entry["auth"], entry["auth_evidence"] = True, am.group(0).strip()[:80]
        return entry
