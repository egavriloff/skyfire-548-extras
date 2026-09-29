-- Apply this to the CHARACTERS database, not world/auth.
-- v3 keeps SkyFire's native item_instance_transmog table as the authoritative
-- appearance store and mirrors active appearances here for compatibility/admin use.

CREATE TABLE IF NOT EXISTS `custom_transmogrification` (
  `GUID` INT UNSIGNED NOT NULL,
  `FakeEntry` INT UNSIGNED NOT NULL DEFAULT 0,
  `Owner` INT UNSIGNED NOT NULL DEFAULT 0,
  PRIMARY KEY (`GUID`),
  KEY `idx_owner` (`Owner`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8;

CREATE TABLE IF NOT EXISTS `custom_transmogrification_sets` (
  `Owner` INT UNSIGNED NOT NULL,
  `PresetID` TINYINT UNSIGNED NOT NULL,
  `SetName` VARCHAR(64) NOT NULL DEFAULT '',
  `SetData` TEXT NOT NULL,
  PRIMARY KEY (`Owner`,`PresetID`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8;
