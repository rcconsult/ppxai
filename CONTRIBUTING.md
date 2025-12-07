# Contributing to ppxai

Thank you for your interest in contributing to ppxai! We welcome contributions from the community.

## How to Contribute

1. **Fork the repository** and create your branch from `master`
2. **Make your changes** ensuring code quality and consistency
3. **Test your changes** thoroughly
4. **Update documentation** if you're adding features or changing behavior
5. **Submit a pull request** with a clear description of your changes

## Development Setup

### TUI (Terminal UI)

1. Clone your fork
2. Create and activate a virtual environment:
   ```bash
   python3 -m venv venv
   source venv/bin/activate  # On macOS/Linux
   ```
3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
4. Set up configuration:
   ```bash
   cp .env.example .env
   # Edit .env and add your API keys (e.g., PERPLEXITY_API_KEY)

   # Optional: For multi-provider setup
   cp ppxai-config.example.json ppxai-config.json
   ```
5. Run the application:
   ```bash
   python ppxai.py
   ```
6. Run tests:
   ```bash
   python -m pytest tests/ -v
   ```

### VS Code Extension

1. Navigate to the extension directory:
   ```bash
   cd vscode-extension
   ```
2. Install Node.js dependencies:
   ```bash
   npm install
   ```
3. Compile TypeScript:
   ```bash
   npm run compile
   ```
4. Press F5 in VS Code to launch Extension Development Host

For more details, see [vscode-extension/README.md](vscode-extension/README.md).

## Code Guidelines

- Follow existing code style and conventions
- Write clear, descriptive commit messages
- Keep changes focused and atomic
- Add tests for new functionality when applicable
- Ensure the application runs without errors

## Reporting Issues

If you find a bug or have a feature request:
- Check existing issues first to avoid duplicates
- Provide detailed information about the issue
- Include steps to reproduce for bugs
- Describe expected vs actual behavior

## Questions?

Feel free to open an issue for questions or discussion before starting work on major changes.

We appreciate your contributions!
