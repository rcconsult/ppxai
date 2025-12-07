import * as vscode from 'vscode';

// Session data interface matching Python backend
export interface SessionData {
    name: string;
    created_at: string;
    provider: string;
    model: string;
    message_count: number;
}

class SessionItem extends vscode.TreeItem {
    constructor(
        public readonly session: SessionData
    ) {
        super(session.name, vscode.TreeItemCollapsibleState.None);

        const date = new Date(session.created_at);
        const dateStr = date.toLocaleDateString();
        const timeStr = date.toLocaleTimeString();

        this.description = `${session.message_count} messages`;
        this.tooltip = `${session.provider} / ${session.model}\n${dateStr} ${timeStr}`;

        this.command = {
            command: 'ppxai.loadSession',
            title: 'Load Session',
            arguments: [session.name]
        };

        this.iconPath = new vscode.ThemeIcon('history');
    }
}

export class SessionsProvider implements vscode.TreeDataProvider<SessionItem> {
    private _onDidChangeTreeData: vscode.EventEmitter<SessionItem | undefined | null | void> = new vscode.EventEmitter<SessionItem | undefined | null | void>();
    readonly onDidChangeTreeData: vscode.Event<SessionItem | undefined | null | void> = this._onDidChangeTreeData.event;

    private _context: vscode.ExtensionContext;

    constructor(context: vscode.ExtensionContext) {
        this._context = context;
    }

    refresh(): void {
        this._onDidChangeTreeData.fire();
    }

    getTreeItem(element: SessionItem): vscode.TreeItem {
        return element;
    }

    async getChildren(_element?: SessionItem): Promise<SessionItem[]> {
        // Note: The sessions tree view will show sessions stored in VSCode's global state
        // The Python backend manages sessions in ~/.ppxai/sessions/
        // For now, we'll keep using VSCode's global state for the tree view
        // The /sessions command in chat uses the backend's sessions
        try {
            const sessions = this._context.globalState.get<Record<string, SessionData>>('ppxai.sessions', {});
            const sessionList = Object.values(sessions);

            // Sort by creation date, newest first
            sessionList.sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime());

            return sessionList.map(s => new SessionItem(s));
        } catch (error) {
            console.error('Failed to get sessions:', error);
            return [];
        }
    }
}
