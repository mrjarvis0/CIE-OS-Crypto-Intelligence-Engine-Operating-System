"""
CIE-OS
A01 Blockchain Intelligence Agent

Tests for the plugin extensibility layer.

The layer's job is to let untrusted code extend A01 without touching the core,
so the cases that matter most are the refusals: an unsigned package, an
untrusted publisher, a capability nobody granted, a removal that would strand a
dependent. A plugin framework that installs whatever it is handed is not an
extension point, it is an execution primitive.

Every module here is synchronous -- nothing in the package awaits -- so these
are plain ``def`` tests rather than the ``async def`` form the rest of the suite
uses.

Two tests below pin behaviour that is wrong on purpose. They are marked in
their docstrings and listed again at the bottom of this module: a defect nobody
has written down gets rediscovered, and a defect asserted without a note gets
mistaken for the intended contract.
"""

from __future__ import annotations

import pytest

from tools.governance.signing import SigningKey
from tools.plugins import (
    Plugin,
    PluginError,
    PluginInstaller,
    PluginLoader,
    PluginManager,
    PluginManifest,
    PluginRecord,
    PluginRegistry,
    PluginState,
    PluginUninstaller,
    PluginUpdater,
    PluginValidator,
    Sandbox,
    SandboxLimits,
)

PUBLISHER = "acme"
SECRET = "signing-secret"


def key() -> SigningKey:
    return SigningKey(PUBLISHER, SECRET)


def manifest(
    plugin_id: str = "demo",
    *,
    version: str = "1.0.0",
    capabilities: list[str] | None = None,
    permissions: list[str] | None = None,
    dependencies: list[str] | None = None,
) -> PluginManifest:
    return PluginManifest(
        id=plugin_id,
        name=plugin_id.title(),
        version=version,
        publisher=PUBLISHER,
        capabilities=list(capabilities or ["read"]),
        permissions=list(permissions or []),
        dependencies=list(dependencies or []),
    )


def trusting_validator() -> PluginValidator:
    validator = PluginValidator()
    validator.trust_publisher(PUBLISHER, key())
    return validator


def installed(
    plugin_manifest: PluginManifest | None = None,
) -> tuple[PluginRegistry, PluginManifest]:
    """A registry holding one signed, installed, activated plugin."""
    plugin_manifest = plugin_manifest or manifest()
    registry = PluginRegistry()
    installer = PluginInstaller(registry=registry, validator=trusting_validator())
    installer.install(
        plugin_manifest,
        signature=key().sign_payload(plugin_manifest.as_dict()),
        publisher=PUBLISHER,
    )
    return registry, plugin_manifest


# ==============================================================================
# PLUGIN
# ==============================================================================


def test_ping_answers_with_identity_and_version():
    """
    The one action the base class implements. It is how a caller checks that a
    plugin loaded and is the build they expected, so it has to answer without
    the plugin having overridden anything.
    """
    result = Plugin(plugin_id="demo", version="2.1.0").execute("ping")

    assert result == {"plugin_id": "demo", "version": "2.1.0"}


def test_an_unimplemented_action_names_the_plugin_and_the_action():
    """
    The documented error signal for an action a subclass did not implement.

    Both names belong in the message: a bare NotImplementedError surfacing from
    a sandbox tells an operator that *something* in the plugin chain is
    unimplemented, which is the least useful true statement available when
    several plugins are loaded.
    """
    plugin = Plugin(plugin_id="demo")

    with pytest.raises(NotImplementedError) as caught:
        plugin.execute("analyze")

    assert "demo" in str(caught.value)
    assert "analyze" in str(caught.value)


def test_a_subclass_keeps_ping_while_adding_its_own_actions():
    """
    Overriding ``execute`` must not cost the identity check, so a subclass
    delegates unknown actions upward rather than replacing the base behaviour.
    """

    class Analyzer(Plugin):
        def execute(self, action, params=None):
            if action == "analyze":
                return {"analyzed": dict(params or {})}
            return super().execute(action, params)

    plugin = Analyzer(plugin_id="analyzer")

    assert plugin.execute("analyze", {"address": "0xabc"}) == {
        "analyzed": {"address": "0xabc"}
    }
    assert plugin.execute("ping")["plugin_id"] == "analyzer"


