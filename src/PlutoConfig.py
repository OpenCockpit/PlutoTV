#   Copyright (C) 2021 Team OpenSPA
#   https://openspa.info/
#
#   SPDX-License-Identifier: GPL-2.0-or-later
#   See LICENSES/README.md for more information.
#

from Components.config import ConfigSelection, ConfigSubsection, config
from Tools.CountryCodes import ISO3166

# for localized messages
from . import _
from .Variables import NUMBER_OF_LIVETV_BOUQUETS


# Geo-spoofing IPs per country code, used for X-Forwarded-For headers.
X_FORWARDS = {
    "us": "185.236.200.172",
    "gb": "185.199.220.58",
    "de": "85.214.132.117",
    "es": "88.26.241.248",
    "ca": "192.206.151.131",
    "br": "177.47.27.205",
    "mx": "200.68.128.83",
    "fr": "176.31.84.249",
    "at": "2.18.68.0",
    "ch": "5.144.31.245",
    "it": "5.133.48.0",
    "ar": "104.103.238.0",
    "co": "181.204.4.74",
    "cr": "138.122.24.0",
    "pe": "190.42.0.0",
    "ve": "103.83.193.0",
    "cl": "161.238.0.0",
    "bo": "186.27.64.0",
    "sv": "190.53.128.0",
    "gt": "190.115.2.25",
    "hn": "181.115.0.0",
    "ni": "186.76.0.0",
    "pa": "168.77.0.0",
    "uy": "179.24.0.0",
    "ec": "181.196.0.0",
    "py": "177.250.0.0",
    "do": "152.166.0.0",
    "se": "185.39.146.168",
    "dk": "80.63.84.58",
    "no": "84.214.150.146",
    "au": "144.48.37.140",
    "fi": "85.194.236.0",
}

# ISO3166 is sorted in English, sorted will sort by locale.
COUNTRY_NAMES = {cc: country[0].split("(")[0].strip() for country in sorted(ISO3166) if (cc := country[1].lower()) in X_FORWARDS}

TSIDS = {cc: f"{i:X}" for i, cc in enumerate(COUNTRY_NAMES, 1)}


# --- Config subsection ---------------------------------------------------

config.plugins.plutotv = ConfigSubsection()
config.plugins.plutotv.country = ConfigSelection(default="local", choices=[("local", _("Local"))] + list(COUNTRY_NAMES.items()))
config.plugins.plutotv.picons = ConfigSelection(default="snp", choices=[("snp", _("service name")), ("srp", _("service reference")), ("", _("None"))])
config.plugins.plutotv.live_tv_mode = ConfigSelection(default="stitcher", choices=[("stitcher", _("Stitcher")), ("jmp2", _("JMP2 proxy")), ("mjh", _("i.mjh.nz"))])


# --- Helper functions -----------------------------------------------------

def getselectedcountries(skip=0):
    return [getattr(config.plugins.plutotv, "live_tv_country" + str(n)).value for n in range(1, NUMBER_OF_LIVETV_BOUQUETS + 1) if n != skip]


def autocountry(_configElement):
    for idx in range(1, NUMBER_OF_LIVETV_BOUQUETS + 1):
        selected_countries = getselectedcountries(idx)  # run only once, not loop during list comprehension
        getattr(config.plugins.plutotv, "live_tv_country" + str(idx)).setChoices([x for x in [("", _("None"))] + list(COUNTRY_NAMES.items()) if x[0] and x[0] not in selected_countries or not x[0] and (idx == NUMBER_OF_LIVETV_BOUQUETS or not getattr(config.plugins.plutotv, "live_tv_country" + str(idx + 1)).value)])


# --- LiveTV country config items -----------------------------------------

for n in range(1, NUMBER_OF_LIVETV_BOUQUETS + 1):
    setattr(config.plugins.plutotv, "live_tv_country" + str(n), ConfigSelection(default="", choices=[("", _("None"))] + list(COUNTRY_NAMES.items())))

for n in range(1, NUMBER_OF_LIVETV_BOUQUETS + 1):
    getattr(config.plugins.plutotv, "live_tv_country" + str(n)).addNotifier(autocountry, initial_call=n == NUMBER_OF_LIVETV_BOUQUETS)
