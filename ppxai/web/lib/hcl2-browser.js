/**
 * Browser shim for hcl2-parser - Must be loaded BEFORE hcl2-parser.min.js
 *
 * This creates a global `module` object that hcl2-parser will use for exports.
 * After hcl2-parser loads, call window.hcl2Init() to expose the `hcl2` global.
 *
 * Usage in HTML:
 *   <script src="lib/hcl2-browser.js"></script>
 *   <script src="lib/hcl2-parser.min.js"></script>
 *   <script>if (window.hcl2Init) hcl2Init();</script>
 *
 * Then use:
 *   const result = hcl2.parseToObject(hclContent);
 *   const jsonString = hcl2.parseToString(hclContent);
 *
 * Added in v1.13.11 for HCL/Terraform tree view support
 */

// Create module.exports in global scope (not inside IIFE)
// GopherJS checks: "undefined"!=typeof module && ($module=module)
if (typeof module === 'undefined') {
    window.module = { exports: {} };
}

// Init function to expose hcl2 global after parser loads
window.hcl2Init = function() {
    if (window.module && window.module.exports) {
        window.hcl2 = {
            parseToString: window.module.exports.parseToString,
            parseToObject: window.module.exports.parseToObject
        };
    }
    // Cleanup
    delete window.hcl2Init;
};
