# Update user config with latest schema
$configPath = Join-Path $env:USERPROFILE '.ppxai\ppxai-config.json'

if (-not (Test-Path $configPath)) {
    Write-Host "Config not found: $configPath"
    exit 1
}

$config = Get-Content $configPath -Raw | ConvertFrom-Json
$changes = @()

# Fix bin_search_paths order (Windows first)
$paths = $config.paths.bin_search_paths
$winPath = '{home}/AppData/Local/ppxai'
if ($paths[0] -ne $winPath -and $paths -contains $winPath) {
    $newPaths = @($winPath) + ($paths | Where-Object { $_ -ne $winPath })
    $config.paths.bin_search_paths = $newPaths
    $changes += "Moved Windows path to front of bin_search_paths"
}

# Add options.enable_grounding to gemini if missing
if ($config.providers.gemini -and -not $config.providers.gemini.options) {
    $config.providers.gemini | Add-Member -NotePropertyName 'options' -NotePropertyValue @{enable_grounding = $true} -Force
    $changes += "Added gemini options.enable_grounding"
}

# Add openai provider if missing
if ($config.providers -and -not $config.providers.openai) {
    $openai = @{
        name = "OpenAI ChatGPT"
        base_url = "https://api.openai.com/v1"
        api_key_env = "OPENAI_API_KEY"
        default_model = "gpt-4o"
        coding_model = "gpt-4o"
        models = @{
            "gpt-4o" = @{name = "GPT-4o"; description = "Latest flagship model with vision"}
            "gpt-4o-mini" = @{name = "GPT-4o Mini"; description = "Fast and affordable for simple tasks"}
            "gpt-4-turbo" = @{name = "GPT-4 Turbo"; description = "Previous generation with 128K context"}
            "o1" = @{name = "o1"; description = "Advanced reasoning model"}
            "o1-mini" = @{name = "o1 Mini"; description = "Fast reasoning model"}
        }
        pricing = @{
            "gpt-4o" = @{input = 2.50; output = 10.00}
            "gpt-4o-mini" = @{input = 0.15; output = 0.60}
            "gpt-4-turbo" = @{input = 10.00; output = 30.00}
            "o1" = @{input = 15.00; output = 60.00}
            "o1-mini" = @{input = 3.00; output = 12.00}
        }
        capabilities = @{web_search = $false; web_fetch = $false; weather = $false; realtime_info = $false}
        web_search = @{preferred = "gemini"}
    }
    $config.providers | Add-Member -NotePropertyName 'openai' -NotePropertyValue $openai -Force
    $changes += "Added openai provider"
}

# Add openrouter provider if missing
if ($config.providers -and -not $config.providers.openrouter) {
    $openrouter = @{
        name = "OpenRouter"
        base_url = "https://openrouter.ai/api/v1"
        api_key_env = "OPENROUTER_API_KEY"
        default_model = "anthropic/claude-sonnet-4"
        coding_model = "anthropic/claude-sonnet-4"
        models = @{
            "anthropic/claude-sonnet-4" = @{name = "Claude Sonnet 4"; description = "Anthropic's balanced model for most tasks"}
            "anthropic/claude-opus-4" = @{name = "Claude Opus 4"; description = "Anthropic's most capable model"}
            "anthropic/claude-haiku" = @{name = "Claude Haiku"; description = "Fast and affordable Claude model"}
            "google/gemini-2.0-flash-001" = @{name = "Gemini 2.0 Flash"; description = "Google's fast multimodal model"}
            "meta-llama/llama-3.1-405b-instruct" = @{name = "Llama 3.1 405B"; description = "Meta's largest open model"}
        }
        pricing = @{
            "anthropic/claude-sonnet-4" = @{input = 3.00; output = 15.00}
            "anthropic/claude-opus-4" = @{input = 15.00; output = 75.00}
            "anthropic/claude-haiku" = @{input = 0.25; output = 1.25}
            "google/gemini-2.0-flash-001" = @{input = 0.10; output = 0.40}
            "meta-llama/llama-3.1-405b-instruct" = @{input = 3.00; output = 3.00}
        }
        capabilities = @{web_search = $false; web_fetch = $false; weather = $false; realtime_info = $false}
    }
    $config.providers | Add-Member -NotePropertyName 'openrouter' -NotePropertyValue $openrouter -Force
    $changes += "Added openrouter provider"
}

if ($changes.Count -gt 0) {
    # Save with UTF-8 no BOM
    $json = $config | ConvertTo-Json -Depth 10
    [System.IO.File]::WriteAllText($configPath, $json, [System.Text.UTF8Encoding]::new($false))
    Write-Host "Updated $configPath :"
    foreach ($change in $changes) {
        Write-Host "  - $change"
    }
} else {
    Write-Host "No changes needed for $configPath"
}
