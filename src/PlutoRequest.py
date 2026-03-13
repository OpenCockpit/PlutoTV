#   Copyright (C) 2021 Team OpenSPA
#   https://openspa.info/
#
#   SPDX-License-Identifier: GPL-2.0-or-later
#   See LICENSES/README.md for more information.
#
#   Credit to Billy2011 @ vuplus-support.org for the configurable
#   live_tv_mode option, the X_FORWARDS idea and dictionary from
#   his version distributed under the same license.
#

import re
import time
import uuid

from Components.config import config
from enigma import eServiceReference
import requests

from .PlutoConfig import X_FORWARDS, TSIDS
from .Variables import STREAM_POOL_SIZE, USER_AGENT


class _PlutoSlot:
    """One virtual device with its own clientID, HTTP session and boot cache."""

    def __init__(self, index, x_forwards, stitcher_fallback):
        self.index = index
        self._x_forwards = x_forwards
        self._stitcher_fallback = stitcher_fallback
        self.session = requests.Session()
        self.client_id = str(uuid.uuid4())
        self.bootCache = {}

    @staticmethod
    def _tokenExpiry(token):
        try:
            from json import loads
            from base64 import urlsafe_b64decode
            payload = token.split(".")[1]
            padding = 4 - len(payload) % 4
            if padding != 4:
                payload += "=" * padding
            return loads(urlsafe_b64decode(payload)).get("exp", 0)
        except Exception:
            return 0

    def boot(self, country=None):
        country = country or config.plugins.plutotv.country.value
        now = time.time()

        if country in self.bootCache:
            if now < self.bootCache[country]["exp"] - 60:
                return self.bootCache[country]["response"]

        headers = {
            'authority': 'boot.pluto.tv',
            'accept': '*/*',
            'accept-language': 'en-US,en;q=0.9',
            'origin': 'https://pluto.tv',
            'referer': 'https://pluto.tv/',
            'sec-ch-ua': '"Chromium";v="122", "Not(A:Brand";v="24", "Google Chrome";v="122"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': '"Linux"',
            'sec-fetch-dest': 'empty',
            'sec-fetch-mode': 'cors',
            'sec-fetch-site': 'same-site',
            'user-agent': USER_AGENT,
        }

        params = {
            'appName': 'web',
            'appVersion': '8.0.0-111b2b9dc00bd0bea9030b30662159ed9e7c8bc6',
            'deviceVersion': '122.0.0',
            'deviceModel': 'web',
            'deviceMake': 'chrome',
            'deviceType': 'web',
            'clientID': self.client_id,
            'clientModelNumber': '1.0.0',
            'serverSideAds': 'false',
            'deviceDNT': '1',
            'drmCapabilities': 'widevine:L3',
            'blockingMode': '',
        }

        if ip := self._x_forwards.get(country):
            headers['X-Forwarded-For'] = ip

        try:
            response = self.session.get(PlutoRequest.BOOT_URL, headers=headers, params=params, timeout=10)
            response.raise_for_status()
            resp = response.json()
            self.bootCache[country] = {
                "response": resp,
                "exp": self._tokenExpiry(resp.get("sessionToken", "")),
                "stitcherUrl": resp.get("servers", {}).get("stitcher", self._stitcher_fallback),
                "stitcherParams": resp.get("stitcherParams", ""),
            }
            print(f"[PlutoTV] Slot {self.index} new token for {country}, stitcher={self.bootCache[country]['stitcherUrl']}")
            return resp
        except Exception as e:
            print(f"[PlutoTV] Slot {self.index} boot error: {e}")
            return {}


