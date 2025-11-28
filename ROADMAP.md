# ppxai Development Roadmap

## Current Release: v1.5.0

**Status**: ✅ Complete - Shell commands & SSL fix

Features implemented:
- Shell command execution tool (`execute_shell_command`)
- SSL certificate verification fix for corporate proxies
- Unified `SSL_VERIFY` environment variable
- 148 tests passing (100%)

---

## Future Enhancements

### v1.6.0: Multi-Provider Configuration (Priority: High)

**Goal**: Support multiple custom providers with easy switching

#### Features

1. **Multiple Custom Provider Support**
   - Configure multiple custom endpoints (not just one)
   - Each provider can have its own:
     - API endpoint URL
     - API key
     - Model configuration
     - Display name
   - Easy switching between providers

2. **Enhanced Provider Configuration**
   - Extend `.env` configuration to support multiple custom providers
   - New format:
     ```bash
     # Provider 1: Internal Code AI
     CUSTOM_PROVIDER_1_NAME=Internal Code AI
     CUSTOM_PROVIDER_1_ENDPOINT=https://api.example.com/v1
     CUSTOM_PROVIDER_1_API_KEY=dummy-key
     CUSTOM_PROVIDER_1_MODEL_ID=openai/gpt-oss-120b

     # Provider 2: OpenAI ChatGPT
     CUSTOM_PROVIDER_2_NAME=OpenAI ChatGPT
     CUSTOM_PROVIDER_2_ENDPOINT=https://api.openai.com/v1
     CUSTOM_PROVIDER_2_API_KEY=sk-proj-...
     CUSTOM_PROVIDER_2_MODEL_ID=gpt-4

     # Provider 3: Local vLLM
     CUSTOM_PROVIDER_3_NAME=Local Llama
     CUSTOM_PROVIDER_3_ENDPOINT=http://localhost:8000/v1
     CUSTOM_PROVIDER_3_API_KEY=dummy
     CUSTOM_PROVIDER_3_MODEL_ID=meta-llama/Llama-3-70b
     ```

3. **Provider Management Commands**
   - `/provider list` - Show all configured providers
   - `/provider switch <name>` - Switch to a specific provider
   - `/provider info` - Show current provider details
   - `/provider add` - Interactive provider addition (future)

4. **Dynamic Provider Discovery**
   - Auto-detect all `CUSTOM_PROVIDER_*` environment variables
   - Build provider list dynamically at startup
   - Support unlimited number of providers

#### Implementation Plan

**Phase 1: Configuration (2-3 hours)**
- [ ] Update `ppxai/config.py` to parse multiple custom providers
- [ ] Create `parse_custom_providers()` function
- [ ] Modify `PROVIDERS` dict to include all discovered providers
- [ ] Update `.env.example` with multi-provider examples

**Phase 2: UI/UX (1-2 hours)**
- [ ] Update provider selection menu to show all providers
- [ ] Add provider metadata (endpoint, model) to selection display
- [ ] Implement `/provider` command with subcommands
- [ ] Update help text and documentation

**Phase 3: Client Management (1 hour)**
- [ ] Update client initialization to support any provider
- [ ] Ensure session metadata tracks provider correctly
- [ ] Test provider switching during session

**Phase 4: Testing (1-2 hours)**
- [ ] Add tests for multi-provider configuration parsing
- [ ] Test provider switching functionality
- [ ] Integration tests with multiple providers
- [ ] Update existing tests to handle new provider structure

**Phase 5: Documentation (1 hour)**
- [ ] Update README.md with multi-provider setup
- [ ] Create MULTI_PROVIDER_GUIDE.md
- [ ] Update `.env.example` with comprehensive examples

**Estimated Total**: 6-9 hours

---

### v1.7.0: Per-Provider Tool Configuration (Priority: Medium)

**Goal**: Configure which tools are available for each provider

#### Features

1. **Tool Configuration Per Provider**
   - Enable/disable specific tools for each provider
   - Different tool sets for different use cases
   - Example use cases:
     - Disable shell commands on production endpoints
     - Enable only file operations for code review bots
     - Full tool access for development/testing

2. **Configuration Format**
   ```bash
   # Provider 1 tools configuration
   CUSTOM_PROVIDER_1_TOOLS=file,shell,calculator,datetime
   # or disable specific tools
   CUSTOM_PROVIDER_1_TOOLS_DISABLE=web_search,fetch_url

   # Provider 2 tools (minimal set)
   CUSTOM_PROVIDER_2_TOOLS=file,calculator

   # Provider 3 tools (all)
   CUSTOM_PROVIDER_3_TOOLS=all
   ```

3. **Tool Management Commands**
   - `/tools available` - Show all available tools in system
   - `/tools enabled` - Show tools enabled for current provider
   - `/tools enable <tool>` - Enable specific tool for current session
   - `/tools disable <tool>` - Disable specific tool for current session
   - `/tools reset` - Reset to provider defaults

4. **Tool Categories**
   - `file` - File operations (read, search, list_directory)
   - `shell` - Shell command execution
   - `web` - Web operations (search, fetch_url)
   - `data` - Data tools (calculator, datetime)
   - `weather` - Weather information
   - `all` - All available tools

#### Implementation Plan

**Phase 1: Configuration Schema (1-2 hours)**
- [ ] Define tool configuration schema
- [ ] Create `parse_provider_tools()` function
- [ ] Add tool categories mapping
- [ ] Update provider config structure

**Phase 2: Tool Manager Enhancement (2-3 hours)**
- [ ] Modify `ToolManager` to support provider-specific tools
- [ ] Implement tool filtering based on provider config
- [ ] Add runtime enable/disable functionality
- [ ] Create tool category groups

