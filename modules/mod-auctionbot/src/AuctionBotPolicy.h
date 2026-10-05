#ifndef SKYFIRE_AUCTIONBOT_POLICY_H
#define SKYFIRE_AUCTIONBOT_POLICY_H

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <limits>

namespace AuctionBotPolicy {
// SkyFire's outbid API still takes uint32 even though auction prices are uint64.
constexpr std::uint64_t MaxPrice = (std::numeric_limits<std::uint32_t>::max)();

inline std::uint64_t Price(double amount) {
  if (!std::isfinite(amount) || amount < 1.0)
    return 1;
  return static_cast<std::uint64_t>(std::min(double(MaxPrice), amount));
}

inline double UnitPrice(std::uint64_t price, std::uint32_t count) {
  return count ? double(price) / double(count) : 0.0;
}
} // namespace AuctionBotPolicy
#endif
