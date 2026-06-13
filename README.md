# OfficeQA Agent

An autonomous agent for the Sentient OfficeQA benchmark.

## Architecture

The agent consists of:

* **Retriever MCP** — Searches Treasury Bulletin documents and locates relevant sections.
* **Table Parser MCP** — Extracts structured values from Treasury tables and handles year/month resolution.
* **Calculator MCP** — Performs all numerical operations including sums, percent changes, geometric means, OLS regression, and Box-Cox transformations.

## Components

* `arena.yaml` — Agent configuration.
* `prompts/` — System instructions and reasoning guidance.
* `skills/` — Domain knowledge and answer formatting rules.
* `mcp/` — Custom MCP servers used by the agent.

## Approach

1. Retrieve relevant Treasury Bulletin documents.
2. Locate and extract the required table data.
3. Perform calculations using deterministic tools.
4. Write the final answer to `/app/answer.txt`.

## Competition

Built for the Sentient OfficeQA benchmark using the Treasury Bulletin corpus.
