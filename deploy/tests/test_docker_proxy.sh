#!/usr/bin/env bash
# Starts only docker-proxy and checks its allowlist from inside the internal network (spec §4.3, §17).
set -euo pipefail
cd "$(dirname "$0")/../.."
export COMPOSE_PROJECT_NAME=hootpr-proxytest  # never touch a running dev stack
docker compose up -d --quiet-pull docker-proxy >/dev/null 2>&1
label="org.hootpr.proxytest=$$"
testnet="hootpr-proxytest-net-$$"
# shellcheck disable=SC2329  # invoked by the EXIT trap
cleanup() {
  docker ps -aq --filter "label=$label" | xargs -r docker rm -fv >/dev/null 2>&1 || true
  docker network rm "$testnet" >/dev/null 2>&1 || true
  docker compose down -v >/dev/null 2>&1 || true
}
trap cleanup EXIT
cid="$(docker compose ps -q docker-proxy)"
net="$(docker inspect -f '{{range $k, $v := .NetworkSettings.Networks}}{{$k}} {{end}}' "$cid" | awk '{print $1}')"
# wait until haproxy accepts connections
for _ in $(seq 1 20); do
  if docker run --rm --network "$net" curlimages/curl:8.10.1 -s -o /dev/null "http://docker-proxy:2375/_ping"; then break; fi
  sleep 0.5
done
code() { docker run --rm --network "$net" curlimages/curl:8.10.1 -s -o /dev/null -w '%{http_code}' -X "$1" "http://docker-proxy:2375$2"; }
fail=0
expect() {
  local got
  got="$(code "$1" "$2")"
  if [ "$got" != "$3" ]; then echo "FAIL $1 $2 -> $got (want $3)"; fail=1; else echo "ok   $1 $2 -> $got"; fi
}
# allowed: ping/version, containers, networks, exec
expect GET /_ping 200
expect GET /version 200
expect GET /containers/json 200
expect GET /networks 200
expect GET /exec/does-not-exist/json 404
# denied: images, build, volumes, system info, swarm, services, secrets, plugins, events, auth
expect GET /images/json 403
expect POST /images/create 403
expect POST /build 403
expect GET /volumes 403
expect GET /info 403
expect GET /swarm 403
expect GET /services 403
expect GET /secrets 403
expect GET /plugins 403
expect GET /events 403
expect POST /auth 403

# Phase 2: the exact calls DockerSandboxManager makes for one review (backend/app/sandbox/docker.py).
# Uses the sandbox image when built, else the already-pulled curl image (any image works: nothing is pulled).
# /work is an anonymous volume (the image's VOLUME): the only place put_archive works on a read-only rootfs.
image="${SANDBOX_IMAGE:-hootpr/sandbox:latest}"
docker image inspect "$image" >/dev/null 2>&1 || image="curlimages/curl:8.10.1"
# req METHOD PATH [JSON]: prints "<http_code> <body>"; a body of "-" sends stdin as a tar archive.
req() {
  local args=(-s -w ' %{http_code}' -X "$1" "http://docker-proxy:2375$2")
  if [ "${3:-}" = "-" ]; then
    args+=(-H 'Content-Type: application/x-tar' --data-binary @-)
    docker run --rm -i --network "$net" curlimages/curl:8.10.1 "${args[@]}"
  elif [ -n "${3:-}" ]; then
    docker run --rm --network "$net" curlimages/curl:8.10.1 "${args[@]}" -H 'Content-Type: application/json' -d "$3"
  else
    docker run --rm --network "$net" curlimages/curl:8.10.1 "${args[@]}"
  fi
}
check() {  # check LABEL WANT_CODE OUTPUT
  local got="${3##* }"
  if [ "$got" != "$2" ]; then echo "FAIL $1 -> $got (want $2): ${3% *}"; fail=1; else echo "ok   $1 -> $got"; fi
}
out="$(req POST /networks/create "{\"Name\":\"$testnet\",\"Driver\":\"bridge\",\"Labels\":{\"org.hootpr.proxytest\":\"$$\"}}")"
check "POST /networks/create" 201 "$out"
spec="{\"Image\":\"$image\",\"Entrypoint\":[\"sleep\"],\"Cmd\":[\"300\"],\"User\":\"10001:10001\",\"WorkingDir\":\"/tmp\",\"Volumes\":{\"/work\":{}},\"Labels\":{\"org.hootpr.proxytest\":\"$$\"},\"HostConfig\":{\"NetworkMode\":\"$testnet\",\"ReadonlyRootfs\":true,\"Tmpfs\":{\"/tmp\":\"rw,size=16m\"},\"Memory\":268435456,\"MemorySwap\":268435456,\"PidsLimit\":256,\"CapDrop\":[\"ALL\"],\"SecurityOpt\":[\"no-new-privileges:true\"]}}"
out="$(req POST "/containers/create?name=hootpr-proxytest-$$" "$spec")"
check "POST /containers/create" 201 "$out"
cid_new="$(printf '%s' "$out" | sed -n 's/.*"Id":"\([0-9a-f]*\)".*/\1/p')"
out="$(req POST "/containers/$cid_new/start")"
check "POST /containers/{id}/start" 204 "$out"
out="$(tar -C "$(mktemp -d)" -cf - . | req PUT "/containers/$cid_new/archive?path=/work" -)"
check "PUT /containers/{id}/archive?path=/work" 200 "$out"
out="$(req POST "/containers/$cid_new/exec" '{"Cmd":["true"],"AttachStdout":true,"AttachStderr":true}')"
check "POST /containers/{id}/exec" 201 "$out"
exec_id="$(printf '%s' "$out" | sed -n 's/.*"Id":"\([0-9a-f]*\)".*/\1/p')"
out="$(req POST "/exec/$exec_id/start" '{"Detach":false,"Tty":false}')"
check "POST /exec/{id}/start" 200 "$out"
out="$(req POST "/networks/$testnet/disconnect" "{\"Container\":\"$cid_new\",\"Force\":true}")"
check "POST /networks/{name}/disconnect" 200 "$out"
out="$(req DELETE "/containers/$cid_new?force=1&v=1")"
check "DELETE /containers/{id}?force=1&v=1" 204 "$out"
# still denied with a body: pulling/building images, creating volumes, system info
out="$(req POST "/images/create?fromImage=alpine&tag=latest")"
check "POST /images/create (pull)" 403 "$out"
out="$(req POST /build)"
check "POST /build" 403 "$out"
out="$(req POST /volumes/create '{"Name":"hootpr-proxytest"}')"
check "POST /volumes/create" 403 "$out"
out="$(req GET /info)"
check "GET /info" 403 "$out"
exit "$fail"
