#include "Errors.h"
#include "_common/ModuleConfig.h"

#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <iostream>

// Config.cpp only needs this core assertion handler; a failed assertion aborts.
namespace Skyfire {
DECLSPEC_NORETURN void Assert(char const*, int, char const*, char const*) {
  std::abort();
}
} // namespace Skyfire

namespace {
void Check(bool condition) {
  if (!condition) {
    std::cerr << "ModuleConfig regression failed\n";
    std::exit(1);
  }
}

void Write(std::filesystem::path const& path, char const* content) {
  std::ofstream file(path);
  file << content;
  Check(bool(file));
}
} // namespace

int main() {
  std::filesystem::path directory = "module-config-fixtures";
  std::filesystem::create_directories(directory);
  auto main = directory / "worldserver.conf";
  auto dist = directory / "example.conf.dist";
  auto user = directory / "example.conf";
  Write(main, "Core.Value = 9\nExample.Value = 0\n");
  Write(dist, "Example.Value = 1\nExample.Default = 5\n");
  Write(user, "Example.Value = 2\n");

  Check(sConfigMgr->LoadInitial(main.generic_string().c_str()));
  ModuleConfig::LoadResult result = ModuleConfig::Load("example");
  Check(result.DistLoaded && result.UserLoaded);
  Check(result.DistPath == dist.generic_string() && result.UserPath == user.generic_string());
  Check(sConfigMgr->GetIntDefault("Example.Value", -1) == 2);
  Check(sConfigMgr->GetIntDefault("Example.Default", -1) == 5);
  Check(sConfigMgr->GetIntDefault("Core.Value", -1) == 9);
  Check(sConfigMgr->GetFilename() == main.generic_string());

  // Module-specific reload restores removed overrides from the shipped defaults.
  Write(user, "# removed override\n");
  ModuleConfig::Load("example");
  Check(sConfigMgr->GetIntDefault("Example.Value", -1) == 1);
  Write(user, "Example.Value = 3\n");
  Check(sConfigMgr->Reload());
  ModuleConfig::Load("example");
  Check(sConfigMgr->GetIntDefault("Example.Value", -1) == 3);

  result = ModuleConfig::Load("missing");
  Check(!result.DistLoaded && !result.UserLoaded);
  Check(sConfigMgr->GetBoolDefault("Missing.Enable", false) == false);

  // Native Windows separators and a bare filename must both resolve siblings.
  Check(sConfigMgr->LoadInitial(main.string().c_str()));
  Check(ModuleConfig::GetSiblingConfigPath("example.conf") == user.string());
  auto originalDirectory = std::filesystem::current_path();
  std::filesystem::current_path(directory);
  Check(sConfigMgr->LoadInitial("worldserver.conf"));
  result = ModuleConfig::Load("example");
  Check(result.DistLoaded && result.UserLoaded);
  Check(result.DistPath == "example.conf.dist" && result.UserPath == "example.conf");
  Check(sConfigMgr->GetIntDefault("Example.Value", -1) == 3);
  std::filesystem::current_path(originalDirectory);
  std::cout << "ModuleConfig regression passed\n";
}
