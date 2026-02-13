/**
 * HTML Preview Panel for VSCode Extension
 *
 * Opens an HTML file using the best available preview method:
 * 1. Microsoft Live Preview (ms-vscode.live-server) — embedded HTTP preview
 * 2. Live Server (ritwickdey.liveserver) — external browser HTTP preview
 * 3. Webview fallback — direct HTML injection (no fetch() for data files)
 *
 * v1.15.4: Initial implementation (webview only)
 * v1.15.4+: Live Preview / Live Server delegation with webview fallback
 */

import * as vscode from 'vscode';
import * as fs from 'fs';
import * as path from 'path';

let activePanel: vscode.WebviewPanel | undefined;
let activeWatcher: vscode.FileSystemWatcher | undefined;
/** Track whether we've shown the Live Preview suggestion this session */
let livePreviewSuggestionShown = false;

/**
 * Open an HTML file in a live-reloading preview panel.
 *
 * Tries Live Preview (embedded HTTP) first, then Live Server (external browser),
 * then falls back to webview injection.
 *
 * @param filePath Absolute path to the HTML file
 * @returns true if preview opened successfully
 */
export async function openHtmlPreview(filePath: string): Promise<boolean> {
    if (!fs.existsSync(filePath)) {
        vscode.window.showErrorMessage(`Preview: file not found: ${filePath}`);
        return false;
    }

    const ext = path.extname(filePath).toLowerCase();
    if (ext !== '.html' && ext !== '.htm') {
        vscode.window.showErrorMessage(`Preview only supports .html/.htm files`);
        return false;
    }

    // Try Live Preview (Microsoft) — best option: embedded HTTP preview
    if (await tryLivePreview(filePath)) {
        return true;
    }

    // Try Live Server (Ritwick Dey) — opens in external browser
    if (await tryLiveServer(filePath)) {
        return true;
    }

    // Fallback: webview injection (static HTML works, fetch() for data files won't)
    suggestLivePreview();
    return openWebviewFallback(filePath);
}

/**
 * Close the active preview panel (webview fallback only).
 * Live Preview / Live Server manage their own lifecycle.
 */
export function closeHtmlPreview(): void {
    if (activeWatcher) {
        activeWatcher.dispose();
        activeWatcher = undefined;
    }
    if (activePanel) {
        activePanel.dispose();
        activePanel = undefined;
    }
}

/**
 * Whether a preview panel is currently open (webview fallback only).
 */
export function isPreviewActive(): boolean {
    return activePanel !== undefined;
}

// ---------------------------------------------------------------------------
// Live Preview (ms-vscode.live-server)
// ---------------------------------------------------------------------------

async function tryLivePreview(filePath: string): Promise<boolean> {
    const ext = vscode.extensions.getExtension('ms-vscode.live-server');
    if (!ext) {
        return false;
    }

    try {
        // Ensure Live Preview uses filesystem watcher (not editor-only changes).
        // AI tool edits write directly to disk, bypassing VSCode's editor model.
        // The default "On All Changes in Editor" only watches in-memory buffers.
        const config = vscode.workspace.getConfiguration('livePreview');
        const currentMode = config.get<string>('autoRefreshPreview');
        if (currentMode !== 'On Changes to Saved Files') {
            await config.update(
                'autoRefreshPreview',
                'On Changes to Saved Files',
                vscode.ConfigurationTarget.Workspace
            );
        }

        await vscode.commands.executeCommand(
            'livePreview.start.preview.atFile',
            vscode.Uri.file(filePath)
        );
        return true;
    } catch {
        return false;
    }
}

// ---------------------------------------------------------------------------
// Live Server (ritwickdey.liveserver)
// ---------------------------------------------------------------------------

async function tryLiveServer(filePath: string): Promise<boolean> {
    const ext = vscode.extensions.getExtension('ritwickdey.LiveServer');
    if (!ext) {
        return false;
    }

    try {
        await vscode.commands.executeCommand(
            'extension.liveServer.goOnline',
            vscode.Uri.file(filePath)
        );
        return true;
    } catch {
        return false;
    }
}

