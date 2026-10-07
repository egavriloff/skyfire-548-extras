#pragma once

#include "Config.h"

#include <string>

namespace ModuleConfig {
struct LoadResult {
    bool DistLoaded;
    bool UserLoaded;
    std::string DistPath;
    std::string UserPath;
};

inline std::string GetSiblingConfigPath(char const* filename) {
  std::string mainConfig = sConfigMgr->GetFilename();
  std::string::size_type pos = mainConfig.find_last_of("/\\");

  if (pos == std::string::npos)
    return filename;

  return mainConfig.substr(0, pos + 1) + filename;
}

inline LoadResult Load(char const* name) {
  std::string base(name);

  std::string dist = GetSiblingConfigPath((base + ".conf.dist").c_str());
  std::string user = GetSiblingConfigPath((base + ".conf").c_str());

  bool distLoaded = sConfigMgr->LoadMore(dist.c_str());
  bool userLoaded = sConfigMgr->LoadMore(user.c_str());

  return {distLoaded, userLoaded, dist, user};
}
} // namespace ModuleConfig
