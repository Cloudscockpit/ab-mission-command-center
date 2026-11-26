# ActionBoard CLI internals

The public executable remains `../submit_mission.py`. Runtime dependencies are
Python 3.9+ standard library only.

- `common.py`: configuration files, defaults, diagnostics, shared edge context
- `auth.py`: credentials, tokens, login and Pod exchange
- `api.py`: proxy and GraphQL transport, read helpers
- `operations.py`: all GraphQL query and mutation documents
- `storage.py`: S3 signing, uploads and downloads
- `documents.py`: local mission documents, metadata and untrusted fetch boundaries
- `commands.py`: command handlers, selection, synchronization and argument parser

Cross-module imports inside functions keep authentication/transport dependencies
acyclic at import time. The compatibility entry point re-exports the original
symbols. Add new GraphQL documents to operations.py so the CI contract validator
includes them automatically.
