import * as vscode from 'vscode';
import * as fs from 'fs';
import * as path from 'path';
import * as dotenv from 'dotenv';

export interface ModelInfo {
    name: string;
    description: string;
}

export interface ProviderConfig {
    name: string;
    base_url: string;
    api_key_env: string;
    default_model: string;
    coding_model?: string;
    models: Record<string, ModelInfo>;
    pricing?: Record<string, { input: number; output: number }>;
    capabilities?: {
        web_search?: boolean;
        web_fetch?: boolean;
        weather?: boolean;
        realtime_info?: boolean;
    };
}

export interface PpxaiConfig {
    default_provider: string;
    providers: Record<string, ProviderConfig>;
}

// Built-in default configuration (Perplexity)
const DEFAULT_CONFIG: PpxaiConfig = {
    default_provider: "perplexity",
    providers: {
        "perplexity": {
            name: "Perplexity AI",
            base_url: "https://api.perplexity.ai",
            api_key_env: "PERPLEXITY_API_KEY",
            default_model: "sonar",
            coding_model: "sonar-pro",
            models: {
                "sonar": { name: "Sonar", description: "Fast, good for general queries" },
                "sonar-pro": { name: "Sonar Pro", description: "Advanced reasoning and analysis" },
                "sonar-reasoning": { name: "Sonar Reasoning", description: "Extended thinking for complex problems" },
                "sonar-reasoning-pro": { name: "Sonar Reasoning Pro", description: "Most capable reasoning model" },
                "sonar-deep-research": { name: "Sonar Deep Research", description: "Comprehensive research and analysis" }
            },
            pricing: {
                "sonar": { input: 1.0, output: 1.0 },
                "sonar-pro": { input: 3.0, output: 15.0 },
                "sonar-reasoning": { input: 1.0, output: 5.0 },
                "sonar-reasoning-pro": { input: 2.0, output: 8.0 },
                "sonar-deep-research": { input: 2.0, output: 8.0 }
            },
            capabilities: {
                web_search: true,
                realtime_info: true
            }
        },
        "openai": {
            name: "OpenAI",
            base_url: "https://api.openai.com/v1",
            api_key_env: "OPENAI_API_KEY",
            default_model: "gpt-4o",
            coding_model: "gpt-4o",
            models: {
                "gpt-4o": { name: "GPT-4o", description: "Most capable model" },
                "gpt-4o-mini": { name: "GPT-4o Mini", description: "Fast and efficient" },
                "gpt-4-turbo": { name: "GPT-4 Turbo", description: "Previous generation flagship" },
                "o1": { name: "o1", description: "Advanced reasoning" },
                "o1-mini": { name: "o1 Mini", description: "Fast reasoning" }
            },
            pricing: {
                "gpt-4o": { input: 2.5, output: 10.0 },
                "gpt-4o-mini": { input: 0.15, output: 0.6 },
                "gpt-4-turbo": { input: 10.0, output: 30.0 },
                "o1": { input: 15.0, output: 60.0 },
                "o1-mini": { input: 3.0, output: 12.0 }
            }
        },
        "openrouter": {
            name: "OpenRouter",
            base_url: "https://openrouter.ai/api/v1",
            api_key_env: "OPENROUTER_API_KEY",
            default_model: "anthropic/claude-3.5-sonnet",
            coding_model: "anthropic/claude-3.5-sonnet",
            models: {
                "anthropic/claude-3.5-sonnet": { name: "Claude 3.5 Sonnet", description: "Anthropic's most capable model" },
                "anthropic/claude-3-opus": { name: "Claude 3 Opus", description: "Most powerful Claude model" },
                "google/gemini-pro-1.5": { name: "Gemini Pro 1.5", description: "Google's latest model" },
                "meta-llama/llama-3.1-405b-instruct": { name: "Llama 3.1 405B", description: "Meta's largest open model" }
            }
        }
    }
};

export class ConfigManager {
    private config: PpxaiConfig;
    private envVars: Record<string, string> = {};
    private currentProvider: string;
    private currentModel: string;

    constructor() {
        this.config = DEFAULT_CONFIG;
        this.currentProvider = DEFAULT_CONFIG.default_provider;
        this.currentModel = DEFAULT_CONFIG.providers[this.currentProvider].default_model;
        this.loadConfig();
    }

