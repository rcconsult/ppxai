/**
 * Agent State Machine for explicit agent loop management.
 *
 * Phase 4a of chatPanel.ts refactoring - replaces implicit state
 * in local variables with explicit state machine transitions.
 *
 * v1.14.x - Enables testable, predictable agent loop behavior
 */

import { HttpClient } from '../httpClient';
import { ChatEventBus } from './eventBus';

// ============================================================================
// State Types (Discriminated Union)
// ============================================================================

/** Agent task configuration */
export interface AgentConfig {
    task: string;
    maxIterations: number;
    toolsEnabled: boolean;
}

/** Consent request data */
export interface ConsentRequest {
    type: 'file' | 'shell';
    filepath?: string;
    command?: string;
    operation?: string;
    working_dir?: string;
}

/** Consent response */
export type ConsentResponseValue = 'y' | 'n' | 'always' | 'never';

/**
 * Agent conversation states - explicit discriminated union.
 *
 * Each state captures all relevant context, replacing implicit
 * variables like `isAgentRunning`, `iteration`, `maxIterations`.
 */
export type AgentState =
    | { status: 'idle' }
    | { status: 'validating'; task: string }
    | { status: 'starting'; task: string; config: AgentConfig }
    | { status: 'iterating'; task: string; iteration: number; maxIterations: number }
    | { status: 'streaming'; task: string; iteration: number; maxIterations: number; response: string }
    | { status: 'awaiting_consent'; task: string; iteration: number; maxIterations: number; request: ConsentRequest }
    | { status: 'complete'; task: string; summary: string }
    | { status: 'max_iterations'; task: string; iterations: number }
    | { status: 'error'; task: string; message: string }
    | { status: 'interrupted'; task: string };

// ============================================================================
// Input Types (State Machine Events)
// ============================================================================

/**
 * Inputs that can trigger state transitions.
 */
export type AgentInput =
    | { type: 'START'; task: string }
    | { type: 'CONFIG_LOADED'; config: AgentConfig }
    | { type: 'VALIDATION_FAILED'; reason: string }
    | { type: 'ITERATION_START'; iteration: number; maxIterations: number }
    | { type: 'STREAM_CHUNK'; content: string }
    | { type: 'STREAM_END'; response: string }
    | { type: 'TASK_COMPLETE'; summary: string }
    | { type: 'CONSENT_REQUIRED'; request: ConsentRequest }
    | { type: 'CONSENT_RESOLVED'; response: ConsentResponseValue }
    | { type: 'MAX_ITERATIONS' }
    | { type: 'ERROR'; message: string }
    | { type: 'INTERRUPT' };

// ============================================================================
// State Machine Implementation
// ============================================================================

/**
 * Agent state machine with explicit transitions.
 *
 * Features:
 * - Pure transition function for testability
 * - Side effects isolated in onTransition
 * - EventBus integration for UI updates
 * - Interrupt handling at any state
 *
 * Usage:
 * ```typescript
 * const machine = new AgentStateMachine(eventBus, backend);
 *
 * // Start agent task
 * await machine.start('Fix the bug in auth.ts');
 *
 * // Check state
 * console.log(machine.getState()); // { status: 'iterating', ... }
 *
 * // Interrupt
 * machine.interrupt();
 * ```
 */
export class AgentStateMachine {
    private state: AgentState = { status: 'idle' };
    private eventBus: ChatEventBus;
    private backend: HttpClient;

    constructor(eventBus: ChatEventBus, backend: HttpClient) {
        this.eventBus = eventBus;
        this.backend = backend;
    }

    /**
     * Get current state (read-only).
     */
    getState(): Readonly<AgentState> {
        return this.state;
    }

    /**
     * Check if agent is currently running (not idle/complete/error).
     */
    isRunning(): boolean {
        return !['idle', 'complete', 'max_iterations', 'error', 'interrupted'].includes(this.state.status);
    }

    /**
     * Process an input and transition state.
     * This is the main entry point for state changes.
     */
    send(input: AgentInput): void {
        const prevState = this.state;
        const nextState = this.transition(this.state, input);

        if (nextState !== prevState) {
            this.state = nextState;
            this.onTransition(prevState, nextState, input);
        }
    }

    /**
     * Start an agent task (convenience method).
     * Validates configuration and begins iteration loop.
     */
    async start(task: string): Promise<void> {
        if (this.isRunning()) {
            console.warn('Agent already running, ignoring start');
            return;
        }

        this.send({ type: 'START', task });

        try {
            // Get agent configuration from backend
            const agentStatus = await this.backend.getAgentStatus();
            const toolsStatus = await this.backend.getToolsStatus();

            if (!agentStatus.agent_mode) {
                this.send({ type: 'VALIDATION_FAILED', reason: 'Agent mode not enabled. Use /tools agent on first.' });
                return;
            }

            const config: AgentConfig = {
                task,
                maxIterations: toolsStatus.max_iterations || 10,
                toolsEnabled: toolsStatus.enabled
            };

            this.send({ type: 'CONFIG_LOADED', config });
        } catch (error) {
            this.send({ type: 'ERROR', message: `Failed to start agent: ${error}` });
        }
    }

