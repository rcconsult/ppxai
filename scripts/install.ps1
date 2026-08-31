# ppxai Windows Installation Script
# Downloads and installs ppxai binaries and configuration files
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File install.ps1 -Local -Force
#   powershell -ExecutionPolicy Bypass -File install.ps1 -Version v1.13.2
#   powershell -ExecutionPolicy Bypass -File install.ps1 -Uninstall
#
# If execution policy allows scripts, you can also run directly:
#   .\install.ps1 -Local -Force
#
# Requirements:
#   - PowerShell 5.1+ (Windows 10/11 default)
#   - Internet connection for downloading binaries (not needed with -Local)
#
# Installation locations:
#   - Binaries: %USERPROFILE%\.ppxai\bin\
#   - Config:   %USERPROFILE%\.ppxai\ppxai-config.json
#   - Env:      %USERPROFILE%\.ppxai\.env
#   - Data:     %USERPROFILE%\.ppxai\sessions\, exports\, checkpoints\

param(
    [string]$Version = "latest",
    [switch]$Local,
    [switch]$Uninstall,
    [switch]$Force,
    [switch]$SkipConfig,
    [switch]$SkipBinaries
)

$ErrorActionPreference = "Stop"

# Configuration
$GITHUB_REPO = "rcconsult/ppxai"
$INSTALL_DIR = Join-Path $env:USERPROFILE ".ppxai"
$BIN_DIR = Join-Path $INSTALL_DIR "bin"
$SESSIONS_DIR = Join-Path $INSTALL_DIR "sessions"
$EXPORTS_DIR = Join-Path $INSTALL_DIR "exports"
$CHECKPOINTS_DIR = Join-Path $INSTALL_DIR "checkpoints"

# Binary names
$BINARIES = @(
    "ppxai-windows.exe",
    "ppxaide-windows.exe",
    "ppxai-server-windows.exe",
    "ppxai-desktop-windows.exe"
)

function Show-Header {
    param([string]$Text)
    Write-Host ""
    Write-Host "=== $Text ===" -ForegroundColor Cyan
    Write-Host ""
}

function Show-Ok {
    param([string]$Text)
    Write-Host "[OK] $Text" -ForegroundColor Green
}

function Show-Warn {
    param([string]$Text)
    Write-Host "[WARN] $Text" -ForegroundColor Yellow
}

function Show-Err {
    param([string]$Text)
    Write-Host "[ERROR] $Text" -ForegroundColor Red
}

function Get-LatestVersion {
    Write-Host "Fetching latest release version..."
    try {
        $releases = Invoke-RestMethod -Uri "https://api.github.com/repos/$GITHUB_REPO/releases/latest"
        return $releases.tag_name
    } catch {
        Show-Err "Failed to fetch latest version: $_"
        exit 1
    }
}

function Get-ReleaseAsset {
    param([string]$Tag)
    Write-Host "Fetching release assets for $Tag..."
    try {
        $release = Invoke-RestMethod -Uri "https://api.github.com/repos/$GITHUB_REPO/releases/tags/$Tag"
        return $release.assets
    } catch {
        Show-Err "Failed to fetch release ${Tag}: $_"
        exit 1
    }
}

function Save-Binary {
    param(
        [string]$Url,
        [string]$OutputPath
    )

    $fileName = Split-Path $OutputPath -Leaf
    Write-Host "  Downloading ${fileName}..."
    try {
        # Use TLS 1.2+
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

        $webClient = New-Object System.Net.WebClient
        $webClient.DownloadFile($Url, $OutputPath)
        Show-Ok "Downloaded $fileName"
    } catch {
        Show-Err "Failed to download ${Url}: $_"
        return $false
    }
    return $true
}