def test_a_plugin_without_a_name_falls_back_to_its_id():
    """A nameless plugin should still be identifiable in a listing."""
    assert Plugin(plugin_id="demo").name == "demo"
    assert Plugin(plugin_id="demo", name="Demo").name == "Demo"


def test_as_dict_carries_the_fields_a_listing_needs():
    plugin = Plugin(
        plugin_id="demo",
        version="1.2.0",
        publisher=PUBLISHER,
        capabilities=["read"],
        permissions=["net"],
    )

    described = plugin.as_dict()

    assert described["plugin_id"] == "demo"
    assert described["version"] == "1.2.0"
    assert described["capabilities"] == ["read"]
    assert described["permissions"] == ["net"]
    assert described["state"] == PluginState.DISCOVERED


# ==============================================================================
# LIFECYCLE
# ==============================================================================


def test_a_plugin_starts_discovered():
    """
    Not ``installed``. The distinction is the whole point of the enum: a plugin
    that has been seen is not a plugin that has been vetted, and starting
    anywhere further along would let an unvalidated package look admitted.
    """
    assert Plugin(plugin_id="demo").state == PluginState.DISCOVERED


def test_the_lifecycle_hooks_advance_the_state():
    plugin = Plugin(plugin_id="demo")

    plugin.initialize()
    assert plugin.state == PluginState.CONFIGURED

    plugin.activate()
    assert plugin.state == PluginState.ACTIVATED

    plugin.deactivate("operator request")
    assert plugin.state == PluginState.DISABLED

    plugin.shutdown()
    assert plugin.state == PluginState.UNINSTALLED


def test_reactivation_after_a_deactivation_is_allowed():
    """
    Disabling is reversible; uninstalling is not. An operator who disables a
    noisy plugin has to be able to switch it back on without reinstalling it.
    """
    plugin = Plugin(plugin_id="demo")

    plugin.activate()
    plugin.deactivate()
    plugin.activate()

    assert plugin.state == PluginState.ACTIVATED


def test_every_state_constant_is_a_known_state():
    """
    The constants and the tuple they were written from can drift apart, and a
    state that exists on the class but not in the vocabulary is one that no
    filter or dashboard will ever match.
    """
    from tools.plugins.plugin import _PLUGIN_STATES

    declared = {
        value
        for name, value in vars(PluginState).items()
        if not name.startswith("_") and isinstance(value, str)
    }

    assert declared == set(_PLUGIN_STATES)


# ==============================================================================
# MANIFEST
# ==============================================================================


def test_a_manifest_parses_from_a_mapping():
    parsed = PluginManifest.from_dict(
        {
            "id": "demo",
            "name": "Demo",
            "version": "2.0.0",
            "capabilities": ["read", "write"],
            "dependencies": ["base"],
        }
    )

    assert parsed.id == "demo"
    assert parsed.version == "2.0.0"
    assert parsed.capabilities == ["read", "write"]
    assert parsed.dependencies == ["base"]
    assert parsed.license == "MIT"


def test_missing_fields_names_what_is_absent():
    """
    Reported as a list rather than a boolean, because "invalid manifest" sends
    a publisher hunting through a file that may only be missing one key.
    """
    assert PluginManifest.from_dict({"id": "demo"}).missing_fields() == ["name"]
    assert PluginManifest.from_dict({}).missing_fields() == ["id", "name"]
    assert manifest().missing_fields() == []


# ==============================================================================
# VALIDATION
# ==============================================================================


def test_an_unsigned_plugin_is_rejected():
    """
    The zero-trust default. An unsigned package is refused rather than admitted
    with a warning, because a warning at install time is read once and a plugin
    runs forever.
    """
    result = PluginValidator().validate(manifest().as_dict())

    assert not result.passed
    assert result.checks["signature"] is False
    assert "plugin unsigned" in result.failures


