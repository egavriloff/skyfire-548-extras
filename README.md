# Build Status
[![Module Verify](https://github.com/egavriloff/skyfire-548-modules/actions/workflows/verify.yml/badge.svg)](https://github.com/egavriloff/skyfire-548-modules/actions/workflows/verify.yml)
[![Build modules](https://github.com/egavriloff/skyfire-548-modules/actions/workflows/build.yml/badge.svg)](https://github.com/egavriloff/skyfire-548-modules/actions/workflows/build.yml)
[![AI Review](https://github.com/egavriloff/skyfire-548-modules/actions/workflows/ai-review.yml/badge.svg)](https://github.com/egavriloff/skyfire-548-modules/actions/workflows/ai-review.yml)

# 🔥 SkyFire Ports

A collection of modules, scripts and other stuff I've ported to **SkyFire** from different WoW emulator projects.

> I'm just a React/JavaScript developer who one day decided that writing UI wasn't enough suffering and started porting C++ modules for a WoW server emulator.

So yeah — I'm **not a WoW emulator expert**, **not a C++ wizard**, and definitely not pretending that I understand every dark ritual happening inside the core.

But if it compiles, the server starts, and the feature actually works — that's already a pretty good day.

---

## 📦 What is this?

This repository contains my ports and adaptations of various modules/scripts for SkyFire.

Most of them were originally written for other cores or projects and required some combination of:

- API adaptation
- C++ changes
- database changes
- core hooks
- config changes
- CMake/build-system changes
- random debugging until the compiler stopped screaming

The goal is to keep these ports separated from the main SkyFire source as much as possible, so they can be installed, removed and updated without turning the core into an archaeological site.

---

## ⚠️ Important

These modules are primarily made for **my SkyFire setup**.

They may work perfectly.

They may need small changes.

They may explode spectacularly on a different SkyFire revision.

Check the module README before installing it and **make a database backup** before applying SQL files.

Seriously.

Make the backup.

---

## 🛠 Installing modules

Each module should contain its own installation instructions, but the general process is usually:

1. Copy/clone the module into the appropriate SkyFire modules/custom directory.

2. Apply the SQL files provided by the module.

   Depending on the module, there may be SQL for:

   - `world`
   - `characters`
   - `auth`

3. Copy the module's `.conf.dist` beside the active `worldserver.conf`, then copy
   it to `.conf` and edit that file. Modules using `modules/_common/ModuleConfig.h`
   load defaults followed by user overrides on startup and `.reload config`.
   For a separate installation, also copy `modules/_common` into the core's
   `modules/` directory. Release archives include this shared directory.

4. Re-run CMake if required.

5. Rebuild the server.

6. Start the server and check the logs for errors.

Some ports require additional changes or hooks inside the core. Those will be documented in the module's README.

If a module includes a migration/update directory, apply the required database migrations before starting the server.

---

## 🗃 Repository structure

Typical module layout:

```text
module-name/
├── README.md
├── src/
├── sql/
│   ├── world/
│   ├── characters/
│   └── auth/
├── conf/
└── patches/
```

Not every module needs all of these directories.

---

## 🔄 Database updates

SQL files are separated by database whenever possible.

For example:

```text
sql/
├── world/
│   └── module_world.sql
├── characters/
│   └── module_characters.sql
└── auth/
    └── module_auth.sql
```

Always check which database an SQL file belongs to before running it.

Do **not** blindly execute every `.sql` file against `world`.

Yes, this warning exists for a reason.

---

## ✅ Tested environment

Unless stated otherwise in the module README, the modules here are tested against the SkyFire version/revision I'm currently using.

Compatibility with:

- other SkyFire revisions
- TrinityCore
- AzerothCore
- AshamaneCore
- older/newer expansions
- heavily modified forks

is **not guaranteed**.

These are ports, not black magic universal compatibility layers.

---

## ❤️ Credits

A lot of the interesting stuff in this repository exists because other people wrote it first.

I mostly port, adapt, fix and integrate things for SkyFire.

Code, ideas or implementations may originate from projects and developers such as:

- **LoAP**
- **AlexKulya / AlexK**
- **HavenCore**
- other WoW emulator projects, forks and community contributors

Whenever I know the original source of a module, I try to mention it in that module's README and preserve the original credits.

If I missed somebody, opened an issue/PR with the original source and I'll add the proper attribution.

Huge thanks to everyone who has spent unreasonable amounts of their life reverse-engineering WoW and writing emulator code so people like me can come along years later and break it in new and interesting ways.

---

## 🧪 Status

This repository is a work in progress.

Modules can generally be considered one of:

**Working** — tested in-game and seems to work.

**Experimental** — compiles and runs, but needs more testing.

**WIP** — currently being ported.

**Broken** — something caught fire.

Individual module READMEs should contain their current status.

---

## 🐛 Bugs / Issues

If something doesn't work, please include:

- module name
- SkyFire revision
- build/compiler information
- relevant server log
- database error if applicable
- what you expected to happen
- what actually happened

`it doesn't work` is technically a bug report, but not a particularly useful one.

---

## 🤝 Contributions

PRs, fixes and improvements are welcome.

Especially if you actually know C++.

I clearly need the help.

---

## 📜 License

Each port/module retains the license and attribution requirements of its original source where applicable.

Check the module directory and original project before redistributing code.

This repository does **not** claim ownership of third-party code simply because it has been modified or ported to SkyFire.
