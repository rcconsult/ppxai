#!/bin/bash
# ppxai installer - downloads pre-built binaries from GitHub releases
#
# Usage:
#   curl -sSL https://raw.githubusercontent.com/rcconsult/ppxai/master/install.sh | bash
#   curl -sSL ... | bash -s -- --version v1.13.0
#   curl -sSL ... | bash -s -- --server-only
#   curl -sSL ... | bash -s -- --with-extension
#
# Options:
#   --version VERSION   Install specific version (default: latest)
#   --server-only       Only install ppxai-server
#   --tui-only          Only install ppxai TUI
#   --with-extension    Also download VSCode extension (.vsix)
#   --with-desktop      Install Linux desktop integration (.desktop file, icon)
#   --with-macos-app    Install macOS .app bundle to /Applications (macOS only)
#   --with-config       Generate config files (~/.ppxai/ppxai-config.json, .env)
#   --with-launchagent  Install LaunchAgent for server auto-start (macOS only)
#   --install-dir DIR   Install directory (default: ~/.local/bin)
#   --uninstall         Remove ppxai installation
#   --help              Show this help message
#
# What gets installed:
#   ~/.local/bin/ppxai              - Rich TUI (original)
#   ~/.local/bin/ppxaide            - Textual TUI (v1.15.0+ - modern async)
#   ~/.local/bin/ppxai-server       - HTTP server for VSCode extension
#   ~/.local/bin/ppxai-desktop      - Desktop web app launcher
#   ~/.local/bin/ppxai-VERSION.vsix - VSCode extension (with --with-extension)
#   ~/.ppxai/ppxai-config.json      - Provider configuration (with --with-config)
#   ~/.ppxai/.env                   - API keys template (with --with-config)
#   ~/.local/share/applications/ppxai.desktop - Desktop entry (with --with-desktop, Linux)
#   ~/.local/share/icons/hicolor/128x128/apps/ppxai.png - Icon (with --with-desktop, Linux)
#   /Applications/ppxai.app         - macOS app bundle (with --with-macos-app)
#   ~/Library/LaunchAgents/com.ppxai.server.plist - LaunchAgent (with --with-launchagent, macOS)

set -euo pipefail

# --- Configuration ---
REPO="rcconsult/ppxai"
INSTALL_DIR="${HOME}/.local/bin"
DATA_DIR="${HOME}/.ppxai"
VERSION="latest"
INSTALL_TUI=true
INSTALL_SERVER=true
INSTALL_DESKTOP_BIN=true
INSTALL_EXTENSION=false
INSTALL_DESKTOP=false
INSTALL_MACOS_APP=false
INSTALL_CONFIG=false
INSTALL_LAUNCHAGENT=false
UNINSTALL=false

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# --- Helper functions ---
info() { echo -e "${BLUE}==>${NC} $*"; }
success() { echo -e "${GREEN}==>${NC} $*"; }
warn() { echo -e "${YELLOW}Warning:${NC} $*"; }
error() { echo -e "${RED}Error:${NC} $*" >&2; }

