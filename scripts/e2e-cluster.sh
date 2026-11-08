#!/usr/bin/env bash
# Bring RAHBAR up on the kind cluster of a GitHub runner, used by ci.yml (e2e-eval)
# and cd.yml (deploy). Usage: scripts/e2e-cluster.sh <overlay>   (ci | ephemeral)
#
# 1. Ollama on the runner, listening on all interfaces, with the pinned embedding model.
# 2. The overlay's OLLAMA_HOST_IP placeholder becomes the kind network's gateway.
# 3. ingress-nginx for kind, then the overlay; wait for the indexer Job, then the rollouts.
# 4. A port-forward to the ingress controller on 127.0.0.1:8081 for the eval / smoke test.
set -euo pipefail
OVERLAY=${1:?usage: e2e-cluster.sh <overlay>}
NS=rahbar

echo "::group::Ollama on the runner (container, published on 0.0.0.0:11434)"
OLLAMA_IMG=ollama/ollama:0.5.7
docker pull "$OLLAMA_IMG" || { OLLAMA_IMG=ollama/ollama:latest; docker pull "$OLLAMA_IMG"; }
docker run -d --name ollama -p 11434:11434 "$OLLAMA_IMG"
for _ in $(seq 1 60); do curl -sf http://localhost:11434 >/dev/null && break; sleep 1; done
docker exec ollama ollama pull nomic-embed-text
echo "::endgroup::"

GW=$(docker network inspect kind -f '{{range .IPAM.Config}}{{.Gateway}} {{end}}' \
     | tr ' ' '\n' | grep -E '^[0-9]+\.' | head -1)
echo "kind gateway (Ollama for the pods): $GW"
docker exec kind-control-plane curl -sf "http://$GW:11434" || {
  echo "the kind node cannot reach Ollama at $GW:11434"; exit 1; }
sed -i "s#OLLAMA_HOST_IP#$GW#" "k8s/overlays/$OVERLAY/kustomization.yaml"

echo "::group::ingress-nginx"
kubectl label node --all ingress-ready=true --overwrite
kubectl apply -f https://raw.githubusercontent.com/kubernetes/ingress-nginx/controller-v1.12.1/deploy/static/provider/kind/deploy.yaml
kubectl wait -n ingress-nginx --for=condition=complete job --all --timeout=180s
kubectl wait -n ingress-nginx --for=condition=ready pod \
  -l app.kubernetes.io/component=controller --timeout=240s
echo "::endgroup::"

echo "::group::RAHBAR ($OVERLAY overlay)"
for attempt in 1 2 3 4 5; do   # the ingress admission webhook can lag a few seconds
  kubectl apply -k "k8s/overlays/$OVERLAY" && break
  echo "apply failed (attempt $attempt), retrying"; sleep 10
done
if ! kubectl wait --for=condition=complete job/indexer -n "$NS" --timeout=900s; then
  kubectl get pods -n "$NS"; kubectl logs job/indexer -n "$NS" --tail=50; exit 1
fi
kubectl logs job/indexer -n "$NS" --tail=1
kubectl rollout status statefulset/chroma -n "$NS" --timeout=180s
kubectl rollout status deployment/redis -n "$NS" --timeout=180s
kubectl rollout status deployment/api -n "$NS" --timeout=300s
kubectl rollout status deployment/ui -n "$NS" --timeout=180s
kubectl get pods -n "$NS" -o wide
echo "::endgroup::"

kubectl port-forward -n ingress-nginx svc/ingress-nginx-controller 8081:80 > /tmp/port-forward.log 2>&1 &
for _ in $(seq 1 30); do
  curl -sf -H "Host: rahbar.local" http://127.0.0.1:8081/ >/dev/null && break; sleep 2
done
echo "RAHBAR is up behind the Ingress at http://127.0.0.1:8081 (Host: rahbar.local)"
