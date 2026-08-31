# API And Privacy

The analyzer can run fully locally for normal exports.

API mode is optional. It sends extracted report data to the configured OpenAI-compatible chat endpoint to produce classified tables. It is designed to avoid gameplay advice, prediction, and subjective analysis unless the user asks for that.

Local API configuration:

```text
C:\Users\<username>\.vic3-save-analyzer\api_config.json
```

The API key is hidden during input and stored locally with light base64 obfuscation. This is convenience storage, not strong encryption. Do not commit this file.

The project `.gitignore` excludes saves, generated reports, local API configs, local community clones, and backup files.
