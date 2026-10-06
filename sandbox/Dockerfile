# HootPR per-job analysis sandbox (spec §4.3, §7.3). Built by `make sandbox-image`; never run by compose.
# The worker creates one short-lived, hardened container per review through docker-proxy.
# Target: linux/amd64 (t3.small), <= 3 GB. Rule DBs (semgrep, trivy, ast-grep-essentials) and tree-sitter
# grammars are baked in: the sandbox is sealed (no network) while tools run. Every version is pinned; bump
# them together and re-run `make test-sandbox`.

ARG DEBIAN_IMAGE=debian:bookworm-20260918-slim
ARG NODE_IMAGE=node:22.23.3-bookworm-slim

# --- static binaries, Go toolchain, rule/vuln DBs ------------------------------------------------------
FROM ${DEBIAN_IMAGE} AS downloads
ARG GO_VERSION=1.27.1
ARG GOLANGCI_VERSION=2.14.0
ARG GITLEAKS_VERSION=8.30.1
ARG TRIVY_VERSION=0.74.0
ARG HADOLINT_VERSION=2.15.1
ARG ACTIONLINT_VERSION=1.7.12
ARG SHELLCHECK_VERSION=0.11.0
ARG PHPSTAN_VERSION=2.2.16
ARG SWIFTLINT_VERSION=0.65.1
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl xz-utils unzip \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /dl
# Every download is a file first (curl retries cannot resume a pipe), then unpacked.
ENV CURL="curl -fsSL --retry 5 --retry-all-errors --retry-delay 3"
RUN $CURL -o go.tgz "https://go.dev/dl/go${GO_VERSION}.linux-amd64.tar.gz" \
 && tar -xzf go.tgz -C /usr/local && rm go.tgz \
 && rm -rf /usr/local/go/test /usr/local/go/api /usr/local/go/misc /usr/local/go/doc \
      /usr/local/go/pkg/tool/linux_amd64/pprof /usr/local/go/pkg/tool/linux_amd64/trace \
      /usr/local/go/pkg/tool/linux_amd64/cover /usr/local/go/pkg/tool/linux_amd64/fix \
      /usr/local/go/pkg/tool/linux_amd64/doc /usr/local/go/pkg/tool/linux_amd64/covdata \
      /usr/local/go/pkg/tool/linux_amd64/preprofile /usr/local/go/pkg/tool/linux_amd64/test2json \
      /usr/local/go/src/cmd \
 && find /usr/local/go/src -type d -name testdata -prune -exec rm -rf {} +