show_help() {
    cat << 'EOF'
ppxai installer - AI chat application for terminal and VSCode

USAGE:
    curl -sSL https://raw.githubusercontent.com/rcconsult/ppxai/master/install.sh | bash
    curl -sSL ... | bash -s -- [OPTIONS]

OPTIONS:
    --version VERSION     Install specific version (default: latest)
    --server-only         Only install ppxai-server (for VSCode extension)
    --tui-only            Only install ppxai TUI (terminal app)
    --with-extension      Also download VSCode extension (.vsix)
    --with-desktop        Install Linux desktop integration (.desktop file, icon)
    --with-macos-app      Install macOS .app bundle to /Applications (macOS only)
    --with-config         Generate config files (~/.ppxai/ppxai-config.json, .env)
    --with-launchagent    Install LaunchAgent for server auto-start (macOS only)
    --install-dir DIR     Install directory (default: ~/.local/bin)
    --uninstall           Remove ppxai installation
    --help                Show this help message

EXAMPLES:
    # Install latest version (TUI + server + desktop)
    curl -sSL https://raw.githubusercontent.com/rcconsult/ppxai/master/install.sh | bash

    # Install with config files (recommended for first-time setup)
    curl -sSL ... | bash -s -- --with-config

    # Install specific version with VSCode extension
    curl -sSL ... | bash -s -- --version v1.13.0 --with-extension

    # Install with Linux desktop integration (adds to app menu)
    curl -sSL ... | bash -s -- --with-desktop

    # macOS: Install app bundle to /Applications
    curl -sSL ... | bash -s -- --with-macos-app

    # macOS: Full installation with app and auto-start server
    curl -sSL ... | bash -s -- --with-macos-app --with-config --with-launchagent

    # Install only the server (for VSCode users)
    curl -sSL ... | bash -s -- --server-only

    # Uninstall ppxai
    curl -sSL ... | bash -s -- --uninstall

AFTER INSTALLATION:
    1. Add ~/.local/bin to your PATH (if not already):
       echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
       source ~/.bashrc

    2. Set up your API key (or use --with-config to generate template):
       echo 'PERPLEXITY_API_KEY=your-key-here' > ~/.ppxai/.env

    3. Run ppxai:
       ppxai              # Rich TUI (original)
       ppxaide            # Textual TUI (v1.15.0+ - modern async)
       ppxai-desktop      # Desktop Web App
       ppxai-server       # HTTP server for VSCode

    4. For VSCode extension (if downloaded with --with-extension):
       code --install-extension ~/.local/bin/ppxai-VERSION.vsix

For more information: https://github.com/rcconsult/ppxai
EOF
}

# --- Parse arguments ---
while [[ $# -gt 0 ]]; do
    case $1 in
        --version)
            VERSION="$2"
            shift 2
            ;;
        --install-dir)
            INSTALL_DIR="$2"
            shift 2
            ;;
        --server-only)
            INSTALL_TUI=false
            INSTALL_DESKTOP_BIN=false
            shift
            ;;
        --tui-only)
            INSTALL_SERVER=false
            INSTALL_DESKTOP_BIN=false
            shift
            ;;
        --with-extension)
            INSTALL_EXTENSION=true
            shift
            ;;
        --with-desktop)
            INSTALL_DESKTOP=true
            shift
            ;;
        --with-macos-app)
            INSTALL_MACOS_APP=true
            shift
            ;;
        --with-config)
            INSTALL_CONFIG=true
            shift
            ;;
        --with-launchagent)
            INSTALL_LAUNCHAGENT=true
            shift
            ;;
        --uninstall)
            UNINSTALL=true
            shift
            ;;
        --help|-h)
            show_help
            exit 0
            ;;
        *)
            error "Unknown option: $1"
            echo "Use --help for usage information"
            exit 1
            ;;
    esac
done

# --- Platform detection ---
detect_platform() {
    local os arch

    # Detect OS
    case "$(uname -s)" in
        Linux*)  os="linux" ;;
        Darwin*) os="macos" ;;
        MINGW*|MSYS*|CYGWIN*) os="windows" ;;
        *)
            error "Unsupported operating system: $(uname -s)"
            exit 1
            ;;
    esac

    # Detect architecture
    case "$(uname -m)" in
        x86_64|amd64)
            if [[ "$os" == "macos" ]]; then
                arch="intel"
            else
                arch="amd64"
            fi
            ;;
        arm64|aarch64)
            arch="arm64"
            ;;
        *)
            error "Unsupported architecture: $(uname -m)"
            exit 1
            ;;
    esac

    echo "${os}-${arch}"
}

# --- Get latest version from GitHub API ---
get_latest_version() {
    local latest
    latest=$(curl -sSL "https://api.github.com/repos/${REPO}/releases/latest" 2>/dev/null | \
        grep '"tag_name"' | sed -E 's/.*"([^"]+)".*/\1/')

    if [[ -z "$latest" ]]; then
        error "Failed to fetch latest version from GitHub"
        exit 1
    fi

    echo "$latest"
}

