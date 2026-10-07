# Shared module configuration

`ModuleConfig.h` loads `<name>.conf.dist` followed by `<name>.conf` through the
core's `ConfigMgr`. Files are resolved beside the main config returned by
`ConfigMgr::GetFilename()`, including paths with Windows separators. A bare main
config filename uses the current working directory. Missing files return `false`
in `LoadResult`; callers keep their C++ defaults and can log the result.

Include `_common/ModuleConfig.h` and call `ModuleConfig::Load("name")` from
`WorldScript::OnConfigLoad` before reading module settings. The existing SkyFire
module target exposes the `modules/` include directory. This helper needs no
script loader or core patch.

Keep the distributed config beside the user config so loading it restores
defaults for removed user options, including on a module-specific reload.
`.reload config` clears/reloads the core config before invoking module hooks.
Files share the core's config store; use distinct option names and the same
section for defaults and user overrides. Additional files override matching keys
in the same section; a different section with the same key can shadow them.

Copy `_common` alongside modules when installing source manually. The build
scripts copy/link it into the core and release archives bundle it with each
module; it is not a separately registered module.

`tests/module_config_test.cpp` checks real SkyFire `ConfigMgr` file loading,
override order, reload and path handling. The existing
`mod-auctionbot/tests/compile.py <MSVC-build-directory>` runs it alongside the
AuctionBot tests with headers and `Config.cpp` from that build's include paths.
