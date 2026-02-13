/**
 * HTML Preview Panel for VSCode Extension
 *
 * Opens an HTML file in a WebviewPanel with live-reload support.
 * Uses FileSystemWatcher to detect changes and automatically refresh.
 *
 * v1.16.0: Initial implementation
 */

import * as vscode from 'vscode';
import * as fs from 'fs';
import * as path from 'path';

let activePanel: vscode.WebviewPanel | undefined;
let activeWatcher: vscode.FileSystemWatcher | undefined;

/**
 * Open an HTML file in a live-reloading preview panel.
 *
 * @param filePath Absolute path to the HTML file
 * @returns true if preview opened successfully
 */
export function openHtmlPreview(filePath: string): boolean {
    if (!fs.existsSync(filePath)) {
        vscode.window.showErrorMessage(`Preview: file not found: ${filePath}`);
        return false;
    }

    const ext = path.extname(filePath).toLowerCase();
    if (ext !== '.html' && ext !== '.htm') {
        vscode.window.showErrorMessage(`Preview only supports .html/.htm files`);
        return false;
    }

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
 * Close the active preview panel.
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
 * Whether a preview panel is currently open.
 */
export function isPreviewActive(): boolean {
    return activePanel !== undefined;
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
