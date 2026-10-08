# AuctionBot 1.0.1 — SkyFire 5.4.8

Standalone port of AuctionHouseBot from Pandaria 5.4.8 Project. The original local
input was source/port; its exact URL and revision were not recorded, so module.yml
keeps those values null. No core changes are required. The original donor license
is GPL-2.0-or-later; notices remain in the ported files.

## Status and components

**Working**, based on the owner's existing live installation. testing.build,
testing.startup and testing.ingame describe that installation. Packaging into this
repository did not include a new build or in-game verification.

```text
mod-auctionbot/
├── module.yml
├── README.md
├── VERSION
├── src/
├── conf/auctionbot.conf.dist
└── tests/
```

Includes source and configuration; no SQL migrations or core patches are needed.
Pandaria 5.4.8 Project attribution remains in the source files.

## Features

- Seller fills auctions using quality/class filters, randomized stacks, properties,
  prices and durations.
- Buyer probabilistically bids on or buys player auctions.
- Alliance, Horde and Neutral settings are independent. Cross-faction auctions use
  one shared market with Neutral settings.
- In-game/console commands provide reload, statistics and auction rebuilding.
- Existing auctioneers are selected automatically or by creature.guid. A market
  without a suitable auctioneer is disabled and logged.

## Build and install

In this repository the module is modules/mod-auctionbot. The local target checkout
is externals/core/repo/. From the repository root on Windows:

```powershell
.\build.cmd modules
.\build.cmd build
```

The first command builds modules; the second also builds worldserver. On Linux/macOS
use ./build.sh modules or ./build.sh build. The launcher links repository modules
into the target core automatically.

For a separate installation copy modules/mod-auctionbot into the core's modules/
directory and copy modules/_common alongside it:

1. Reconfigure CMake with MODULES=1 so the new directories are discovered.
2. Build worldserver. The module system registers Addmod_auctionbotScripts()
   automatically; this is a static module, not a separate DLL.
3. Put auctionbot.conf.dist beside the active worldserver.conf, then copy it to
   auctionbot.conf. A standard Windows build also copies .conf.dist beside the
   executable; when the main config lives elsewhere, put module configs beside it.
4. Set a dedicated account ID that already has at least one character. The module
   does not create accounts, characters, NPCs or database tables.
5. Enable the desired agents and restart, or run .ahbot reload if the server already
   includes the module.

_common/ModuleConfig.h loads .conf.dist then user .conf on startup, .reload config
and .ahbot reload. Keep overrides in auctionbot.conf. Both agents are disabled by
default. A missing account/character prevents the bot from starting.

## Initial configuration

Replace account 123 with your dedicated account ID:

```ini
AuctionHouseBot.Account = 123
AuctionHouseBot.Seller.Enabled = 1
AuctionHouseBot.Buyer.Enabled = 0
AuctionHouseBot.Update.Interval = 20
AuctionHouseBot.ItemsPerCycle.Normal = 10
AuctionHouseBot.ItemsPerCycle.Boost = 20
AuctionHouseBot.Items.Amount.Gray = 0
AuctionHouseBot.Items.Amount.White = 20
AuctionHouseBot.Items.Amount.Green = 20
AuctionHouseBot.Items.Amount.Blue = 10
AuctionHouseBot.Items.Amount.Purple = 0
AuctionHouseBot.Items.Amount.Orange = 0
AuctionHouseBot.Items.Amount.Yellow = 0
```

Quotas are approximate because the donor distributes them between classes with
rounding. The interval applies to one seller/buyer operation on one market; a full
market rotation may take several intervals.

For buying, enable Buyer.Enabled and the desired Buyer.Alliance/Horde/Neutral.Enabled
settings. A shared auction house requires Neutral.Enabled. Auctioneer.Alliance,
Horde and Neutral values of 0 select automatically. Explicit values are creature.guid,
not creature entry or character GUID; an invalid explicit value disables that market
without automatic replacement.

## Commands

Console commands omit the leading dot. In-game access requires GM privileges and
existing RBAC_PERM_COMMAND_RELOAD_CONFIG (630). No new SQL permissions/localizations
are required; command messages are English.

```text
.ahbot status
.ahbot reload
.ahbot items <gray> <white> <green> <blue> <purple> <orange> <yellow>
.ahbot items <gray|white|green|blue|purple|orange|yellow> <amount>
.ahbot ratio <alliance> <horde> <neutral>
.ahbot ratio <alliance|horde|neutral> <percent>
.ahbot rebuild
.ahbot rebuild all
```

items/ratio numbers range from 0 to 10000. Changes last until reload/restart; edit
the config for persistence. rebuild expires only bot auctions without bids;
rebuild all includes auctions with bids. The normal auction update handles completion
and mail. These commands do not immediately delete all auctions or alter other sellers.

## Economy and limits

- The donor economy creates items/money; bids/deposits do not debit the character.
- Normal mail delivers sold/bought/expired items and proceeds. Version 1.0 has no
  automatic dedicated-account mail cleanup.
- Do not use a personal playing account: its auctions count as bot auctions. Keep
  the same account to manage previously created bot auctions.
- Prices are limited to 4,294,967,295 copper per auction. Storage uses uint64 but
  the outbid notification API takes uint32; Buyer skips auctions/bids above that
  limit. Internal sums and bid persistence use uint64.
- Duration: 1–72 hours; cycle: 1–1000 operations; interval: 1–3600 seconds.
- Seller disables itself with an ahbot log message if item/loot templates provide
  no eligible items. No special module tables are required.

## Verification

From the repository root run bash .ci/module-verify/verify.sh for static checks.
Use build.cmd modules or ./build.sh modules for compilation; static checks do not
replace a real build.

For an existing MSVC Release/x64 build, pass its build directory explicitly:

```powershell
python modules/mod-auctionbot/tests/compile.py "D:/path/to/SkyFire_548/build"
```

This reads modules/modules.vcxproj, compiles four module files and runs C++ tests
for money limits, fractional stack prices and random properties. Logs/results go
to the module's ignored .validation directory. Docker/Ninja does not generate
.vcxproj and is unsupported by this optional script. It does not link/deploy worldserver.

After building, separately verify in game:

1. Disabled agents show disabled in .ahbot status and create no auctions.
2. Seller creates eligible items/prices on the configured market.
3. Players buying bot auctions receive items through normal mail.
4. Auctions survive restart without missing-auctioneer GUID errors.
5. Buyer bids/buys eligible player auctions; refunds and seller proceeds are correct.
6. Reload disabling agents stops new operations; existing auctions follow normal
   core rules. rebuild leaves other sellers' auctions alone.
7. Shared auctions are populated once, not three times.

Live server/DB checks are separate from compilation.

## Version 1.0.1 fix

Removed Item::SetItemRandomProperties() on auction items without a Player owner.
In SkyFire that inventory method calls SetState()/AddToUpdateQueueOf(nullptr),
causing an assertion. The module now fills random property/suffix fields only on
new unsaved ownerless items; normal SaveToDB() persists them in the auction transaction.
The regression test covers ordinary items, three property enchantment slots,
five suffix slots, ITEM_NEW persistence and absence of a Player update queue.

Rebuild worldserver after updating. No DB migration or config change is needed.
AuctionHouseBot.Account is auth.account.id, not characters.guid.
