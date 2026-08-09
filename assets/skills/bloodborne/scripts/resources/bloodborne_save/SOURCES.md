# Bloodborne Save Parser Resources

This directory contains static resource JSON copied from the GitHub repository:

- Project: Noxde/Bloodborne-save-editor
- URL: https://github.com/Noxde/Bloodborne-save-editor
- License: GPL-3.0
- Purpose: read-only Bloodborne userdata analysis for shadPS4/decrypted saves
- Files copied: `offsets.json`, `bosses.json`, `items.json`, `weapons.json`, `armors.json`, `upgrades.json`
- Save parser implementation (`bb_save.py`) is derived from reverse-engineering the Noxde editor's Rust source (`src-tauri/src/data_handling/` — `offsets.rs`, `upgrades.rs`, `slots.rs`, `inventory.rs`, `enums.rs`). This covers:
  - Stats: offsets relative to FACE marker and username block
  - Inventory: 16-byte slot records with item/armor/weapon type detection via byte markers (0xB0/0x40 for items, 0x10 for armor)
  - Boss flags: bitmask checks in the AOB region
  - Upgrade records (gems + runes): 40-byte records starting at absolute offset 84, type byte at +8 (0x01=gem, 0x02=rune), shape at +12, six effect IDs at +16..+39. Effect names resolved from `upgrades.json`
  - Equipped slot blocks: 60-byte blocks between upgrades_end and username-147, containing 5 gem/rune slots each. Slots matched to inventory articles via 8-byte unique keys. Garbage-skip pattern: 0xFFFFFFFF00000000
  - Caryll Runes: parsed from upgrade records (type=0x02) cross-referenced with equipped slot blocks. Distinguishes equipped vs. inventory/storage runes
- Local use: the Bloodborne skill CLI parses save files without modifying them. It does not implement save editing, writeback, backup, teleport, stat mutation, inventory mutation, boss mutation, or re-encryption

The game data is stable for Bloodborne version 1.09 / The Old Hunters final release. Keep this bundle static unless a better source is deliberately selected and attributed.
