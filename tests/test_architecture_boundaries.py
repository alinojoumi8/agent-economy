from importlib import import_module
from inspect import signature


RETAINED_SYMBOLS = {
    "hosted.auth": (
        "AuthFailure",
        "LoginThrottlePolicy",
        "SessionCredentials",
        "UserRecord",
    ),
    "engine.types": (
        "ActionEnvelope",
        "Clause",
        "ValidationError",
    ),
    "agents.passports": (
        "LocalCitizenshipService",
        "SqlitePassportRepository",
    ),
}

REMOVED_SYMBOLS = {
    "hosted.auth": (
        "AuthService",
        "AuthStore",
        "InviteRecord",
        "PendingUser",
        "SessionRecord",
        "AuthenticatedSession",
        "login_throttle_key",
    ),
    "engine.types": (
        "Money",
        "Contract",
        "Obligation",
        "LegalMatter",
        "LegalDecision",
        "Claim",
        "InformationExposure",
        "Bill",
        "PolicyRuleChange",
        "Region",
        "FxOrder",
        "DatasetManifest",
        "ScenarioPack",
    ),
    "agents.passports": ("PassportRepository",),
}


def test_retained_architecture_symbols_remain_importable():
    for module_name, symbol_names in RETAINED_SYMBOLS.items():
        module = import_module(module_name)
        missing = [name for name in symbol_names if not hasattr(module, name)]
        assert not missing, f"{module_name} no longer exposes {missing}"


def test_removed_architecture_symbols_do_not_return():
    for module_name, symbol_names in REMOVED_SYMBOLS.items():
        module = import_module(module_name)
        restored = [name for name in symbol_names if hasattr(module, name)]
        assert not restored, f"{module_name} restored retired symbols {restored}"

    passports = import_module("agents.passports")
    parameters = signature(passports.LocalCitizenshipService).parameters
    assert "repository" not in parameters
