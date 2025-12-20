# ppxai Feature Roadmap Proposal (Post-v1.10.3)

**Report Date:** 2025-12-18
**Version Reviewed:** v1.10.3
**Latest Release:** v1.10.8 (Session Management Unification)

> **Note:** A detailed implementation plan for v1.11.0 is available at [docs/v1.11.0-agentic-workflow-plan.md](docs/v1.11.0-agentic-workflow-plan.md)

Based on a review of the current v1.10.3 codebase and project trajectory, this proposal outlines the next strategic steps to evolve ppxai from a terminal chatbot into an autonomous developer agent.

## 1. Project Assessment (v1.10.3)

**Current State:**
- **Infrastructure:** Robust. The transition to a layered architecture (Engine/Server/Client) and HTTP+SSE backend is complete.
- **Distribution:** CI/CD pipelines and standalone bundling are active. v1.10.3 introduced pre-built server binaries.
- **Gap:** The interaction model remains strictly turn-based (User $\rightarrow$ AI $\rightarrow$ User). It lacks "agency"—the ability to plan and execute multi-step coding tasks autonomously.

---

## 2. Proposed Features & Releases

### v1.11.0: "The Agent Release" (Agentic Workflow)
**Goal:** Enable autonomous multi-step task execution.

#### A. Native File Editing Tools (`edit_file`)
- **Problem:** `execute_shell_command` is risky for code editing (escaping issues, lack of atomicity).
- **Solution:** Implement `ppxai/engine/tools/builtin/editor.py`.
- **Capabilities:**
  - `apply_patch`: Apply standard unified diffs.
  - `replace_block`: Search and replace text blocks safely.
  - `insert_text`: Insert code at specific lines.

#### B. The `/agent` Loop
- **Description:** A new execution mode allowing the engine to self-loop up to $N$ times.
- **Workflow Example:**
  1. **Plan:** AI decides to run tests $\rightarrow$ analyze failure $\rightarrow$ fix code $\rightarrow$ verify.
  2. **Loop 1:** Runs `pytest`. Result: Failure at line 42.
  3. **Loop 2:** Calls `edit_file` to fix line 42.
  4. **Loop 3:** Runs `pytest` again. Result: Pass.
  5. **Completion:** Returns success to user.

#### C. `@git` Context Provider
- **Description:** dynamic context tag that injects `git diff` (staged & unstaged).
- **Use Case:** "/agent review my changes @git" $\rightarrow$ Instant code review of work-in-progress.

---

### v1.12.0: "The Context Release" (Deep Awareness)
**Goal:** Give the AI "eyes" to see the project structure and state without manual description.

#### A. Project Structure Awareness (`@tree`)
- **Description:** Automatically injects a visual directory tree (respecting `.gitignore`).
- **Benefit:** Prevents hallucination of non-existent file paths and helps the AI understand architecture.

#### B. Local RAG / Semantic Search (`@codebase`)
- **Description:** Lightweight local vector embedding of the project.
- **Benefit:** Allows semantic queries like "Find the user authentication logic" instead of needing to know exact filenames.

#### C. IDE Diagnostics (`@problems`)
- **Integration:** (VS Code Extension) Inject active linter errors/warnings into the chat context.
- **Use Case:** "/fix @problems" $\rightarrow$ Automatically clears all linting errors in the open file.

---

### v1.13.0: "The Integration Release" (Editor Immersion)
**Goal:** Move beyond the chat sidebar.

#### A. Inline Completion (Ghost Text)
- **Description:** Hook into VS Code's inline provider API.
- **Tech:** Use the HTTP backend to serve "Fill-In-The-Middle" (FIM) requests to fast local models (e.g., DeepSeek-Coder/Ollama) or hosted providers.

#### B. Code Lenses
- **Description:** "Fix This" or "Explain" buttons appearing directly above functions in the code editor.

---

## 3. Known Issues (v1.10.3)

### TUI Markdown Table Rendering Bug
- **Severity:** Medium
- **Description:** Markdown tables in the TUI are not rendering properly. Table syntax (`|:---|:---|:---|`) and content are displayed as raw text instead of formatted tables.
- **Affected:** Rich console markdown rendering in `ppxai/ui.py`
- **Workaround:** View formatted output in VSCode extension which renders tables correctly
- **Fix Target:** v1.10.4

---

## 4. What Shipped in v1.10.3 (Released 2025-12-18)

**Focus:** Pre-built Server Binaries for VSCode Extension

-   ✅ Standalone `ppxai-server` executables (no Python required)
-   ✅ macOS (ARM + Intel), Linux, Windows binaries
-   ✅ GitHub Actions CI/CD for automated builds
-   ✅ Updated documentation for installation options
-   ✅ Extension version bump to 1.10.3

## 5. Immediate Action Plan (v1.10.4 Quick Wins)

These features can be implemented immediately with low effort to provide high value:

1.  **Implement `@git` Context:**
    -   Add logic to `engine/context.py` to capture `git diff` output.
    -   *Why:* Drastically improves the "Code Review" use case.

2.  **Implement `@tree` Context:**
    -   Add a directory tree generator helper.
    -   *Why:* Fixes path hallucinations and improves architectural reasoning.
