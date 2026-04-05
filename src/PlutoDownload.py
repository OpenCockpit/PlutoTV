#   Copyright (C) 2021 Team OpenSPA
#   https://openspa.info/
#
#   SPDX-License-Identifier: GPL-2.0-or-later
#   See LICENSES/README.md for more information.
#

import datetime
import os
import re
import time

from Components.ActionMap import ActionMap
from Components.config import config
from Components.Label import Label
from Components.ProgressBar import ProgressBar
from Screens.MessageBox import MessageBox
from Screens.Screen import Screen
from Tools.Directories import fileExists
from enigma import eDVBDB, eEPGCache, eTimer
from twisted.internet import threads  # for updating GUI widgets

# for localized messages
from . import _
from .PlutoConfig import COUNTRY_NAMES, TSIDS, getselectedcountries
from .PlutoRequest import plutoRequest
from .PiconFetcher import PiconFetcher
from .Variables import TIMER_FILE, PLUGIN_FOLDER, BOUQUET_FILE, BOUQUET_NAME, PLUGIN_ICON


class PlutoDownloadBase():
    downloadActive = False  # shared between instances

    def __init__(self, silent=False):
        self.channelsList = {}
        self.guideList = {}
        self.categories = []
        self.state = 1  # this is a hack
        self.silent = silent
        PlutoDownloadBase.downloadActive = False
        self.epgcache = eEPGCache.getInstance()

    def cc(self):
        countries = [x for x in getselectedcountries() if x] or [config.plugins.plutotv.country.value]
        # Delete bouquets of not selected countries. Don't delete the bouquets we are updating so they retain their current position.
        eDVBDB.getInstance().removeBouquet(re.escape(BOUQUET_FILE) % f"(?!{'|'.join(countries)}).+")
        yield from countries

    def download(self):
        if PlutoDownloadBase.downloadActive:
            if not self.silent:
                self.session.openWithCallback(self.close, MessageBox, _("A silent download is in progress."), MessageBox.TYPE_INFO, timeout=30)
            print("[PlutoDownload] A silent download is in progress.")
            return
        self.ccGenerator = self.cc()
        self.piconFetcher = PiconFetcher(self)
        self.manager()

    def manager(self):
        PlutoDownloadBase.downloadActive = True
        if cc := next(self.ccGenerator, None):
            self.downloadBouquet(cc)
        else:
            self.channelsList.clear()
            self.guideList.clear()
            self.categories.clear()
            PlutoDownloadBase.downloadActive = False
            self.ccGenerator = None
            if self.piconFetcher.piconList:
                self.total = len(self.piconFetcher.piconList)
                threads.deferToThread(self.updateProgressBar, 0)  # reset
                threads.deferToThread(self.updateAction, _("picons"))  # GUI widget
                threads.deferToThread(self.updateStatus, _("Fetching picons..."))  # GUI widget
                self.piconFetcher.fetchPicons()
                threads.deferToThread(self.updateProgressBar, self.total)  # reset
            self.piconFetcher = None
            threads.deferToThread(self.updateStatus, _("LiveTV update completed"))  # GUI widget
            time.sleep(3)
            self.exitOk()
            self.start()

    def downloadBouquet(self, cc):
        self.bouquet = []
        self.bouquetCC = cc
        self.tsid = TSIDS.get(cc, "0")
        self.stop()
        self.channelsList.clear()
        self.guideList.clear()
        self.categories.clear()
        threads.deferToThread(self.updateAction, cc)  # GUI widget
        threads.deferToThread(self.updateProgressBar, 0)  # reset
        threads.deferToThread(self.updateStatus, _("Processing data..."))  # GUI widget
        channels = sorted(plutoRequest.getChannels(cc), key=lambda x: x["number"])
        guide = self.getGuidedata(cc)
        for channel in channels:
            self.buildM3U(channel)

        # Sort categories alphabetically, and channels within each category by name
        self.categories.sort(key=str.casefold)
        for _group, channels_in_group in self.channelsList.items():
            channels_in_group.sort(key=lambda ch: ch[2].casefold())

        self.total = len(channels)

        if len(self.categories) == 0:
            self.noCategories()
        else:
            if self.categories[0] in self.channelsList:
                self.subtotal = len(self.channelsList[self.categories[0]])
            else:
                self.subtotal = 0
            self.key = 0
            self.chitem = 0
            for event in guide:
                self.buildGuide(event)
            for i in range(self.total + 1):
                self.updateprogress(param=i)

    def updateprogress(self, param):
        if hasattr(self, "state") and self.state == 1:  # hack for exit before end
            threads.deferToThread(self.updateProgressBar, param)
            if param < self.total:
                key = self.categories[self.key]
                if self.chitem == self.subtotal:
                    self.chitem = 0
                    found = False
                    while not found:
                        self.key += 1
                        key = self.categories[self.key]
                        found = key in self.channelsList
                    self.subtotal = len(self.channelsList[key])

                if self.chitem == 0:
                    self.bouquet.append(f"1:64:{self.key}:0:0:0:0:0:0:0::{self.categories[self.key]}")

                ch_sid, ch_hash, ch_name, ch_logourl, _id = self.channelsList[key][self.chitem]

                mode = config.plugins.plutotv.live_tv_mode.value
                if mode == "jmp2":
                    stream_url = (plutoRequest.JMP2_URL_TEMPLATE % _id).replace(":", "%3a")
                elif mode == "mjh":
                    mjh_streams = plutoRequest.getMjhStreams(self.bouquetCC)
                    if not (stream_url := mjh_streams.get(_id, "").replace(":", "%3a")):
                        stream_url = plutoRequest.PLUTO_SCHEMA + _id
                else:
                    stream_url = plutoRequest.PLUTO_SCHEMA + _id

                ref = f"4097:0:1:{ch_sid}:{self.tsid}:1:2:0:0:0"
                self.bouquet.append(f"{ref}:{stream_url}:{ch_name}")
                self.chitem += 1
                # print("[updateprogress] ref", ref)
                threads.deferToThread(self.updateStatus, _("Waiting for Channel: ") + ch_name)  # GUI widget

                chevents = []
                if ch_hash in self.guideList:
                    for evt in self.guideList[ch_hash]:
                        title = evt[0]
                        summary = evt[1]
                        begin = int(round(evt[2]))
                        duration = evt[3]
                        genre = evt[4]

                        chevents.append((begin, duration, title, "", summary, genre))
                if len(chevents) > 0:
                    iterator = iter(chevents)
                    events_tuple = tuple(iterator)
                    self.epgcache.importEvents(ref + ":https%3a//.m3u8", events_tuple)

                self.piconFetcher.addPicon(ref, ch_name, ch_logourl, self.silent)
            else:
                bouquet_name = BOUQUET_NAME % COUNTRY_NAMES.get(self.bouquetCC, self.bouquetCC)
                bouquet_file = BOUQUET_FILE % self.bouquetCC
                eDVBDB.getInstance().addOrUpdateBouquet(bouquet_name, bouquet_file, self.bouquet, False)  # place at bottom if not exists
                # addOrUpdateBouquet doesn't update #NAME for existing bouquets, so patch the file
                bouquet_path = "/etc/enigma2/" + bouquet_file
                if os.path.isfile(bouquet_path):
                    with open(bouquet_path, "r", encoding="utf-8") as f:
                        lines = f.readlines()
                    if lines and lines[0].startswith("#NAME"):
                        lines[0] = f"#NAME {bouquet_name}\r\n"
                        with open(bouquet_path, "w", encoding="utf-8") as f:
                            f.writelines(lines)
                os.makedirs(os.path.dirname(TIMER_FILE), exist_ok=True)  # create config folder recursive if not exists
                with open(TIMER_FILE, "w", encoding="utf-8") as f:
                    f.write(str(time.time()))
                self.manager()

    def buildGuide(self, event):
        # (title, summary, start, duration, genre)
        _id = event.get("_id", "")
        if len(_id) == 0:
            return
        self.guideList[_id] = []
        timelines = event.get("timelines", [])
        chplot = (event.get("description", "") or event.get("summary", ""))

        for item in timelines:
            episode = (item.get("episode", {}) or item)
            series = (episode.get("series", {}) or item)
            epdur = int(episode.get("duration", "0") or "0") // 1000  # in seconds
            epgenre = episode.get("genre", "")
            etype = series.get("type", "film")

            genre = self.convertgenre(epgenre)

            offset = datetime.datetime.now() - datetime.datetime.utcnow()
            try:
                starttime = self.strpTime(item["start"]) + offset
            except Exception:
                continue
            start = time.mktime(starttime.timetuple())
            title = (item.get("title", ""))
            tvplot = (series.get("description", "") or series.get("summary", "") or chplot)
            epnumber = episode.get("number", 0)
            epseason = episode.get("season", 0)
            epname = episode.get("name", "")
            epmpaa = episode.get("rating", "")
            epplot = (episode.get("description", "") or tvplot or epname)

            if len(epmpaa) > 0 and "Not Rated" not in epmpaa:
                epplot = f"({epmpaa}). {epplot}"

            noserie = ("live", "film")
            if epseason > 0 and epnumber > 0 and etype not in noserie:
                title = f"{title} (T{epseason})"
                epplot = f"T{epseason} Ep.{epnumber} {epplot}"

            if epdur > 0:
                self.guideList[_id].append((title, epplot, start, epdur, genre))

    def buildM3U(self, channel):
        # (number, _id, name, logo, url)
        logo = (channel.get("colorLogoPNG", {}).get("path", None) or None)
        group = channel.get("category", "")
        _id = channel["_id"]

        if group not in self.channelsList:
            self.channelsList[group] = []
            self.categories.append(group)

        if int(channel["number"]) == 0:
            number = _id[-4:].upper()
        else:
            number = f"{channel['number']:X}"

        self.channelsList[group].append((str(number), _id, channel["name"], logo, _id))
        return True

    @staticmethod
    def convertgenre(genre):
        genre_id = 0
        if genre in {"Classics", "Romance", "Thrillers", "Horror"} or "Sci-Fi" in genre or "Action" in genre:
            genre_id = 0x10
        elif "News" in genre or "Educational" in genre:
            genre_id = 0x20
        elif genre == "Comedy":
            genre_id = 0x30
        elif "Children" in genre:
            genre_id = 0x50
        elif genre == "Music":
            genre_id = 0x60
        elif genre == "Documentaries":
            genre_id = 0xA0
        return genre_id

    @staticmethod
    def getGuidedata(cc):
        start = (datetime.datetime.fromtimestamp(PlutoDownloadBase.getLocalTime()).strftime("%Y-%m-%dT%H:00:00Z"))
        stop = (datetime.datetime.fromtimestamp(PlutoDownloadBase.getLocalTime()) + datetime.timedelta(hours=24)).strftime("%Y-%m-%dT%H:00:00Z")
        return sorted(plutoRequest.getBaseGuide(start, stop, cc), key=lambda x: x["number"])

    @staticmethod
    def getLocalTime():
        offset = datetime.datetime.utcnow() - datetime.datetime.now()
        return time.time() + offset.total_seconds()

    @staticmethod
    def strpTime(datestring, fmt="%Y-%m-%dT%H:%M:%S.%fZ"):
        try:
            return datetime.datetime.strptime(datestring, fmt)
        except TypeError:
            return datetime.datetime.fromtimestamp(time.mktime(time.strptime(datestring, fmt)))

    def start(self):
        pass

    def stop(self):
        pass

    def exitOk(self, answer=None):
        pass

    def updateProgressBar(self, param):
        pass

    def updateStatus(self, name):
        pass

    def updateAction(self, cc=""):
        pass


