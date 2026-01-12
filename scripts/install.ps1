# ppxai Windows Installation Script
# Downloads and installs ppxai binaries and configuration files
#
# Usage:
#   .\install.ps1                    # Install latest release
#   .\install.ps1 -Version v1.13.2   # Install specific version
#   .\install.ps1 -Uninstall         # Remove installation
#
# Requirements:
#   - PowerShell 5.1+ (Windows 10/11 default)
#   - Internet connection for downloading binaries
#
# Installation locations:
#   - Binaries: %USERPROFILE%\.ppxai\bin\
#   - Config:   %USERPROFILE%\.ppxai\ppxai-config.json
#   - Env:      %USERPROFILE%\.ppxai\.env
#   - Data:     %USERPROFILE%\.ppxai\sessions\, exports\, checkpoints\

param(
    [string]$Version = "latest",
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
    "ppxai-server-windows.exe",
    "ppxai-desktop-windows.exe"
)

function Write-Header {
    param([string]$Text)
    Write-Host ""
    Write-Host "=== $Text ===" -ForegroundColor Cyan
    Write-Host ""
}

function Write-Success {
    param([string]$Text)
    Write-Host "[OK] $Text" -ForegroundColor Green
}

function Write-Warning {
    param([string]$Text)
    Write-Host "[WARN] $Text" -ForegroundColor Yellow
}

function Write-Error {
    param([string]$Text)
    Write-Host "[ERROR] $Text" -ForegroundColor Red
}

function Get-LatestVersion {
    Write-Host "Fetching latest release version..."
    try {
        $releases = Invoke-RestMethod -Uri "https://api.github.com/repos/$GITHUB_REPO/releases/latest"
        return $releases.tag_name
    } catch {
        Write-Error "Failed to fetch latest version: $_"
        exit 1
    }
}

function Get-ReleaseAssets {
    param([string]$Tag)
    Write-Host "Fetching release assets for $Tag..."
    try {
        $release = Invoke-RestMethod -Uri "https://api.github.com/repos/$GITHUB_REPO/releases/tags/$Tag"
        return $release.assets
    } catch {
        Write-Error "Failed to fetch release $Tag : $_"
        exit 1
    }
}

function Download-Binary {
    param(
        [string]$Url,
        [string]$OutputPath
    )

    Write-Host "  Downloading $(Split-Path $OutputPath -Leaf)..."
    try {
        # Use TLS 1.2+
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

        $webClient = New-Object System.Net.WebClient
        $webClient.DownloadFile($Url, $OutputPath)
        Write-Success "Downloaded $(Split-Path $OutputPath -Leaf)"
    } catch {
        Write-Error "Failed to download $Url : $_"
        return $false
    }
    return $true
}

function Install-Binaries {
    param([string]$Tag)

    Write-Header "Installing Binaries"

    # Create bin directory
    if (-not (Test-Path $BIN_DIR)) {
        New-Item -ItemType Directory -Path $BIN_DIR -Force | Out-Null
        Write-Success "Created $BIN_DIR"
    }

    # Get release assets
    $assets = Get-ReleaseAssets -Tag $Tag

    foreach ($binary in $BINARIES) {
        $asset = $assets | Where-Object { $_.name -eq $binary }
        if ($asset) {
            $outputPath = Join-Path $BIN_DIR $binary

            # Check if already exists
            if ((Test-Path $outputPath) -and -not $Force) {
                Write-Warning "$binary already exists. Use -Force to overwrite."
                continue
            }

            $success = Download-Binary -Url $asset.browser_download_url -OutputPath $outputPath
            if (-not $success) {
                Write-Warning "Skipping $binary"
            }
        } else {
            Write-Warning "Asset $binary not found in release $Tag"
        }
    }

    # Create convenient aliases (without -windows suffix)
    $aliases = @{
        "ppxai.exe" = "ppxai-windows.exe"
        "ppxai-server.exe" = "ppxai-server-windows.exe"
        "ppxai-desktop.exe" = "ppxai-desktop-windows.exe"
    }

    foreach ($alias in $aliases.GetEnumerator()) {
        $source = Join-Path $BIN_DIR $alias.Value
        $target = Join-Path $BIN_DIR $alias.Key
        if (Test-Path $source) {
            Copy-Item $source $target -Force
            Write-Success "Created alias $($alias.Key)"
        }
    }
}

