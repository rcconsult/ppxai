# Specification Guidelines for Code Generation

This guide helps you write effective specifications for the `/implement` command in ppxai. Well-structured specifications lead to better, more accurate code implementations.

## Table of Contents

- [Quick Start](#quick-start)
- [General Guidelines](#general-guidelines)
- [Specification Templates](#specification-templates)
  - [REST API Endpoint](#rest-api-endpoint)
  - [CLI Tool](#cli-tool)
  - [Library/Module](#librarymodule)
  - [Algorithm](#algorithm)
  - [UI Component](#ui-component)
- [Best Practices](#best-practices)
- [Examples](#examples)

## Quick Start

In ppxai, use the `/spec` command to access specification guidelines and templates:

```bash
# Show general guidelines
/spec

# Show specific template
/spec api      # REST API endpoint template
/spec cli      # Command-line tool template
/spec lib      # Library/module template
/spec algo     # Algorithm template
/spec ui       # UI component template
```

## General Guidelines

A well-written specification should include these five key sections:

### 1. Overview
- **What**: Brief description of what you're building
- **Why**: Purpose and problem it solves
- **Language/Framework**: Specify the technology stack

### 2. Requirements

#### Functional Requirements
- List specific features and behaviors
- Define input/output expectations
- Specify data structures and formats

#### Non-Functional Requirements
- Performance expectations
- Security considerations
- Scalability needs
- Error handling requirements

### 3. Technical Details
- API signatures or interfaces
- Data models/schemas
- External dependencies
- Configuration needs

### 4. Constraints & Assumptions
- Platform limitations
- Library/version constraints
- Assumptions about the environment

### 5. Examples
- Sample inputs and expected outputs
- Usage scenarios
- Edge cases to consider

---

## Specification Templates

### REST API Endpoint

Use this template when implementing HTTP/REST API endpoints:

```markdown
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
curl -X POST /api/v1/resource \
  -H "Content-Type: application/json" \
  -d '{"field1": "value"}'
```
```

**Example Usage:**

```bash
/implement **Endpoint**: POST /api/v1/users
**Purpose**: Create a new user account
**Language**: Python with Flask

**Authentication**: Required (JWT token in Authorization header)

**Request:**
- Headers: Content-Type: application/json, Authorization: Bearer <token>
- Body Schema:
  ```json
  {
    "email": "string (valid email address)",
    "username": "string (3-20 chars, alphanumeric)",
    "password": "string (min 8 chars, must include number and special char)"
  }
  ```

**Response:**
- Success (201):
  ```json
  {
    "id": "uuid",
    "email": "string",
    "username": "string",
    "created_at": "ISO 8601 timestamp"
  }
  ```
- Error (400):
  ```json
  {
    "error": "Email already exists"
  }
  ```

**Validation Rules**:
- Email must be valid format and unique
- Username must be 3-20 characters, alphanumeric only, unique
- Password must be at least 8 characters with one number and one special character

**Business Logic**:
1. Validate input format and constraints
2. Check if email/username already exists in database
3. Hash password using bcrypt
4. Create user record in PostgreSQL database
5. Return created user (without password)

**Error Handling**:
- 400: Invalid input or duplicate email/username
- 401: Invalid/missing JWT token
- 500: Database connection errors
```

---

### CLI Tool

Use this template for command-line applications and tools:

```markdown
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
```

**Example Usage:**

```bash
/implement **Command**: gitstat [--detailed] [--format json|text] [path]
**Purpose**: Analyze Git repository statistics and generate reports
**Language**: Python 3.8+

**Options:**
- `-d, --detailed`: Show detailed statistics including file-by-file analysis
- `-f, --format <format>`: Output format (json or text), default: text
- `--since <date>`: Show statistics since date (ISO format: YYYY-MM-DD)
- `--author <name>`: Filter by author name

**Arguments:**
- `path`: Path to Git repository (optional, default: current directory)

**Output:**
- stdout: Statistics report in specified format
- Exit code 0: Success
- Exit code 1: Invalid repository or path
- Exit code 2: Invalid arguments

**Output Format (text):**
```
Repository Statistics
====================
Total Commits: 150
Contributors: 5
Files Changed: 45
Insertions: +2,340
Deletions: -890
...
```

**Output Format (json):**
```json
{
  "total_commits": 150,
  "contributors": 5,
  "files_changed": 45,
  "insertions": 2340,
  "deletions": 890
}
```

**Examples:**
```bash
gitstat
gitstat --detailed --format json ~/my-project
gitstat --since 2024-01-01 --author "John Doe"
```

**Dependencies**: GitPython, click
**Error Handling**: Clear error messages for invalid paths, missing dependencies
```

---

### Library/Module

Use this template for reusable libraries, packages, or modules:

```markdown
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
```

**Example Usage:**

```bash
/implement **Module Name**: rate_limiter
**Purpose**: Flexible rate limiting library with multiple algorithms
**Language**: Python 3.8+

**Public API:**

1. **Class**: `RateLimiter(algorithm='token_bucket', rate=100, period=60)`
   - Purpose: Create a rate limiter instance
   - Parameters:
     - `algorithm` (str): Algorithm to use ('token_bucket', 'sliding_window', 'fixed_window')
     - `rate` (int): Number of allowed requests
     - `period` (int): Time period in seconds
   - Example:
     ```python
     limiter = RateLimiter(algorithm='token_bucket', rate=100, period=60)
     ```

2. **Method**: `allow(key: str) -> bool`
   - Purpose: Check if request should be allowed
   - Parameters:
     - `key` (str): Identifier for the requester (e.g., user_id, ip_address)
   - Returns: bool - True if allowed, False if rate limit exceeded
   - Example:
     ```python
     if limiter.allow('user_123'):
         # Process request
         pass
     else:
         # Return 429 Too Many Requests
         pass
     ```

3. **Method**: `reset(key: str) -> None`
   - Purpose: Reset the rate limit counter for a specific key
   - Parameters:
     - `key` (str): Identifier to reset

**Internal Architecture:**
- Abstract base class `RateLimitAlgorithm`
- Concrete implementations: `TokenBucket`, `SlidingWindow`, `FixedWindow`
- In-memory storage using dict (can be extended to Redis)

**Dependencies**: None (stdlib only)
**Thread Safety**: Yes, uses threading.Lock
**Performance**: O(1) for allow() checks

**Usage Example:**
```python
from rate_limiter import RateLimiter

# Create limiter: 100 requests per minute
limiter = RateLimiter(rate=100, period=60)

# In your web handler
def handle_request(user_id):
    if not limiter.allow(user_id):
        return {"error": "Rate limit exceeded"}, 429

    # Process normal request
    return {"data": "..."}, 200
```
```

---

### Algorithm

Use this template for algorithm implementations:

```markdown
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
```

**Example Usage:**

```bash
/implement **Algorithm Name**: Quick Select (k-th smallest element)
**Purpose**: Find the k-th smallest element in an unsorted array
**Language**: Python

**Input:**
- Type: Array of integers
- Constraints: 1 <= array length <= 10^5, -10^9 <= values <= 10^9
- Format: List[int], and integer k (1-indexed)

**Output:**
- Type: Single integer (k-th smallest element)

**Requirements:**
- Time Complexity: O(n) average case, O(n²) worst case
- Space Complexity: O(1) - in-place algorithm preferred
- Use Hoare's partition scheme for efficiency

**Algorithm Approach:**
1. Use quicksort's partition logic
2. After partitioning, determine which side contains k-th element
3. Recursively partition only the relevant side
4. Return element when pivot position equals k

**Edge Cases to Handle:**
- k = 1 (minimum element)
- k = n (maximum element)
- Array with all same elements
- Array with two elements
- Empty array (should raise error)
- k out of bounds (should raise error)

**Test Cases:**
```
Input: [3, 2, 1, 5, 6, 4], k=2
Output: 2

Input: [3, 2, 3, 1, 2, 4, 5, 5, 6], k=4
Output: 3

Input: [1], k=1
Output: 1

Input: [5, 5, 5, 5], k=2
Output: 5
```
```

---

### UI Component

Use this template for user interface components:

```markdown
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
```

**Example Usage:**

```bash
/implement **Component Name**: UserAvatar
**Purpose**: Display user avatar with status indicator and tooltip
**Framework**: React 18 with TypeScript

**Props:**
- `user` (User, required): User object with {id, name, avatarUrl, status}
- `size` ('small' | 'medium' | 'large', optional): Avatar size, default: 'medium'
- `showStatus` (boolean, optional): Show online status indicator, default: true
- `onClick` ((userId: string) => void, optional): Click handler

**State Management:**
- Internal state: `isImageLoaded` (boolean)
- Internal state: `showTooltip` (boolean)
- No external state needed

**Visual Design:**
- Layout: Circular avatar with status dot in bottom-right corner
- Styling: CSS modules, supports light/dark theme
- Sizes: small (32px), medium (48px), large (64px)
- Responsive: Scales proportionally on mobile
- Status colors: green (online), yellow (away), gray (offline)

**Behavior:**
- Hover: Show tooltip with user name and status
- Click: Call onClick handler if provided
- Loading: Show skeleton loader while image loads
- Error: Show fallback with user initials if image fails

**Accessibility:**
- ARIA label: "Avatar of {username}, status: {status}"
- Keyboard navigation: Focusable if onClick provided
- High contrast mode support
- Screen reader announces status changes

**Example Usage:**
```tsx
<UserAvatar
  user={{
    id: '123',
    name: 'John Doe',
    avatarUrl: 'https://example.com/avatar.jpg',
    status: 'online'
  }}
  size="medium"
  showStatus={true}
  onClick={(userId) => console.log('Clicked:', userId)}
/>
```

**Error Handling:**
- Broken image: Display user initials (first + last name)
- Missing name: Display "?" as fallback
- Invalid size: Default to 'medium'
```

---

## Best Practices

### 1. Be Specific
❌ **Bad**: "Create a function that sorts data"
✅ **Good**: "Create a merge sort function that sorts an array of integers in ascending order with O(n log n) time complexity"

### 2. Include Context
❌ **Bad**: "Make a login endpoint"
✅ **Good**: "Create a POST /api/v1/auth/login endpoint using Express.js that accepts email/password, validates against PostgreSQL, and returns a JWT token"

### 3. Specify Error Handling
❌ **Bad**: "Handle errors"
✅ **Good**: "Return 400 for invalid input with specific field errors, 401 for invalid credentials, 500 for database errors with generic message"

### 4. Provide Examples
Always include:
- Example inputs and expected outputs
- Edge cases
- Common usage scenarios

### 5. Define Performance Requirements
When relevant, specify:
- Time complexity expectations
- Space complexity constraints
- Scalability needs

### 6. Mention Dependencies
List:
- Required libraries/packages
- Framework versions
- External services

---

## Examples

### Example 1: Simple Function

**Bad Specification:**
```
Create a function to validate emails
```

**Good Specification:**
```
Create an email validation function in Python that:
- Accepts a string input
- Returns True if valid email format, False otherwise
- Validates using regex: username@domain.extension
- Username: alphanumeric plus dots, hyphens, underscores
- Domain: alphanumeric plus hyphens
- Extension: 2-6 alphabetic characters
- Case insensitive
- Examples:
  - "user@example.com" → True
  - "user.name+tag@example.co.uk" → True
  - "invalid@" → False
  - "@example.com" → False
```

### Example 2: Complex Feature

**Bad Specification:**
```
Implement file upload
```

**Good Specification:**
```
Implement file upload endpoint in Node.js/Express with:

**Endpoint**: POST /api/v1/upload
**Authentication**: Required (JWT)

**Request:**
- multipart/form-data
- Field: "file" (single file)
- Max size: 10MB
- Allowed types: PDF, DOCX, TXT

**Process:**
1. Validate file type and size
2. Generate unique filename (UUID + timestamp)
3. Upload to AWS S3 bucket "documents"
4. Store metadata in MongoDB: {userId, filename, s3Key, uploadedAt, fileSize}
5. Return document ID and download URL

**Response:**
- Success (200): {id, filename, url, uploadedAt}
- Error (400): "Invalid file type" or "File too large"
- Error (401): "Unauthorized"
- Error (500): "Upload failed"

**Dependencies**: multer, aws-sdk, mongodb
**Error Handling**: Clean up partial uploads on failure
```

---

## Getting Help

- Use `/spec` in ppxai to view these guidelines
- Use `/spec <type>` to see specific templates
- Start with a template and customize for your needs
- Include as much detail as possible for best results

## Contributing

Found a way to improve these specifications? Contributions are welcome! Please submit a pull request or open an issue.
