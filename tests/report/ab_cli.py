"""The ActionBoard CLI from packages/actionboard-mcp, importable by the report tests.

`submit_mission` is every CLI module's names in one namespace, as the retired
src/skills/mission-report/scripts/submit_mission.py entry point exposed them.
"""
import os
import sys
import types

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PACKAGE_SRC = os.path.join(ROOT, "packages", "actionboard-mcp", "src")
sys.path.insert(0, PACKAGE_SRC)

from actionboard_mcp.actionboard_cli import (  # noqa: E402
    api, auth, commands, common, documents, keychain, operations, storage)

submit_mission = types.SimpleNamespace(**{
    name: value
    for module in (operations, storage, documents, common, keychain, auth, api, commands)
    for name, value in vars(module).items() if not name.startswith("__")
})
