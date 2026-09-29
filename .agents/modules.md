## SkyFire Module Naming

Real modules must use the `mod-<name>` naming convention.

Examples:

- `mod-solocraft`
- `mod-transmog`

The module directory name and `module.yml` slug must match.

SkyFire converts the module directory name to the module loader function name.

Example:

`mod-solocraft`

uses:

`Addmod_solocraftScripts()`
