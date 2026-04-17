#   Copyright (C) 2021 Team OpenSPA
#   https://openspa.info/
#
#   SPDX-License-Identifier: GPL-2.0-or-later
#   See LICENSES/README.md for more information.
#

import os
import shutil
import threading
import time
from itertools import count as _count

from Components.config import config
from Tools.Directories import fileExists, sanitizeFilename
import requests

from .Variables import PLUGIN_FOLDER, PLUGIN_ICON, USER_AGENT


class PiconFetcher:
    def __init__(self, parent=None):
        self.parent = parent
        self.piconDir = self.getPiconPath()
        self.pluginPiconDir = os.path.join(self.piconDir, "PlutoTV")
        piconWidth = 220
        piconHeight = 132
        self.resolutionStr = f"?h={piconHeight}&w={piconWidth}"
        self.piconList = []

    def createFolders(self):
        os.makedirs(self.piconDir, exist_ok=True)
        os.makedirs(self.pluginPiconDir, exist_ok=True)
        self.defaultIcon = os.path.join(self.pluginPiconDir, PLUGIN_ICON)
        shutil.copy(os.path.join(PLUGIN_FOLDER, PLUGIN_ICON), self.defaultIcon)

    def addPicon(self, ref, name, url, silent):
        if not config.plugins.plutotv.picons.value:
            return
        piconname = os.path.join(self.piconDir, ch_name + ".png") if config.plugins.plutotv.picons.value == "snp" and (ch_name := sanitizeFilename(name.lower())) else os.path.join(self.piconDir, ref.replace(":", "_") + ".png")
        one_week_ago = time.time() - 60 * 60 * 24 * 7
        if not (fileExists(piconname) and (silent or os.path.getmtime(piconname) > one_week_ago)):
            self.piconList.append((url, piconname))

    def fetchPicons(self):
        maxthreads = 100  # make configurable
        self._counter = _count()
        failed = []
        self.createFolders()
        if self.piconList:
            picon_threads = [threading.Thread(target=self.downloadURL, args=(url, filename)) for url, filename in self.piconList]
            for thread in picon_threads:
                while threading.active_count() > maxthreads:
                    time.sleep(1)
                try:
                    thread.start()
                except RuntimeError:
                    failed.append(thread)
            for thread in picon_threads:
                if thread not in failed:
                    thread.join()
            print("[Fetcher] all fetched")

    def downloadURL(self, url, piconname):
        filepath = os.path.join(self.pluginPiconDir, piconname.removeprefix(self.piconDir).removeprefix(os.sep))  # second removeprefix ensures no leading / is left on the filename as this would be recognised as an absolute path by os.path.join and the join would be skipped
        counter = next(self._counter)
        try:
            response = requests.get(f"{url}{self.resolutionStr}", timeout=2.50, headers={"User-Agent": USER_AGENT})
            response.raise_for_status()
            content_type = response.headers.get('content-type')
            if content_type and content_type.lower() == 'image/png' and len(rc := response.content):
                with open(filepath, "wb") as f:
                    f.write(rc)
        except requests.exceptions.RequestException:
            pass
        if not fileExists(filepath):  # it seems nothing was downloaded
            filepath = self.defaultIcon
        self.makesoftlink(filepath, piconname)
        if self.parent:
            from twisted.internet.reactor import callFromThread
            callFromThread(self.parent.updateProgressBar, counter)

    def makesoftlink(self, filepath, softlinkpath):
        svgpath = softlinkpath.removesuffix(".png") + ".svg"
        islink = os.path.islink(softlinkpath)
        # isfile follows symbolic links so we need to check this is not a symbolic link first
        # or if user.svg exists do not write symbolic link
        if not islink and os.path.isfile(softlinkpath) or os.path.isfile(svgpath):
            return  # if a file exists here don't touch it, it is not ours
        if islink:
            if os.readlink(softlinkpath) == filepath:
                return
            os.remove(softlinkpath)
        os.symlink(filepath, softlinkpath)

    def removeall(self):
        if os.path.exists(self.piconDir):
            for f in os.listdir(self.piconDir):
                item = os.path.join(self.piconDir, f)
                if os.path.islink(item) and self.pluginPiconDir in os.readlink(item):
                    os.remove(item)
        if os.path.exists(self.pluginPiconDir):
            shutil.rmtree(self.pluginPiconDir)

    @staticmethod
    def getPiconPath():
        try:
            from Components.Renderer.Picon import lastPiconPath, searchPaths
        except ImportError:
            try:
                from Components.Renderer.Picon import piconLocator
                lastPiconPath = piconLocator.activePiconPath
                searchPaths = piconLocator.searchPaths
            except ImportError:
                lastPiconPath = None
                searchPaths = None
        if searchPaths and len(searchPaths) == 1:
            return searchPaths[0]
        return lastPiconPath or "/picon"