    private loadConfig(): void {
        // Load .env file
        this.loadEnvFile();

        // Try to load ppxai-config.json
        const configPath = this.findConfigFile();
        if (configPath) {
            try {
                const configContent = fs.readFileSync(configPath, 'utf-8');
                const loadedConfig = JSON.parse(configContent) as Partial<PpxaiConfig>;

                // Merge with defaults
                if (loadedConfig.providers) {
                    this.config.providers = { ...this.config.providers, ...loadedConfig.providers };
                }
                if (loadedConfig.default_provider) {
                    this.config.default_provider = loadedConfig.default_provider;
                }

                console.log(`Loaded config from: ${configPath}`);
            } catch (error) {
                console.error(`Failed to load config from ${configPath}:`, error);
            }
        }

        // Apply VS Code settings
        const vsConfig = vscode.workspace.getConfiguration('ppxai');
        const defaultProvider = vsConfig.get<string>('defaultProvider');
        const defaultModel = vsConfig.get<string>('defaultModel');

        if (defaultProvider && this.config.providers[defaultProvider]) {
            this.currentProvider = defaultProvider;
        } else {
            this.currentProvider = this.config.default_provider;
        }

        if (defaultModel) {
            this.currentModel = defaultModel;
        } else {
            this.currentModel = this.config.providers[this.currentProvider]?.default_model || '';
        }
    }

    private loadEnvFile(): void {
        const envPaths = [
            // Workspace .env
            vscode.workspace.workspaceFolders?.[0]?.uri.fsPath
                ? path.join(vscode.workspace.workspaceFolders[0].uri.fsPath, '.env')
                : null,
            // ppxai project .env (relative to extension's out/ directory)
            path.join(__dirname, '..', '..', '.env'),
            // Home directory .ppxai/.env
            path.join(process.env.HOME || '', '.ppxai', '.env'),
        ].filter(Boolean) as string[];

        for (const envPath of envPaths) {
            if (fs.existsSync(envPath)) {
                const result = dotenv.config({ path: envPath });
                if (result.parsed) {
                    this.envVars = { ...this.envVars, ...result.parsed };
                    console.log(`Loaded .env from: ${envPath}`);
                }
            }
        }

        // Also include process.env
        this.envVars = { ...this.envVars, ...process.env as Record<string, string> };
    }

    private findConfigFile(): string | null {
        const vsConfig = vscode.workspace.getConfiguration('ppxai');
        const customPath = vsConfig.get<string>('configPath');

        const searchPaths = [
            customPath,
            // Workspace config
            vscode.workspace.workspaceFolders?.[0]?.uri.fsPath
                ? path.join(vscode.workspace.workspaceFolders[0].uri.fsPath, 'ppxai-config.json')
                : null,
            // ppxai project config (relative to extension's out/ directory)
            path.join(__dirname, '..', '..', 'ppxai-config.json'),
            // Home directory config
            path.join(process.env.HOME || '', '.ppxai', 'ppxai-config.json'),
        ].filter(Boolean) as string[];

        for (const configPath of searchPaths) {
            if (fs.existsSync(configPath)) {
                return configPath;
            }
        }

        return null;
    }

    reload(): void {
        this.loadConfig();
    }

    getProviders(): string[] {
        return Object.keys(this.config.providers);
    }

    getProviderConfig(provider?: string): ProviderConfig | undefined {
        return this.config.providers[provider || this.currentProvider];
    }

    getCurrentProvider(): string {
        return this.currentProvider;
    }

    getCurrentModel(): string {
        return this.currentModel;
    }

    setProvider(provider: string): boolean {
        if (this.config.providers[provider]) {
            this.currentProvider = provider;
            this.currentModel = this.config.providers[provider].default_model;
            return true;
        }
        return false;
    }

    setModel(model: string): boolean {
        const provider = this.config.providers[this.currentProvider];
        if (provider && provider.models[model]) {
            this.currentModel = model;
            return true;
        }
        return false;
    }

    getModels(provider?: string): Array<{ id: string; name: string; description: string }> {
        const p = this.config.providers[provider || this.currentProvider];
        if (!p) {return [];}

        return Object.entries(p.models).map(([id, info]) => ({
            id,
            name: info.name,
            description: info.description
        }));
    }

    getApiKey(provider?: string): string | undefined {
        const p = this.config.providers[provider || this.currentProvider];
        if (!p) {return undefined;}

        return this.envVars[p.api_key_env];
    }

    getBaseUrl(provider?: string): string {
        const p = this.config.providers[provider || this.currentProvider];
        return p?.base_url || 'https://api.perplexity.ai';
    }

    getCodingModel(provider?: string): string {
        const p = this.config.providers[provider || this.currentProvider];
        return p?.coding_model || p?.default_model || this.currentModel;
    }
}