class PlutoDownload(PlutoDownloadBase, Screen):
    skin = f"""
        <screen name="PlutoTVdownload" position="60,60" resolution="1920,1080" size="615,195" flags="wfNoBorder" backgroundColor="#ff000000">
        <eLabel position="0,0" size="615,195" zPosition="-1" alphatest="blend" backgroundColor="#2d101214" cornerRadius="8" widgetBorderWidth="2" widgetBorderColor="#2d888888"/>
        <ePixmap position="15,80" size="120,45" pixmap="{PLUGIN_FOLDER}/{PLUGIN_ICON}" scale="1" alphatest="blend" transparent="1" zPosition="10"/>
        <widget name="action" halign="left" valign="center" position="13,9" size="433,30" font="Regular;25" foregroundColor="#dfdfdf" transparent="1" backgroundColor="#000000" borderColor="black" borderWidth="1" noWrap="1"/>
        <widget name="progress" position="150,97" size="420,12" borderWidth="0" backgroundColor="#1143495b" pixmap="{PLUGIN_FOLDER}/images/progreso.png" zPosition="2" alphatest="blend" />
        <eLabel name="progess_background" position="150,97" size="420,12" backgroundColor="#102a3b58" />
        <widget name="wait" valign="center" halign="center" position="150,63" size="420,30" font="Regular;22" foregroundColor="#dfdfdf" transparent="1" backgroundColor="#000000" borderColor="black" borderWidth="1" noWrap="1"/>
        <widget name="status" halign="center" valign="center" position="150,120" size="420,30" font="Regular;24" foregroundColor="#ffffff" transparent="1" backgroundColor="#000000" borderColor="black" borderWidth="1" noWrap="1"/>
        </screen>"""

    def __init__(self, session):
        self.session = session
        Screen.__init__(self, session)
        self.title = _("PlutoTV updating")
        PlutoDownloadBase.__init__(self)
        self.total = 0
        self["progress"] = ProgressBar()
        self["action"] = Label()
        self.updateAction()
        self["wait"] = Label()
        self["status"] = Label(_("Please wait..."))
        self["actions"] = ActionMap(["OkCancelActions"], {"cancel": self.exit}, -1)
        self.onFirstExecBegin.append(self.init)

    def updateAction(self, cc=""):
        self["action"].text = _("Updating: Pluto TV %s") % cc.upper()

    def init(self):
        self["progress"].setValue(0)
        threads.deferToThread(self.download)

    def exit(self):
        self.session.openWithCallback(self.cleanup, MessageBox, _("The download is in progress. Exit now?"), MessageBox.TYPE_YESNO, timeout=30)

    def cleanup(self, answer=None):
        if answer:
            PlutoDownloadBase.downloadActive = False
            self.exitOk(answer)

    def exitOk(self, answer=True):
        if answer:
            Silent.stop()
            Silent.start()
            self.close(True)

    def updateProgressBar(self, param):
        try:
            progress = min(((param + 1) * 100) // self.total, 100)
        except Exception:
            progress = 0
        self["progress"].setValue(progress)
        self["wait"].text = str(progress) + " %"

    def updateStatus(self, name):
        self["status"].text = name

    def noCategories(self):
        self.session.openWithCallback(self.exitOk, MessageBox, _("There is no data, it is possible that Pluto TV is not available in your country"), type=MessageBox.TYPE_ERROR, timeout=10)


class DownloadSilent(PlutoDownloadBase):
    def __init__(self):
        self.afterUpdate = []  # for callbacks
        PlutoDownloadBase.__init__(self, silent=True)
        self.timer = eTimer()
        self.timer.timeout.get().append(self.download)

    def init(self, session):  # called on session start
        self.session = session
        with open("/etc/enigma2/bouquets.tv", "r", encoding="utf-8") as f:
            bouquets = f.read()
        if "pluto_tv" in bouquets:
            self.start(True)

    def start(self, fromSessionStart=False):
        self.stop()
        minutes = 60 * 5
        if fileExists(TIMER_FILE):
            with open(TIMER_FILE, "r", encoding="utf-8") as f:
                last = float(f.read().strip())
            minutes -= int((time.time() - last) / 60)
            if minutes < 0:
                minutes = 1  # do we want to do this so close to reboot
        self.timer.startLongTimer(minutes * 60)
        if not fromSessionStart:
            self.afterUpdateCallbacks()

    def stop(self):
        self.timer.stop()

    def afterUpdateCallbacks(self):
        for f in self.afterUpdate:
            if callable(f):
                f()

    def noCategories(self):
        print("[Pluto TV] There is no data, it is possible that Pluto TV is not available in your country.")
        self.stop()
        os.makedirs(os.path.dirname(TIMER_FILE), exist_ok=True)  # create config folder recursive if not exists
        with open(TIMER_FILE, "w", encoding="utf-8") as f:
            f.write(str(time.time()))
        self.start()


Silent = DownloadSilent()
