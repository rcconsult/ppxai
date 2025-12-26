#!/usr/bin/env node

/**
 * Example MCP Server for ppxai
 *
 * This demonstrates how to create a custom MCP server with tools.
 * This example provides text manipulation tools.
 */

import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";

// Create the MCP server
const server = new Server(
  {
    name: "example-text-tools",
    version: "1.0.0",
  },
  {
    capabilities: {
      tools: {},
    },
  }
);

// Define available tools
server.setRequestHandler("tools/list", async () => {
  return {
    tools: [
      {
        name: "reverse_text",
        description: "Reverse the characters in a text string",
        inputSchema: {
          type: "object",
          properties: {
            text: {
              type: "string",
              description: "Text to reverse",
            },
          },
          required: ["text"],
        },
      },
      {
        name: "count_words",
        description: "Count words, characters, and lines in text",
        inputSchema: {
          type: "object",
          properties: {
            text: {
              type: "string",
              description: "Text to analyze",
            },
          },
          required: ["text"],
        },
      },
      {
        name: "to_uppercase",
        description: "Convert text to uppercase",
        inputSchema: {
          type: "object",
          properties: {
            text: {
              type: "string",
              description: "Text to convert",
            },
          },
          required: ["text"],
        },
      },
      {
        name: "to_lowercase",
        description: "Convert text to lowercase",
        inputSchema: {
          type: "object",
          properties: {
            text: {
              type: "string",
              description: "Text to convert",
            },
          },
          required: ["text"],
        },
      },
    ],
  };
});

// Handle tool execution
server.setRequestHandler("tools/call", async (request) => {
  const { name, arguments: args } = request.params;

  try {
    let result;

    switch (name) {
      case "reverse_text":
        result = args.text.split("").reverse().join("");
        break;

      case "count_words":
        const lines = args.text.split("\n");
        const words = args.text.split(/\s+/).filter((w) => w.length > 0);
        const chars = args.text.length;

        result = `Statistics for text:\n`;
        result += `  Lines: ${lines.length}\n`;
        result += `  Words: ${words.length}\n`;
        result += `  Characters: ${chars}\n`;
        break;

      case "to_uppercase":
        result = args.text.toUpperCase();
        break;

      case "to_lowercase":
        result = args.text.toLowerCase();
        break;

      default:
        throw new Error(`Unknown tool: ${name}`);
    }

    return {
      content: [
        {
          type: "text",
          text: result,
        },
      ],
    };
  } catch (error) {
    return {
      content: [
        {
          type: "text",
          text: `Error: ${error.message}`,
        },
      ],
      isError: true,
    };
  }
});

// Start the server
const transport = new StdioServerTransport();
await server.connect(transport);

console.error("Example MCP Server running on stdio");
