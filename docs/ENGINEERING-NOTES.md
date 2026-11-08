# Engineering notes

## 1. Indexing in API startup: what breaks with 3 replicas and one Chroma volume?
Three things break. (a) Three api pods start together and all write to the one Chroma
collection on one ReadWriteOnce PVC: three writers, each halfway through a different
document, leave an index no single run produced. (b) Every restart, rolling update or
OOMKill re-runs extraction, OCR and embedding: our real index took 801 s (about 13 min,
`indexer finished ... "seconds": 801.2` in the Job log), so every rollout would cost 13
minutes per pod. (c) Readiness lies or the pod dies: either the pod reports ready on an
empty collection, or it takes 13 min and the probes kill it halfway.

What prevents it: indexing is a Job, the only writer. `k8s/base/indexer-job.yaml` line 7
`kind: Job`, line 14 `backoffLimit: 4`, line 21 `restartPolicy: OnFailure`; the weekly
`reindex-cronjob.yaml` uses the same image. The api only reads, and its readiness probe
(`k8s/base/api-deployment.yaml` lines 66-68, path `/readyz`) keeps it out of the Service
until the collection is non-empty. See docs/adr/0001-indexer-as-job.md.

## 2. Readiness and liveness swapped, Chroma slow for 90 seconds: what happens?
Our liveness probe (`api-deployment.yaml` lines 58-60) hits `/healthz`, which touches
nothing; readiness (lines 66-68) hits `/readyz`, which checks Chroma, the collection and
Redis. Swapped, liveness would depend on Chroma: with `periodSeconds: 20` and
`failureThreshold: 3`, after about 60 s of slow Chroma the kubelet kills all three api
containers at once. They restart, the startup probe waits, Chroma is still slow, and they
are killed again: a restart storm. The service is fully down although only one
dependency was slow, and restarting the api fixes nothing. With the probes the right way
round, the pods fail readiness, leave the Service endpoints without restarting, and come
back by themselves within one readiness period (10 s) after Chroma recovers.
`maxUnavailable: 0` (line 17) means a rollout never removes a ready pod before its
replacement is ready.

## 3. What does a CPU-based HPA measure on a generation service, and what should scale it?
`k8s/base/hpa.yaml` scales on CPU utilisation (line 24, `averageUtilization: 70`,
min 3 replicas at line 16), computed as usage / `requests.cpu`. But an api pod spends
12 to 46 s per question waiting on Ollama (eval/results.json, per_question seconds), and
waiting on a socket costs almost no CPU. So under load the requests queue while CPU
stays near idle, and the HPA does not scale: it measures the wrong thing.
The right signal is concurrency or latency: in-flight requests per pod, or the p95 of
`rahbar_request_seconds` / `rahbar_generation_seconds`, which we already expose on
`/metrics`. To use it we would need Prometheus scraping the pods and an adapter
(prometheus-adapter, or KEDA) exposing that series to the HPA as a custom metric.
Generation itself is the real bottleneck, so the honest fix is also more Ollama capacity:
scaling api pods in front of one laptop's Ollama only lengthens Ollama's queue.

## 4. The indexer's peak memory, its limit, the margin, and the exit code when it is wrong
`kubectl top pods` during the real index showed the indexer peaking at about 1438 Mi
(docs/evidence/kubectl-top-real-index.txt), while OCR rendered pages of the two scanned
PDFs and the embeddings were collected. The limit is `memory: 2Gi`
(`k8s/base/indexer-job.yaml` line 45; request 512Mi at line 42), so the margin is
2048 - 1438 = 610 Mi, about 42% above the peak. If the limit were below the peak, the
kernel would kill the container: status OOMKilled, exit code 137, and with
`restartPolicy: OnFailure` the Job would retry up to `backoffLimit: 4` times and fail
each time, a CrashLoopBackOff that only the memory limit can fix.

## 5. recall@5 by question type: where is it worst, and why?
From `eval/results.json` (baseline: 400/50 chunks, TOP_K 5, nomic-embed-text):

| Question type | recall@3 | recall@5 |
| --- | --- | --- |
| exact (q11 clause 1.21, q12 tuition fee) | **0.50** | 1.00 |
| ordinary (8 questions) | 0.81 | 0.94 |
| version (q09 attendance, q10 repeats) | 1.00 | 1.00 |
| injection (q15) | 1.00 | 1.00 |
| **overall** | **0.81** | **0.96** |

