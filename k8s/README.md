# RAHBAR on Kubernetes: from a fresh cluster to a working pipeline

## 1. Cluster
```bash
minikube start --driver=docker --cni=calico --memory=5120 --cpus=4
minikube addons enable metrics-server
minikube addons enable ingress
minikube addons enable storage-provisioner     # creates the PVCs; without it they stay Pending
minikube addons enable default-storageclass
```
Give minikube at least **5 GiB**. At 3 GiB, ingestion plus an eval run froze the whole node:
API-server TLS timeouts, then evicted pods. You can raise the limit on a running cluster
without a restart:
`docker update --memory 5g --memory-swap 6g minikube`.

## 2. Images and manifests
```bash
make images                       # build api, indexer, ui and load them into minikube
make eval-image                   # build the eval Job image (rahbar-eval:dev)
kubectl apply -k k8s/overlays/dev
kubectl get pvc -n rahbar         # data-chroma-0, redis-data and data-lake must be Bound
```

## 3. The data lake (PVC `data-lake`, mounted at /data)
| Folder | Holds |
| --- | --- |
| /data/incoming | new documents waiting for ingestion |
| /data/lake | documents that passed verification, plus `_registry.json` (hash, version, family, status) |
| /data/quarantine | documents that failed verification (not indexed) |
| /data/archive | superseded versions, kept for rollback |
| /data/reports | one verification report per ingestion run (`.json` + `.md`) |
| /data/results | evaluation result files and gate decisions |
| /data/traces | one JSON line per query (`traces-YYYYMMDD.jsonl`) |

Put documents into `incoming` through the data-shell pod. Copy only the documents,
not READMEs or scripts:
```bash
kubectl apply -f k8s/tools/data-shell.yaml
kubectl wait --for=condition=Ready pod/data-shell -n rahbar
for f in <folder>/*.{pdf,md,html}; do kubectl cp "$f" rahbar/data-shell:/data/incoming/$(basename "$f"); done
```
To delete, archive or restore a document, write `/data/incoming/_requests.json`, e.g.
`[{"action": "archive", "doc_id": "fee-structure-page"}]`. The next ingestion run applies it.

## 4. Ingestion: verify, update the lake, sync the index (Part A)
```bash
kubectl create job -n rahbar --from=cronjob/reindex ingest-$(date +%H%M)
kubectl logs -n rahbar -f job/ingest-<HHMM>
kubectl exec -n rahbar data-shell -- sh -c 'cat $(ls -t /data/reports/*.md | head -1)'
```
The log ends with `index sync finished`, which gives the counts: unchanged, added,
replaced, deleted, `chunks_embedded`, and whether `index_version` was bumped. Running it
again on an unchanged lake gives `chunks_embedded: 0` in about 10 s. The CronJob
`reindex` runs the same thing weekly.

## 5. Evaluation Job and release gate (Parts B and C)
```bash
kubectl delete job -n rahbar eval --ignore-not-found
sed 's/value: "job"/value: "<label>"/' k8s/eval-job.yaml | kubectl apply -f -
kubectl logs -n rahbar -f job/eval
kubectl cp rahbar/data-shell:/data/results ./eval/results
```
- The Job runs `suite.py` (module, component and end-to-end levels) and then `gate.py`
  against `/data/results/baseline.json`.
- Its exit code is the gate's: if the gate fails, the Job fails.
- Thresholds live in the ConfigMap `gate-config`. To change one, run
  `kubectl edit configmap -n rahbar gate-config` and re-run the Job.
- To evaluate the candidate instead, set `EVAL_API` to `http://api-candidate:8000`.
- For the typo noise test, add `EVAL_GOLDEN=/eval/golden_typos.jsonl`.

## 6. Candidate release (Part C, F3)
```bash
kubectl apply -f k8s/candidate/networkpolicy-candidate.yaml
kubectl apply -f k8s/candidate/index-candidate.yaml        # collection rahbar_c250, chunk size 250
kubectl logs -n rahbar -f job/index-candidate
kubectl apply -f k8s/candidate/api-candidate.yaml          # 1 replica + Service api-candidate
# evaluate it (section 5 with EVAL_API=http://api-candidate:8000), then only if the gate passes:
kubectl set env -n rahbar deployment/api CHROMA_COLLECTION=rahbar_c250
kubectl rollout status -n rahbar deployment/api
kubectl rollout undo -n rahbar deployment/api               # back to the previous collection
```
Every trace records `collection` and `index_version`, so after an undo a trace shows
which version answered.

## 7. Traces and monitoring (Part D)
```bash
kubectl exec -n rahbar deploy/api -- python -m app.trace_tool <trace_id>     # one query
kubectl exec -n rahbar deploy/api -- python -m app.trace_summary --since 1h  # a window
```
The summary reports the top-1 similarity distribution, abstention, cache hit and
fallback rates, p50 and p95 latency per stage, injections flagged per rail, and the
collections used. Prometheus metrics are at `/metrics`.

## 8. Resources
```bash
kubectl top pods -n rahbar
kubectl top node
```
Chroma needs a memory limit of at least 2Gi. It was OOMKilled at 1Gi during an eval run,
which turned every eval answer into a connection error. Keep the api HPA at one replica
on a laptop while ingesting.