def test_a_signature_from_an_untrusted_publisher_is_rejected():
    """
    A valid signature is not an identity claim on its own -- anyone can sign
    anything with their own key. Trust has to be established out of band, and
    the publisher naming itself in the manifest is not that.
    """
    package = manifest()
    signature = key().sign_payload(package.as_dict())

    result = PluginValidator().validate(
        package.as_dict(), signature=signature, publisher=PUBLISHER
    )

    assert not result.passed
    assert "not trusted" in result.failures[0]


def test_a_signed_plugin_from_a_trusted_publisher_passes():
    package = manifest()

    result = trusting_validator().validate(
        package.as_dict(),
        signature=key().sign_payload(package.as_dict()),
        publisher=PUBLISHER,
    )

    assert result.passed
    assert all(result.checks.values())
    assert result.failures == []


def test_a_tampered_manifest_fails_verification():
    """
    The signature covers the manifest, so editing the manifest after signing --
    to widen a capability, say -- has to invalidate it.
    """
    package = manifest()
    signature = key().sign_payload(package.as_dict())

    tampered = package.as_dict()
    tampered["capabilities"] = ["read", "write", "admin"]

    result = trusting_validator().validate(
        tampered, signature=signature, publisher=PUBLISHER
    )

    assert not result.passed
    assert "signature invalid" in result.failures


def test_a_capability_outside_the_allowlist_is_named():
    package = manifest(capabilities=["read", "admin"])

    result = trusting_validator().validate(
        package.as_dict(),
        signature=key().sign_payload(package.as_dict()),
        publisher=PUBLISHER,
        allowed_capabilities=["read"],
    )

    assert not result.passed
    assert "admin" in result.failures[0]


def test_a_permission_outside_the_allowlist_is_named():
    package = manifest(permissions=["net", "fs"])

    result = trusting_validator().validate(
        package.as_dict(),
        signature=key().sign_payload(package.as_dict()),
        publisher=PUBLISHER,
        allowed_permissions=["net"],
    )

    assert not result.passed
    assert "fs" in result.failures[0]


def test_no_allowlist_means_no_capability_gate():
    """
    Omitting the allowlist is "not checked here", not "nothing allowed". The
    caller that has no policy should not be silently given the strictest one.
    """
    package = manifest(capabilities=["anything"])

    result = trusting_validator().validate(
        package.as_dict(),
        signature=key().sign_payload(package.as_dict()),
        publisher=PUBLISHER,
    )

    assert result.checks["capabilities"] is True


# ==============================================================================
# REGISTRY
# ==============================================================================


def test_a_registered_plugin_is_retrievable():
    registry = PluginRegistry()

    registry.register(PluginRecord(plugin_id="demo", version="1.0.0"))

    assert registry.get("demo").version == "1.0.0"
    assert len(registry) == 1


def test_an_unknown_plugin_reads_as_absent_rather_than_raising():
    """
    ``get`` is the "do I have this" question and answers None. ``require`` is
    the "I am about to use this" question and raises -- two questions that a
    single method would force every caller to conflate.
    """
    assert PluginRegistry().get("missing") is None


def test_require_raises_and_names_the_plugin():
    with pytest.raises(KeyError) as caught:
        PluginRegistry().require("missing")

    assert "missing" in str(caught.value)


def test_registering_a_manifest_copies_its_identity():
    registry = PluginRegistry()

    record = registry.register_manifest(
        manifest("demo", capabilities=["read"], dependencies=["base"])
    )

    assert record.plugin_id == "demo"
    assert record.publisher == PUBLISHER
    assert record.capabilities == ["read"]
    assert record.dependencies == ["base"]
    assert record.state == PluginState.INSTALLED


def test_re_registering_replaces_rather_than_duplicates():
    """
    A plugin id is the identity, so two records under one id would let a
    lookup return either version depending on insertion order.
    """
    registry = PluginRegistry()

    registry.register_manifest(manifest("demo", version="1.0.0"))
    registry.register_manifest(manifest("demo", version="2.0.0"))

    assert len(registry) == 1
    assert registry.require("demo").version == "2.0.0"