# --- Download binary from GitHub releases ---
download_binary() {
    local name="$1"
    local platform="$2"
    local version="$3"
    local suffix=""

    # Windows binaries have .exe extension
    if [[ "$platform" == windows* ]]; then
        suffix=".exe"
    fi

    local asset_name="${name}-${platform}${suffix}"
    local url="https://github.com/${REPO}/releases/download/${version}/${asset_name}"
    local target="${INSTALL_DIR}/${name}${suffix}"

    info "Downloading ${name} ${version} for ${platform}..."

    if ! curl -sSL --fail "$url" -o "$target" 2>/dev/null; then
        error "Failed to download ${asset_name}"
        error "URL: $url"
        return 1
    fi

    chmod +x "$target"
    success "Installed: $target"
}

# --- Download VSCode extension ---
download_extension() {
    local version="$1"
    local version_num="${version#v}"  # Remove 'v' prefix
    local asset_name="ppxai-${version_num}.vsix"
    local url="https://github.com/${REPO}/releases/download/${version}/${asset_name}"
    local target="${INSTALL_DIR}/${asset_name}"

    info "Downloading VSCode extension ${version}..."

    if ! curl -sSL --fail "$url" -o "$target" 2>/dev/null; then
        error "Failed to download ${asset_name}"
        error "URL: $url"
        return 1
    fi

    success "Downloaded: $target"
    echo ""
    info "To install the VSCode extension, run:"
    echo "    code --install-extension $target"
}

# --- Install Linux desktop integration ---
install_desktop_integration() {
    local version="$1"

    # Only install on Linux
    if [[ "$(uname -s)" != "Linux" ]]; then
        warn "Desktop integration is only available on Linux"
        return 0
    fi

    local apps_dir="${HOME}/.local/share/applications"
    local icons_dir="${HOME}/.local/share/icons/hicolor/128x128/apps"
    local desktop_url="https://raw.githubusercontent.com/${REPO}/${version}/resources/ppxai.desktop"
    local icon_url="https://raw.githubusercontent.com/${REPO}/${version}/resources/ppxai.png"

    info "Installing Linux desktop integration..."

    # Create directories
    mkdir -p "$apps_dir" "$icons_dir"

    # Download .desktop file
    if curl -sSL --fail "$desktop_url" -o "${apps_dir}/ppxai.desktop" 2>/dev/null; then
        # Update Exec path to use installed binary
        sed -i "s|Exec=ppxai-desktop|Exec=${INSTALL_DIR}/ppxai-desktop|" "${apps_dir}/ppxai.desktop"
        success "Installed: ${apps_dir}/ppxai.desktop"
    else
        warn "Failed to download .desktop file"
    fi

    # Download icon
    if curl -sSL --fail "$icon_url" -o "${icons_dir}/ppxai.png" 2>/dev/null; then
        success "Installed: ${icons_dir}/ppxai.png"
    else
        warn "Failed to download icon"
    fi

    # Update desktop database if available
    if command -v update-desktop-database &>/dev/null; then
        update-desktop-database "$apps_dir" 2>/dev/null || true
    fi

    # Update icon cache if available
    if command -v gtk-update-icon-cache &>/dev/null; then
        gtk-update-icon-cache -f -t "${HOME}/.local/share/icons/hicolor" 2>/dev/null || true
    fi
}