class PlutoRequest:
    BASE_API = "https://api.pluto.tv"
    BOOT_URL = "https://boot.pluto.tv/v4/start"
    CHANNELS_URL = "https://service-channels.clusters.pluto.tv/v2/guide/channels"
    CATEGORIES_URL = "https://service-channels.clusters.pluto.tv/v2/guide/categories"
    TIMELINES_URL = "https://service-channels.clusters.pluto.tv/v2/guide/timelines"
    STITCHER_FALLBACK = "https://cfd-v4-service-channel-stitcher-use1-1.prd.pluto.tv"
    BASE_VOD = BASE_API + "/v3/vod/categories?includeItems=true&deviceType=web"
    SEASON_VOD = BASE_API + "/v3/vod/series/%s/seasons?includeItems=true&deviceType=web"

    # Legacy API endpoints (fallback for countries not on the new service-channels API)
    LEGACY_CHANNELS_URL = BASE_API + "/v2/channels.json"
    LEGACY_GUIDE_URL = BASE_API + "/v2/channels"

    # for URL insertion at runtime
    PLUTO_SCHEMA = "pluto%3a//"

    # JMP2 proxy URL template
    JMP2_URL_TEMPLATE = "https://jmp2.uk/plu-%s.m3u8"

    # i.mjh.nz playlist URL template (per country code)
    MJH_PLAYLIST_URL = "https://i.mjh.nz/PlutoTV/%s.m3u8"

    def __init__(self):
        # Slot 0 is the "primary" slot used for metadata / API calls.
        self._pool = [_PlutoSlot(i, X_FORWARDS, self.STITCHER_FALLBACK) for i in range(STREAM_POOL_SIZE)]
        self._stream_index = 0
        self.requestCache = {}
        self._sid = str(uuid.uuid1().hex)
        self._deviceId = str(uuid.uuid4().hex)

    # Legacy convenience properties so existing code keeps working.
    @property
    def session(self):
        return self._pool[0].session

    @property
    def bootCache(self):
        return self._pool[0].bootCache

    @bootCache.setter
    def bootCache(self, value):
        self._pool[0].bootCache = value

    def _nextStreamSlot(self):
        """Round-robin through pool slots for stream URLs."""
        slot = self._pool[self._stream_index % STREAM_POOL_SIZE]
        self._stream_index += 1
        return slot

    def boot(self, country=None):
        """Boot the primary (metadata) slot."""
        return self._pool[0].boot(country)

    def _authHeaders(self, country=None):
        """Build authorization headers for service-channels API."""
        country = country or config.plugins.plutotv.country.value
        token = self.boot(country).get('sessionToken', '')
        headers = {
            'authority': 'service-channels.clusters.pluto.tv',
            'accept': '*/*',
            'accept-language': 'en-US,en;q=0.9',
            'authorization': f'Bearer {token}',
            'origin': 'https://pluto.tv',
            'referer': 'https://pluto.tv/',
        }
        if ip := X_FORWARDS.get(country):
            headers['X-Forwarded-For'] = ip
        return headers

    def buildStreamURL(self, channel_id, country=None):
        """Build authenticated stitcher stream URL.

        Uses a pool slot so each concurrent stream gets its own clientID
        device identity, preventing Pluto from killing concurrent streams.
        """
        country = country or config.plugins.plutotv.country.value
        slot = self._nextStreamSlot()
        slot.boot(country)
        cache = slot.bootCache.get(country, {})
        token = cache.get('response', {}).get('sessionToken', '')
        stitcherUrl = cache.get('stitcherUrl', self.STITCHER_FALLBACK)
        stitcherParams = cache.get('stitcherParams', '')
        url = (
            f"{stitcherUrl}/v2/stitch/hls/channel/{channel_id}/master.m3u8"
            f"?jwt={token}&masterJWTPassthrough=true"
        )
        if stitcherParams:
            url += f"&{stitcherParams}"
        print(f"[PlutoTV] buildStreamURL slot {slot.index} for {channel_id}")
        return url

    def _apiHeaders(self, country=None):
        """Build authorization headers for api.pluto.tv endpoints (VOD)."""
        country = country or config.plugins.plutotv.country.value
        token = self.boot(country).get('sessionToken', '')
        headers = {
            'accept': 'application/json, text/javascript, */*; q=0.01',
            'authorization': f'Bearer {token}',
            'origin': 'https://pluto.tv',
            'referer': 'https://pluto.tv/',
            'user-agent': USER_AGENT,
        }
        if ip := X_FORWARDS.get(country):
            headers['X-Forwarded-For'] = ip
        return headers

    def _legacyHeaders(self, country=None):
        """Build headers for legacy api.pluto.tv endpoints (no Bearer token needed)."""
        headers = {
            'accept': 'application/json, text/javascript, */*; q=0.01',
            'host': 'api.pluto.tv',
            'connection': 'keep-alive',
            'referer': 'http://pluto.tv/',
            'origin': 'http://pluto.tv',
            'user-agent': USER_AGENT,
        }
        if ip := X_FORWARDS.get(country or config.plugins.plutotv.country.value):
            headers['X-Forwarded-For'] = ip
        return headers

    def getMjhStreams(self, country=None):
        """Fetch and parse the i.mjh.nz PlutoTV m3u8 playlist.

        Returns a dict mapping channel_id -> stream_url.
        Results are cached for 4 hours.
        """
        country = country or config.plugins.plutotv.country.value
        now = time.time()
        if country not in self.requestCache:
            self.requestCache[country] = {}
        cache_key = "_mjh_streams"
        if cache_key in self.requestCache[country] and self.requestCache[country][cache_key][1] > (now - 4 * 3600):
            return self.requestCache[country][cache_key][0]

        url = self.MJH_PLAYLIST_URL % country
        streams = {}
        try:
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            channel_id = None
            for line in response.text.splitlines():
                line = line.strip()
                if line.startswith("#EXTINF:"):
                    if not (match := re.search(r'channel-id="([^"]+)"', line)):
                        # fallback: tvg-id format "id.cc.pluto.tv"
                        if (match := re.search(r'tvg-id="([^"]+)"', line)):
                            channel_id = match.group(1).split(".")[0]
                        else:
                            channel_id = None
                    else:
                        channel_id = match.group(1)
                elif line and not line.startswith("#") and channel_id:
                    streams[channel_id] = line
                    channel_id = None
            self.requestCache[country][cache_key] = (streams, now)
            print(f"[PlutoTV] getMjhStreams: {len(streams)} channels for {country}")
        except Exception as e:
            print(f"[PlutoTV] getMjhStreams error for {country}: {e}")
        return streams

    def getURL(self, url, param=None, header=None, life=60 * 15, country=None):
        if header is None:
            header = {"User-agent": USER_AGENT}
        if param is None:
            param = {}
        now = time.time()
        if (country := country or config.plugins.plutotv.country.value) not in self.requestCache:
            self.requestCache[country] = {}
        if url in self.requestCache[country] and self.requestCache[country][url][1] > (now - life):
            return self.requestCache[country][url][0]
        try:
            req = requests.get(url, param, headers=header, timeout=10)
            req.raise_for_status()
            response = req.json()
            req.close()
            self.requestCache[country][url] = (response, now)
            return response
        except Exception:
            return {}

    def buildVodStreamURL(self, vod_url, country=None):
        """Rewrite a VOD stitched URL to use the correct stitcher host + JWT auth.

        Uses a pool slot so each concurrent stream gets its own clientID
        device identity, preventing Pluto from killing concurrent streams.
        """
        country = country or config.plugins.plutotv.country.value
        slot = self._nextStreamSlot()
        slot.boot(country)
        cache = slot.bootCache.get(country, {})
        token = cache.get('response', {}).get('sessionToken', '')
        stitcherUrl = cache.get('stitcherUrl', self.STITCHER_FALLBACK)
        stitcherParams = cache.get('stitcherParams', '')

        # Extract the path from the old URL (strip host and query string)
        # e.g. https://service-stitcher-ipv4.clusters.pluto.tv/stitch/hls/episode/XXX/master.m3u8?...
        path = vod_url.split('?')[0]  # remove query string
        path = re.sub(r'^https?://[^/]+', '', path)  # remove scheme+host, keep /path

        # Ensure /v2 prefix (old URLs use /stitch/..., new stitcher needs /v2/stitch/...)
        if path.startswith('/stitch/'):
            path = '/v2' + path

        url = (
            f"{stitcherUrl}{path}"
            f"?jwt={token}&masterJWTPassthrough=true"
        )
        if stitcherParams:
            url += f"&{stitcherParams}"
        return url

    def getVOD(self, epid, country=None):
        country = country or config.plugins.plutotv.country.value
        return self.getURL(self.SEASON_VOD % epid, header=self._apiHeaders(country), life=60 * 60, country=country)

    def getOndemand(self, country=None):
        country = country or config.plugins.plutotv.country.value
        return self.getURL(self.BASE_VOD, header=self._apiHeaders(country), life=60 * 60, country=country)

    def getChannels(self, country=None):
        """Fetch channels via v2/guide/channels + categories, returned in legacy format.

        Falls back to the legacy api.pluto.tv endpoint if the new API returns
        no data (some countries like Finland are not on the new API).
        """
        country = country or config.plugins.plutotv.country.value
        headers = self._authHeaders(country)
        params = {'channelIds': '', 'offset': '0', 'limit': '1000', 'sort': 'number:asc'}

        try:
            response = self.session.get(self.CHANNELS_URL, params=params, headers=headers, timeout=10)
            response.raise_for_status()
            channel_list = response.json().get("data", [])
        except Exception as e:
            print(f"[PlutoTV] getChannels new API error for {country}: {e}")
            channel_list = []

        if not channel_list:
            print(f"[PlutoTV] getChannels: new API returned no channels for {country}, trying legacy API")
            return self._getChannelsLegacy(country)

        try:
            response = self.session.get(self.CATEGORIES_URL, params=params, headers=headers, timeout=10)
            response.raise_for_status()
            cat_data = response.json().get("data", [])
        except Exception:
            cat_data = []

        categories = {}
        for elem in cat_data:
            cat_name = elem.get('name', '')
            for ch_id in elem.get('channelIDs', []):
                categories[ch_id] = cat_name

        result = []
        for ch in channel_list:
            ch_id = ch.get('id', '')
            logo_url = next(
                (img["url"] for img in ch.get("images", []) if img.get("type") == "colorLogoPNG"),
                None
            )
            result.append({
                '_id': ch_id,
                'name': ch.get('name', ''),
                'slug': ch.get('slug', ''),
                'number': ch.get('number', 0),
                'category': categories.get(ch_id, ''),
                'colorLogoPNG': {'path': logo_url},
            })

        return result

    def _getChannelsLegacy(self, country):
        """Fetch channels via the legacy api.pluto.tv/v2/channels.json endpoint."""
        params = {'sid': self._sid, 'deviceId': self._deviceId}
        headers = self._legacyHeaders(country)
        try:
            response = requests.get(self.LEGACY_CHANNELS_URL, params=params, headers=headers, timeout=10)
            response.raise_for_status()
            channels = response.json()
            if isinstance(channels, list):
                print(f"[PlutoTV] getChannels legacy API returned {len(channels)} channels for {country}")
                return channels
            print(f"[PlutoTV] getChannels legacy API unexpected response for {country}")
            return []
        except Exception as e:
            print(f"[PlutoTV] getChannels legacy API error for {country}: {e}")
            return []

    def getBaseGuide(self, start, stop, country=None):
        """Fetch guide data via v2/guide/timelines, returned in legacy format.

        Falls back to the legacy api.pluto.tv endpoint if the new API returns
        no data (some countries like Finland are not on the new API).
        """
        country = country or config.plugins.plutotv.country.value
        headers = self._authHeaders(country)

        if not (channels := self.getChannels(country)):
            return []

        channel_ids = [ch['_id'] for ch in channels]
        channel_lookup = {ch['_id']: ch for ch in channels}

        all_entries = []
        group_size = 100
        for i in range(0, len(channel_ids), group_size):
            group = channel_ids[i:i + group_size]
            params = {
                'start': start,
                'channelIds': ','.join(group),
                'duration': '1440',
            }
            try:
                response = self.session.get(self.TIMELINES_URL, params=params, headers=headers, timeout=10)
                response.raise_for_status()
                data = response.json().get("data", [])
                for entry in data:
                    ch_id = entry.get('channelId', '')
                    ch_data = channel_lookup.get(ch_id, {})
                    all_entries.append({
                        '_id': ch_id,
                        'number': ch_data.get('number', 0),
                        'name': ch_data.get('name', ''),
                        'timelines': entry.get('timelines', []),
                    })
            except Exception as e:
                print(f"[PlutoTV] getBaseGuide new API error for {country}: {e}")

        if not all_entries:
            print(f"[PlutoTV] getBaseGuide: new API returned no data for {country}, trying legacy API")
            return self._getBaseGuideLegacy(start, stop, country)

        return all_entries

    def _getBaseGuideLegacy(self, start, stop, country):
        """Fetch guide data via the legacy api.pluto.tv/v2/channels endpoint."""
        params = {'start': start, 'stop': stop, 'sid': self._sid, 'deviceId': self._deviceId}
        headers = self._legacyHeaders(country)
        try:
            response = requests.get(self.LEGACY_GUIDE_URL, params=params, headers=headers, timeout=10)
            response.raise_for_status()
            guide = response.json()
            if isinstance(guide, list):
                print(f"[PlutoTV] getBaseGuide legacy API returned {len(guide)} entries for {country}")
                return guide
            print(f"[PlutoTV] getBaseGuide legacy API unexpected response for {country}")
            return []
        except Exception as e:
            print(f"[PlutoTV] getBaseGuide legacy API error for {country}: {e}")
            return []


plutoRequest = PlutoRequest()


def playServiceExtension(nav, sref, *_args, **_kwargs):
    return recordServiceExtension(nav, sref), False


def recordServiceExtension(_nav, sref, *_args, **_kwargs):
    parts = sref.toString().split(":")
    if len(parts) > 10 and parts[10].lower().startswith(plutoRequest.PLUTO_SCHEMA):
        _id = parts[10][len(plutoRequest.PLUTO_SCHEMA):]
        cc = {v: k for k, v in TSIDS.items()}.get(parts[4], None)
        stream_url = plutoRequest.buildStreamURL(_id, cc)
        parts[10] = stream_url.replace(":", "%3a")
        sref = eServiceReference(":".join(parts))
    return sref
