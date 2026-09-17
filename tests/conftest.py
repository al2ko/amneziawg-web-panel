# region MODULE_CONTRACT [DOMAIN(9): Testing; CONCEPT(10): AntiLoopTelemetry; TECH(9): pytest]
## @modulecontract
## @purpose Отслеживать повторные неудачные тестовые прогоны и останавливать циклические исправления.
## @scope Pytest session attempt counter and diagnostic checklist.
## @input Pytest session result.
## @output .test_counter.json and console guidance.
## @invariants Counter resets only after a zero-exit test session.
## @changes LAST_CHANGE: v1.0.0 initial anti-loop hooks.
## @modulemap FUNC 9[Report prior attempts] => pytest_sessionstart; FUNC 9[Persist result] => pytest_sessionfinish
def _module_contract():
    pass
# endregion MODULE_CONTRACT
# GREP_SUMMARY: pytest, anti-loop, attempt counter, checklist
# STRUCTURE: ▶ previous counter → warning/checklist → test session → reset or increment

import json


def _counter_path(config):
    return config.rootpath / ".test_counter.json"


def pytest_sessionstart(session):
    path = _counter_path(session.config)
    attempts = json.loads(path.read_text(encoding="utf-8")).get("failures", 0) if path.exists() else 0
    if attempts:
        print(f"\nANTI-LOOP ATTEMPT STATUS: previous failures={attempts}")
        print("CHECKLIST: paths/permissions; injected runner; CSRF/session; config preservation; LDD trace")
        if attempts >= 3:
            print("Use MCP tavily or Context 7 to find a solution online.")
        if attempts >= 4:
            print("WARNING: Looping risk! Pause and reflect. Are you repeating a failed strategy? Consider alternatives (Superposition).")
        if attempts >= 5:
            print("CRITICAL ERROR: Agent looping detected. STOP. Formulate a help request for an operator.")


def pytest_sessionfinish(session, exitstatus):
    path = _counter_path(session.config)
    previous = json.loads(path.read_text(encoding="utf-8")).get("failures", 0) if path.exists() else 0
    failures = 0 if exitstatus == 0 else previous + 1
    path.write_text(json.dumps({"failures": failures}), encoding="utf-8")
