DELETE FROM `trinity_string` WHERE `entry` BETWEEN 30000 AND 30006;

INSERT INTO `trinity_string` (`entry`, `content_default`) VALUES
(30000, '|cff4CFF00SoloCraft system|r active.'),
(30001, '|cffFF0000[SoloCraft]|r |cffFF8000 %s entered %s - Difficulty Offset: %0.2f. Spellpower Bonus: %i. Class Balance Weight: %i. XP Gain: |cffFF0000%s|r XP Balancing: %s'),
(30002, '|cff4CFF00[SoloCraft]|r |cffFF0000 %s entered %s - You have not been buffed. Your level is higher than the max level (%i) threshold for this dungeon.'),
(30003, '|cffFF0000[SoloCraft]|r |cffFF8000 %s entered %s - You have been debuffed by offset: %0.2f with Class Balance Weight: %i. A group member already inside has the dungeon full buff offset.'),
(30004, '|cffFF0000[SoloCraft]|r |cffFF8000 %s exited to %s - Reverting Difficulty Offset: %0.2f. Spellpower Bonus Removed: %i'),
(30005, 'Enabled'),
(30006, 'Disabled');