// ---------------------------------------------------------------------------
// Webview Fallback
// ---------------------------------------------------------------------------

function openWebviewFallback(filePath: string): boolean {
    const fileDir = path.dirname(filePath);
    const fileName = path.basename(filePath);
    const localResourceRoot = vscode.Uri.file(fileDir);

    // Dispose previous panel and watcher
    closeHtmlPreview();

    // Create webview panel
    activePanel = vscode.window.createWebviewPanel(
        'ppxaiPreview',
        `Preview: ${fileName}`,
        vscode.ViewColumn.Beside,
        {
            enableScripts: true,
            localResourceRoots: [localResourceRoot]
        }
    );

    // Load and set content
    loadContent(filePath, activePanel, localResourceRoot);

    // Watch for file changes (HTML + sibling CSS/JS/images)
    const assetPattern = new vscode.RelativePattern(
        fileDir, '*.{html,htm,css,js,json,svg,png,jpg}'
    );
    activeWatcher = vscode.workspace.createFileSystemWatcher(assetPattern);
    activeWatcher.onDidChange(() => {
        if (activePanel) {
            loadContent(filePath, activePanel, localResourceRoot);
        }
    });

    // Clean up when panel is closed
    activePanel.onDidDispose(() => {
        activePanel = undefined;
        if (activeWatcher) {
            activeWatcher.dispose();
            activeWatcher = undefined;
        }
    });

    return true;
}

/**
 * Load HTML content into the webview, rewriting relative asset paths.
 */
function loadContent(
    filePath: string,
    panel: vscode.WebviewPanel,
    resourceRoot: vscode.Uri
): void {
    let html: string;
    try {
        html = fs.readFileSync(filePath, 'utf-8');
    } catch (e) {
        panel.webview.html = `<html><body><h2>Error reading file</h2><pre>${e}</pre></body></html>`;
        return;
    }

    // Rewrite relative src/href attributes to webview URIs
    const fileDir = path.dirname(filePath);
    html = rewriteAssetPaths(html, panel.webview, fileDir);

    panel.webview.html = html;
}

/**
 * Rewrite relative paths in src="" and href="" attributes to webview URIs.
 *
 * Handles: src="style.css", href="./lib/app.js", src="images/logo.png"
 * Skips: absolute URLs (http://, https://), data URIs, anchors (#)
 */
function rewriteAssetPaths(
    html: string,
    webview: vscode.Webview,
    fileDir: string
): string {
    // Match src="..." and href="..." attributes (double or single quotes)
    return html.replace(
        /((?:src|href)\s*=\s*)(["'])((?!https?:\/\/|data:|#|\/\/).*?)\2/gi,
        (match, attr, quote, relativePath) => {
            // Skip empty paths
            if (!relativePath.trim()) {
                return match;
            }
            // Resolve to absolute path
            const absPath = path.resolve(fileDir, relativePath);
            if (!fs.existsSync(absPath)) {
                return match; // Keep original if file doesn't exist
            }
            const webviewUri = webview.asWebviewUri(vscode.Uri.file(absPath));
            return `${attr}${quote}${webviewUri}${quote}`;
        }
    );
}

// ---------------------------------------------------------------------------
// User guidance
// ---------------------------------------------------------------------------

function suggestLivePreview(): void {
    if (livePreviewSuggestionShown) {
        return;
    }
    livePreviewSuggestionShown = true;

    vscode.window.showInformationMessage(
        'For full preview support (dynamic data loading via fetch), install the "Live Preview" extension.',
        'Install Live Preview'
    ).then(choice => {
        if (choice === 'Install Live Preview') {
            vscode.commands.executeCommand(
                'workbench.extensions.installExtension',
                'ms-vscode.live-server'
            );
        }
    });
}