**Worst: exact-term questions, at k=3.** q11 ("What does clause 1.21 of the academic rules
require?") has recall@3 = 0 and recall@5 = 1: the right chunk is retrieved, but only in
4th or 5th place. Its top hits were "Preamble" and "Code Of Conduct" chunks. q05 (the B+
grade points) shows the same pattern (0 at k=3, 1 at k=5). Among ordinary questions, q03
stays at 0.5 even at k=5: it has two relevant sections and only one is retrieved.

**Why embeddings struggle there.** A dense embedding represents what a passage is *about*,
not its exact tokens. "1.21", "B+" or "3.33" carry almost no meaning to the model, so a
question that is mostly a clause number lands near every chunk about academic rules in
general. Two details of our corpus make it worse: the attendance clause sits in a chunk
our chunker labelled with a table-of-contents line ("9 Policy on Retake Examination 31"),
so its heading does not help; and the prospectus restates the same rules with different
clause numbers (attendance is clause 1 there, 1.21 in the handbook), which adds
near-duplicate competitors.

**The technique from the RAG lecture that addresses it: hybrid retrieval.** Run a keyword
(BM25) search beside the vector search and merge the two rankings (e.g. reciprocal rank
fusion): BM25 matches the literal "1.21" and "B+" that the embedding blurs. A reranker over
the top 10-20 candidates, and a chunker that skips table-of-contents lines, would help too.
We also measured the opposite direction: bigger chunks (600/80) dropped overall recall@5
to 0.81 and recall@3 to 0.65, because one large chunk dilutes the specific clause; the CI
gate failed that run.

## 6. EMBED_MODEL changed on the API only: what does your system do?
We watched this happen. The index was built with `embed_model: dummy-768` (the week-1
dummy index) while the ConfigMap was switched to `nomic-embed-text`. After
`kubectl rollout restart deployment/api`, every new api pod stayed at 0/1 READY: `/readyz`
compares the collection's `embed_model` metadata with its own EMBED_MODEL and returns
503, logging `embedding model mismatch: refusing to become ready` with both values
(`api/app/routes/health.py` lines 73 and 79). Because of `maxUnavailable: 0`, the old
pods kept serving, so users saw no outage. After the real index was built, the same pods
turned 1/1 on their own.
Without the guardrail: each question would be embedded with one model and compared with
vectors from another. Vectors from different models are not comparable, so retrieval
returns unrelated passages with no error anywhere, and the system confidently answers
from the wrong evidence.

## 7. The failure that cost us more than an hour
**Symptom.** The first real indexer run crashed after 12 minutes of OCR, at the embedding
stage, with `httpx.ConnectTimeout` on `POST /api/embed`.

**What we wrongly believed.** That Ollama was reachable, because
`minikube ssh "curl -s http://host.minikube.internal:11434"` printed "Ollama is running".

**What told us the truth.** `kubectl get networkpolicy -n rahbar` did not list
`egress-to-ollama-host` at all. Re-running
`kubectl apply -k k8s/overlays/dev 2>&1 | grep -i invalid` showed
`Invalid value: "<YOUR-IP>/32": must be a valid CIDR`: a placeholder had been committed
into `k8s/overlays/dev/netpol-ollama.yaml`. `kubectl apply -k` applied every other object
and rejected only that one, so default-deny blocked the pod's egress. The `minikube ssh`
test had passed because the node is not subject to NetworkPolicy; the pod is.

**The second half.** With the CIDR fixed to 192.168.49.1, a test from inside an api pod
(`kubectl exec ... python -c "urllib.request.urlopen('http://host.minikube.internal:11434')"`)
returned `Connection refused`. On Docker Desktop, 192.168.49.1 is Docker's own VM, not
the Windows machine where Ollama runs.
`minikube ssh "getent hosts host.docker.internal"` gave 192.168.65.254, the real host;
we pointed `OLLAMA_URL` and the egress `ipBlock` at it in the dev overlay.

**What we do differently.** Read the output of `kubectl apply` instead of assuming it all
applied, and test connectivity from a pod, not from the node.