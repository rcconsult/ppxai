"""
JSON-RPC server for VS Code extension integration.

This module provides backward compatibility by importing from the new server location.
The actual implementation is now in ppxai/server/jsonrpc.py using the new engine layer.
"""

# Re-export from new location for backward compatibility
from .server.jsonrpc import JsonRpcServer, main

__all__ = ["JsonRpcServer", "main"]

if __name__ == "__main__":
    main()