RUN $CURL -o golangci.tgz "https://github.com/golangci/golangci-lint/releases/download/v${GOLANGCI_VERSION}/golangci-lint-${GOLANGCI_VERSION}-linux-amd64.tar.gz" \
 && tar -xzf golangci.tgz --strip-components=1 -C /usr/local/bin "golangci-lint-${GOLANGCI_VERSION}-linux-amd64/golangci-lint" \
 && $CURL -o gitleaks.tgz "https://github.com/gitleaks/gitleaks/releases/download/v${GITLEAKS_VERSION}/gitleaks_${GITLEAKS_VERSION}_linux_x64.tar.gz" \
 && tar -xzf gitleaks.tgz -C /usr/local/bin gitleaks \
 && $CURL -o trivy.tgz "https://github.com/aquasecurity/trivy/releases/download/v${TRIVY_VERSION}/trivy_${TRIVY_VERSION}_Linux-64bit.tar.gz" \
 && tar -xzf trivy.tgz -C /usr/local/bin trivy \
 && $CURL -o /usr/local/bin/hadolint "https://github.com/hadolint/hadolint/releases/download/v${HADOLINT_VERSION}/hadolint-linux-x86_64" \
 && $CURL -o actionlint.tgz "https://github.com/rhysd/actionlint/releases/download/v${ACTIONLINT_VERSION}/actionlint_${ACTIONLINT_VERSION}_linux_amd64.tar.gz" \
 && tar -xzf actionlint.tgz -C /usr/local/bin actionlint \
 && $CURL -o shellcheck.txz "https://github.com/koalaman/shellcheck/releases/download/v${SHELLCHECK_VERSION}/shellcheck-v${SHELLCHECK_VERSION}.linux.x86_64.tar.xz" \
 && tar -xJf shellcheck.txz --strip-components=1 -C /usr/local/bin "shellcheck-v${SHELLCHECK_VERSION}/shellcheck" \
 && mkdir -p /opt/hootpr/bin \
 && $CURL -o /opt/hootpr/bin/phpstan.phar "https://github.com/phpstan/phpstan/releases/download/${PHPSTAN_VERSION}/phpstan.phar" \
 && $CURL -o swiftlint.zip "https://github.com/realm/SwiftLint/releases/download/${SWIFTLINT_VERSION}/swiftlint_linux_amd64.zip" \
 && unzip -q swiftlint.zip -d swiftlint \
 && install -m 0755 "$(find swiftlint -type f -name 'swiftlint*' | head -n1)" /usr/local/bin/swiftlint \
 && rm -rf /dl/* && chmod 0755 /usr/local/bin/* && chmod 0644 /opt/hootpr/bin/phpstan.phar
# Offline vulnerability DB + misconfiguration checks bundle (refreshed by rebuilding the image).
RUN trivy fs --cache-dir /opt/trivy-cache --download-db-only --no-progress \
 && mkdir -p /tmp/empty && trivy config --cache-dir /opt/trivy-cache --quiet /tmp/empty >/dev/null \
 && rm -rf /opt/trivy-cache/fanal
COPY semgrep-rules.txt /dl/semgrep-rules.txt
RUN mkdir -p /opt/semgrep-packs && while read -r pack; do \
      [ -z "$pack" ] && continue; \
      $CURL "https://semgrep.dev/c/${pack}" -o "/opt/semgrep-packs/$(echo "$pack" | tr '/' '_').yml"; \
    done < /dl/semgrep-rules.txt
# ast-grep-essentials: CodeRabbit's security rule pack for reviews.tools.ast_grep.essential_rules (phase-3 R17,
# plan contract C4). Only rules/<lang>/**.yml and utils/ are kept (no tests); the final stage makes them
# loadable by the pinned ast-grep. Bump the pin with
# `git ls-remote https://github.com/coderabbitai/ast-grep-essentials HEAD`.
ARG AST_GREP_ESSENTIALS_REF=73120109bf45c284d0cd8a37bdd7082e80e92e87
RUN $CURL -o essentials.tgz "https://github.com/coderabbitai/ast-grep-essentials/archive/${AST_GREP_ESSENTIALS_REF}.tar.gz" \
 && tar -xzf essentials.tgz -C /tmp \
 && mkdir -p /opt/ast-grep-essentials \
 && cp -r "/tmp/ast-grep-essentials-${AST_GREP_ESSENTIALS_REF}/rules" /opt/ast-grep-essentials/rules \
 && cp -r "/tmp/ast-grep-essentials-${AST_GREP_ESSENTIALS_REF}/utils" /opt/ast-grep-essentials/utils \
 && rm -rf essentials.tgz "/tmp/ast-grep-essentials-${AST_GREP_ESSENTIALS_REF}"

# --- Node tools (eslint + plugins, markdownlint-cli, ast-grep) ------------------------------------------
FROM ${NODE_IMAGE} AS node
COPY package.json /opt/hootpr/configs/package.json
RUN cd /opt/hootpr/configs && npm install --omit=dev --no-audit --no-fund --no-package-lock \
 && npm cache clean --force \
 && test -x node_modules/@ast-grep/cli/ast-grep && rm -rf node_modules/@ast-grep/cli-linux-x64-*

# --- the sandbox ------------------------------------------------------------------------------------------
FROM ${DEBIAN_IMAGE}
ARG SEMGREP_VERSION=1.178.0
ARG CHECKOV_VERSION=3.3.20
ARG RUFF_VERSION=0.16.9
ARG YAMLLINT_VERSION=1.38.0
ARG TSLP_VERSION=1.20.0
ARG RUBOCOP_VERSION=1.91.0
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
# HOME is the /tmp tmpfs (the worker sets the same); caches go to the /work volume (HOOTPR_WORK_CACHE).
ENV DEBIAN_FRONTEND=noninteractive PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PATH=/opt/venv/bin:/usr/local/go/bin:/opt/hootpr/configs/node_modules/.bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
    HOME=/tmp XDG_CACHE_HOME=/work/.hootpr/cache \
    HOOTPR_TRIVY_CACHE=/opt/trivy-cache HOOTPR_WORK_CACHE=/work/.hootpr \
    HOOTPR_PHPSTAN=/opt/hootpr/bin/phpstan.phar TREE_SITTER_LANGUAGE_PACK_LIBS_DIR=/opt/hootpr/grammars \
    SEMGREP_SEND_METRICS=off SEMGREP_ENABLE_VERSION_CHECK=0 \
    TRIVY_NO_PROGRESS=true TRIVY_DISABLE_VEX_NOTICE=true \
    GIT_TERMINAL_PROMPT=0 NODE_OPTIONS=--max-old-space-size=512
RUN apt-get update && apt-get install -y --no-install-recommends \
      git ca-certificates ripgrep python3 python3-venv jq ruby php-cli php-xml php-mbstring \
      ruby-dev build-essential \
 && gem install --no-document rubocop -v "${RUBOCOP_VERSION}" \
 && apt-get purge -y --auto-remove ruby-dev build-essential \
 && rm -rf /var/lib/apt/lists/* /root/.gem /var/lib/gems/*/cache /usr/share/doc/* /usr/share/man/* \
 && git config --system --add safe.directory '*'
RUN python3 -m venv /opt/venv \
 && /opt/venv/bin/pip install "semgrep==${SEMGREP_VERSION}" "checkov==${CHECKOV_VERSION}" \
      "ruff==${RUFF_VERSION}" "yamllint==${YAMLLINT_VERSION}" "tree-sitter-language-pack==${TSLP_VERSION}" \
 && /opt/venv/bin/pip uninstall -y -q pip \
 && find /opt/venv -name '__pycache__' -prune -exec rm -rf {} + \
 && find /opt/venv/lib/python3*/site-packages -mindepth 2 -maxdepth 2 -type d -name tests -prune -exec rm -rf {} +
