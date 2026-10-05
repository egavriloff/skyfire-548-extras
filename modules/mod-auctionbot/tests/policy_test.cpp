#include "AuctionBotPolicy.h"
#include <cassert>

int main()
{
    using namespace AuctionBotPolicy;
    // Invalid settings cannot produce zero prices or undefined float-to-integer casts.
    assert(Price(0) == 1);
    assert(Price(-100) == 1);
    assert(Price(std::numeric_limits<double>::quiet_NaN()) == 1);
    assert(Price(std::numeric_limits<double>::infinity()) == 1);
    assert(Price(12345.75) == 12345);
    assert(Price(double(MaxPrice)) == MaxPrice);
    assert(Price(double(MaxPrice) + 1000000) == MaxPrice);
    // One copper across a stack must retain its fractional unit price.
    assert(std::abs(UnitPrice(1, 20) - 0.05) < 1e-12);
    assert(UnitPrice(100, 0) == 0);
    assert(UnitPrice(MaxPrice, 1) == double(MaxPrice));
    assert(Price(double(Price(100)) * 0.6) <= Price(100));
}
