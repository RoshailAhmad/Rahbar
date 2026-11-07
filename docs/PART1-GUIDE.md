# Part 1: Kubernetes and infrastructure (Roshail)

Everything in this zip goes into the repository root, on top of the starter kit.
Commit it in small pieces, from your own GitHub account, on `dev` (step 2). Delete this file before you submit, or keep it as team notes.

## What is in this drop

| File | What it is |
| --- | --- |
| `api/Dockerfile`, `api/.dockerignore` | Two-stage Python 3.12 image, UID 10001, exec-form uvicorn with a 20 s graceful drain |
| `indexer/Dockerfile`, `indexer/.dockerignore` | Same pattern, plus tesseract and poppler for OCR; the corpus is baked in at `/corpus`, the CI fixtures at `/fixtures` |
| `ui/Dockerfile`, `ui/.dockerignore` | `nginx-unprivileged`, UID 101, port 8080 |
| `k8s/base/*` | Namespace, 5 ServiceAccounts, ConfigMap, Secret placeholder (not applied), Chroma StatefulSet with a PVC, Redis Deployment with a PVC, api (3 replicas, 3 probes, maxSurge 1 / maxUnavailable 0, preStop), ui, 4 ClusterIP Services, Ingress, HPA 3 to 8, PDB, indexer Job, weekly CronJob, 8 NetworkPolicies |
| `k8s/components/stubs/` | Week-1 switch: stub retriever, stub LLM, `EMBED_MODEL=dummy-768`, indexer runs `--dummy` |
| `k8s/overlays/dev/` | minikube: base + stubs + egress to Ollama on your laptop |
| `k8s/overlays/prod/` | What CI validates and CD deploys; CD sets the images to the commit SHA |
| `k8s/overlays/ci/` | For the e2e-eval job: fixture corpus, stub LLM, `:ci` images |
| `Makefile` | New targets: `stage-corpus`, `images` (now stages the corpus first), `apply` (waits in the right order), `status`, `evidence` |
| `.gitignore` | Also ignores the staged corpus in `indexer/corpus/` and `indexer/fixtures/` |

Already verified: all three overlays build and pass `kubeconform -strict`. Every Part 1 line of `scripts/check_submission.py` (sections G and I) is `ok`. The images were NOT test-built (no Docker Hub access where they were written), so step 4 is the first real build.

---

## Step 1. Tools (once)

On Windows, do all of this inside WSL 2 (Ubuntu). You need: Docker Desktop with WSL integration on, `minikube`, `kubectl`, `kustomize` (optional: `kubectl apply -k` has it built in), `make`, Python 3.12 and Ollama.

```bash
minikube version && kubectl version --client && docker ps
```

## Step 2. Repository and branches (do this with Mehak, before anything else)

1. One of you unzips `rahbar-starter.zip`, runs `git init`, commits it as `chore: starter kit`, and pushes to a new GitHub repo.
2. Add the other person as a collaborator. Each of you sets your own identity:
   `git config user.name "Your Name"` and `git config user.email "the email on your GitHub account"`.
3. Create `dev`: `git checkout -b dev && git push -u origin dev`.
4. Protect `main` (Settings → Branches → Add rule for `main`): require a pull request, require 1 approval, require status checks (add the CI jobs once `ci.yml` exists), and block force pushes.
   **Screenshot this page → `docs/evidence/branch-protection.png`.**
5. From now on: work on `dev` or a feature branch, open PRs into `main`, and the other person approves.

Commit messages use the conventional prefixes the checker counts (`feat:`, `fix:`, `docs:`, `build:`, `ci:`, `chore:`). Commit after every step below, not once at the end.

## Step 3. Drop in the files

Unzip `rahbar-part1.zip` into the repo root (it overwrites `Makefile` and `.gitignore` on purpose). Then commit in pieces, for example:

```bash
git add api/Dockerfile api/.dockerignore             && git commit -m "build(api): add non-root two-stage Dockerfile"
git add indexer/Dockerfile indexer/.dockerignore     && git commit -m "build(indexer): add Dockerfile with OCR deps and baked corpus"
git add ui/Dockerfile ui/.dockerignore               && git commit -m "build(ui): add nginx-unprivileged Dockerfile"
git add Makefile .gitignore                          && git commit -m "build: stage corpus before image builds, add apply/status/evidence targets"
git add k8s/base/namespace.yaml k8s/base/serviceaccounts.yaml && git commit -m "feat(k8s): namespace and per-workload service accounts"
git add k8s/base/configmap.yaml k8s/base/secret.placeholder.yaml && git commit -m "feat(k8s): configmap with the embedding pin, secret placeholder"
git add k8s/base/chroma-statefulset.yaml             && git commit -m "feat(k8s): chroma statefulset with volumeClaimTemplates"
git add k8s/base/redis.yaml                          && git commit -m "feat(k8s): redis cache deployment with pvc"
git add k8s/base/api-deployment.yaml k8s/base/pdb.yaml && git commit -m "feat(k8s): api deployment with three probes and zero-downtime rollout"
git add k8s/base/ui-deployment.yaml                  && git commit -m "feat(k8s): ui deployment"
git add k8s/base/services.yaml k8s/base/ingress.yaml && git commit -m "feat(k8s): clusterip services and ingress"
git add k8s/base/indexer-job.yaml k8s/base/reindex-cronjob.yaml && git commit -m "feat(k8s): indexer job and weekly reindex cronjob"
git add k8s/base/hpa.yaml                            && git commit -m "feat(k8s): hpa 3-8 on cpu"
git add k8s/base/networkpolicy.yaml                  && git commit -m "feat(k8s): default-deny network policies"
git add k8s/base/kustomization.yaml k8s/components k8s/overlays && git commit -m "feat(k8s): kustomize base, stubs component, dev/prod/ci overlays"
git push
```

