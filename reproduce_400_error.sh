#!/bin/bash
# Script to reproduce the 400 error with debug logging
#
# Usage: ./reproduce_400_error.sh
#
# This script runs ppxai and sends the exact sequence that causes the error:
# 1. Query without tools
# 2. Enable tools
# 3. Enable verbose mode
# 4. Query with tools (should trigger 400 error)
#
# The debug logs will show:
# - History synced to EngineClient (when /tools enable is called)
# - Messages being sent to API (before each request)

echo "=== Reproducing 400 Error with Debug Logging ==="
echo ""
echo "This will:"
echo "1. Send a query without tools"
echo "2. Enable tools (should show history sync)"
echo "3. Enable verbose mode"
echo "4. Send a query with tools (should show 400 error + debug logs)"
echo ""
echo "Press Ctrl-C to exit after seeing the error"
echo ""
echo "Starting ppxai..."
echo ""

# Set provider to avoid interactive prompt
export MODEL_PROVIDER=perplexity

# Run ppxai with the test sequence
uv run ppxai <<EOF
review the roadmap items
/tools enable
/tools set verbose on
use tools to review the current project
/exit
EOF