**Phase 3: Commands (1-2 hours)**
- [ ] Implement `/tools available` command
- [ ] Implement `/tools enabled` command
- [ ] Implement `/tools enable/disable <tool>` commands
- [ ] Update `/tools` command help text

**Phase 4: Validation & Security (1 hour)**
- [ ] Validate tool names in configuration
- [ ] Prevent enabling unavailable tools
- [ ] Add warnings for dangerous tool combinations
- [ ] Implement tool access logging (optional)

**Phase 5: Testing (2 hours)**
- [ ] Test tool filtering per provider
- [ ] Test runtime enable/disable
- [ ] Test tool category groups
- [ ] Integration tests with multiple providers

**Phase 6: Documentation (1 hour)**
- [ ] Update TOOLS.md with configuration guide
- [ ] Add security best practices
- [ ] Document tool categories
- [ ] Update `.env.example`

**Estimated Total**: 8-11 hours

---

### v1.8.0: Enhanced Tool System (Priority: Low)

**Goal**: Improve tool capabilities and user experience

#### Features

1. **Tool Aliases**
   - Short aliases for frequently used tools
   - User-configurable aliases
   - Example: `ls` → `list_directory`, `calc` → `calculator`

2. **Tool Presets**
   - Pre-defined tool combinations for specific tasks
   - `coding` preset: file + shell + calculator
   - `research` preset: web + fetch_url + calculator + datetime
   - `admin` preset: shell + file + datetime
   - `safe` preset: calculator + datetime only

3. **Tool Execution History**
   - Track which tools are used
   - Usage statistics per tool
   - Most used tools dashboard
   - `/tools stats` command

4. **Interactive Tool Configuration**
   - `/tools wizard` - Interactive tool setup
   - Guided configuration for beginners
   - Test tool functionality before enabling

5. **Tool Plugins**
   - Support for custom user-defined tools
   - Tool plugin directory (`~/.ppxai/tools/`)
   - Hot-reload tool plugins
   - Tool marketplace (future consideration)

#### Implementation Plan

**Phase 1: Tool Aliases (1 hour)**
- [ ] Add alias configuration to tool definitions
- [ ] Implement alias resolution in command handler
- [ ] Update tool help to show aliases

**Phase 2: Tool Presets (2 hours)**
- [ ] Define preset configurations
- [ ] Implement preset loading
- [ ] Add `/tools preset <name>` command
- [ ] Create preset templates

**Phase 3: Usage Tracking (2 hours)**
- [ ] Add tool execution logging
- [ ] Create usage statistics storage
- [ ] Implement `/tools stats` command
- [ ] Add visualization for stats

**Phase 4: Interactive Configuration (2-3 hours)**
- [ ] Create tool configuration wizard
- [ ] Implement interactive prompts
- [ ] Add tool testing functionality
- [ ] Build guided setup flow

**Phase 5: Plugin System (4-5 hours)**
- [ ] Design plugin interface
- [ ] Implement plugin discovery
- [ ] Add plugin loading mechanism
- [ ] Create plugin template/examples
- [ ] Add plugin validation

**Phase 6: Testing & Docs (2 hours)**
- [ ] Test all new features
- [ ] Write plugin development guide
- [ ] Update documentation
- [ ] Create example plugins

**Estimated Total**: 13-16 hours

---

## Additional Future Considerations

### v2.0.0: Major Enhancements (Long-term)

1. **Advanced Session Management**
   - Session branching and merging
   - Session templates
   - Collaborative sessions (multi-user)

2. **Enhanced Streaming**
   - Real-time tool execution visualization
   - Progress indicators for long-running commands
   - Streaming token cost estimation

3. **Advanced Context Management**
   - Automatic context pruning
   - Smart context summarization
   - Context compression strategies

4. **Multi-Modal Support**
   - Image analysis tools
   - Document processing (PDF, DOCX)
   - Code screenshot analysis

5. **Workflow Automation**
   - Macro recording and playback
   - Scheduled tasks
   - Batch processing

6. **Performance Optimization**
   - Async tool execution
   - Tool result caching
   - Request batching

---

## Development Priorities

### Immediate (v1.6.0)
- ✅ **Must Have**: Multiple custom provider support
- ✅ **Must Have**: Provider switching commands
- ✅ **Should Have**: Provider management UI

### Short-term (v1.7.0)
- ✅ **Must Have**: Per-provider tool configuration
- ✅ **Should Have**: Tool categories
- ⚠️ **Nice to Have**: Runtime tool enable/disable

### Mid-term (v1.8.0)
- ⚠️ **Nice to Have**: Tool aliases
- ⚠️ **Nice to Have**: Tool presets
- ⚠️ **Nice to Have**: Usage statistics

### Long-term (v2.0.0+)
- 💡 **Future**: Plugin system
- 💡 **Future**: Multi-modal support
- 💡 **Future**: Workflow automation

---

## Contributing

Interested in working on any of these features?

1. Check the roadmap for the feature you want to implement
2. Create a feature branch: `git checkout -b feature/your-feature-name`
3. Follow the implementation plan outlined above
4. Write tests (maintain 100% pass rate)
5. Update documentation
6. Submit a pull request

---

## Notes

- All estimates are development time only (not including code review)
- Testing should maintain 100% test pass rate
- Documentation is mandatory for all new features
- Security considerations should be evaluated for each feature
- Backward compatibility must be maintained

---

**Last Updated**: November 28, 2025
**Current Version**: v1.5.0
**Next Target**: v1.6.0 (Multi-Provider Configuration)
