---
provider_hints:
  custom:
    - "You have native tool calling - use tools directly without XML formatting."
    - "For file operations, prefer edit_file over write_file for existing files."
model_hints:
  "qwen3*":
    - "You are a strong coding model - prioritize working code over explanations."
    - "Execute tools immediately rather than describing what you would do."
    - "Use edit_file for surgical changes, write_file only for new files."
  "gpt-oss*":
    - "You are a coding specialist - prioritize working code over explanations."
    - "Execute tools immediately rather than describing what you would do."
  "Qwen/Qwen3-Coder*":
    - "You are a code-specialized model - prioritize working code over explanations."
    - "Execute tools immediately rather than describing what you would do."
    - "Use edit_file for surgical changes, write_file only for new files."
    - "You have native tool calling via qwen3_coder parser - use tools directly."
  "Qwen/Qwen3-Next*":
    - "You are a hybrid attention MoE model - use your extended context efficiently."
    - "Execute tools immediately rather than describing what you would do."
    - "Use edit_file for surgical changes, write_file only for new files."
  "RedHatAI/*":
    - "Execute tools immediately rather than describing what you would do."
    - "Use edit_file for surgical changes, write_file only for new files."
---

# Web Tools & Corporate Proxy Support

- `SSL_VERIFY=false` disables SSL certificate verification
- `SSL_CERT_FILE=/path/to/cert.pem` loads a custom CA certificate
- Timeouts configurable via `tools.<name>.timeout` in ppxai-config.json (default: 15s)