function Install-BinariesFromGitHub {
    param([string]$Tag)

    Show-Header "Installing Binaries from GitHub"

    # Create bin directory
    if (-not (Test-Path $BIN_DIR)) {
        New-Item -ItemType Directory -Path $BIN_DIR -Force | Out-Null
        Show-Ok "Created $BIN_DIR"
    }

    # Get release assets
    $assets = Get-ReleaseAsset -Tag $Tag

    foreach ($binary in $BINARIES) {
        $asset = $assets | Where-Object { $_.name -eq $binary }
        if ($asset) {
            $outputPath = Join-Path $BIN_DIR $binary

            # Check if already exists
            if ((Test-Path $outputPath) -and -not $Force) {
                Show-Warn "$binary already exists. Use -Force to overwrite."
                continue
            }

            $success = Save-Binary -Url $asset.browser_download_url -OutputPath $outputPath
            if (-not $success) {
                Show-Warn "Skipping $binary"
            }
        } else {
            Show-Warn "Asset $binary not found in release $Tag"
        }
    }

    # Create convenient aliases (without -windows suffix)
    $aliases = @{
        "ppxai.exe" = "ppxai-windows.exe"
        "ppxaide.exe" = "ppxaide-windows.exe"
        "ppxai-server.exe" = "ppxai-server-windows.exe"
        "ppxai-desktop.exe" = "ppxai-desktop-windows.exe"
    }

    foreach ($alias in $aliases.GetEnumerator()) {
        $source = Join-Path $BIN_DIR $alias.Value
        $target = Join-Path $BIN_DIR $alias.Key
        if (Test-Path $source) {
            Copy-Item $source $target -Force
            Show-Ok "Created alias $($alias.Key)"
        }
    }
}