def test_state_changes_are_recorded_against_the_plugin():
    registry = PluginRegistry()
    registry.register_manifest(manifest())

    registry.set_state("demo", PluginState.ACTIVATED)

    assert registry.require("demo").state == PluginState.ACTIVATED


def test_setting_the_state_of_an_unknown_plugin_raises():
    with pytest.raises(KeyError):
        PluginRegistry().set_state("missing", PluginState.ACTIVATED)


def test_plugins_are_findable_by_state_and_capability():
    """
    The two queries the manager actually issues: "what is running" and "who
    can do this". Both have to answer from the registry rather than from a
    caller-side scan, or two callers will filter differently.
    """
    registry = PluginRegistry()
    registry.register_manifest(manifest("reader", capabilities=["read"]))
    registry.register_manifest(manifest("writer", capabilities=["write"]))
    registry.set_state("reader", PluginState.ACTIVATED)

    assert [r.plugin_id for r in registry.by_state(PluginState.ACTIVATED)] == ["reader"]
    assert [r.plugin_id for r in registry.by_state(PluginState.INSTALLED)] == ["writer"]
    assert [r.plugin_id for r in registry.by_capability("write")] == ["writer"]
    assert registry.by_capability("admin") == []


def test_unregistering_returns_the_record_it_removed():
    """
    The removed record is what an uninstaller needs for its audit entry, and
    it is gone from the registry by the time anyone could go looking for it.
    """
    registry = PluginRegistry()
    registry.register_manifest(manifest())

    removed = registry.unregister("demo")

    assert removed.plugin_id == "demo"
    assert registry.get("demo") is None
    assert registry.unregister("demo") is None


# ==============================================================================
# LOADER
# ==============================================================================


def test_a_manifest_without_a_factory_loads_the_base_plugin():
    """
    A manifest that declares no code still has to produce something
    executable, or ``ping`` could not be used to check that a package
    installed at all.
    """
    plugin = PluginLoader().load(manifest("demo", capabilities=["read"]))

    assert isinstance(plugin, Plugin)
    assert plugin.plugin_id == "demo"
    assert plugin.capabilities == ["read"]
    assert plugin.state == PluginState.LOADED


def test_a_registered_factory_supplies_the_instance():
    class Custom(Plugin):
        pass

    loader = PluginLoader()
    loader.register_factory("demo", lambda m: Custom(plugin_id=m.id, version=m.version))

    plugin = loader.load(manifest())

    assert isinstance(plugin, Custom)
    assert loader.can_load("demo")
    assert not loader.can_load("other")


def test_loading_twice_returns_the_same_instance():
    """
    A plugin holds state across actions, so a second load returning a fresh
    object would silently discard whatever the first one had accumulated.
    """
    loader = PluginLoader()

    first = loader.load(manifest())
    second = loader.load(manifest())

    assert first is second
    assert len(loader.loaded()) == 1


def test_unloading_drops_the_instance_and_is_idempotent():
    loader = PluginLoader()
    loader.load(manifest())

    assert loader.unload("demo") is not None
    assert loader.loaded() == []
    assert loader.unload("demo") is None


def test_the_loader_cache_survives_an_update_and_serves_stale_code():
    """
    **Known defect, pinned rather than endorsed.**

    ``load`` caches by plugin id and nothing invalidates that cache, so a
    plugin updated in the registry keeps executing the instance built from the
    old manifest. An operator who updates a plugin to fix a bug is told the new
    version is installed while the old code goes on running -- until something
    unrelated restarts the process.

    The fix is for the updater to evict the loader's entry. That is a change to
    the update path rather than to this test, so this pins the current
    behaviour and will fail when it is corrected -- which is the point.
    """
    loader = PluginLoader()
    loader.load(manifest("demo", version="1.0.0"))

    reloaded = loader.load(manifest("demo", version="2.0.0"))

    assert reloaded.version == "1.0.0"


# ==============================================================================
# SANDBOX
# ==============================================================================


