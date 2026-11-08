# Architecture
Browser ──► Ingress (rahbar.local, ingress-nginx)
├─ / ──► Service ui ──► ui pods (nginx-unprivileged, 2 replicas)
└─ /api ──► Service api ──► api pods (FastAPI, 3-8 replicas, HPA)
├─► Service chroma ──► chroma-0 (StatefulSet + PVC)
├─► Service redis ──► redis (Deployment + PVC)
└─► Ollama on the host (embeddings + generation)

indexer Job / weekly reindex CronJob ──► Ollama (embeddings) ──► chroma (the only writer)
ConfigMap rahbar-config ──► api and indexer (one EMBED_MODEL pin for both)


Everything runs in the `rahbar` namespace. All four Services are ClusterIP; the only way
in from outside is the Ingress, which routes `/` to the ui and `/api` to the api.

## Why Chroma is a StatefulSet, not a Deployment
Chroma owns data on disk. A StatefulSet gives its pod a stable identity (`chroma-0`) and
a PVC created from `volumeClaimTemplates` that is re-attached to the same pod after every
restart or reschedule. We deleted `chroma-0` during testing and it came back with the same
volume and the same index. A Deployment treats pods as interchangeable and does not tie a
volume to an identity; with a ReadWriteOnce volume a rolling update would also try to
mount it in two pods at once. One replica, because Chroma has one writer (the indexer Job).
Redis is a Deployment with its own PVC and the `Recreate` strategy for the same RWO reason.

## Request path
1. The Ingress sends `/api/ask` to the api Service; the api validates the question
   (3-500 characters).
2. The api embeds the question with the pinned model, checks the Redis semantic cache
   (keyed by `index_version`), queries Chroma for the top 5 chunks (excluding superseded
   documents), applies the relevance floor, sends the best 3 to the model with the Answer
   JSON schema, validates, retries once, falls back if needed, and drops any citation that
   does not match a retrieved chunk.
3. Every request logs one JSON line with its request id, chunk ids and scores, and updates
   the Prometheus metrics on `/metrics`.

## Network policy (deny by default)
`k8s/base/networkpolicy.yaml` starts with `default-deny-all` (ingress and egress), then
allows only:
- DNS (UDP/TCP 53) to kube-dns, for every pod;
- ui from the ingress-nginx namespace;
- api from the ingress-nginx namespace and from ui;
- chroma from api and the indexer only;
- redis from api only (so the indexer invalidates the cache through `index_version`, not
  by touching Redis);
- api and indexer egress to Ollama on the host (`k8s/overlays/dev/netpol-ollama.yaml`).
The ui pod cannot reach chroma: `wget` from the ui pod to `chroma:8000` times out.
The cluster runs Calico; the default minikube CNI would accept these objects and ignore them.

## Security
- One ServiceAccount per workload, `automountServiceAccountToken: false` everywhere.
- `runAsNonRoot`, numeric non-root users, `readOnlyRootFilesystem: true` (with `/tmp` as
  an emptyDir where needed), `allowPrivilegeEscalation: false`, all capabilities dropped,
  `seccompProfile: RuntimeDefault`.
- Secrets are created from the command line (`make secret`); only a placeholder with
  `REPLACE_ME` is committed, and it is not listed in the kustomization.
- Retrieved text and model output are untrusted: delimited in the prompt as data,
  schema-constrained, validated with Pydantic, never passed to eval or used to build queries.

## Two deployment problems worth recording
- **Chroma crash-looped** with `expected u16 for key "PORT"`. Because the Service is named
  `chroma`, Kubernetes injected `CHROMA_PORT=tcp://10.x.x.x:8000` into the pod, and Chroma
  reads every `CHROMA_*` variable as its own config. Fix: `enableServiceLinks: false` on
  the Chroma pod.
- **Ollama on a Windows host with Docker Desktop** is not at `host.minikube.internal`
  (192.168.49.1, Docker's VM) but at `host.docker.internal` (192.168.65.254). The dev
  overlay patches `OLLAMA_URL` and the egress `ipBlock` to that address.