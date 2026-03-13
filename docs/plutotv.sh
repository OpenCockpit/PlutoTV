#!/bin/sh
rm -f /etc/opkg/cockpit-feed.conf
opkg update
echo src/gz cockpit-all https://OpenCockpit.github.io/Cockpit-Feed/packages/all > /etc/opkg/cockpit-feed-all.conf
opkg update
opkg install enigma2-plugin-extensions-plutotv
init 2
init 3