def test_a_successful_call_returns_its_value():
    result = Sandbox().run(lambda a, b: a + b, 2, 3)

    assert result.ok
    assert result.value == 5
    assert result.actions == 1


def test_a_raising_plugin_is_contained_rather_than_propagated():
    """
    The sandbox exists so a plugin cannot take the host down with it. The
    exception type and message survive into the result, because "the plugin
    failed" without saying how is not something an operator can act on.
    """

    def explode():
        raise ValueError("bad input")

    result = Sandbox().run(explode)

    assert not result.ok
    assert result.value is None
    assert "ValueError" in result.error
    assert "bad input" in result.error


def test_an_unimplemented_action_reaches_the_result_intact():
    """
    The plugin-level error signal has to survive the sandbox boundary, or the
    most common plugin failure arrives as an anonymous one.
    """
    result = Sandbox().run(Plugin(plugin_id="demo").execute, "analyze")

    assert not result.ok
    assert "NotImplementedError" in result.error
    assert "analyze" in result.error


def test_temporary_storage_refuses_content_over_the_limit():
    sandbox = Sandbox(SandboxLimits(max_output_bytes=8))

    sandbox.write_tmp("small", b"12345678")

    assert sandbox.read_tmp("small") == b"12345678"
    with pytest.raises(ValueError):
        sandbox.write_tmp("big", b"123456789")


def test_an_unwritten_key_reads_as_empty():
    assert Sandbox().read_tmp("never-written") == b""


def test_the_result_summary_omits_the_value():
    """
    ``as_dict`` is what gets logged, and a plugin's return value may be large
    or hold whatever the plugin was given. The outcome is loggable; the payload
    is not.
    """
    described = Sandbox().run(lambda: {"secret": "value"}).as_dict()

    assert described["ok"] is True
    assert "value" not in described


# ==============================================================================
# INSTALL
# ==============================================================================


def test_installing_registers_and_activates():
    registry, _ = installed()

    record = registry.require("demo")

    assert record.state == PluginState.ACTIVATED
    assert record.version == "1.0.0"


def test_an_unsigned_package_is_not_installed():
    registry = PluginRegistry()
    installer = PluginInstaller(registry=registry, validator=trusting_validator())

    result = installer.install(manifest())

    assert not result.installed
    assert "unsigned" in result.detail
    assert registry.get("demo") is None


def test_a_missing_dependency_blocks_installation():
    """
    Refused before registration, not after. A plugin registered against a
    dependency that is not there would be activated and broken at the same
    time, and the registry would report it as healthy.
    """
    registry = PluginRegistry()
    installer = PluginInstaller(registry=registry, validator=trusting_validator())
    package = manifest("dependent", dependencies=["base"])

    result = installer.install(
        package,
        signature=key().sign_payload(package.as_dict()),
        publisher=PUBLISHER,
    )

    assert not result.installed
    assert "base" in result.detail
    assert registry.get("dependent") is None


def test_a_satisfied_dependency_installs():
    registry, _ = installed(manifest("base"))
    installer = PluginInstaller(registry=registry, validator=trusting_validator())
    package = manifest("dependent", dependencies=["base"])

    result = installer.install(
        package,
        signature=key().sign_payload(package.as_dict()),
        publisher=PUBLISHER,
    )

    assert result.installed
    assert registry.require("dependent").state == PluginState.ACTIVATED


def test_dependency_checking_can_be_waived_but_not_by_default():
    """
    The escape hatch an operator needs when installing a set of plugins that
    reference each other. Opt-in, because the failure it suppresses is the one
    that produces a registry full of plugins that cannot run.
    """
    registry = PluginRegistry()
    installer = PluginInstaller(registry=registry, validator=trusting_validator())
    package = manifest("dependent", dependencies=["base"])
    signature = key().sign_payload(package.as_dict())

    assert not installer.install(
        package, signature=signature, publisher=PUBLISHER
    ).installed
    assert installer.install(
        package,
        signature=signature,
        publisher=PUBLISHER,
        check_dependencies=False,
    ).installed


