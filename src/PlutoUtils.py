# Copyright (C) 2026 by xcentaurix
# License: GNU General Public License v3.0 (see LICENSE file for details)

import os
from pickle import load as pickle_load, dump as pickle_dump
from time import time

import requests
from Components.config import config, ConfigSelection
from Components.Harddisk import harddiskmanager
from Tools.Directories import fileExists
from twisted.internet.reactor import callFromThread

from .Variables import RESUMEPOINTS_FILE, USER_AGENT


# --- Data folder management -----------------------------------------------

_data_folder = ""


def getDataFolder():
    return _data_folder


def _getMountChoices():
    choices = []
    for p in harddiskmanager.getMountedPartitions():
        if os.path.exists(p.mountpoint):
            d = os.path.normpath(p.mountpoint)
            if p.mountpoint != "/":
                choices.append((p.mountpoint, d))
    choices.sort()
    return choices


def _getMountDefault(choices):
    choices = {x[1]: x[0] for x in choices}
    return choices.get("/media/hdd") or choices.get("/media/usb") or ""


def _onPartitionChange(*_args, **_kwargs):
    choices = _getMountChoices()
    config.plugins.plutotv.datalocation.setChoices(choices=choices, default=_getMountDefault(choices))
    updateDataFolder()


def updateDataFolder(*_args, **_kwargs):
    global _data_folder
    _data_folder = ""
    if v := config.plugins.plutotv.datalocation.value:
        if os.path.exists(v):
            _data_folder = os.path.join(v, "PlutoTV")
            os.makedirs(_data_folder, exist_ok=True)


def initMountChoices():
    choices = _getMountChoices()
    if not choices:
        choices = [("/tmp", "/tmp")]
    config.plugins.plutotv.datalocation = ConfigSelection(choices=choices, default=_getMountDefault(choices))
    harddiskmanager.on_partition_list_change.append(_onPartitionChange)
    config.plugins.plutotv.datalocation.addNotifier(updateDataFolder, immediate_feedback=False)


initMountChoices()


# --- Resume points --------------------------------------------------------

class ResumePoints:
    # We can't use the ResumePoints class built in to enigma because
    # the id's are hashes, not srefs, so would be deleted on reboot.
    def __init__(self):
        self.resumePointFile = RESUMEPOINTS_FILE
        self.resumePointCache = {}
        self.loadResumePoints()
        self.cleanCache()  # get rid of stale entries on reboot

    def loadResumePoints(self):
        self.resumePointCache.clear()
        if fileExists(self.resumePointFile):
            with open(self.resumePointFile, "rb") as f:
                self.resumePointCache.update(pickle_load(f, encoding="utf8"))

    def saveResumePoints(self):
        os.makedirs(os.path.dirname(self.resumePointFile), exist_ok=True)
        with open(self.resumePointFile, "wb") as f:
            pickle_dump(self.resumePointCache, f, protocol=5)

    def setResumePoint(self, session, sid):
        service = session.nav.getCurrentService()
        if service and session.nav.getCurrentlyPlayingServiceOrGroup():
            if seek := service.seek():
                pos = seek.getPlayPosition()
                if not pos[0]:
                    lru = int(time())
                    duration = sl[1] if (sl := seek.getLength()) else None
                    position = pos[1]
                    self.resumePointCache[sid] = [lru, position, duration]
                    self.saveResumePoints()

    def getResumePoint(self, sid):
        last = None
        length = 0
        if sid and (entry := self.resumePointCache.get(sid)):
            entry[0] = int(time())  # update LRU timestamp
            last = entry[1]
            length = entry[2]
        return last, length

    def cleanCache(self):
        changed = False
        now = int(time())
        for sid, v in list(self.resumePointCache.items()):
            if now > v[0] + 30 * 24 * 60 * 60:  # keep resume points a maximum of 30 days
                del self.resumePointCache[sid]
                changed = True
        if changed:
            self.saveResumePoints()


resumePointsInstance = ResumePoints()


# --- Poster downloading ---------------------------------------------------

def downloadPoster(url, name, callback):
    data_folder = getDataFolder()
    filename = os.path.join(data_folder, name)
    if not fileExists(filename):
        try:
            response = requests.get(url, timeout=2.50, headers={"User-Agent": USER_AGENT})
            response.raise_for_status()
            content_type = response.headers.get('content-type')
            if content_type and content_type.lower() == 'image/jpeg' and len(rc := response.content):
                with open(filename, "wb") as f:
                    f.write(rc)
        except requests.exceptions.RequestException:
            pass
    callFromThread(callback, filename, name)


# --- Image helper ---------------------------------------------------------

def pickBestImage(imgs):
    """Pick poster and best available image from a covers list."""
    poster = ""
    image = ""
    if len(imgs) > 2:
        image = imgs[2].get("url", "")
    if len(imgs) > 1 and not image:
        image = imgs[1].get("url", "")
    if len(imgs) > 0:
        poster = imgs[0].get("url", "")
    return poster, image
