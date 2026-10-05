#ifndef SKYFIRE_AUCTIONBOT_ITEM_PROPERTIES_H
#define SKYFIRE_AUCTIONBOT_ITEM_PROPERTIES_H

#include "Item.h"

namespace AuctionBotModule {
// Only for freshly created, ownerless auction items. ITEM_NEW makes SaveToDB
// persist every field; inventory setters would require a live Player and
// enqueue this item. Do not use this path for inventory or already saved items.
template <class ItemType>
bool InitializeNewItemProperties(ItemType& item, int32 propertyId, uint32 const* enchantments) {
  if (item.GetState() != ITEM_NEW || item.GetOwnerGUID() || item.IsInUpdateQueue())
    return false;
  if (!propertyId)
    return true;
  if (!enchantments)
    return false;

  item.SetInt32Value(ITEM_FIELD_RANDOM_PROPERTIES_ID, propertyId);
  bool suffix = propertyId < 0;
  if (suffix)
    item.UpdateItemSuffixFactor();

  uint32 first = suffix ? PROP_ENCHANTMENT_SLOT_0 : PROP_ENCHANTMENT_SLOT_1;
  uint32 count = suffix ? 5 : 3;
  for (uint32 i = 0; i < count; ++i) {
    uint32 field = ITEM_FIELD_ENCHANTMENT + (first + i) * MAX_ENCHANTMENT_OFFSET;
    item.SetUInt32Value(field + ENCHANTMENT_ID_OFFSET, enchantments[i]);
    item.SetUInt32Value(field + ENCHANTMENT_DURATION_OFFSET, 0);
    item.SetUInt32Value(field + ENCHANTMENT_CHARGES_OFFSET, 0);
  }
  return true;
}
} // namespace AuctionBotModule
#endif