## Step 4. Cluster, Ollama, images

```bash
make cluster                       # minikube with Calico + metrics-server + ingress
```

Calico matters: without it, NetworkPolicies are accepted and then silently ignored.

Ollama (you don't need it for week-1 stubs, but set it up now):

```bash
OLLAMA_HOST=0.0.0.0 ollama serve   # its own terminal; must listen on all interfaces
ollama pull llama3.2:3b
ollama pull nomic-embed-text
```

Check the host IP the cluster sees, and put it in `k8s/overlays/dev/netpol-ollama.yaml` if it is not `192.168.49.1`:

```bash
minikube ssh "grep host.minikube.internal /etc/hosts"
```

Build and load the images:

```bash
make images                        # stages the corpus, builds 3 images, minikube image load
```

If a build fails, fix it and commit as `fix(...)`. A failure here is the first time these Dockerfiles meet a real Docker, so it's possible.

## Step 5. Deploy (week-1 stub mode)

```bash
make apply                         # applies k8s/overlays/dev, waits for chroma, redis, the indexer Job, api, ui
make status
```

Expected: `chroma-0`, 1 `redis`, 3 `api`, 2 `ui` pods Running and READY, and the `indexer` Job `Complete`.

Ask through the Ingress:

```bash
make ask Q="What CGPA puts a student on academic warning?"
# macOS/Windows docker driver: run `minikube tunnel` in another terminal, then
make ask INGRESS_IP=127.0.0.1 Q="..."
```

For the browser, add `rahbar.local` to your hosts file (pointing to `minikube ip`, or `127.0.0.1` with the tunnel) and open http://rahbar.local.

If something is not Running, use the handout's order: `kubectl get pods -n rahbar` → `kubectl describe pod <pod> -n rahbar` (read Events) → `kubectl logs <pod> -n rahbar [--previous]`.

**Known risk, Chroma.** It runs here as UID 1000 with a read-only root filesystem. If `chroma-0` crash-loops with a permission or read-only error in its logs, set `readOnlyRootFilesystem: false` on the Chroma container only. Then write one line about it in `docs/ARCHITECTURE.md`: what failed, and that the data volume is still the only writable path.

## Step 6. Demonstrations and evidence (`docs/evidence/`)

Save each piece of output to a file or take a screenshot. The checker wants at least 5 evidence files.

**a. Resources from real usage (4.5).** Ask a few questions, run the reindex once, then:

```bash
make evidence                      # writes kubectl-top.txt, get-endpoints.txt, get-hpa.txt, get-pods.txt
kubectl top pods -n rahbar --containers     # run this WHILE the indexer is running, for its peak
```

Then edit the `requests`/`limits` in the manifests so each one is justified by these numbers. Rule of thumb: request ≈ normal usage, memory limit ≈ peak + 30–50%. Commit as `perf(k8s): set requests/limits from kubectl top`.

**b. HPA reads a real number, not `<unknown>`:** `kubectl get hpa -n rahbar` → `get-hpa.txt`.

**c. Scaling and endpoints (4.6):**

```bash
kubectl scale deployment/api --replicas=4 -n rahbar
kubectl get endpoints api -n rahbar        # 4 IPs; the Service was never touched
```

The HPA will pull it back toward 3, which is fine to mention.

**d. Rollout and undo (4.6).** Make a visible change: edit the `<title>` or heading in `ui/index.html`, then:

```bash
docker build -t rahbar-ui:v2 ui && minikube image load rahbar-ui:v2
kubectl set image deployment/ui ui=rahbar-ui:v2 -n rahbar
kubectl rollout status deployment/ui -n rahbar      # screenshot, plus the page showing v2
kubectl rollout undo deployment/ui -n rahbar
kubectl rollout status deployment/ui -n rahbar      # screenshot, plus the page back to v1
```

Do the same for the api once Mehak has a visible change (for example a version field).

**e. Delete a pod, nothing breaks:**

```bash
kubectl delete $(kubectl get pod -n rahbar -l app=api -o name | head -1) -n rahbar   # ONE api pod
make ask Q="..."                   # still answers
kubectl delete pod chroma-0 -n rahbar     # comes back as chroma-0 with the same PVC; the index survives
```

**f. NetworkPolicy works:** the ui must not reach chroma.

```bash
UI=$(kubectl get pod -n rahbar -l app=ui -o name | head -1)
kubectl exec -n rahbar $UI -- wget -qO- -T 3 http://chroma:8000/api/v2/heartbeat   # must time out
API=$(kubectl get pod -n rahbar -l app=api -o name | head -1)
kubectl exec -n rahbar $API -- python -c "import urllib.request;print(urllib.request.urlopen('http://chroma:8000/api/v2/heartbeat').read())"   # must work
```

**g. Re-index with no redeploy:** `make index` (it runs `kubectl create job --from=cronjob/reindex ...`), then `kubectl get pods -n rahbar` to show the api pods kept their age.

**h. Embedding-pin demo (4.4), once Mehak's `/readyz` check exists.** Delete the `components:` lines from `k8s/overlays/dev/kustomization.yaml` (this switches to the real model and pipeline), apply, and do NOT re-index:

```bash
kubectl apply -k k8s/overlays/dev
kubectl rollout restart deployment/api -n rahbar
kubectl get pods -n rahbar -l app=api      # 0/1 READY, screenshot
kubectl logs -n rahbar <api-pod> | grep -i mismatch   # the log line naming the conflict
```

Then re-index (`make index`) and watch them turn 1/1. Note: `kubectl apply` refuses to change the existing `indexer` Job (Jobs are immutable). Run `kubectl delete job indexer -n rahbar` first if apply complains.

## Step 7. What Part 2 (Mehak) must match

Send Mehak this list. These are the places where her code and your manifests have to agree:

1. **`/readyz`** must do the real checks: Chroma reachable, collection non-empty, Redis reachable, embedding model equals `EMBED_MODEL`. Until then, readiness lies and demos (h) and the indexer-ordering guarantees don't hold.
2. **ConfigMap keys already provided:** `REDIS_HOST`, `REDIS_PORT`, `REDIS_URL`, `RELEVANCE_FLOOR`, `CACHE_THRESHOLD`, plus the starter's keys. Read them in `api/app/config.py` / `indexer/pipeline/config.py`. Tune the floor and threshold values with data and update them here.
3. **Cache invalidation:** the NetworkPolicy only lets the api reach Redis (the handout says "redis from api only"), so the indexer cannot flush Redis directly. Have the indexer write an index version (for example a timestamp) into the Chroma collection metadata, and have the api include it in cache keys or flush when it changes.
4. **Corpus:** documents are baked into the indexer image. `make stage-corpus` copies `corpus/raw/` into the build context, so after `make fetch`, rebuild with `make images`. Mehak documents this choice in `docs/PIPELINE.md`.
5. **The api writes only to `/tmp`** (read-only root filesystem). Any library cache must go there; `HOME=/tmp` is already set.

## Step 8. Your docs (write these in your own words)

These are graded on your reasoning, and you'll need to defend them in a viva, so write them yourself. Points to cover:

- **`docs/adr/0001-indexer-as-job.md`** (the first file the marker reads). Cover the four failures of indexing at API startup:
  - three writers racing on one PVC
  - a re-index on every restart
  - readiness that either lies or gets the pod killed
  - no re-index without a redeploy

  Then the decision: a Job is the only writer, the api only reads, and readiness waits for a non-empty collection. Name the files: `k8s/base/indexer-job.yaml`, `reindex-cronjob.yaml`, and the readiness probe in `api-deployment.yaml`.
- **`docs/ARCHITECTURE.md`:** an architecture diagram, and why Chroma is a StatefulSet. A stable identity (`chroma-0`) means the same PVC from `volumeClaimTemplates` is re-attached after a restart; a Deployment's pods are interchangeable and don't own a volume. Also cover the request path (Ingress → ui / api → chroma + redis), the NetworkPolicy allow-list, and the security context.
- **`docs/ENGINEERING-NOTES.md`**, questions 1–4 (yours; 5–7 are shared). Point to file and line numbers:
  - Q1: the indexer Job and the api manifest
  - Q2: the probes in `api-deployment.yaml`
  - Q3: `hpa.yaml` (CPU-based scaling measures idle CPU while the api waits on the LLM; scale on in-flight requests via custom metrics instead)
  - Q4: your `kubectl top` numbers vs the indexer limit, and exit code 137 (OOMKilled)
- **README section:** the exact apply order (`make cluster` → Ollama → `make images` → `make secret` if hosted → `make apply` → `make ask`), and the `kubectl create secret` line.
- **`docs/AI-USAGE.md`:** state that Claude drafted the Dockerfiles, manifests, Makefile targets and this guide, and what you changed after testing (for example the Ollama IP, resource numbers, any Chroma fix).

## Step 9. Before you hand off to Part 3

```bash
kustomize build k8s/overlays/prod | kubeconform -strict -summary   # CI's manifests job runs exactly this
make check                                                         # sections G and I should stay ok
```

The CI/CD people need the `prod` and `ci` overlays (already here). `cd.yml` sets the image tags with `kustomize edit set image ...:${{ github.sha }}` inside `k8s/overlays/prod`.