# --- Generate config file ---
generate_config() {
    local config_path="${DATA_DIR}/ppxai-config.json"

    if [[ -f "$config_path" ]]; then
        warn "ppxai-config.json already exists, skipping"
        return 0
    fi

    info "Generating ppxai-config.json..."

    cat > "$config_path" << 'CONFIGEOF'
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "version": "1.3",
  "default_provider": "perplexity",
  "session": {
    "auto_restore": "prompt",
    "auto_save_interval": 1
  },
  "paths": {
    "bin_search_paths": [
      "{home}/.local/bin",
      "{home}/.ppxai/bin",
      "/usr/local/bin"
    ],
    "data_dir": "{home}/.ppxai"
  },
  "providers": {
    "perplexity": {
      "name": "Perplexity AI",
      "base_url": "https://api.perplexity.ai",
      "api_key_env": "PERPLEXITY_API_KEY",
      "default_model": "sonar-pro",
      "coding_model": "sonar-pro",
      "models": {
        "sonar": {
          "name": "Sonar",
          "description": "Lightweight search model with real-time grounding"
        },
        "sonar-pro": {
          "name": "Sonar Pro",
          "description": "Advanced search model for complex queries"
        },
        "sonar-reasoning-pro": {
          "name": "Sonar Reasoning Pro",
          "description": "Precision reasoning with Chain of Thought capabilities"
        },
        "sonar-deep-research": {
          "name": "Sonar Deep Research",
          "description": "Exhaustive research with comprehensive reports"
        }
      },
      "pricing": {
        "sonar": {"input": 0.20, "output": 0.20},
        "sonar-pro": {"input": 3.00, "output": 15.00},
        "sonar-reasoning-pro": {"input": 5.00, "output": 15.00},
        "sonar-deep-research": {"input": 5.00, "output": 15.00}
      },
      "capabilities": {
        "web_search": true,
        "web_fetch": true,
        "weather": true,
        "realtime_info": true
      }
    },
    "gemini": {
      "name": "Google Gemini",
      "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
      "api_key_env": "GEMINI_API_KEY",
      "default_model": "gemini-2.5-flash",
      "coding_model": "gemini-2.5-pro",
      "models": {
        "gemini-2.5-flash": {
          "name": "Gemini 2.5 Flash",
          "description": "Latest fast model, best price/performance"
        },
        "gemini-2.5-pro": {
          "name": "Gemini 2.5 Pro",
          "description": "Most capable model for complex reasoning"
        }
      },
      "pricing": {
        "gemini-2.5-flash": {"input": 0.15, "output": 0.60},
        "gemini-2.5-pro": {"input": 1.25, "output": 5.00}
      },
      "capabilities": {
        "web_search": true,
        "web_fetch": false,
        "weather": false,
        "realtime_info": false
      }
    },
    "openai": {
      "name": "OpenAI ChatGPT",
      "base_url": "https://api.openai.com/v1",
      "api_key_env": "OPENAI_API_KEY",
      "default_model": "gpt-4o",
      "coding_model": "gpt-4o",
      "models": {
        "gpt-4o": {
          "name": "GPT-4o",
          "description": "Latest flagship model with vision"
        },
        "gpt-4o-mini": {
          "name": "GPT-4o Mini",
          "description": "Fast and affordable for simple tasks"
        },
        "o1": {
          "name": "o1",
          "description": "Advanced reasoning model"
        }
      },
      "pricing": {
        "gpt-4o": {"input": 2.50, "output": 10.00},
        "gpt-4o-mini": {"input": 0.15, "output": 0.60},
        "o1": {"input": 15.00, "output": 60.00}
      },
      "capabilities": {
        "web_search": false,
        "web_fetch": false,
        "weather": false,
        "realtime_info": false
      }
    },
    "openrouter": {
      "name": "OpenRouter",
      "base_url": "https://openrouter.ai/api/v1",
      "api_key_env": "OPENROUTER_API_KEY",
      "default_model": "anthropic/claude-sonnet-4",
      "coding_model": "anthropic/claude-sonnet-4",
      "models": {
        "anthropic/claude-sonnet-4": {
          "name": "Claude Sonnet 4",
          "description": "Anthropic's balanced model for most tasks"
        },
        "anthropic/claude-opus-4": {
          "name": "Claude Opus 4",
          "description": "Anthropic's most capable model"
        },
        "google/gemini-2.0-flash-001": {
          "name": "Gemini 2.0 Flash",
          "description": "Google's fast multimodal model"
        }
      },
      "pricing": {
        "anthropic/claude-sonnet-4": {"input": 3.00, "output": 15.00},
        "anthropic/claude-opus-4": {"input": 15.00, "output": 75.00},
        "google/gemini-2.0-flash-001": {"input": 0.10, "output": 0.40}
      },
      "capabilities": {
        "web_search": false,
        "web_fetch": false,
        "weather": false,
        "realtime_info": false
      }
    }
  },
  "tools": {
    "shell": {
      "require_consent": true,
      "dangerous_commands": [
        "^rm\\s+",
        "^sudo\\s+",
        "^chmod\\s+",
        "^chown\\s+"
      ],
      "allowed_commands": [
        "^ls\\s+",
        "^cat\\s+",
        "^echo\\s+",
        "^pwd$",
        "^whoami$"
      ]
    },
    "agent": {
      "max_iterations": 10,
      "max_tool_iterations": 15,
      "context_char_limit": 2000,
      "min_task_words": 3,
      "checkpoint_backend": "auto"
    },
    "web_search": {
      "preferred": "auto"
    }
  }
}
CONFIGEOF

    success "Created: $config_path"
}