# ==============================================================================
# UPDATE
# ==============================================================================


def test_an_update_to_a_newer_version_is_applied():
    registry, _ = installed()

    result = PluginUpdater(registry).update("demo", manifest(version="1.1.0"))

    assert result.updated
    assert result.from_version == "1.0.0"
    assert result.to_version == "1.1.0"
    assert registry.require("demo").version == "1.1.0"


def test_updating_a_plugin_that_is_not_installed_is_refused():
    result = PluginUpdater(PluginRegistry()).update("demo", manifest())

    assert not result.updated
    assert result.detail == "plugin not installed"


def test_a_manifest_for_a_different_plugin_is_refused():
    """
    The guard against an update swapping one plugin for another under an id
    the operator already trusts.
    """
    registry, _ = installed()

    result = PluginUpdater(registry).update("demo", manifest("other", version="9.0.0"))

    assert not result.updated
    assert result.detail == "manifest id mismatch"
    assert registry.require("demo").version == "1.0.0"


def test_the_same_or_an_older_version_is_not_an_update():
    registry, _ = installed()
    updater = PluginUpdater(registry)

    assert updater.update("demo", manifest(version="1.0.0")).detail == "no newer version"
    assert updater.update("demo", manifest(version="0.9.0")).detail == "no newer version"
    assert registry.require("demo").version == "1.0.0"


def test_an_update_that_drops_a_capability_is_incompatible():
    """
    Something downstream was wired to that capability. Removing it during an
    update would break the caller rather than the plugin, which is the harder
    failure to trace back.
    """
    registry, _ = installed(manifest(capabilities=["read", "write"]))

    result = PluginUpdater(registry).update(
        "demo", manifest(version="2.0.0", capabilities=["read"])
    )

    assert not result.updated
    assert result.detail == "incompatible update"


def test_an_update_that_adds_a_capability_is_allowed():
    registry, _ = installed(manifest(capabilities=["read"]))

    result = PluginUpdater(registry).update(
        "demo", manifest(version="2.0.0", capabilities=["read", "write"])
    )

    assert result.updated


def test_rollback_restores_the_previous_manifest():
    registry, previous = installed()
    updater = PluginUpdater(registry)
    updater.update("demo", manifest(version="1.1.0"))

    result = updater.rollback("demo", previous)

    assert result.rolled_back
    assert not result.updated
    assert registry.require("demo").version == "1.0.0"


def test_an_update_silently_deactivates_an_active_plugin():
    """
    **Known defect, pinned rather than endorsed.**

    ``update`` re-registers the manifest, and ``register_manifest`` builds a
    fresh record whose state defaults to ``INSTALLED``. An activated plugin is
    therefore deactivated by its own successful update, and nothing in the
    result says so -- ``updated`` is true and the plugin has stopped running.

    The fix is to carry the previous state across the re-registration. This
    pins the current behaviour so that fix has to be deliberate.
    """
    registry, _ = installed()
    assert registry.require("demo").state == PluginState.ACTIVATED

    PluginUpdater(registry).update("demo", manifest(version="1.1.0"))

    assert registry.require("demo").state == PluginState.INSTALLED


# ==============================================================================
# UNINSTALL
# ==============================================================================


def test_uninstalling_removes_the_record():
    registry, _ = installed()

    result = PluginUninstaller(registry).uninstall("demo")

    assert result.removed
    assert registry.get("demo") is None


def test_uninstalling_something_that_is_not_installed_is_refused():
    result = PluginUninstaller(PluginRegistry()).uninstall("demo")

    assert not result.removed
    assert result.detail == "plugin not installed"


def test_a_plugin_with_dependents_is_not_removed():
    """
    Removing it would leave the dependents registered and broken, and the
    registry would go on reporting them as installed.
    """
    registry, _ = installed(manifest("base"))
    registry.register_manifest(manifest("dependent", dependencies=["base"]))

    result = PluginUninstaller(registry).uninstall("base")

    assert not result.removed
    assert "dependent" in result.detail
    assert registry.get("base") is not None


