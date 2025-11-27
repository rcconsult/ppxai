"""
System prompts and templates for coding tasks.
"""

# System prompts for coding tasks
CODING_PROMPTS = {
    "generate": """You are an expert software engineer. Generate clean, efficient, and well-documented code based on the user's requirements. Follow these guidelines:
- Use best practices and design patterns appropriate for the language
- Include error handling where appropriate
- Add clear comments explaining complex logic
- Follow language-specific conventions and style guides
- Ensure code is production-ready and maintainable
- Include usage examples if helpful""",

    "test": """You are an expert in software testing. Generate comprehensive unit tests for the provided code. Follow these guidelines:
- Cover edge cases and error conditions
- Use appropriate testing framework for the language (pytest, jest, go test, etc.)
- Include both positive and negative test cases
- Test boundary conditions
- Ensure tests are independent and repeatable
- Add descriptive test names and comments
- Aim for high code coverage""",

    "docs": """You are a technical documentation expert. Generate clear, comprehensive documentation for the provided code. Include:
- Overview/purpose of the code
- Function/method signatures with parameter descriptions
- Return value descriptions
- Usage examples with code snippets
- Any important notes, warnings, or gotchas
- Dependencies or prerequisites
- Use appropriate documentation format (docstrings, JSDoc, GoDoc, etc.)""",

    "implement": """You are an expert software architect and engineer. Implement the requested feature with production-quality code. Follow these guidelines:
- Break down complex features into manageable components
- Use SOLID principles and clean code practices
- Include proper error handling and validation
- Add logging where appropriate
- Consider performance and scalability
- Provide clear code structure and organization
- Include inline comments for complex logic
- Suggest additional improvements or considerations""",

    "debug": """You are an expert debugger and problem solver. Analyze errors, exceptions, and bugs to provide clear solutions. Follow these guidelines:
- Identify the root cause of the error, not just symptoms
- Explain why the error occurred in simple terms
- Provide step-by-step solution with corrected code
- Suggest preventive measures to avoid similar issues
- Include relevant debugging techniques or tools
- Consider edge cases that might cause similar problems
- Explain any important concepts related to the bug""",

    "explain": """You are an expert code educator and technical communicator. Explain code logic, concepts, and implementations clearly. Follow these guidelines:
- Break down complex code into understandable steps
- Explain the "why" behind design decisions, not just the "what"
- Use analogies and examples to clarify difficult concepts
- Highlight key patterns, algorithms, or techniques used
- Point out important details that might be overlooked
- Explain dependencies and how components interact
- Relate concepts to real-world scenarios when helpful
- Focus on understanding, not just describing the code""",

    "convert": """You are an expert in multiple programming languages and cross-language translation. Convert code accurately between languages while maintaining functionality and idioms. Follow these guidelines:
- Preserve the original logic and behavior exactly
- Use idiomatic patterns and conventions for the target language
- Adapt data structures to target language equivalents
- Update imports, libraries, and dependencies appropriately
- Adjust error handling to target language standards
- Maintain or improve code quality in translation
- Add comments explaining significant translation decisions
- Highlight any limitations or differences in the conversion
- Suggest target language-specific improvements where beneficial"""
}

# Specification templates and guidelines
SPEC_GUIDELINES = """
# Specification Guidelines for Best Outcomes

Writing clear, detailed specifications helps generate better code implementations. Follow this structure:

## 1. Overview
- **What**: Brief description of what you're building
- **Why**: Purpose and problem it solves
- **Language/Framework**: Specify the technology stack

## 2. Requirements
### Functional Requirements
- List specific features and behaviors
- Define input/output expectations
- Specify data structures and formats

### Non-Functional Requirements
- Performance expectations
- Security considerations
- Scalability needs
- Error handling requirements

## 3. Technical Details
- API signatures or interfaces
- Data models/schemas
- External dependencies
- Configuration needs

## 4. Constraints & Assumptions
- Platform limitations
- Library/version constraints
- Assumptions about the environment

## 5. Examples
- Sample inputs and expected outputs
- Usage scenarios
- Edge cases to consider

---

## Quick Templates

Use `/spec <type>` to see templates for specific implementation types:
- `/spec api` - REST API endpoint
- `/spec cli` - Command-line tool
- `/spec lib` - Library/module
- `/spec algo` - Algorithm implementation
- `/spec ui` - UI component
"""