# --- Generate .env template ---
generate_env_template() {
    local env_path="${DATA_DIR}/.env"

    if [[ -f "$env_path" ]]; then
        warn ".env already exists, skipping"
        return 0
    fi

    info "Generating .env template..."

    cat > "$env_path" << 'ENVEOF'
# ppxai Environment Configuration
# ================================
# Add your API keys below. Uncomment the providers you want to use.
# At least one provider key is required.
#
# Get API keys from:
#   - Perplexity: https://www.perplexity.ai/settings/api
#   - Gemini:     https://aistudio.google.com/apikey
#   - OpenAI:     https://platform.openai.com/api-keys
#   - OpenRouter: https://openrouter.ai/keys

# =============================================================================
# PERPLEXITY AI (Recommended - includes web search)
# =============================================================================
# Perplexity provides real-time web search with AI-powered answers.
# Models: sonar (fast), sonar-pro (advanced), sonar-reasoning-pro, sonar-deep-research
#
# PERPLEXITY_API_KEY=pplx-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

# =============================================================================
# GOOGLE GEMINI (Free tier available)
# =============================================================================
# Google's multimodal AI with web search grounding.
# Models: gemini-2.5-flash, gemini-2.5-pro, gemini-3-flash-preview
#
# GEMINI_API_KEY=AIzaxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

# =============================================================================
# OPENAI (ChatGPT)
# =============================================================================
# OpenAI's GPT models including GPT-4o and o1.
# Models: gpt-4o, gpt-4o-mini, o1, o1-mini
#
# OPENAI_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

# =============================================================================
# OPENROUTER (Access to multiple providers)
# =============================================================================
# Access Claude, Gemini, Llama, and other models through one API.
# See available models: https://openrouter.ai/models
#
# OPENROUTER_API_KEY=sk-or-v1-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

# =============================================================================
# ADVANCED OPTIONS
# =============================================================================

# SSL Verification (for corporate proxies with SSL inspection)
# Set to false if you get SSL certificate errors behind a corporate proxy
# SSL_VERIFY=true

# Custom provider API key (for local vLLM/Ollama servers)
# LOCAL_API_KEY=dummy
ENVEOF

    success "Created: $env_path"
    info "Edit $env_path to add your API keys"
}

# --- Create data directories ---
create_data_directories() {
    info "Creating data directories..."

    local dirs=(
        "$DATA_DIR"
        "$DATA_DIR/sessions"
        "$DATA_DIR/exports"
        "$DATA_DIR/checkpoints"
    )

    for dir in "${dirs[@]}"; do
        if [[ ! -d "$dir" ]]; then
            mkdir -p "$dir"
            success "Created: $dir"
        fi
    done
}

