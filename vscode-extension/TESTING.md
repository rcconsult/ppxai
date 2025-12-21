# VSCode Extension Testing

## Current Status

The VSCode extension currently **does not have automated tests**. This document outlines the testing approach that should be implemented.

## Recommended Test Framework

Use the official VSCode Extension Testing framework:
- `@vscode/test-electron` - Extension test runner
- `mocha` - Test framework
- `chai` or `assert` - Assertions

## Test Structure (Recommended)

```
vscode-extension/
├── src/
│   └── test/
│       ├── suite/
│       │   ├── index.ts           # Test suite entry point
│       │   ├── chatPanel.test.ts  # Chat panel tests
│       │   ├── httpClient.test.ts # HTTP client tests
│       │   └── commands.test.ts   # Command tests
│       └── runTest.ts             # Test runner
├── package.json                   # Add test scripts
└── .vscode/
    └── launch.json                # Debug configuration
```

## Priority Test Cases

### 1. Chat Panel Tests (`chatPanel.test.ts`)

#### `/tools help editing` Command
```typescript
describe('ChatViewProvider', () => {
  describe('handleToolsCommand', () => {
    it('should display file editing help for /tools help editing', async () => {
      // Mock webview postMessage
      const postMessageSpy = sinon.spy();
      chatPanel._view.webview.postMessage = postMessageSpy;

      // Execute command
      await chatPanel.handleToolsCommand(['help', 'editing']);

      // Verify message posted
      assert(postMessageSpy.calledOnce);
      const message = postMessageSpy.firstCall.args[0];
      assert.equal(message.type, 'systemMessage');
      assert(message.content.includes('File Editing Tools Guide'));
    });

    it('should show available topics for /tools help', async () => {
      const postMessageSpy = sinon.spy();
      chatPanel._view.webview.postMessage = postMessageSpy;

      await chatPanel.handleToolsCommand(['help']);

      const message = postMessageSpy.firstCall.args[0];
      assert(message.content.includes('Available help topics'));
      assert(message.content.includes('editing'));
    });
  });

  describe('getFileEditingHelp', () => {
    it('should return markdown content with all sections', () => {
      const help = chatPanel.getFileEditingHelp();

      // Check key sections
      assert(help.includes('File Editing Tools Guide'));
      assert(help.includes('Overview'));
      assert(help.includes('Quick Start'));
      assert(help.includes('Consent System'));
      assert(help.includes('apply_patch'));
      assert(help.includes('replace_block'));
      assert(help.includes('insert_text'));
      assert(help.includes('delete_lines'));
    });

    it('should include all consent options', () => {
      const help = chatPanel.getFileEditingHelp();

      assert(help.includes('y (yes)') || help.includes('**y**'));
      assert(help.includes('n (no)') || help.includes('**n**'));
      assert(help.includes('always'));
      assert(help.includes('never'));
    });

    it('should include examples and troubleshooting', () => {
      const help = chatPanel.getFileEditingHelp();

      assert(help.includes('Example'));
      assert(help.includes('Troubleshooting'));
      assert(help.includes('/tools enable'));
    });
  });
});
```

### 2. HTTP Client Tests (`httpClient.test.ts`)

```typescript
describe('HttpClient', () => {
  it('should enable tools via POST /tools', async () => {
    const client = new HttpClient('http://localhost:54320');
    await client.enableTools();
    // Verify request sent
  });

  it('should list tools via GET /tools', async () => {
    const client = new HttpClient('http://localhost:54320');
    const tools = await client.listTools();
    assert(Array.isArray(tools));
  });
});
```

### 3. Command Tests (`commands.test.ts`)

```typescript
describe('Extension Commands', () => {
  it('should open chat panel on ppxai.openChat', async () => {
    await vscode.commands.executeCommand('ppxai.openChat');
    // Verify panel is visible
  });

  it('should switch provider on ppxai.switchProvider', async () => {
    await vscode.commands.executeCommand('ppxai.switchProvider');
    // Verify quick pick shown
  });
});
```

## Setup Instructions (When Implementing)

### 1. Install Dependencies

```bash
cd vscode-extension
npm install --save-dev @vscode/test-electron mocha @types/mocha chai @types/chai sinon @types/sinon
```

### 2. Update package.json

```json
{
  "scripts": {
    "test": "node ./out/test/runTest.js",
    "pretest": "npm run compile && npm run lint"
  }
}
```

### 3. Create Test Runner (`src/test/runTest.ts`)

```typescript
import * as path from 'path';
import { runTests } from '@vscode/test-electron';

async function main() {
  const extensionDevelopmentPath = path.resolve(__dirname, '../../');
  const extensionTestsPath = path.resolve(__dirname, './suite/index');

  await runTests({
    extensionDevelopmentPath,
    extensionTestsPath
  });
}

main();
```

### 4. Run Tests

```bash
npm test
```

## Current Test Coverage Summary

### ✅ Python Backend (ppxai package)
- **273/278 tests passing (98.2%)**
- File editing tools: 25 tests
- Help commands: 11 tests (TUI + UI)
- HTTP server endpoints: Covered
- Commands: Comprehensive coverage

### ❌ TypeScript Extension (vscode-extension)
- **0 tests (not implemented)**
- Recommended: ~20-30 tests
- Priority: `/tools help editing`, consent dialogs, HTTP client

## Testing Without Full Setup

For manual testing of the help command:

1. **Build extension**: `npm run compile && npx vsce package`
2. **Install**: `code --install-extension ppxai-1.11.0.vsix --force`
3. **Reload VSCode**
4. **Test command**: Type `/tools help editing` in chat

Expected: Rich markdown help content displayed in chat panel

## Future Improvements

1. **Add automated tests** using @vscode/test-electron
2. **CI/CD integration** - Run tests on every PR
3. **Coverage reports** - Track test coverage percentage
4. **E2E tests** - Test full user workflows
5. **Integration tests** - Test with real ppxai-server

## References

- [VSCode Extension Testing Guide](https://code.visualstudio.com/api/working-with-extensions/testing-extension)
- [vscode-test API](https://github.com/microsoft/vscode-test)
- [Extension Test Samples](https://github.com/microsoft/vscode-extension-samples/tree/main/helloworld-test-sample)