function Install-Config {
    Write-Header "Installing Configuration"

    # Create data directories
    foreach ($dir in @($INSTALL_DIR, $SESSIONS_DIR, $EXPORTS_DIR, $CHECKPOINTS_DIR)) {
        if (-not (Test-Path $dir)) {
            New-Item -ItemType Directory -Path $dir -Force | Out-Null
            Write-Success "Created $dir"
        }
    }

    # Install ppxai-config.json
    $configPath = Join-Path $INSTALL_DIR "ppxai-config.json"
    if ((Test-Path $configPath) -and -not $Force) {
        Write-Warning "ppxai-config.json already exists. Use -Force to overwrite."
    } else {
        $configContent = Get-ConfigTemplate
        # Write UTF-8 without BOM (PowerShell 5.1's -Encoding UTF8 adds BOM which breaks JSON parsing)
        [System.IO.File]::WriteAllText($configPath, $configContent, [System.Text.UTF8Encoding]::new($false))
        Write-Success "Created ppxai-config.json"
    }

    # Install .env
    $envPath = Join-Path $INSTALL_DIR ".env"
    if ((Test-Path $envPath) -and -not $Force) {
        Write-Warning ".env already exists. Use -Force to overwrite."
    } else {
        $envContent = Get-EnvTemplate
        # Write UTF-8 without BOM
        [System.IO.File]::WriteAllText($envPath, $envContent, [System.Text.UTF8Encoding]::new($false))
        Write-Success "Created .env (edit to add your API keys)"
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
      "default_model": "gemini-2.0-flash",
      "coding_model": "gemini-2.5-pro",
      "models": {
        "gemini-2.0-flash": {
          "name": "Gemini 2.0 Flash",
          "description": "Fast model with multimodal support"
        },
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
        "gemini-2.0-flash": {"input": 0.10, "output": 0.40},
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
# Models: gemini-2.0-flash, gemini-2.5-flash, gemini-2.5-pro
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
    Write-Header "Updating PATH"

    $currentPath = [Environment]::GetEnvironmentVariable("PATH", "User")

    if ($currentPath -notlike "*$BIN_DIR*") {
        $newPath = "$BIN_DIR;$currentPath"
        [Environment]::SetEnvironmentVariable("PATH", $newPath, "User")
        Write-Success "Added $BIN_DIR to user PATH"
        Write-Host ""
        Write-Host "NOTE: Restart your terminal or run this command to update PATH:" -ForegroundColor Yellow
        Write-Host '  $env:PATH = [Environment]::GetEnvironmentVariable("PATH", "User")' -ForegroundColor Yellow
    } else {
        Write-Success "$BIN_DIR is already in PATH"
    }
}

function Uninstall-Ppxai {
    Write-Header "Uninstalling ppxai"

    # Remove binaries
    if (Test-Path $BIN_DIR) {
        Remove-Item -Path $BIN_DIR -Recurse -Force
        Write-Success "Removed $BIN_DIR"
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
                Write-Success "Removed ppxai-config.json"
            }
            if (Test-Path $envPath) {
                Remove-Item $envPath -Force
                Write-Success "Removed .env"
            }
        }
    }

    # Remove from PATH
    $currentPath = [Environment]::GetEnvironmentVariable("PATH", "User")
    if ($currentPath -like "*$BIN_DIR*") {
        $newPath = ($currentPath -split ";" | Where-Object { $_ -ne $BIN_DIR }) -join ";"
        [Environment]::SetEnvironmentVariable("PATH", $newPath, "User")
        Write-Success "Removed $BIN_DIR from PATH"
    }

    Write-Host ""
    Write-Success "ppxai uninstalled successfully"
    Write-Host ""
    Write-Host "Note: Session data in $SESSIONS_DIR was preserved." -ForegroundColor Yellow
    Write-Host "Delete $INSTALL_DIR manually to remove all data." -ForegroundColor Yellow
}

function Show-PostInstall {
    Write-Header "Installation Complete"

    Write-Host "ppxai has been installed to: $INSTALL_DIR" -ForegroundColor Green
    Write-Host ""
    Write-Host "Next steps:" -ForegroundColor Cyan
    Write-Host "  1. Edit your API keys:"
    Write-Host "     notepad $INSTALL_DIR\.env" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "  2. Run ppxai:"
    Write-Host "     ppxai                  # Terminal UI" -ForegroundColor Yellow
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

# Resolve version
if ($Version -eq "latest") {
    $Version = Get-LatestVersion
}
Write-Host "Version: $Version" -ForegroundColor Green

# Install binaries
if (-not $SkipBinaries) {
    Install-Binaries -Tag $Version
}

# Install config
if (-not $SkipConfig) {
    Install-Config
}

# Update PATH
Add-ToPath

# Show post-install instructions
Show-PostInstall
