# RAHBAR

# RAHBAR: grounded question answering over FAST-NUCES rules, on Kubernetes

[![ci](https://github.com/RoshailAhmad/Rahbar/actions/workflows/ci.yml/badge.svg?branch=dev)](https://github.com/RoshailAhmad/Rahbar/actions/workflows/ci.yml)
[![cd](https://github.com/RoshailAhmad/Rahbar/actions/workflows/cd.yml/badge.svg)](https://github.com/RoshailAhmad/Rahbar/actions/workflows/cd.yml)

A student asks whether they can register after failing a prerequisite; the answer is in a
clause of a PDF that a newer PDF has superseded. RAHBAR answers questions about FAST-NUCES
academic rules **only from the university's own documents**, cites the exact document and
section, prefers the current version of a policy over the repealed one, and says
"the documents do not cover this" instead of inventing an answer. It runs on Kubernetes:
an indexer Job writes a Chroma vector store, a 3-replica FastAPI service reads it, Redis
caches answers, and CI fails the build when retrieval quality drops.

![RAHBAR answering with a citation](docs/evidence/<screenshot>.png)

## Architecture
Browser ─► Ingress (rahbar.local)
├─ / ─► ui (nginx, 2 pods)
└─ /api ─► api (FastAPI, 3-8 pods, HPA)
├─► chroma-0 (StatefulSet + PVC) vector store, read-only for the api
├─► redis (Deployment + PVC) semantic cache
└─► Ollama on the host nomic-embed-text + qwen2.5:1.5b
indexer Job / weekly CronJob ─► Ollama (embeddings) ─► chroma (the only writer)

Details: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) · design decisions: [docs/adr/](docs/adr/) ·
pipeline and measurements: [docs/PIPELINE.md](docs/PIPELINE.md) · corpus:
[docs/CORPUS.md](docs/CORPUS.md) · evaluation: [eval/results.json](eval/results.json).

**Measured (baseline):** recall@3 0.81, recall@5 0.96, citation validity 1.0, abstention
correctness 1.0, about 19 s per answer on a laptop CPU.

## From a clean clone to an answered question
Needs Docker, minikube, kubectl, make and Ollama (on Windows, run the commands in WSL 2).

```bash
git clone https://github.com/RoshailAhmad/Rahbar.git && cd Rahbar

# 1. cluster with Calico (NetworkPolicy), metrics-server and ingress
make cluster

# 2. Ollama on the host, listening on all interfaces, with the pinned models
OLLAMA_HOST=0.0.0.0 ollama serve          # in its own terminal
ollama pull nomic-embed-text
ollama pull qwen2.5:1.5b

# 3. the corpus (public PDFs, not committed: see corpus/MANIFEST.md for URLs and SHA-256)
make install && make fetch

# 4. build the three images and load them into minikube
make images

# 5. only if LLM_PROVIDER=hosted: the key, created from the command line, never a file
#    export LLM_API_KEY=... && make secret
#    (runs: kubectl create secret generic rahbar-secret -n rahbar --from-literal=LLM_API_KEY="$LLM_API_KEY")

# 6. apply (namespace, config, chroma, redis, api, ui, ingress, netpol, hpa, indexer Job),
#    waiting for the indexer to finish before the api becomes ready
make apply

# 7. ask
make ask Q="What CGPA puts a student on academic warning?"
```
Apply order inside `make apply`: `kubectl apply -k k8s/overlays/dev`, then wait for
chroma, redis, `job/indexer` (complete), api and ui. Re-index without a redeploy:
`make index` (`kubectl create job --from=cronjob/reindex ...`).

**Windows / Docker Desktop notes.** The minikube IP is not reachable from Windows; use
`kubectl port-forward -n ingress-nginx svc/ingress-nginx-controller 8081:80 --address 0.0.0.0`
and `make ask INGRESS_IP=127.0.0.1:8081 ...`, and add `127.0.0.1 rahbar.local` to the hosts
file for the browser (http://rahbar.local:8081). Ollama on the Windows host is at
`host.docker.internal` (192.168.65.254), not `host.minikube.internal`; the dev overlay
sets `OLLAMA_URL` and the egress NetworkPolicy to that address.

## API
| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/api/ask` | `{"question": "..."}` (3-500 chars) → answer, citations, `answered_from_context`, confidence, retrieved chunks, `cached` |
| GET | `/healthz` | liveness: the process is alive (touches no dependency) |
| GET | `/readyz` | readiness: Chroma reachable, collection non-empty, embedding model matches, Redis reachable; 503 naming the failure otherwise |
| GET | `/metrics` | Prometheus: requests, latency, retrieval and generation latency, cache hits/misses, abstentions, fallbacks, tokens in/out |

## CI/CD
- `ci.yml` (pull requests to main, pushes to dev): ruff + mypy, pytest with coverage
  ≥ 60%, `kustomize build | kubeconform -strict`, image builds, Trivy (fails on fixable
  HIGH/CRITICAL), and **e2e-eval**: a kind cluster indexes the fixture corpus and
  `eval/run_eval.py` enforces the gate (recall@5 within 5 points of baseline, 100%
  abstention, citation validity ≥ 95%).
- `cd.yml` (pushes to main): test → build-push to Docker Hub tagged with the commit SHA
  (never `:latest`) → deploy to an ephemeral kind cluster, `kubectl rollout status`, smoke
  test through the Ingress.
- `main` is protected: pull request, one approval, all CI checks required.

## Team and AI use
Roshail: Kubernetes, CI/CD, architecture docs. Mehak: corpus, indexer, API pipeline,
evaluation, pipeline docs. AI assistance is disclosed in [docs/AI-USAGE.md](docs/AI-USAGE.md).
