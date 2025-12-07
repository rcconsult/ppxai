"""
Server interfaces for the ppxai engine.

Provides JSON-RPC, HTTP, and WebSocket servers for IDE integration.
"""

from .jsonrpc import JsonRpcServer, main

__all__ = ["JsonRpcServer", "main"]
