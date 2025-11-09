# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

ppxai is a terminal-based UI application for interacting with the Perplexity AI API. It provides an interactive chat interface with model selection, conversation history, and streaming responses.

## Development Setup

1. Create and activate virtual environment:
   ```bash
   python3 -m venv venv
   source venv/bin/activate  # On macOS/Linux
   ```

2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Set up environment variables:
   ```bash
   cp .env.example .env
   # Edit .env and add your PERPLEXITY_API_KEY
   ```

4. Run the application:
   ```bash
   python ppxai.py
   ```

## Architecture

The application consists of a single-file implementation with the following key components:

- **PerplexityClient**: Handles API communication with Perplexity using the OpenAI SDK (Perplexity has OpenAI-compatible API). Manages conversation history and supports both streaming and non-streaming responses.

- **Main UI Loop**: Uses `prompt_toolkit` for input handling with history support, and `rich` for formatted console output including markdown rendering, tables, and panels.

- **Model Selection**: Supports multiple Perplexity models (Sonar Small/Large/Huge in both online and chat variants) with interactive selection.

- **Commands**: The app supports slash commands for clearing history, changing models, viewing help, and exiting.

## Common Commands

Run the application:
```bash
python ppxai.py
```

Install/update dependencies:
```bash
pip install -r requirements.txt
```

Make the script executable:
```bash
chmod +x ppxai.py
./ppxai.py
```