# --- Install macOS app bundle ---
install_macos_app() {
    local version="$1"

    if [[ "$(uname -s)" != "Darwin" ]]; then
        warn "--with-macos-app is only available on macOS"
        return 0
    fi

    local arch
    if [[ "$(uname -m)" == "arm64" ]]; then
        arch="arm64"
    else
        arch="intel"
    fi

    local version_num="${version#v}"
    local dmg_name="ppxai-${version_num}-macos-${arch}.dmg"
    local dmg_url="https://github.com/${REPO}/releases/download/${version}/${dmg_name}"
    local tmp_dmg="/tmp/${dmg_name}"
    local mount_point="/Volumes/ppxai Desktop"

    info "Installing macOS app bundle..."

    # Download DMG
    info "Downloading ${dmg_name}..."
    if ! curl -sSL --fail "$dmg_url" -o "$tmp_dmg" 2>/dev/null; then
        warn "DMG not available for ${arch} architecture"
        warn "URL: $dmg_url"
        warn "You can still use the command-line binaries"
        return 0
    fi

    # Mount DMG
    info "Mounting DMG..."
    if ! hdiutil attach "$tmp_dmg" -nobrowse -quiet; then
        error "Failed to mount DMG"
        rm -f "$tmp_dmg"
        return 1
    fi

    # Copy app to /Applications
    info "Installing to /Applications..."
    if [[ -d "/Applications/ppxai.app" ]]; then
        warn "Removing existing /Applications/ppxai.app"
        rm -rf "/Applications/ppxai.app"
    fi

    cp -R "${mount_point}/ppxai.app" /Applications/

    # Unmount DMG
    hdiutil detach "$mount_point" -quiet 2>/dev/null || true
    rm -f "$tmp_dmg"

    # Remove quarantine attribute
    info "Removing quarantine attribute..."
    xattr -cr /Applications/ppxai.app 2>/dev/null || true

    success "Installed: /Applications/ppxai.app"
    echo ""
    info "Launch from Spotlight (Cmd+Space) or Applications folder"
}

# --- Install macOS LaunchAgent ---
install_launchagent() {
    if [[ "$(uname -s)" != "Darwin" ]]; then
        warn "--with-launchagent is only available on macOS"
        return 0
    fi

    local agents_dir="${HOME}/Library/LaunchAgents"
    local plist_path="${agents_dir}/com.ppxai.server.plist"

    info "Installing LaunchAgent for ppxai-server..."

    mkdir -p "$agents_dir"

    # Determine server path
    local server_path="${INSTALL_DIR}/ppxai-server"
    if [[ -d "/Applications/ppxai.app" ]]; then
        server_path="/Applications/ppxai.app/Contents/MacOS/ppxai-server"
    fi

    cat > "$plist_path" << PLISTEOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.ppxai.server</string>
    <key>ProgramArguments</key>
    <array>
        <string>${server_path}</string>
    </array>
    <key>RunAtLoad</key>
    <false/>
    <key>KeepAlive</key>
    <false/>
    <key>StandardOutPath</key>
    <string>${DATA_DIR}/ppxai-server.log</string>
    <key>StandardErrorPath</key>
    <string>${DATA_DIR}/ppxai-server.log</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/usr/local/bin:/usr/bin:/bin:${INSTALL_DIR}</string>
    </dict>
</dict>
</plist>
PLISTEOF

    success "Created: $plist_path"
    echo ""
    info "LaunchAgent commands:"
    echo "    Start server:  launchctl load $plist_path"
    echo "    Stop server:   launchctl unload $plist_path"
    echo "    Enable at login: Change RunAtLoad to <true/> in plist"
}

# --- Remove quarantine from binaries (macOS) ---
remove_quarantine() {
    if [[ "$(uname -s)" != "Darwin" ]]; then
        return 0
    fi

    info "Removing quarantine attribute from binaries..."

    for binary in ppxai ppxaide ppxai-server ppxai-desktop; do
        local path="${INSTALL_DIR}/${binary}"
        if [[ -f "$path" ]]; then
            xattr -cr "$path" 2>/dev/null || true
        fi
    done

    success "Quarantine attributes removed"
}