COPY --from=downloads /usr/local/go /usr/local/go
COPY --from=downloads /usr/local/bin/ /usr/local/bin/
COPY --from=downloads /opt/hootpr/bin/ /opt/hootpr/bin/
COPY --from=downloads /opt/trivy-cache /opt/trivy-cache
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /opt/hootpr/configs/ /opt/hootpr/configs/
COPY configs/ /opt/hootpr/configs/
COPY --from=downloads /opt/semgrep-packs/ /tmp/semgrep-packs/
COPY build/merge_semgrep_rules.py /tmp/merge_semgrep_rules.py
RUN mkdir -p /opt/hootpr/configs/semgrep \
 && python3 /tmp/merge_semgrep_rules.py /opt/hootpr/configs/semgrep/hootpr.yml /tmp/semgrep-packs/*.yml \
 && rm -rf /tmp/semgrep-packs /tmp/merge_semgrep_rules.py
# Upstream util ids use characters the pinned ast-grep rejects (one bad file breaks the whole scan): rename
# them, drop anything ast-grep still cannot load, and require a usable pack. Readable by uid 10001.
COPY --from=downloads /opt/ast-grep-essentials/ /tmp/ast-grep-essentials/
COPY build/sanitize_ast_grep_rules.py /tmp/sanitize_ast_grep_rules.py
RUN python3 /tmp/sanitize_ast_grep_rules.py /tmp/ast-grep-essentials /opt/hootpr/ast-grep/essentials ast-grep \
 && test "$(find /opt/hootpr/ast-grep/essentials/rules -name '*.yml' | wc -l)" -ge 100 \
 && chmod -R a+rX,go-w /opt/hootpr/ast-grep \
 && rm -rf /tmp/ast-grep-essentials /tmp/sanitize_ast_grep_rules.py
COPY hootpr_tools/ /opt/hootpr/tools/
COPY build/bake_grammars.py /tmp/bake_grammars.py
RUN python3 /tmp/bake_grammars.py /opt/hootpr/tools /opt/hootpr/grammars \
 && rm -rf /tmp/bake_grammars.py /opt/hootpr/tools/__pycache__
RUN groupadd --gid 10001 sandbox && useradd --uid 10001 --gid 10001 --no-create-home --home-dir /tmp sandbox \
 && mkdir -p /work && chown 10001:10001 /work
# /work is an anonymous volume: writable scratch on disk (not tmpfs), removed with the container.
VOLUME ["/work"]
USER 10001:10001
WORKDIR /work
LABEL org.hootpr.sandbox.version="phase3"
CMD ["sleep", "infinity"]
