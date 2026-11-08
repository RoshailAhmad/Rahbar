# AI usage
## Mehak (Part 2: corpus, indexer, API, evaluation)
- Tool: Claude (claude.ai).
- Claude drafted: the five indexer stages (extract, clean, chunk, embed, store) and their
  tests; the API query pipeline (Chroma retriever, Ollama/hosted providers, prompt,
  relevance floor, retry and fallback, citation check, Redis semantic cache, metrics) and
  its tests; the four functions in eval/run_eval.py; a first draft of the golden set.
- What we changed after running it on our corpus:
  - heading detection: numbered sentences ("14 Political activities ... within") were
    being taken as section titles, so a numbered line must now read like a title;
  - the relevance floor (0.69) and grounding guards, after the 1B model invented hostel
    rules from a loosely related passage;
  - tolerant citation matching, after a correct answer was declined because the model
    reworded section names;
  - llama3.2:1b, 3 passages and a 4096-token context, after measuring 3.5 min per answer
    with the 3B model and timeouts with an 8192-token context;
  - the golden set's section names, to match what our chunker actually produced.
- We ran, read and can explain every file; the measurements in PIPELINE.md are ours.