# --- Uninstall ppxai ---
uninstall_ppxai() {
    echo ""
    echo "╔═══════════════════════════════════════╗"
    echo "║        ppxai uninstaller              ║"
    echo "╚═══════════════════════════════════════╝"
    echo ""

    local removed_something=false

    # Remove binaries
    for binary in ppxai ppxaide ppxai-server ppxai-desktop; do
        local path="${INSTALL_DIR}/${binary}"
        if [[ -f "$path" ]]; then
            rm -f "$path"
            success "Removed: $path"
            removed_something=true
        fi
    done

    # Remove VSCode extensions
    for vsix in "${INSTALL_DIR}"/ppxai-*.vsix; do
        if [[ -f "$vsix" ]]; then
            rm -f "$vsix"
            success "Removed: $vsix"
            removed_something=true
        fi
    done

    # Remove Linux desktop integration
    if [[ "$(uname -s)" == "Linux" ]]; then
        local desktop_file="${HOME}/.local/share/applications/ppxai.desktop"
        local icon_file="${HOME}/.local/share/icons/hicolor/128x128/apps/ppxai.png"

        if [[ -f "$desktop_file" ]]; then
            rm -f "$desktop_file"
            success "Removed: $desktop_file"
            removed_something=true
        fi

        if [[ -f "$icon_file" ]]; then
            rm -f "$icon_file"
            success "Removed: $icon_file"
            removed_something=true
        fi
    fi

    # Remove macOS app and LaunchAgent
    if [[ "$(uname -s)" == "Darwin" ]]; then
        if [[ -d "/Applications/ppxai.app" ]]; then
            rm -rf "/Applications/ppxai.app"
            success "Removed: /Applications/ppxai.app"
            removed_something=true
        fi

        local plist="${HOME}/Library/LaunchAgents/com.ppxai.server.plist"
        if [[ -f "$plist" ]]; then
            launchctl unload "$plist" 2>/dev/null || true
            rm -f "$plist"
            success "Removed: $plist"
            removed_something=true
        fi
    fi

    if [[ "$removed_something" == false ]]; then
        warn "No ppxai installation found"
    fi

    echo ""
    info "Configuration preserved at: $DATA_DIR"
    echo "    To remove all data: rm -rf $DATA_DIR"
    echo ""
}