def test_force_removes_a_plugin_with_dependents():
    registry, _ = installed(manifest("base"))
    registry.register_manifest(manifest("dependent", dependencies=["base"]))

    result = PluginUninstaller(registry).uninstall("base", force=True)

    assert result.removed
    assert registry.get("base") is None


def test_removal_is_recorded_after_the_record_is_gone():
    """
    The audit entry is the only trace left once the record is dropped, so a
    version that was running has to be recoverable from history rather than
    from the registry.
    """
    registry, _ = installed(manifest(version="3.1.0"))
    uninstaller = PluginUninstaller(registry)

    uninstaller.uninstall("demo")

    entry = uninstaller.history()[-1]
    assert entry["plugin_id"] == "demo"
    assert entry["version"] == "3.1.0"
    assert entry["state"] == PluginState.UNINSTALLED


def test_a_refused_uninstall_is_not_written_to_history():
    """History records removals; a refusal removed nothing."""
    registry, _ = installed(manifest("base"))
    registry.register_manifest(manifest("dependent", dependencies=["base"]))
    uninstaller = PluginUninstaller(registry)

    uninstaller.uninstall("base")

    assert uninstaller.history() == []


# ==============================================================================
# MANAGER
# ==============================================================================


def test_the_manager_installs_through_its_own_registry():
    """
    The components share one registry. Two registries would let a plugin be
    installed and simultaneously not found.
    """
    registry = PluginRegistry()
    manager = PluginManager(
        registry=registry,
        installer=PluginInstaller(registry=registry, validator=trusting_validator()),
    )
    package = manifest()

    result = manager.install(
        package,
        signature=key().sign_payload(package.as_dict()),
        publisher=PUBLISHER,
    )

    assert result.installed
    assert manager.registry.require("demo").state == PluginState.ACTIVATED


def test_executing_an_action_runs_it_sandboxed():
    registry, _ = installed()
    manager = PluginManager(registry=registry)

    assert manager.execute("demo", "ping") == {
        "plugin_id": "demo",
        "version": "1.0.0",
    }


def test_an_unimplemented_action_surfaces_as_a_plugin_error():
    """
    The chain this asserts end to end: the plugin raises, the sandbox contains
    it, and the manager re-raises it as the layer's own error type -- with the
    original type and message still readable, so the caller can tell an
    unimplemented action from a crashed one.
    """
    registry, _ = installed()
    manager = PluginManager(registry=registry)

    with pytest.raises(PluginError) as caught:
        manager.execute("demo", "analyze")

    assert "NotImplementedError" in str(caught.value)
    assert "analyze" in str(caught.value)


def test_executing_an_uninstalled_plugin_raises():
    with pytest.raises(KeyError):
        PluginManager(registry=PluginRegistry()).execute("demo", "ping")


def test_a_registered_factory_is_used_for_execution():
    """
    The path a real plugin takes: the manager holds the loader, so a factory
    registered on that loader has to be what runs -- not the base ``Plugin``
    the loader falls back to.
    """
    registry, _ = installed()
    loader = PluginLoader()

    class Analyzer(Plugin):
        def execute(self, action, params=None):
            if action == "analyze":
                return {"ok": True}
            return super().execute(action, params)

    loader.register_factory("demo", lambda m: Analyzer(plugin_id=m.id, version=m.version))
    manager = PluginManager(registry=registry, loader=loader)

    assert manager.execute("demo", "analyze") == {"ok": True}


# ==============================================================================
# KNOWN DEFECTS PINNED ABOVE
# ==============================================================================
#
# Both are asserted as they currently behave so that a fix fails loudly rather
# than silently changing a contract nobody wrote down.
#
# 1. test_the_loader_cache_survives_an_update_and_serves_stale_code
#    PluginLoader caches by id and nothing evicts it, so an updated plugin goes
#    on executing pre-update code while the registry reports the new version.
#
# 2. test_an_update_silently_deactivates_an_active_plugin
#    PluginUpdater.update re-registers the manifest, resetting the record's
#    state to INSTALLED, so a successful update stops an activated plugin
#    without saying so.
