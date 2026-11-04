// SPDX-License-Identifier: BSD-2-Clause-Patent
// The persistent-store hooks NativeRamBlock.cpp (an unchanged copy of UniXNU RamBlock 4be2d7e) imports weakly
// (native_ufs_store_*). On sheng, ShengUfs provides them. This file used to define no-store stubs for fuxi
// (mode 0, "no store on fuxi") because fuxi had no storage driver and the kernel is linked statically, so a
// weak import still needs a definition. Since the ShengUfs driver itself is now linked into this board's
// kernel (scripts/build-fuxi-ufs.py), it provides the real definitions, and keeping the stubs gave duplicate
// symbols at the kernel link (Build #28), so they are gone. The driver's store mode is the sheng-data-persist
// boot argument, which this board does not set, so it reports mode 0 and NativeRamBlock keeps a volatile RAM
// disk and never calls the others, exactly as with the stubs. The file stays, as an empty translation unit,
// so the RAM block build's file list is unchanged.
#include <stdint.h>