    /**
     * Interrupt a running task.
     */
    interrupt(): void {
        if (this.isRunning()) {
            this.send({ type: 'INTERRUPT' });
        }
    }

    /**
     * Reset to idle state (for cleanup).
     */
    reset(): void {
        this.state = { status: 'idle' };
    }

    /**
     * Pure state transition function.
     * Given current state and input, returns next state.
     * No side effects - makes testing easy.
     */
    private transition(state: AgentState, input: AgentInput): AgentState {
        // Handle INTERRUPT from any running state
        if (input.type === 'INTERRUPT') {
            if (state.status === 'validating' || state.status === 'starting' ||
                state.status === 'iterating' || state.status === 'streaming' ||
                state.status === 'awaiting_consent') {
                const task = 'task' in state ? state.task : '';
                return { status: 'interrupted', task };
            }
            return state; // No-op if not running
        }

        // Handle ERROR from any running state
        if (input.type === 'ERROR') {
            const task = 'task' in state ? state.task : '';
            return { status: 'error', task, message: input.message };
        }

        // State-specific transitions
        switch (state.status) {
            case 'idle':
                if (input.type === 'START') {
                    return { status: 'validating', task: input.task };
                }
                break;

            case 'validating':
                if (input.type === 'CONFIG_LOADED') {
                    return { status: 'starting', task: state.task, config: input.config };
                }
                if (input.type === 'VALIDATION_FAILED') {
                    return { status: 'error', task: state.task, message: input.reason };
                }
                break;

            case 'starting':
                if (input.type === 'ITERATION_START') {
                    return {
                        status: 'iterating',
                        task: state.task,
                        iteration: input.iteration,
                        maxIterations: input.maxIterations
                    };
                }
                break;

            case 'iterating':
                if (input.type === 'STREAM_CHUNK') {
                    return {
                        status: 'streaming',
                        task: state.task,
                        iteration: state.iteration,
                        maxIterations: state.maxIterations,
                        response: input.content
                    };
                }
                if (input.type === 'CONSENT_REQUIRED') {
                    return {
                        status: 'awaiting_consent',
                        task: state.task,
                        iteration: state.iteration,
                        maxIterations: state.maxIterations,
                        request: input.request
                    };
                }
                if (input.type === 'STREAM_END') {
                    return {
                        status: 'streaming',
                        task: state.task,
                        iteration: state.iteration,
                        maxIterations: state.maxIterations,
                        response: input.response
                    };
                }
                break;

            case 'streaming':
                if (input.type === 'STREAM_CHUNK') {
                    return {
                        ...state,
                        response: state.response + input.content
                    };
                }
                if (input.type === 'STREAM_END') {
                    // Check if task is complete or continue to next iteration
                    // This will be determined by external logic
                    return state;
                }
                if (input.type === 'TASK_COMPLETE') {
                    return { status: 'complete', task: state.task, summary: input.summary };
                }
                if (input.type === 'ITERATION_START') {
                    // Next iteration starting
                    return {
                        status: 'iterating',
                        task: state.task,
                        iteration: input.iteration,
                        maxIterations: input.maxIterations
                    };
                }
                if (input.type === 'MAX_ITERATIONS') {
                    return {
                        status: 'max_iterations',
                        task: state.task,
                        iterations: state.maxIterations
                    };
                }
                if (input.type === 'CONSENT_REQUIRED') {
                    return {
                        status: 'awaiting_consent',
                        task: state.task,
                        iteration: state.iteration,
                        maxIterations: state.maxIterations,
                        request: input.request
                    };
                }
                break;

            case 'awaiting_consent':
                if (input.type === 'CONSENT_RESOLVED') {
                    // Return to iterating state after consent is resolved
                    return {
                        status: 'iterating',
                        task: state.task,
                        iteration: state.iteration,
                        maxIterations: state.maxIterations
                    };
                }
                break;

            case 'complete':
            case 'max_iterations':
            case 'error':
            case 'interrupted':
                // Terminal states - only START can restart
                if (input.type === 'START') {
                    return { status: 'validating', task: input.task };
                }
                break;
        }

        // No valid transition - return current state
        return state;
    }

    /**
     * Handle side effects when state changes.
     * Emits events to EventBus for UI updates.
     */
    private onTransition(from: AgentState, to: AgentState, input: AgentInput): void {
        // Log transition for debugging
        console.log(`Agent: ${from.status} -> ${to.status} (${input.type})`);

        // Emit events based on new state
        switch (to.status) {
            case 'validating':
                this.eventBus.emit('agent:started', to.task);
                break;

            case 'iterating':
                this.eventBus.emit('agent:iteration', to.iteration, to.maxIterations);
                break;

            case 'complete':
                this.eventBus.emit('agent:complete', to.summary);
                break;

            case 'max_iterations':
                this.eventBus.emit('agent:max_iterations', to.iterations);
                break;

            case 'error':
                this.eventBus.emit('agent:error', to.message);
                break;

            case 'interrupted':
                this.eventBus.emit('agent:interrupted');
                break;
        }
    }
}
