# Agent OS Code-OSS distribution

This directory contains the tracked overlay for the Agent OS desktop IDE. It does not vendor a generated Code-OSS checkout.

```bash
node apps/code-oss/scripts/bootstrap.mjs
node apps/code-oss/scripts/install.mjs
node apps/code-oss/scripts/verify.mjs
cd .code-oss/upstream
npm install
npm run watch
./scripts/code.sh
```

`bootstrap.mjs` checks out the exact MIT Code-OSS revision from `upstream.lock.json` and installs `extensions/agent-os` as a built-in extension. The checkout lives under `.code-oss/` and is reproducible.

The existing Tauri application is a Surface/reference implementation during migration. It is not the IDE runtime.
