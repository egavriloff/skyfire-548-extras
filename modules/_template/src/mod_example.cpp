#include "Config.h"
#include "Log.h"
#include "Player.h"
#include "ScriptMgr.h"
#include "_common/ModuleConfig.h"

class mod_example_worldscript: public WorldScript {
  public:
    mod_example_worldscript(): WorldScript("mod_example_worldscript") {}

    void OnConfigLoad(bool /*reload*/) override {
      ModuleConfig::Load("example");
    }
};

class mod_example_playerscript: public PlayerScript {
  public:
    mod_example_playerscript(): PlayerScript("mod_example_playerscript") {}

    void OnLogin(Player* player, bool /*firstLogin*/) override {
      if (!sConfigMgr->GetBoolDefault("Example.Enable", true))
        return;

      SF_LOG_INFO("modules", "[mod-example] Player '%s' logged in.", player ? player->GetName().c_str() : "<unknown>");
    }
};

void AddSC_mod_example() {
  new mod_example_worldscript();
  new mod_example_playerscript();
}
