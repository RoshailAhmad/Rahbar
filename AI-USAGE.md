# AI usage statement: Assignment 03 (RAGOps on Kubernetes)

**Team:** Roshail Ahmad (24i-3163, lead), Mehak Ali (24i-3155)

## Tool used

We used one AI tool: **Claude (Anthropic), through the claude.ai chat app**. We did not use ChatGPT, Copilot or any other assistant.

## What the AI did

- **Planning:** split the assignment into two parts with time estimates, and gave step-by-step command guidance.
- **Code drafts.** We reviewed, ran, tested and committed every one:
  - Kubernetes manifests: the data-lake PVC, the data-shell pod, the eval Job, the `gate-config` ConfigMap, the eval and candidate NetworkPolicies, and the `k8s/candidate/` objects.
  - The eval suite (`eval/suite.py`), the release gate (`eval/gate.py`, `gate.yaml`), the judge (`eval/judge.py`), `eval/job.py`, `eval/compare.py`, and the eval Dockerfile.
  - API tracing and guardrails (`api/app/services/trace.py`, `answer.py` changes, `trace_tool.py`, `trace_summary.py`), plus seed support and metrics.
  - First drafts of the pipeline modules Mehak integrated: `verify.py`, `ingest.py` request handling, `update.py`, the evaluation levels, query coverage, and the Batch B generator.
- **Debugging:** helped diagnose the Chroma OOMKill (raised its memory to 768Mi/2Gi), the CI indexer reading an empty `DATA_DIR`, the PVC stuck in Pending, and a hanging `kubectl wait`.
- **Golden set:** wrote synthetic questions q24–q31 and q40–q47, each tied to a page of our corpus. We checked each one against the source document before marking it `reviewed: true`.
- **Writing:** drafted the READMEs, this file and the report text from our run outputs and our descriptions of the work.

## What we did ourselves

- **Running and checking:**
  - Ran every command, Job and evaluation on our own cluster (minikube on WSL2).
  - Collected every number in the report from those runs.
  - Took all the screenshots.
- **Hand-written golden questions:** q32–q39 (four each), written without AI.
- **Hand labels** (`eval/hand_labels.jsonl`):
  - Each of us read four generated answers against their retrieved context and gave our own supported / not-supported verdict.
  - The AI did not label them. It only computed the agreement with the judge afterwards (3/8).
- **Decisions:**
  - Chose the thresholds and the release decision.
  - Decided which results to trust (for example, we discarded eval run 1 because Chroma was restarting during it).
- **Mehak's integration work:**
  - Integrated, tested and merged the indexer pipeline, the levels and the coverage work.
  - Ran Batch B generation.

## Limits we are aware of

- The faithfulness judge is itself a small LLM (qwen2.5:1.5b). We measured its agreement with our hand labels instead of trusting it.
- Some code structure follows the AI's drafts. We can explain and modify every part of it, and the demo will show that.