# --- Main ---
main() {
    # Handle uninstall first
    if [[ "$UNINSTALL" == true ]]; then
        uninstall_ppxai
        exit 0
    fi

    echo ""
    echo "╔═══════════════════════════════════════╗"
    echo "║        ppxai installer                ║"
    echo "║   AI chat for terminal and VSCode     ║"
    echo "╚═══════════════════════════════════════╝"
    echo ""

    # Check dependencies
    if ! command -v curl &>/dev/null; then
        error "curl is required but not installed."
        error "Please install curl and try again."
        exit 1
    fi

    # Get version
    if [[ "$VERSION" == "latest" ]]; then
        info "Fetching latest version..."
        VERSION=$(get_latest_version)
    fi
    success "Version: $VERSION"

    # Detect platform
    PLATFORM=$(detect_platform)
    success "Platform: $PLATFORM"

    # Create install directory
    if [[ ! -d "$INSTALL_DIR" ]]; then
        info "Creating directory: $INSTALL_DIR"
        mkdir -p "$INSTALL_DIR"
    fi

    # Create data directories
    create_data_directories

    echo ""

    # Download binaries
    local failed=false

    if [[ "$INSTALL_TUI" == true ]]; then
        if ! download_binary "ppxai" "$PLATFORM" "$VERSION"; then
            failed=true
        fi
        # Also download ppxaide (Textual TUI - v1.15.0+)
        if ! download_binary "ppxaide" "$PLATFORM" "$VERSION"; then
            warn "ppxaide download failed - only Rich TUI (ppxai) will be available"
        fi
    fi

    if [[ "$INSTALL_SERVER" == true ]]; then
        if ! download_binary "ppxai-server" "$PLATFORM" "$VERSION"; then
            failed=true
        fi
    fi

    if [[ "$INSTALL_DESKTOP_BIN" == true ]]; then
        if ! download_binary "ppxai-desktop" "$PLATFORM" "$VERSION"; then
            warn "ppxai-desktop download failed (non-fatal)"
        fi
    fi

    # Remove quarantine attribute on macOS
    remove_quarantine

    if [[ "$INSTALL_EXTENSION" == true ]]; then
        if ! download_extension "$VERSION"; then
            warn "VSCode extension download failed (non-fatal)"
        fi
    fi

    if [[ "$INSTALL_DESKTOP" == true ]]; then
        install_desktop_integration "$VERSION"
    fi

    if [[ "$INSTALL_MACOS_APP" == true ]]; then
        install_macos_app "$VERSION"
    fi

    if [[ "$INSTALL_CONFIG" == true ]]; then
        generate_config
        generate_env_template
    fi

    if [[ "$INSTALL_LAUNCHAGENT" == true ]]; then
        install_launchagent
    fi

    if [[ "$failed" == true ]]; then
        error "Some downloads failed"
        exit 1
    fi

    echo ""

    # Check if INSTALL_DIR is in PATH
    if [[ ":$PATH:" != *":$INSTALL_DIR:"* ]]; then
        echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        warn "$INSTALL_DIR is not in your PATH"
        echo ""
        echo "Add it to your shell configuration:"
        echo ""

        # Detect shell and suggest appropriate config file
        local shell_name shell_rc
        shell_name=$(basename "${SHELL:-/bin/bash}")

        case "$shell_name" in
            zsh)  shell_rc="~/.zshrc" ;;
            bash)
                if [[ -f "$HOME/.bash_profile" ]]; then
                    shell_rc="~/.bash_profile"
                else
                    shell_rc="~/.bashrc"
                fi
                ;;
            fish) shell_rc="~/.config/fish/config.fish" ;;
            *)    shell_rc="~/.profile" ;;
        esac

        if [[ "$shell_name" == "fish" ]]; then
            echo "    echo 'set -gx PATH \$HOME/.local/bin \$PATH' >> $shell_rc"
        else
            echo "    echo 'export PATH=\"\$HOME/.local/bin:\$PATH\"' >> $shell_rc"
        fi
        echo "    source $shell_rc"
        echo ""
        echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    fi

    # Check for API key (skip if config was generated)
    if [[ "$INSTALL_CONFIG" != true ]] && [[ ! -f "${DATA_DIR}/.env" ]] && [[ -z "${PERPLEXITY_API_KEY:-}" ]]; then
        echo ""
        echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        info "Next: Set up your API key"
        echo ""
        echo "Option 1: Generate config files with templates:"
        echo "    curl -sSL ... | bash -s -- --with-config"
        echo ""
        echo "Option 2: Create ~/.ppxai/.env manually:"
        echo "    echo 'PERPLEXITY_API_KEY=your-key-here' > ~/.ppxai/.env"
        echo ""
        echo "Get your API key at: https://www.perplexity.ai/settings/api"
        echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    fi

    echo ""
    success "Installation complete!"
    echo ""

    if [[ "$INSTALL_TUI" == true ]]; then
        echo "    Run 'ppxai' to start the terminal UI"
    fi
    if [[ "$INSTALL_SERVER" == true ]]; then
        echo "    Run 'ppxai' for Rich TUI (original) or 'ppxaide' for Textual TUI (v1.15.0+ modern)"
        echo "    Run 'ppxai-server' to start the HTTP server (for VSCode)"
    fi
    if [[ "$INSTALL_DESKTOP_BIN" == true ]]; then
        echo "    Run 'ppxai-desktop' to start the Desktop Web App"
    fi
    if [[ "$INSTALL_MACOS_APP" == true ]] && [[ -d "/Applications/ppxai.app" ]]; then
        echo "    Launch 'ppxai' from Applications or Spotlight"
    fi
    if [[ "$INSTALL_EXTENSION" == true ]]; then
        local version_num="${VERSION#v}"
        echo "    Run 'code --install-extension ~/.local/bin/ppxai-${version_num}.vsix' to install VSCode extension"
    fi
    if [[ "$INSTALL_CONFIG" == true ]]; then
        echo ""
        info "Config files created at ~/.ppxai/"
        echo "    Edit ~/.ppxai/.env to add your API keys"
    fi

    echo ""
    echo "Documentation: https://github.com/${REPO}"
    echo ""
}

main "$@"
