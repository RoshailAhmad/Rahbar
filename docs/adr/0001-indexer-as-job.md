# ADR 0001: The indexer is a Job; the API only reads

## Status
Accepted · 2026-11-08

## Context
The api runs 3 replicas (an HPA allows 3 to 8) behind one Service. The index lives in one
Chroma StatefulSet with a single ReadWriteOnce PVC. Building the index is slow and heavy:
our real run (extract, OCR of two scanned PDFs, chunk, embed 569 chunks) took 801 s and
peaked at about 1438 Mi of memory, while answering a question needs a few hundred MB.
"Indexing runs once, and again when the material changes; querying runs on every
question." The two paths have completely different lifecycles.

## Decision
Indexing is a Kubernetes Job, the only writer to Chroma:
- `k8s/base/indexer-job.yaml`: `kind: Job`, `restartPolicy: OnFailure`, `backoffLimit: 4`,
  its own memory limit (2Gi) sized from `kubectl top`.
- `k8s/base/reindex-cronjob.yaml`: the same image and arguments, weekly. A manual re-index
  is `kubectl create job --from=cronjob/reindex manual-reindex-1 -n rahbar`.
- The api never writes. Its readiness probe (`/readyz`) returns 503 until Chroma is
  reachable, the collection is non-empty, its `embed_model` matches the api's
  EMBED_MODEL, and Redis is reachable. A pod is withheld from the Service until there is
  something correct to retrieve.
- When a re-index runs, the store drops and recreates the collection and writes a new
  `index_version`; the api's cache keys include it, so old cached answers stop matching.

## Options considered
Indexing in api startup was rejected:
1. Three pods race to write one volume: three writers, each halfway through a different
   document, leave an index no single run produced.
2. Every restart re-indexes: a rolling update, an OOMKill or a node drain would each pay
   the 13-minute extraction and embedding cost again.
3. Readiness becomes a lie: either the pod reports ready on an empty index, or it takes
   13 minutes and the probes kill it halfway through.
4. No re-index without a redeploy: new material would mean rebuilding and rolling the api.

An init container on the api has the same problems (it still runs per pod, per restart).
A long-running "indexer Deployment" polling for changes would hold memory sized for the
peak all week for work that happens once.

## Consequences
- Re-indexing is one command, with no redeploy and no change to the api.
- We saw readiness protect users: after switching to the real model, new api pods stayed
  0/1 until the indexer finished, while the old pods kept serving; then they turned 1/1
  by themselves.
- Dropping and recreating the collection means that during a re-index the collection is
  briefly empty and readiness drops; acceptable at our scale. At larger scale we would
  build into a new collection and switch an alias.
- The indexer image carries the corpus (baked in at build time), so new documents mean a
  new indexer image, never a new api image.