import OpenAI from 'openai';
import { ConfigManager } from './config';

export interface Message {
    role: 'user' | 'assistant' | 'system';
    content: string;
}

export interface UsageStats {
    totalTokens: number;
    promptTokens: number;
    completionTokens: number;
    estimatedCost: number;
}

export interface SessionData {
    name: string;
    createdAt: string;
    provider: string;
    model: string;
    messages: Message[];
    usage: UsageStats;
}

// Coding prompts (ported from Python)
export const CODING_PROMPTS: Record<string, string> = {
    explain: `You are a code explanation expert. Analyze the provided code and explain:
1. What the code does (high-level overview)
2. How it works (step-by-step breakdown)
3. Key concepts and patterns used
4. Potential issues or improvements

Be clear and concise. Use examples where helpful.`,

    test: `You are a unit testing expert. Generate comprehensive unit tests for the provided code.
Include:
1. Happy path tests
2. Edge cases
3. Error handling tests
4. Mock external dependencies where needed

Use appropriate testing framework conventions for the language.`,

    docs: `You are a documentation expert. Generate clear, comprehensive documentation for the provided code.
Include:
1. Overview/description
2. Parameters/arguments
3. Return values
4. Usage examples
5. Any important notes or warnings

Follow the documentation conventions for the language (JSDoc, docstrings, etc).`,

    debug: `You are a debugging expert. Analyze the provided error and:
1. Identify the root cause
2. Explain why this error occurs
3. Provide a solution
4. Suggest preventive measures

Be specific and actionable.`,

    implement: `You are an expert software developer. Implement the requested functionality.
Follow best practices:
1. Clean, readable code
2. Proper error handling
3. Appropriate comments
4. Efficient algorithms

Provide complete, working code.`,

    convert: `You are a code conversion expert. Convert the provided code to the target language.
Ensure:
1. Functional equivalence
2. Idiomatic code in target language
3. Proper error handling
4. Equivalent data structures`
};

export class AIClient {
    private client: OpenAI;
    private configManager: ConfigManager;
    private conversationHistory: Message[] = [];
    private sessionUsage: UsageStats = {
        totalTokens: 0,
        promptTokens: 0,
        completionTokens: 0,
        estimatedCost: 0
    };
    private sessionName: string;
    private sessionCreatedAt: string;
    public autoRoute: boolean = true;

    constructor(configManager: ConfigManager) {
        this.configManager = configManager;
        this.sessionName = `session_${new Date().toISOString().replace(/[:.]/g, '-')}`;
        this.sessionCreatedAt = new Date().toISOString();

        // Initialize OpenAI client
        this.client = this.createClient();
    }

    private createClient(): OpenAI {
        const apiKey = this.configManager.getApiKey();
        const baseURL = this.configManager.getBaseUrl();

        if (!apiKey) {
            throw new Error(`No API key found for provider ${this.configManager.getCurrentProvider()}. Check your .env file.`);
        }

        return new OpenAI({
            apiKey,
            baseURL
        });
    }

    reinitialize(): void {
        this.client = this.createClient();
    }

    async chat(message: string, onChunk?: (chunk: string) => void): Promise<string> {
        this.conversationHistory.push({
            role: 'user',
            content: message
        });

        try {
            const model = this.configManager.getCurrentModel();

            if (onChunk) {
                // Streaming response
                const stream = await this.client.chat.completions.create({
                    model,
                    messages: this.conversationHistory,
                    stream: true
                });

                let fullResponse = '';
                for await (const chunk of stream) {
                    const content = chunk.choices[0]?.delta?.content || '';
                    if (content) {
                        fullResponse += content;
                        onChunk(content);
                    }
                }

                this.conversationHistory.push({
                    role: 'assistant',
                    content: fullResponse
                });

                return fullResponse;
            } else {
                // Non-streaming response
                const response = await this.client.chat.completions.create({
                    model,
                    messages: this.conversationHistory,
                    stream: false
                });

                const assistantMessage = response.choices[0]?.message?.content || '';

                this.conversationHistory.push({
                    role: 'assistant',
                    content: assistantMessage
                });

                // Track usage
                if (response.usage) {
                    this.trackUsage(response.usage, model);
                }

                return assistantMessage;
            }
        } catch (error) {
            // Remove failed message from history
            this.conversationHistory.pop();
            throw error;
        }
    }