SPEC_TEMPLATES = {
    "api": """
**REST API Endpoint Specification Template:**

**Endpoint**: [HTTP_METHOD] /api/v1/resource
**Purpose**: [What this endpoint does]

**Authentication**: [Required/Optional, type]

**Request:**
- Headers: [Content-Type, Authorization, etc.]
- Body Schema:
  ```json
  {
    "field1": "type (description)",
    "field2": "type (description)"
  }
  ```

**Response:**
- Success (200):
  ```json
  {
    "data": {},
    "message": "Success"
  }
  ```
- Error (4xx/5xx):
  ```json
  {
    "error": "Error message"
  }
  ```

**Validation Rules**: [List validation requirements]
**Business Logic**: [Describe the processing steps]
**Error Handling**: [How to handle specific errors]

**Example Request:**
```bash
curl -X POST /api/v1/resource \\
  -H "Content-Type: application/json" \\
  -d '{"field1": "value"}'
```
""",

    "cli": """
**CLI Tool Specification Template:**

**Command**: program-name [command] [options] [arguments]
**Purpose**: [What this tool does]

**Commands:**
- `command1` - [Description]
- `command2` - [Description]

**Options:**
- `-f, --flag`: [Description, default value]
- `-o, --option <value>`: [Description]

**Arguments:**
- `arg1`: [Description, required/optional]

**Input/Output:**
- Input: [stdin, files, arguments]
- Output: [stdout, files, exit codes]

**Error Handling:**
- Exit code 0: Success
- Exit code 1: [Error type]
- Exit code 2: [Error type]

**Examples:**
```bash
program-name command1 --flag value arg1
program-name command2 -o option < input.txt > output.txt
```

**Dependencies**: [Required libraries, system tools]
**Configuration**: [Config files, environment variables]
""",

    "lib": """
**Library/Module Specification Template:**

**Module Name**: module_name
**Purpose**: [What this library provides]
**Language**: [Python, JavaScript, Go, etc.]

**Public API:**

1. **Function/Class**: `name(param1, param2)`
   - Purpose: [What it does]
   - Parameters:
     - `param1` (type): [Description]
     - `param2` (type): [Description]
   - Returns: [Type and description]
   - Raises: [Exceptions/errors]
   - Example:
     ```python
     result = name(value1, value2)
     ```

2. **Function/Class**: [Repeat for each public interface]

**Internal Architecture:**
- [Key components and their relationships]

**Dependencies**: [External libraries needed]
**Thread Safety**: [If applicable]
**Performance Characteristics**: [Time/space complexity]

**Usage Example:**
```python
from module_name import ClassName

obj = ClassName(config)
result = obj.method(args)
```
""",

    "algo": """
**Algorithm Specification Template:**

**Algorithm Name**: [Name or description]
**Purpose**: [Problem it solves]
**Language**: [Preferred language]

**Input:**
- Type: [Array, tree, graph, etc.]
- Constraints: [Size limits, value ranges]
- Format: [Specific structure]

**Output:**
- Type: [What the algorithm returns]
- Format: [Structure of the result]

**Requirements:**
- Time Complexity: [Target: O(n log n), etc.]
- Space Complexity: [Target: O(1), O(n), etc.]
- Special Constraints: [In-place, iterative vs recursive]

**Algorithm Approach:**
[High-level description of the approach]
- Step 1: [Description]
- Step 2: [Description]
- Step 3: [Description]

**Edge Cases to Handle:**
- Empty input
- Single element
- Duplicate values
- [Other specific cases]

**Test Cases:**
```
Input: [1, 2, 3]
Output: [expected]

Input: []
Output: [expected]

Input: [edge case]
Output: [expected]
```
""",

    "ui": """
**UI Component Specification Template:**

**Component Name**: ComponentName
**Purpose**: [What this component displays/does]
**Framework**: [React, Vue, Angular, etc.]

**Props/Inputs:**
- `prop1` (type, required/optional): [Description, default]
- `prop2` (type, required/optional): [Description, default]

**State Management:**
- [Internal state needed]
- [External state/store]

**Events/Callbacks:**
- `onEvent1`: [When triggered, parameters]
- `onEvent2`: [When triggered, parameters]

**Visual Design:**
- Layout: [Describe structure]
- Styling: [CSS approach, theme]
- Responsive: [Mobile/desktop behavior]

**Behavior:**
- User Interactions: [Click, hover, etc.]
- Loading States: [How to show loading]
- Error States: [How to display errors]

**Accessibility:**
- ARIA labels
- Keyboard navigation
- Screen reader support

**Example Usage:**
```jsx
<ComponentName
  prop1="value"
  prop2={data}
  onEvent1={handler}
/>
```
"""
}
