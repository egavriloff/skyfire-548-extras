# ruRU localization

Target: SkyFire 5.4.8 World DB.

Generated, reviewed localization SQL bundle. Coverage describes the published
entity selection; counters come from the approved reviews used for these SQL files.

| Entity | Target | Candidates | Exported | Target % | Evidence % |
| --- | ---: | ---: | ---: | ---: | ---: |
| achievement_reward | 175 | 28 | 19 | 10.86% | 67.86% |
| creature | 57,180 | 57,014 | 46,992 | 82.18% | 82.42% |
| creature_text | 7,406 | 7,100 | 2,332 | 31.49% | 32.85% |
| db_script_string | 186 | 37 | 37 | 19.89% | 100.00% |
| gameobject | 30,187 | 29,490 | 23,372 | 77.42% | 79.25% |
| gossip_menu_option | 5,006 | 4,951 | 2,849 | 56.91% | 57.54% |
| item | 72,255 | 72,252 | 69,413 | 96.07% | 96.07% |
| npc_text | 8,298 | 8,246 | 5,887 | 70.94% | 71.39% |
| page_text | 1,879 | 1,721 | 974 | 51.84% | 56.60% |
| points_of_interest | 605 | 295 | 78 | 12.89% | 26.44% |
| quest | 17,934 | 17,929 | 17,216 | 96.00% | 96.02% |
| skyfire_string | 1,128 | 843 | 739 | 65.51% | 87.66% |
| TOTAL | 202,239 | 199,906 | 169,908 | 84.01% | 84.99% |

Summary:

- Exported: 169,908
- Skipped: 32,331
- Conflicts: 8,246
- Unsupported: 20,274
- Missing: 3,811

Developer diagnostics for the local review report:

```sh
python tools/localization/localize.py coverage --locale ruRU --verbose
```

That command reads the local review workspace, which may be newer than this
publication. This README is a fixed summary of the published SQL bundle.
