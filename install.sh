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
#   --install-dir DIR   Install directory (default: ~/.local/bin)
#   --help              Show this help message
#
# What gets installed:
#   ~/.local/bin/ppxai              - Terminal UI application
#   ~/.local/bin/ppxai-server       - HTTP server for VSCode extension
#   ~/.local/bin/ppxai-VERSION.vsix - VSCode extension (with --with-extension)

set -euo pipefail

# --- Configuration ---
REPO="rcconsult/ppxai"
INSTALL_DIR="${HOME}/.local/bin"
VERSION="latest"
INSTALL_TUI=true
INSTALL_SERVER=true
INSTALL_EXTENSION=false

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
    --version VERSION   Install specific version (default: latest)
    --server-only       Only install ppxai-server (for VSCode extension)
    --tui-only          Only install ppxai TUI (terminal app)
    --with-extension    Also download VSCode extension (.vsix)
    --install-dir DIR   Install directory (default: ~/.local/bin)
    --help              Show this help message

EXAMPLES:
    # Install latest version (TUI + server)
    curl -sSL https://raw.githubusercontent.com/rcconsult/ppxai/master/install.sh | bash

    # Install specific version with VSCode extension
    curl -sSL ... | bash -s -- --version v1.13.0 --with-extension

    # Install only the server (for VSCode users)
    curl -sSL ... | bash -s -- --server-only

AFTER INSTALLATION:
    1. Add ~/.local/bin to your PATH (if not already):
       echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
       source ~/.bashrc

    2. Set up your API key:
       echo 'PERPLEXITY_API_KEY=your-key-here' > ~/.ppxai/.env

    3. Run ppxai:
       ppxai

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
            shift
            ;;
        --tui-only)
            INSTALL_SERVER=false
            shift
            ;;
        --with-extension)
            INSTALL_EXTENSION=true
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

# --- Main ---
main() {
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

    echo ""

    # Download binaries
    local failed=false

    if [[ "$INSTALL_TUI" == true ]]; then
        if ! download_binary "ppxai" "$PLATFORM" "$VERSION"; then
            failed=true
        fi
    fi

    if [[ "$INSTALL_SERVER" == true ]]; then
        if ! download_binary "ppxai-server" "$PLATFORM" "$VERSION"; then
            failed=true
        fi
    fi

    if [[ "$INSTALL_EXTENSION" == true ]]; then
        if ! download_extension "$VERSION"; then
            warn "VSCode extension download failed (non-fatal)"
        fi
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

    # Create config directory if it doesn't exist
    if [[ ! -d "$HOME/.ppxai" ]]; then
        mkdir -p "$HOME/.ppxai"
    fi

    # Check for API key
    if [[ ! -f "$HOME/.ppxai/.env" ]] && [[ -z "${PERPLEXITY_API_KEY:-}" ]]; then
        echo ""
        echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        info "Next: Set up your API key"
        echo ""
        echo "Create ~/.ppxai/.env with your API key:"
        echo ""
        echo "    echo 'PERPLEXITY_API_KEY=your-key-here' > ~/.ppxai/.env"
        echo ""
        echo "Or set it as an environment variable:"
        echo ""
        echo "    export PERPLEXITY_API_KEY=your-key-here"
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
        echo "    Run 'ppxai-server' to start the HTTP server (for VSCode)"
    fi
    if [[ "$INSTALL_EXTENSION" == true ]]; then
        local version_num="${VERSION#v}"
        echo "    Run 'code --install-extension ~/.local/bin/ppxai-${version_num}.vsix' to install VSCode extension"
    fi

    echo ""
    echo "Documentation: https://github.com/${REPO}"
    echo ""
}

main "$@"
