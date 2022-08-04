# lensbridge-samyang
A script as a bridge of SAMYANG "Lens Manager" and SAMYANG lens connected by CH340G

Users can adjust/update SAMYANG lens by its "Lens Manager" and "Lens Station Dock".

But without SAMYANG's dock, this script cooperates with a USB-Serial-Port hardware like CH340G, and a virtual serial pair like COM0COM, can do the same thing.

In brief, user must connect lens to RX/TX/RTS/DTR of a serial port listening on COMz, make a virtual serial port pair like COMx<->COMy, modify some parameters of this script, the run it. A bridge connecting COMz and COMx will be setup with protocol translating/transfering. Run "Lens Manager" and connect it to COMy, and "Lens Manager" will work like that there's a "Lens Station Dock" existing.

This script can emulate a lens without connecting to a real lens too.

Some function is not implemented, because I have only a AF45/1.8 lens for testing/hacking. Maybe someone can add supports for other lenses in this script. 

Other comments are inside script "broker.py", read them carefully before using it.