    async codingTask(
        taskType: string,
        content: string,
        language?: string,
        filename?: string,
        onChunk?: (chunk: string) => void
    ): Promise<string> {
        const systemPrompt = CODING_PROMPTS[taskType];
        if (!systemPrompt) {
            throw new Error(`Unknown task type: ${taskType}`);
        }

        // Use coding model if auto-route is enabled
        const model = this.autoRoute
            ? this.configManager.getCodingModel()
            : this.configManager.getCurrentModel();

        // Build user message
        let userMessage = '';
        if (filename) {
            userMessage += `File: ${filename}\n\n`;
        }

        switch (taskType) {
            case 'explain':
                userMessage += `Explain this code:\n\n\`\`\`${language || ''}\n${content}\n\`\`\``;
                break;
            case 'test':
                userMessage += `Generate unit tests for this code:\n\n\`\`\`${language || ''}\n${content}\n\`\`\``;
                break;
            case 'docs':
                userMessage += `Generate documentation for this code:\n\n\`\`\`${language || ''}\n${content}\n\`\`\``;
                break;
            case 'debug':
                userMessage += `Debug this error:\n\n${content}`;
                break;
            case 'implement':
                userMessage += `Implement the following in ${language || 'the appropriate language'}:\n\n${content}`;
                break;
            default:
                userMessage += content;
        }

        const messages: Message[] = [
            { role: 'system', content: systemPrompt },
            { role: 'user', content: userMessage }
        ];

        try {
            if (onChunk) {
                // Streaming
                const stream = await this.client.chat.completions.create({
                    model,
                    messages,
                    stream: true
                });

                let fullResponse = '';
                for await (const chunk of stream) {
                    const content = chunk.choices[0]?.delta?.content || '';
                    if (content) {
                        fullResponse += content;
                        onChunk(content);
                    }
                }

                // Add to conversation history
                this.conversationHistory.push({
                    role: 'user',
                    content: `[${taskType}] ${userMessage.slice(0, 100)}...`
                });
                this.conversationHistory.push({
                    role: 'assistant',
                    content: fullResponse
                });

                return fullResponse;
            } else {
                // Non-streaming
                const response = await this.client.chat.completions.create({
                    model,
                    messages,
                    stream: false
                });

                const result = response.choices[0]?.message?.content || '';

                // Add to conversation history
                this.conversationHistory.push({
                    role: 'user',
                    content: `[${taskType}] ${userMessage.slice(0, 100)}...`
                });
                this.conversationHistory.push({
                    role: 'assistant',
                    content: result
                });

                if (response.usage) {
                    this.trackUsage(response.usage, model);
                }

                return result;
            }
        } catch (error) {
            throw error;
        }
    }

    private trackUsage(usage: OpenAI.Completions.CompletionUsage, model: string): void {
        this.sessionUsage.promptTokens += usage.prompt_tokens || 0;
        this.sessionUsage.completionTokens += usage.completion_tokens || 0;
        this.sessionUsage.totalTokens += usage.total_tokens || 0;

        // Get pricing from config
        const provider = this.configManager.getProviderConfig();
        const pricing = provider?.pricing?.[model];
        if (pricing) {
            const inputCost = (usage.prompt_tokens / 1_000_000) * pricing.input;
            const outputCost = (usage.completion_tokens / 1_000_000) * pricing.output;
            this.sessionUsage.estimatedCost += inputCost + outputCost;
        }
    }

    getHistory(): Message[] {
        return [...this.conversationHistory];
    }

    clearHistory(): void {
        this.conversationHistory = [];
    }

    getUsage(): UsageStats {
        return { ...this.sessionUsage };
    }

    getSessionData(): SessionData {
        return {
            name: this.sessionName,
            createdAt: this.sessionCreatedAt,
            provider: this.configManager.getCurrentProvider(),
            model: this.configManager.getCurrentModel(),
            messages: this.getHistory(),
            usage: this.getUsage()
        };
    }

    loadSession(data: SessionData): void {
        this.sessionName = data.name;
        this.sessionCreatedAt = data.createdAt;
        this.conversationHistory = data.messages;
        this.sessionUsage = data.usage;
    }

    getStatus(): { provider: string; model: string; hasApiKey: boolean } {
        return {
            provider: this.configManager.getCurrentProvider(),
            model: this.configManager.getCurrentModel(),
            hasApiKey: !!this.configManager.getApiKey()
        };
    }
}
