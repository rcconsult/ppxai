# Project Overview

The `ppxai` project is a Python-based command-line interface (CLI) application that allows users to interact with Perplexity AI models. It provides an interactive chat experience directly in the terminal, featuring model selection, conversation history management, streaming responses, and rich terminal UI elements like Markdown rendering and clickable source citations. The application can be run from source or distributed as a standalone executable across Windows, macOS, and Linux, thanks to PyInstaller.

## Main Technologies

*   **Python:** The core language of the application.
*   **Perplexity AI API:** Used for interacting with Perplexity AI models.
*   **`openai` library:** Python client for the Perplexity AI API.
*   **`rich`:** Provides a sophisticated terminal UI with rich text, Markdown rendering, panels, and tables.
*   **`prompt_toolkit`:** Enables interactive command-line input with features like history.
*   **`python-dotenv`:** For loading environment variables from a `.env` file.
*   **`PyInstaller`:** Used to package the application into standalone executables.

## Building and Running

### Running from Source (For Developers)

1.  Clone the repository.
2.  Set up and activate a Python virtual environment:
    ```bash
    python3 -m venv venv
    source venv/bin/activate  # macOS/Linux
    # venv\Scripts\activate   # Windows
    ```
3.  Install dependencies:
    ```bash
    pip install -r requirements.txt
    ```
4.  Copy `.env.example` to `.env` and add your `PERPLEXITY_API_KEY`:
    ```bash
    cp .env.example .env
    # Edit .env and add: PERPLEXITY_API_KEY=your_api_key_here
    ```
5.  Run the application:
    ```bash
    python ppxai.py
    ```

### Building Standalone Executables

*   **Quick Build (macOS/Linux):**
    ```bash
    ./build.sh
    ```
    (creates `dist/ppxai`)
*   **Quick Build (Windows):**
    ```batch
    build.bat
    ```
    (creates `dist\ppxai.exe`)
*   **Manual Build:** After setting up a virtual environment and installing dependencies, run:
    ```bash
    pyinstaller ppxai.spec
    ```
*   **Distribution:** Distribute the executable along with the `.env.example` file and instructions for users to set their API key in a `.env` file.

## Development Conventions

*   **API Key Management:** Uses a `.env` file and `python-dotenv` for secure handling of the `PERPLEXITY_API_KEY`.
*   **Terminal UI:** Leverages `rich` for an enhanced user experience in the terminal, including Markdown formatting and clickable links.
*   **Command Handling:** Integrates a simple command system within the chat interface (e.g., `/model`, `/clear`, `/quit`).
*   **Automated Builds:** Utilizes GitHub Actions for cross-platform executable builds.
*   **Code Structure:** `ppxai.py` centralizes the application logic, `PerplexityClient` handles API communication, and separate functions manage UI aspects.

## GitHub Community Files

The project includes comprehensive GitHub community files to facilitate collaboration:

*   **Contributing Guide (`CONTRIBUTING.md`):** Provides detailed guidelines for contributors, including development setup, code guidelines, and reporting issues.
*   **Pull Request Template (`.github/PULL_REQUEST_TEMPLATE.md`):** Standardized PR template with sections for description, type of change, testing checklist, and contributor guidelines. Tailored to ppxai workflow including model testing and slash command verification.
*   **Issue Templates (`.github/ISSUE_TEMPLATE/`):** Structured templates for bug reports and feature requests to help maintainers triage issues efficiently.
*   **Security Policy (`SECURITY.md`):** Outlines how to report security vulnerabilities responsibly.
*   **Code of Conduct (`CODE_OF_CONDUCT.md`):** Contributor Covenant Code of Conduct for maintaining a welcoming community.

## Release Management

*   **Current Version:** v1.3.2
*   **Versioning:** Follows Semantic Versioning (SemVer)
*   **Release Process:** Documented in `RELEASE.md` with both automated (GitHub Actions) and manual build options
*   **Distribution:** Pre-built executables available for Linux, macOS, and Windows on GitHub Releases
