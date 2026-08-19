# Secure Boot

NixOS/Clan currently does not support [Secure Boot](https://wiki.gentoo.org/wiki/Secure_Boot); disable it in BIOS. Optional [video guide](https://www.youtube.com/watch?v=BKVShiMUePc).

## Insert USB Stick

- Insert the USB stick into a computer USB port.

## Access UEFI/BIOS

- Restart the computer; during restart, press the appropriate key to enter UEFI/BIOS settings. Press quickly and repeatedly if necessary; the entry window is brief.
::::admonition[The key depends on your laptop or motherboard manufacturer. Click to see a reference list:]{type=tip collapsible}

|Manufacturer|UEFI/BIOS Key(s)|
|---|---|
|ASUS|`Del`, `F2`|
|MSI|`Del`, `F2`|
|Gigabyte|`Del`, `F2`|
|ASRock|`Del`, `F2`|
|Lenovo|`F1`, `F2`, `Enter` (alternatively `Fn + F2`)|
|HP|`Esc`, `F10`|
|Dell|`F2`, `Fn + F2`, `Esc`|
|Acer|`F2`, `Del`|
|Samsung|`F2`, `F10`|
|Toshiba|`F2`, `Esc`|
|Sony|`F2`, `Assist` button|
|Fujitsu|`F2`|
|Microsoft Surface|`Volume Up` + `Power`|
|IBM/Lenovo ThinkPad|`Enter`, `F1`, `F12`|
|Biostar|`Del`|
|Zotac|`Del`, `F2`|
|EVGA|`Del`|
|Origin PC|`F2`, `Delete`|

:::admonition[Note]{type=note}
Press the key quickly and repeatedly if necessary; the UEFI/BIOS entry window is brief.
:::
::::

## Access Advanced Mode (Optional)

- If UEFI/BIOS uses `Simple` or `Easy` mode, click `Advanced Mode` (often lower right) for more settings. Optional: boot settings may already be available in the basic view.

## Disable Secure Boot

- Locate `Secure Boot`, typically under `Security`, `Boot`, or a similarly named section; set it to `Disabled`.

## Change Boot Order

- Find `Boot Order`, `Boot Sequence`, or `Boot Priority`; set the USB device as the first boot option so the computer boots from the USB stick.

## Save and Exit

- Save changes before exiting via `Save & Exit` or the corresponding function key (often `F10`). The computer should restart and boot from the USB stick.
