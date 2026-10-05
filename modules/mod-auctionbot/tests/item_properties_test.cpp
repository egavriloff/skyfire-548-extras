#include "AuctionBotItemProperties.h"
#include <cassert>
#include <iomanip>
#include <map>

// An ownerless ITEM_NEW double: inventory update APIs are deliberately absent.
// Any regression to SetState/SetEnchantment/SetItemRandomProperties fails to compile.
struct NewAuctionItem {
    ItemUpdateState state = ITEM_NEW;
    uint64 owner = 0;
    bool queued = false;
    int32 property = 0;
    unsigned suffixUpdates = 0;
    std::map<uint32, uint32> fields;
    ItemUpdateState GetState() const {
      return state;
    }
    uint64 GetOwnerGUID() const {
      return owner;
    }
    bool IsInUpdateQueue() const {
      return queued;
    }
    void SetInt32Value(uint32 field, int32 value) {
      assert(field == ITEM_FIELD_RANDOM_PROPERTIES_ID);
      property = value;
    }
    void SetUInt32Value(uint32 field, uint32 value) {
      fields[field] = value;
    }
    void UpdateItemSuffixFactor() {
      ++suffixUpdates;
    }
};

int main() {
  using AuctionBotModule::InitializeNewItemProperties;
  uint32 enchants[5] = {101, 102, 103, 104, 105};
  NewAuctionItem plain;
  assert(InitializeNewItemProperties(plain, 0, nullptr));
  assert(plain.fields.empty() && plain.property == 0);

  NewAuctionItem property;
  assert(InitializeNewItemProperties(property, 123, enchants));
  assert(property.property == 123 && property.suffixUpdates == 0);
  assert(property.fields.size() == 9);
  assert(property.fields.at(ITEM_FIELD_ENCHANTMENT + PROP_ENCHANTMENT_SLOT_1 * MAX_ENCHANTMENT_OFFSET) == 101);
  assert(property.fields.at(ITEM_FIELD_ENCHANTMENT + PROP_ENCHANTMENT_SLOT_3 * MAX_ENCHANTMENT_OFFSET) == 103);
  assert(property.state == ITEM_NEW && !property.queued && !property.owner);

  NewAuctionItem suffix;
  assert(InitializeNewItemProperties(suffix, -456, enchants));
  assert(suffix.property == -456 && suffix.suffixUpdates == 1);
  assert(suffix.fields.size() == 15);
  assert(suffix.fields.at(ITEM_FIELD_ENCHANTMENT + PROP_ENCHANTMENT_SLOT_0 * MAX_ENCHANTMENT_OFFSET) == 101);
  assert(suffix.fields.at(ITEM_FIELD_ENCHANTMENT + PROP_ENCHANTMENT_SLOT_4 * MAX_ENCHANTMENT_OFFSET) == 105);
  assert(suffix.state == ITEM_NEW && !suffix.queued && !suffix.owner);

  for (auto const& pair : suffix.fields)
    if ((pair.first - ITEM_FIELD_ENCHANTMENT) % MAX_ENCHANTMENT_OFFSET != ENCHANTMENT_ID_OFFSET)
      assert(pair.second == 0);

  NewAuctionItem saved;
  saved.state = ITEM_UNCHANGED;
  assert(!InitializeNewItemProperties(saved, 123, enchants));
  NewAuctionItem owned;
  owned.owner = 1;
  assert(!InitializeNewItemProperties(owned, 123, enchants));
  NewAuctionItem queued;
  queued.queued = true;
  assert(!InitializeNewItemProperties(queued, 123, enchants));
  NewAuctionItem missing;
  assert(!InitializeNewItemProperties(missing, 123, nullptr));
  assert(missing.fields.empty() && missing.property == 0);
}