function Install-BinariesFromLocal {
    Show-Header "Installing Binaries from local folder"

    # Resolve the bin/ folder next to this script
    $scriptDir = Split-Path -Parent $MyInvocation.ScriptName
    $localBinDir = Join-Path $scriptDir "bin"

    if (-not (Test-Path $localBinDir)) {
        Show-Err "Local bin folder not found: $localBinDir"
        exit 1
    }

    # Create target bin directory
    if (-not (Test-Path $BIN_DIR)) {
        New-Item -ItemType Directory -Path $BIN_DIR -Force | Out-Null
        Show-Ok "Created $BIN_DIR"
    }

    # Stop running ppxai-server if any
    $serverProc = Get-Process -Name 'ppxai-server' -ErrorAction SilentlyContinue
    if ($serverProc) {
        Write-Host "  Stopping running ppxai-server..."
        $serverProc | Stop-Process -Force
        Start-Sleep -Seconds 2
        Show-Ok "Stopped ppxai-server"
    }

    # Local bin/ uses short names (ppxai.exe, not ppxai-windows.exe)
    $localBinaries = @("ppxai.exe", "ppxaide.exe", "ppxai-server.exe", "ppxai-desktop.exe")
    $copied = 0

    foreach ($binary in $localBinaries) {
        $source = Join-Path $localBinDir $binary
        $target = Join-Path $BIN_DIR $binary

        if (-not (Test-Path $source)) {
            Show-Warn "$binary not found in $localBinDir - skipping"
            continue
        }

        if ((Test-Path $target) -and -not $Force) {
            # Compare file sizes to detect if update is needed
            $sourceSize = (Get-Item $source).Length
            $targetSize = (Get-Item $target).Length
            if ($sourceSize -eq $targetSize) {
                Show-Warn "$binary already up to date. Use -Force to overwrite."
                continue
            }
        }

        Copy-Item $source $target -Force
        $size = [math]::Round((Get-Item $target).Length / 1MB, 1)
        Show-Ok "Installed $binary - $size MB"
        $copied++
    }

    # Also install VSIX if present
    $vsixFiles = Get-ChildItem -Path $scriptDir -Filter "ppxai-*.vsix" -ErrorAction SilentlyContinue
    if ($vsixFiles) {
        $latestVsix = $vsixFiles | Sort-Object Name -Descending | Select-Object -First 1
        Write-Host ""
        Write-Host "  Found VSCode extension: $($latestVsix.Name)" -ForegroundColor Cyan
        $codePath = Get-Command code -ErrorAction SilentlyContinue
        if ($codePath) {
            & code --install-extension $latestVsix.FullName --force 2>$null
            if ($LASTEXITCODE -eq 0) {
                Show-Ok "Installed VSCode extension: $($latestVsix.Name)"
            } else {
                Show-Warn "VSCode extension install failed. Install manually:"
                Write-Host "    code --install-extension `"$($latestVsix.FullName)`"" -ForegroundColor Yellow
            }
        } else {
            Show-Warn "VSCode not found in PATH. Install extension manually:"
            Write-Host "    code --install-extension `"$($latestVsix.FullName)`"" -ForegroundColor Yellow
        }
    }

    # Ensure data directories exist
    foreach ($dir in @($INSTALL_DIR, $SESSIONS_DIR, $EXPORTS_DIR, $CHECKPOINTS_DIR)) {
        if (-not (Test-Path $dir)) {
            New-Item -ItemType Directory -Path $dir -Force | Out-Null
        }
    }

    # Install ppxai-config.json if present next to script
    $localConfig = Join-Path $scriptDir "ppxai-config.json"
    $targetConfig = Join-Path $INSTALL_DIR "ppxai-config.json"
    if (Test-Path $localConfig) {
        if ((Test-Path $targetConfig) -and -not $Force) {
            Show-Warn "ppxai-config.json already exists. Use -Force to overwrite."
        } else {
            Copy-Item $localConfig $targetConfig -Force
            Show-Ok "Installed ppxai-config.json"
        }
    }

    # Install AGENTS.md if present next to script
    $localAgents = Join-Path $scriptDir "AGENTS.md"
    $targetAgents = Join-Path $INSTALL_DIR "AGENTS.md"
    if (Test-Path $localAgents) {
        if ((Test-Path $targetAgents) -and -not $Force) {
            Show-Warn "AGENTS.md already exists. Use -Force to overwrite."
        } else {
            Copy-Item $localAgents $targetAgents -Force
            Show-Ok "Installed AGENTS.md"
        }
    }

    # Install web UI files if present next to script
    $localWeb = Join-Path $scriptDir "web"
    $targetWeb = Join-Path $INSTALL_DIR "web"
    if (Test-Path $localWeb) {
        Copy-Item $localWeb $targetWeb -Recurse -Force
        $webFileCount = (Get-ChildItem $targetWeb -Recurse -File).Count
        Show-Ok "Installed web UI - $webFileCount files"
    }

    # Install .env
    $envPath = Join-Path $INSTALL_DIR ".env"
    $localEnv = Join-Path $scriptDir ".env"
    if (Test-Path $localEnv) {
        if ((Test-Path $envPath) -and -not $Force) {
            Show-Warn ".env already exists. Use -Force to overwrite."
        } else {
            Copy-Item $localEnv $envPath -Force
            Show-Ok "Installed .env"
        }
    } elseif (-not (Test-Path $envPath)) {
        $envContent = Get-EnvTemplate
        $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
        [System.IO.File]::WriteAllText($envPath, $envContent, $utf8NoBom)
        Show-Ok "Created .env template"
    }

    if ($copied -eq 0) {
        Write-Host ""
        Write-Host "  No binaries were updated. Use -Force to overwrite." -ForegroundColor Yellow
    } else {
        Write-Host ""
        Show-Ok "Installed $copied binaries to $BIN_DIR"
    }
}

function Install-Config {
    Show-Header "Installing Configuration"

    # Create data directories
    foreach ($dir in @($INSTALL_DIR, $SESSIONS_DIR, $EXPORTS_DIR, $CHECKPOINTS_DIR)) {
        if (-not (Test-Path $dir)) {
            New-Item -ItemType Directory -Path $dir -Force | Out-Null
            Show-Ok "Created $dir"
        }
    }

    # Install ppxai-config.json
    $configPath = Join-Path $INSTALL_DIR "ppxai-config.json"
    if ((Test-Path $configPath) -and -not $Force) {
        Show-Warn "ppxai-config.json already exists. Use -Force to overwrite."
    } else {
        $configContent = Get-ConfigTemplate
        # Write UTF-8 without BOM
        $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
        [System.IO.File]::WriteAllText($configPath, $configContent, $utf8NoBom)
        Show-Ok "Created ppxai-config.json"
    }

    # Install .env
    $envPath = Join-Path $INSTALL_DIR ".env"
    if ((Test-Path $envPath) -and -not $Force) {
        Show-Warn ".env already exists. Use -Force to overwrite."
    } else {
        $envContent = Get-EnvTemplate
        # Write UTF-8 without BOM
        $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
        [System.IO.File]::WriteAllText($envPath, $envContent, $utf8NoBom)
        Show-Ok "Created .env"
    }
}

function Get-ConfigTemplate {
    return @'
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
      "{home}/.ppxai/bin",
      "{home}/AppData/Local/ppxai",
      "{home}/.local/bin"
    ],
    "data_dir": "{home}/.ppxai"
  },
  "providers": {
    "perplexity": {
      "name": "Perplexity AI",
      "base_url": "https://api.perplexity.ai",
      "api_key_env": "PERPLEXITY_API_KEY",
      "default_model": "perplexity/sonar",
      "coding_model": "perplexity/sonar",
      "models": {
        "perplexity/sonar": {
          "name": "Sonar",
          "description": "Lightweight search model with real-time grounding (Responses wire - survives the 2026-09-27 retirement)",
          "facts": {
            "wire_protocol": "responses",
            "tool_mode": "auto",
            "max_tokens": 4096
          }
        },
        "sonar-pro": {
          "name": "Sonar Pro",
          "description": "Advanced search model for complex queries. CHAT-COMPLETIONS ONLY - Perplexity retires that endpoint 2026-09-27 and does not serve this model on the Responses wire (measured 2026-08-31)."
        },
        "sonar-reasoning-pro": {
          "name": "Sonar Reasoning Pro",
          "description": "Precision reasoning with Chain of Thought. CHAT-COMPLETIONS ONLY - see sonar-pro."
        }
      },
      "pricing": {
        "perplexity/sonar": {"input": 0.20, "output": 0.20},
        "sonar": {"input": 0.20, "output": 0.20},
        "sonar-pro": {"input": 3.00, "output": 15.00},
        "sonar-reasoning-pro": {"input": 5.00, "output": 15.00}
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
      "default_model": "gemini-3.5-flash",
      "coding_model": "gemini-3.1-pro-preview",
      "__comment_models": "The 2.5 line (2.5-flash / 2.5-pro) sunsets from 2026-10-16 - ai.google.dev deprecations. These are its successors; prices match ppxai-config.example.json, which is the reviewed source. See debt Item 54.",
      "models": {
        "gemini-3.5-flash": {
          "name": "Gemini 3.5 Flash",
          "description": "Fast model, best price/performance"
        },
        "gemini-3.1-pro-preview": {
          "name": "Gemini 3.1 Pro (preview)",
          "description": "Most capable model for complex reasoning. Still PREVIEW - there is no GA successor in the Pro tier yet."
        },
        "gemini-3.1-flash-lite": {
          "name": "Gemini 3.1 Flash Lite",
          "description": "Cheapest tier. Carries its own 2027-05-07 sunset."
        }
      },
      "pricing": {
        "gemini-3.5-flash": {"input": 0.50, "output": 3.00},
        "gemini-3.1-pro-preview": {"input": 2.00, "output": 12.00},
        "gemini-3.1-flash-lite": {"input": 0.10, "output": 0.40}
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
      "default_model": "gpt-5.6-terra",
      "coding_model": "gpt-5.6-terra",
      "__comment_models": "gpt-5.6-terra benchmarked at parity with gpt-5.5 for 40% of the price (2026-08-31; benchmarks/tuning/openai-5.6-terra-vs-5.5.json). Its facts row is REQUIRED: the 5.6 line 400s on any tools array over chat-completions, so wire_protocol must be responses - see benchmarks/tuning/openai-5.6-tools-hazard.json. gpt-5.5 stays configured as a fallback; it has no sunset.",
      "models": {
        "gpt-5.6-terra": {
          "name": "GPT-5.6 Terra",
          "description": "Cost-efficient flagship. Parity with gpt-5.5 at 40% of the price.",
          "facts": {
            "wire_protocol": "responses",
            "tool_mode": "native",
            "max_tokens": 128000
          }
        },
        "gpt-5.5": {
          "name": "GPT-5.5",
          "description": "Previous flagship. Kept as a fallback - no sunset announced."
        },
        "gpt-5.4-mini": {
          "name": "GPT-5.4 Mini",
          "description": "Fast and affordable for simple tasks"
        }
      },
      "pricing": {
        "gpt-5.6-terra": {"input": 2.00, "output": 12.00},
        "gpt-5.5": {"input": 5.00, "output": 30.00},
        "gpt-5.4-mini": {"input": 0.25, "output": 2.00}
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
        "^del\\s+",
        "^rmdir\\s+",
        "^format\\s+",
        "^rd\\s+/s"
      ],
      "allowed_commands": [
        "^dir\\s+",
        "^type\\s+",
        "^echo\\s+",
        "^cd$",
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
'@
}

function Get-EnvTemplate {
    return @'
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
# Models: gemini-3.5-flash, gemini-3.1-pro-preview, gemini-3.1-flash-lite
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
'@
}

function Add-ToPath {
    Show-Header "Updating PATH"

    $currentPath = [Environment]::GetEnvironmentVariable("PATH", "User")

    if ($currentPath -notlike "*$BIN_DIR*") {
        $newPath = "$BIN_DIR;$currentPath"
        [Environment]::SetEnvironmentVariable("PATH", $newPath, "User")
        Show-Ok "Added $BIN_DIR to user PATH"
        Write-Host ""
        Write-Host "NOTE: Restart your terminal or run this command to update PATH:" -ForegroundColor Yellow
        Write-Host '  $env:PATH = [Environment]::GetEnvironmentVariable("PATH", "User")' -ForegroundColor Yellow
    } else {
        Show-Ok "$BIN_DIR is already in PATH"
    }
}

function Uninstall-Ppxai {
    Show-Header "Uninstalling ppxai"

    # Remove binaries
    if (Test-Path $BIN_DIR) {
        Remove-Item -Path $BIN_DIR -Recurse -Force
        Show-Ok "Removed $BIN_DIR"
    }

    # Ask about config removal
    $configPath = Join-Path $INSTALL_DIR "ppxai-config.json"
    $envPath = Join-Path $INSTALL_DIR ".env"

    if ((Test-Path $configPath) -or (Test-Path $envPath)) {
        Write-Host ""
        $response = Read-Host "Remove configuration files? (y/N)"
        if ($response -eq "y" -or $response -eq "Y") {
            if (Test-Path $configPath) {
                Remove-Item $configPath -Force
                Show-Ok "Removed ppxai-config.json"
            }
            if (Test-Path $envPath) {
                Remove-Item $envPath -Force
                Show-Ok "Removed .env"
            }
        }
    }

    # Remove from PATH
    $currentPath = [Environment]::GetEnvironmentVariable("PATH", "User")
    if ($currentPath -like "*$BIN_DIR*") {
        $newPath = ($currentPath -split ";" | Where-Object { $_ -ne $BIN_DIR }) -join ";"
        [Environment]::SetEnvironmentVariable("PATH", $newPath, "User")
        Show-Ok "Removed $BIN_DIR from PATH"
    }

    Write-Host ""
    Show-Ok "ppxai uninstalled successfully"
    Write-Host ""
    Write-Host "Note: Session data in $SESSIONS_DIR was preserved." -ForegroundColor Yellow
    Write-Host "Delete $INSTALL_DIR manually to remove all data." -ForegroundColor Yellow
}

function Show-PostInstall {
    Show-Header "Installation Complete"

    Write-Host "ppxai has been installed to: $INSTALL_DIR" -ForegroundColor Green
    Write-Host ""
    Write-Host "Next steps:" -ForegroundColor Cyan
    Write-Host "  1. Edit your API keys:"
    Write-Host "     notepad $INSTALL_DIR\.env" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "  2. Run ppxai:"
    Write-Host "     ppxai                  # Rich TUI" -ForegroundColor Yellow
    Write-Host "     ppxaide                # Textual TUI" -ForegroundColor Yellow
    Write-Host "     ppxai-server           # HTTP server for VSCode" -ForegroundColor Yellow
    Write-Host "     ppxai-desktop          # Desktop web app" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "  3. For VSCode extension:"
    Write-Host "     - Install ppxai extension from VSIX"
    Write-Host "     - ppxai-server will auto-start when you open chat"
    Write-Host ""
    Write-Host "Documentation: https://github.com/$GITHUB_REPO" -ForegroundColor Cyan
}

# =============================================================================
# Main
# =============================================================================

Write-Host ""
Write-Host "ppxai Windows Installer" -ForegroundColor Cyan
Write-Host "=======================" -ForegroundColor Cyan

if ($Uninstall) {
    Uninstall-Ppxai
    exit 0
}

if ($Local) {
    # Local mode: install from bin/ folder next to this script
    # Config/AGENTS.md/.env are installed by Install-BinariesFromLocal
    # from the script directory - do NOT call Install-Config (cloud template)
    Write-Host "Mode: Local install" -ForegroundColor Green

    Install-BinariesFromLocal

    Add-ToPath
    Show-PostInstall
} else {
    # GitHub mode: download from releases
    if ($Version -eq "latest") {
        $Version = Get-LatestVersion
    }
    Write-Host "Version: $Version" -ForegroundColor Green

    if (-not $SkipBinaries) {
        Install-BinariesFromGitHub -Tag $Version
    }

    if (-not $SkipConfig) {
        Install-Config
    }

    Add-ToPath
    Show-PostInstall
}
