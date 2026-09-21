// visionGate.js — pure attach-time vision gate decision (v1.19.3).
//
// Kept in its own file, separate from main.js, for one reason: it has NO
// DOM/`document`/`vscode` dependency, so it can be loaded under plain Node
// (see tests/test_vscode_vision_gate_behavior.py) as well as in the webview
// browser context via a plain <script> tag (chatPanel.ts's
// `_getHtmlForWebview`, loaded before main.js so `shouldBlockImageAttach`
// is a global by the time main.js's `stageFile()` calls it).
//
// Mirrors ppxai/web/app.js's `_stageFile` gate exactly (owner decision 8,
// docs/plan-adr-0007-completion-service.md, 2026-09-21):
//   - modelSupportsVision === false        -> warn (only a KNOWN-false blocks)
//   - modelSupportsVision === true/undefined/null -> allow (unknown must not warn)
//   - a non-image attachment is never gated, regardless of vision support
//
// Web does not actually prevent the file from being staged or sent — the
// warning is informational; the real block (if any) happens server-side,
// because only the server knows whether a VL sidecar or the shell tool can
// stand in for native vision. This module names that decision
// "shouldBlockImageAttach" because that is the client-side question it
// answers ("should this attach trigger the vision-unsupported warning?"),
// not a claim that the client itself blocks anything.
(function (root, factory) {
    var api = factory();
    if (typeof module === 'object' && module.exports) {
        module.exports = api;
    }
    if (root) {
        root.shouldBlockImageAttach = api.shouldBlockImageAttach;
    }
})(typeof self !== 'undefined' ? self : (typeof window !== 'undefined' ? window : null), function () {
    /**
     * @param {boolean} isImage - whether the staged file's media type starts with "image/"
     * @param {boolean|undefined|null} modelSupportsVision - AppState.modelSupportsVision
     * @returns {boolean} true if this attach should trigger the vision-unsupported warning
     */
    function shouldBlockImageAttach(isImage, modelSupportsVision) {
        return isImage === true && modelSupportsVision === false;
    }

    return { shouldBlockImageAttach: shouldBlockImageAttach };
});
