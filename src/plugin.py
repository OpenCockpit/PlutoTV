#   Copyright (C) 2021 Team OpenSPA
#   https://openspa.info/
#
#   SPDX-License-Identifier: GPL-2.0-or-later
#   See LICENSES/README.md for more information.
#
#   PlutoTV is free software: you can redistribute it and/or modify
#   it under the terms of the GNU General Public License as published by
#   the Free Software Foundation, either version 3 of the License, or
#   (at your option) any later version.
#
#   PlutoTV is distributed in the hope that it will be useful,
#   but WITHOUT ANY WARRANTY; without even the implied warranty of
#   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#   GNU General Public License for more details.
#
#   You should have received a copy of the GNU General Public License
#   along with PlutoTV.  If not, see <http://www.gnu.org/licenses/>.
#


import os
import re
from time import strftime, gmtime, localtime
from urllib.parse import quote
from twisted.internet import threads

from Components.ActionMap import ActionMap, HelpableActionMap
from Components.config import config
from Components.Label import Label
from Components.MenuList import MenuList
from Components.MultiContent import MultiContentEntryText, MultiContentEntryPixmapAlphaBlend
from Components.Pixmap import Pixmap
from Components.ScrollLabel import ScrollLabel
from Components.ServiceEventTracker import ServiceEventTracker
from Components.Sources.StaticText import StaticText
from Plugins.Plugin import PluginDescriptor
from Screens.ChoiceBox import ChoiceBox
from Screens.HelpMenu import HelpableScreen
from Screens.InfoBar import MoviePlayer
from Screens.MessageBox import MessageBox
from Screens.Screen import Screen
from Screens.Setup import Setup
from Tools.Directories import fileExists, isPluginInstalled, resolveFilename, SCOPE_CURRENT_SKIN
from Tools.Hex2strColor import Hex2strColor
from Tools.LoadPixmap import LoadPixmap
from Tools import Notifications
from enigma import BT_KEEP_ASPECT_RATIO, BT_SCALE, BT_HALIGN_CENTER, BT_VALIGN_CENTER, eListboxPythonMultiContent, eServiceReference, eTimer, gFont, iPlayableService
from skin import applySkinFactor, fonts, parameters

from . import _, __
from .PlutoConfig import COUNTRY_NAMES, getselectedcountries
from .PlutoRequest import plutoRequest, playServiceExtension, recordServiceExtension, startProactiveRefresh
from .PlutoDownload import PlutoDownload, Silent
from .PiconFetcher import PiconFetcher
from .PlutoUtils import resumePointsInstance, downloadPoster, pickBestImage
from .Variables import TIMER_FILE, PLUGIN_FOLDER, BOUQUET_FILE, NUMBER_OF_LIVETV_BOUQUETS, PLUGIN_ICON


class PlutoList(MenuList):
    def __init__(self, entries):
        self.menu_png = LoadPixmap(x if fileExists(x := resolveFilename(SCOPE_CURRENT_SKIN, "icons/pluto_menu.png")) else f"{PLUGIN_FOLDER}/images/menu.png")
        self.series_png = LoadPixmap(x if fileExists(x := resolveFilename(SCOPE_CURRENT_SKIN, "icons/pluto_series.png")) else f"{PLUGIN_FOLDER}/images/series.png")
        self.cine_png = LoadPixmap(x if fileExists(x := resolveFilename(SCOPE_CURRENT_SKIN, "icons/pluto_cine.png")) else f"{PLUGIN_FOLDER}/images/cine.png")
        self.cine_half_png = LoadPixmap(x if fileExists(x := resolveFilename(SCOPE_CURRENT_SKIN, "icons/pluto_cine_half.png")) else f"{PLUGIN_FOLDER}/images/cine_half.png")
        self.cine_end_png = LoadPixmap(x if fileExists(x := resolveFilename(SCOPE_CURRENT_SKIN, "icons/pluto_cine_end.png")) else f"{PLUGIN_FOLDER}/images/cine_end.png")

        MenuList.__init__(self, entries, content=eListboxPythonMultiContent)
        font = fonts.get("PlutoList", applySkinFactor("Regular", 19, 35))
        self.l.setFont(0, gFont(font[0], font[1]))
        self.l.setItemHeight(font[2])

    def listentry(self, name, data, _id, epid=0):
        res = [(name, data, _id, epid)]

        png = None
        if data == "menu":
            png = self.menu_png
        elif data in {"series", "seasons"}:
            png = self.series_png
        elif data in {"movie", "episode"}:
            png = self.cine_png
            if data == "episode":
                sid = epid
            else:
                sid = _id
            last, length = resumePointsInstance.getResumePoint(sid)
            if last:
                if self.cine_half_png and (last > 900000) and (not length or (last < length - 900000)):
                    png = self.cine_half_png
                elif self.cine_end_png and last >= length - 900000:
                    png = self.cine_end_png

        res.append(MultiContentEntryText(pos=applySkinFactor(45, 7), size=applySkinFactor(533, 35), font=0, text=name))
        if png:
            res.append(MultiContentEntryPixmapAlphaBlend(pos=applySkinFactor(7, 9), size=applySkinFactor(20, 20), png=png, flags=BT_SCALE | BT_KEEP_ASPECT_RATIO))
        return res


class PlutoTV(Screen, HelpableScreen):
    skin = f"""
        <screen name="PlutoTV" zPosition="2" position="0,0" resolution="1920,1080" size="1920,1080" flags="wfNoBorder" title="Pluto TV" transparent="0">
            <ePixmap pixmap="{PLUGIN_FOLDER}/images/plutotv-backdrop.jpg" position="0,0" size="1920,1080" zPosition="-2" alphatest="off" />
            <eLabel position="70,30" size="1780,90" zPosition="1" backgroundColor="#16101113" cornerRadius="12"/><!-- header background -->
            <ePixmap pixmap="{PLUGIN_FOLDER}/images/logo.png" position="70,30" size="486,90" zPosition="5" alphatest="blend" transparent="1" scale="1"/>
            <widget source="global.CurrentTime" render="Label" position="e-400,48" size="300,55" font="Regular; 43" halign="right" zPosition="5" backgroundColor="#00000000" transparent="1">
                <convert type="ClockToText">Format:%H:%M</convert>
            </widget>

            <widget name="loading" position="center,center" size="800,60" font="Regular;50" backgroundColor="#00000000" transparent="0" zPosition="10" halign="center" valign="center" />
            <widget source="playlist" render="Label" position="400,48" size="1150,55" font="Regular;40" backgroundColor="#00000000" transparent="5" foregroundColor="#00ffff00" zPosition="2" halign="center" />
            <eLabel position="70,170" size="615,750" zPosition="1" backgroundColor="#16101113"/><!-- list background -->
            <widget name="feedlist" position="70,170" size="615,728" scrollbarMode="showOnDemand" enableWrapAround="1" transparent="1" zPosition="5" foregroundColor="#00ffffff" backgroundColorSelected="#00ff0063" backgroundColor="#00000000" />
            <widget source="vtitle" render="Label" position="685,170" size="1165,750" zPosition="0" backgroundColor="#16101113" foregroundColor="#16101113" font="Regular;1"><!-- background for all info -->
                <convert type="ConditionalShowHide"/>
            </widget>
            <widget source="vtitle" render="Label" position="778,180" size="1065,48" font="Regular;35" backgroundColor="#00000000" foregroundColor="#00ffff00" zPosition="3" transparent="1" />
            <widget name="posterBG" position="733,233" size="472,679" widgetBorderWidth="2" font="Regular;0" backgroundColor="black" foregroundColor="black" widgetBorderColor="#00ffde2b" cornerRadius="27" zPosition="3" alphatest="blend"/>
            <widget name="poster" position="735,235" size="468,675" zPosition="5" cornerRadius="25" backgroundColor="black" transparent="1" alphatest="blend"/>
            <widget name="info" position="1223,235" size="619,675" zPosition="5" font="Regular;27" transparent="1" />

            <widget source="updated" render="Label" position="70,950" size="615,50" zPosition="1" backgroundColor="#16101113" foregroundColor="#16101113" font="Regular;1"><!-- updated background -->
                <convert type="ConditionalShowHide"/>
            </widget>
            <widget source="updated" render="Label" position="70,950" size="615,50" font="Regular;25" zPosition="5" transparent="1" valign="center" halign="center"/>

            <eLabel position="0,e-60" size="1920,60" zPosition="1" backgroundColor="#16101113" cornerRadius="12"/><!-- key background -->
            <widget addon="ColorButtonsSequence" connection="key_red,key_green,key_yellow,key_blue"
                textColors="key_red:#00ff0808,key_green:#0004c81b,key_yellow:#00edf506,key_blue:#00077cf5"
                position="224,1030" size="1694,42" font="Regular;33" backgroundColor="#00000000" transparent="1" alignment="left" zPosition="10" spacing="10" />
            <ePixmap pixmap="buttons/key_menu.png" alphatest="blend" position="30,1031" size="52,38" backgroundColor="#00000000" transparent="1" zPosition="2"/>
            <ePixmap pixmap="buttons/key_help.png" alphatest="blend" position="82,1031" size="52,38" backgroundColor="#00000000" transparent="1" zPosition="2"/>
        </screen>"""

    def __init__(self, session):
        self.session = session
        Screen.__init__(self, session)
        HelpableScreen.__init__(self)

        self.colors = parameters.get("PlutoTvColors", [])  # First item must be default text colour. If parameter is missing adding colours will be skipped.

        self["feedlist"] = PlutoList([])
        self["playlist"] = StaticText()
        self["loading"] = Label(_("Loading data... Please wait"))
        self["vtitle"] = StaticText()
        self["key_red"] = StaticText(_("Exit"))
        self["key_yellow"] = StaticText()
        self.mdb = isPluginInstalled("tmdb") and "tmdb" or isPluginInstalled("IMDb") and "imdb"
        self.yellowLabel = _("TMDb Search") if self.mdb == "tmdb" else (_("IMDb Search") if self.mdb else "")
        self["key_green"] = StaticText()
        self["updated"] = StaticText()
        self["key_menu"] = StaticText(_("MENU"))
        self["key_blue"] = StaticText(_("Change country"))
        self["poster"] = Pixmap()
        self["posterBG"] = Label()
        self["info"] = ScrollLabel()  # combined info for fluid layout

        self["feedlist"].onSelectionChanged.append(self.update_data)

        self.picname = ""

        self["actions"] = HelpableActionMap(
            self, ["SetupActions", "InfobarChannelSelection", "MenuActions"],
            {
                "ok": (self.action, _("Go forward one level including starting playback")),
                "cancel": (self.exit, _("Go back one level including exiting")),
                "save": (self.green, _("Create or update PlutoTV live bouquets")),
                "historyBack": (self.back, _("Go back one level")),
                "menu": (self.loadSetup, _("Open the plugin configuration screen")),
            }, -1
        )

        self["MDBActions"] = HelpableActionMap(
            self, ["ColorActions"],
            {
                "yellow": (self.MDB, _("Search for information in %s") % (_("The Movie Database") if self.mdb == "tmdb" else _("the Internet Movie Database"))),
            }, -1
        )
        self["MDBActions"].setEnabled(False)

        self["CountryActions"] = HelpableActionMap(
            self,
            ["ColorActions"],
            {
                "blue": (self.switchCountry, _("Load the VoD list of another country")),
            },
            -1
        )

        self["InfoNavigationActions"] = HelpableActionMap(
            self, ["NavigationActions"],
            {
                "pageUp": (self["info"].pageUp, _("Scroll the information field")),
                "pageDown": (self["info"].pageDown, _("Scroll the information field")),
            }, -1
        )

        self.updatebutton()

        if self.updatebutton not in Silent.afterUpdate:
            Silent.afterUpdate.append(self.updatebutton)

        self.updateDataTimer = eTimer()
        self.updateDataTimer.callback.append(self.update_data_delayed)
        self.country = config.plugins.plutotv.country.value
        self.initialise()
        self.onLayoutFinish.append(self.getCategories)

    def initialise(self):
        self.titlemenu = _("VOD Menu") + (" - " + COUNTRY_NAMES[self.country] if self.country in COUNTRY_NAMES else "")
        self.films = []
        self.menu = []
        self.history = []
        self.chapters = {}
        self.numSeasons = 0
        self.vinfo = ""
        self.description = ""
        self.eptitle = ""
        self.epinfo = ""
        self["feedlist"].setList([])
        self["poster"].hide()
        self["posterBG"].hide()
        self["info"].setText("")
        self["vtitle"].setText("")
        self["playlist"].setText(self.titlemenu)
        self["loading"].show()
        self.title = _("PlutoTV") + " - " + self.titlemenu

    def update_data(self):
        self.updateDataTimer.stop()
        if not (selection := self.getSelection()):
            return
        _index, _name, __type, _id = selection
        self["MDBActions"].setEnabled(False)
        self["key_yellow"].text = ""
        if __type == "menu":
            self["poster"].hide()
            self["posterBG"].hide()
            self.updateInfo()
        else:
            self.updateDataTimer.start(500, 1)

    def update_data_delayed(self):
        if not (selection := self.getSelection()):
            return
        index, _name, __type, _id = selection
        if __type in {"movie", "series"}:
            film = self.films[index]
            self.description = film[2].decode("utf-8")
            self["vtitle"].text = film[1].decode("utf-8")
            info = film[4].decode("utf-8") + "       "
            self["MDBActions"].setEnabled(True)
            self["key_yellow"].text = self.yellowLabel

            if __type == "movie":
                info += strftime("%Hh %Mm", gmtime(int(film[5])))
            else:
                info += __("%s Season available", "%s Seasons available", film[10]) % film[10]
                self.numSeasons = film[10]
            self.vinfo = info
            picname = film[0] + ".jpg"
            self.picname = picname
            pic = film[6]
            if len(picname) > 5:
                self["poster"].hide()
                self["posterBG"].hide()
                threads.deferToThread(downloadPoster, pic, picname, self.downloadPosterCallback)

        elif __type == "seasons":
            self.eptitle = ""
            self.epinfo = ""
            if self.numSeasons == 1:  # if numSeasons == 1 skip displaying the seasons level and go directly to the next level.
                # Fix a timing issue. Calling self.lastAction directly results in the title for the previous level being displayed.
                self.lastActionTimer = eTimer()
                self.lastActionTimer.callback.append(self.lastAction)
                self.lastActionTimer.start(10, 1)

        elif __type == "episode":
            film = self.chapters[_id][index]
            self.eptitle = film[1].decode("utf-8") + "  " + strftime("%Hh %Mm", gmtime(int(film[5])))
            self.epinfo = film[3].decode("utf-8")
            self.updateInfo()

    def updateInfo(self):
        # combine info for fluid layout
        vinfoColored = self.vinfo and self.addColor(self.vinfo)
        eptitleColored = self.eptitle and self.addColor(self.eptitle)
        spacer = "\n" if (vinfoColored or self.description) and (eptitleColored or self.epinfo) else ""
        self["info"].setText("\n".join([x for x in (vinfoColored, self.description, spacer, eptitleColored, self.epinfo) if x]))

    def downloadPosterCallback(self, filename, name):
        if name == self.picname:  # check if this is the current image we are waiting for
            self.updateInfo()
            self.showPoster(filename, name)

    def showPoster(self, filename, name):
        try:
            if name == self.picname and filename and os.path.isfile(filename):
                self["poster"].instance.setPixmapScale(BT_SCALE | BT_KEEP_ASPECT_RATIO | BT_HALIGN_CENTER | BT_VALIGN_CENTER)
                self["poster"].instance.setPixmap(LoadPixmap(filename))
                self["poster"].show()
                self["posterBG"].show()
        except Exception as ex:
            print("[PlutoScreen] showPoster, ERROR", ex)

    def getCategories(self):
        self.lvod = {}
        threads.deferToThread(plutoRequest.getOndemand, self.country).addCallback(self.getCategoriesCallback)

    def getCategoriesCallback(self, ondemand):
        if not (categories := ondemand.get("categories", [])):
            self.session.open(MessageBox, _("There is no data, it is possible that Pluto TV is not available in your country"), type=MessageBox.TYPE_ERROR, timeout=10)
        else:
            for category in categories:
                self.buildlist(category)
            # Sort categories and items within each category alphabetically
            self.menu.sort(key=lambda x: re.sub(r"^[\W_]+", "", x.decode("utf-8").casefold()))
            for _key, items in self.lvod.items():
                items.sort(key=lambda x: re.sub(r"^[\W_]+", "", x[1].decode("utf-8")).casefold())
            entries = []
            for key in self.menu:
                entries.append(self["feedlist"].listentry(key.decode("utf-8"), "menu", ""))
            self["feedlist"].setList(entries)
        self["loading"].hide()

    def buildlist(self, category):
        name = category["name"].encode("utf-8")
        self.lvod[name] = []

        self.menu.append(name)
        items = category.get("items", [])
        for item in items:
            # film = (_id, name, summary, genre, rating, duration, poster, image, type)
            itemid = item.get("_id", "")
            if not itemid:
                continue
            itemname = item.get("name", "").encode("utf-8")
            itemsummary = item.get("summary", "").encode("utf-8")
            itemgenre = item.get("genre", "").encode("utf-8")
            itemrating = item.get("rating", "").encode("utf-8")
            itemduration = int(item.get("duration", "0") or "0") // 1000  # in seconds
            itemtype = item.get("type", "")
            seasons = len(item.get("seasonsNumbers", []))
            urls = item.get("stitched", {}).get("urls", [])
            url = urls[0].get("url", "") if urls else ""

            itemposter, itemimage = pickBestImage(item.get("covers", []))
            self.lvod[name].append((itemid, itemname, itemsummary, itemgenre, itemrating, itemduration, itemposter, itemimage, itemtype, url, seasons))

    def buildchapters(self, chapters):
        self.chapters.clear()
        items = chapters.get("seasons", [])
        for item in items:
            chs = item.get("episodes", [])
            for ch in chs:
                if (season := str(ch.get("season", 0))) != "0":
                    if season not in self.chapters:
                        self.chapters[season] = []
                    _id = ch.get("_id", "")
                    name = ch.get("name", "").encode("utf-8")
                    number = str(ch.get("number", 0))
                    summary = ch.get("description", "").encode("utf-8")
                    rating = ch.get("rating", "")
                    duration = ch.get("duration", 0) // 1000
                    genre = ch.get("genre", "").encode("utf-8")
                    imgs = ch.get("covers", [])
                    urls = ch.get("stitched", {}).get("urls", [])
                    url = urls[0].get("url", "") if urls else ""

                    itemposter, itemimage = pickBestImage(imgs)
                    self.chapters[season].append((_id, name, number, summary, rating, duration, genre, itemposter, itemimage, url))

    def getSelection(self):
        index = self["feedlist"].getSelectionIndex()
        if current := self["feedlist"].getCurrent():
            data = current[0]
            return index, data[0], data[1], data[2]
        return None

    def action(self):
        if not (selection := self.getSelection()):
            return
        self.lastAction = self.action
        index, name, __type, _id = selection
        menu = []
        menuact = self.titlemenu
        if __type == "menu":
            self.films = self.lvod[self.menu[index]]
            for x in self.films:
                sname = x[1].decode("utf-8")
                stype = x[8]
                sid = x[0]
                menu.append(self["feedlist"].listentry(sname, stype, sid))
            self["feedlist"].moveToIndex(0)
            self["feedlist"].setList(menu)
            self.titlemenu = name
            self["playlist"].text = self.titlemenu
            self.title = _("PlutoTV") + " - " + self.titlemenu
            self.history.append((index, menuact))
        elif __type == "series":
            self["loading"].show()
            self._series_name = name
            self._series_index = index
            self._series_menuact = menuact
            threads.deferToThread(plutoRequest.getVOD, _id, self.country).addCallback(self._getVODCallback)
        elif __type == "seasons":
            for key in self.chapters[_id]:
                sname = key[1].decode("utf-8")
                stype = "episode"
                sid = key[0]
                menu.append(self["feedlist"].listentry(_("Episode") + " " + key[2] + ". " + sname, stype, _id, key[0]))
            self["feedlist"].setList(menu)
            self.titlemenu = menuact.split(" - ")[0] + " - " + name
            self["playlist"].text = self.titlemenu
            self.title = _("PlutoTV") + " - " + self.titlemenu
            self.history.append((index, menuact))
            self["feedlist"].moveToIndex(0)
        elif __type == "movie":
            film = self.films[index]
            sid = film[0]
            name = film[1].decode("utf-8")
            url = film[9]
            self.playVOD(name, sid, url)
        elif __type == "episode":
            film = self.chapters[_id][index]
            sid = film[0]
            name = film[1].decode("utf-8")
            url = film[9]
            self.playVOD(name, sid, url)

    def back(self):
        if not (selection := self.getSelection()):
            return
        self.lastAction = self.back
        _index, _name, __type, _id = selection
        menu = []
        if self.history:
            hist = self.history[-1][0]
            histname = self.history[-1][1]
            if __type in {"movie", "series"}:
                for key in self.menu:
                    menu.append(self["feedlist"].listentry(key.decode("utf-8"), "menu", ""))
                self["vtitle"].text = ""
                self.vinfo = ""
                self.description = ""
            elif __type == "seasons":
                for x in self.films:
                    sname = x[1].decode("utf-8")
                    stype = x[8]
                    sid = x[0]
                    menu.append(self["feedlist"].listentry(sname, stype, sid))
            elif __type == "episode":
                for key in list(self.chapters.keys()):
                    sname = str(key)
                    stype = "seasons"
                    sid = str(key)
                    menu.append(self["feedlist"].listentry(_("Season") + " " + sname, stype, sid))
            self["feedlist"].setList(menu)
            self.history.pop()
            self["feedlist"].moveToIndex(hist)
            self.titlemenu = histname
            self["playlist"].text = self.titlemenu
            self.title = _("PlutoTV") + " - " + self.titlemenu
            if not self.history:
                self["poster"].hide()

    def _getVODCallback(self, chapters):
        self.buildchapters(chapters)
        menu = []
        for key in list(self.chapters.keys()):
            menu.append(self["feedlist"].listentry(_("Season") + " " + key, "seasons", key))
        self["feedlist"].setList(menu)
        self.titlemenu = self._series_name + " - " + _("Seasons")
        self["playlist"].text = self.titlemenu
        self.title = _("PlutoTV") + " - " + self.titlemenu
        self.history.append((self._series_index, self._series_menuact))
        self["feedlist"].moveToIndex(0)
        self["loading"].hide()

    def playVOD(self, name, sid, url=None):
        if url:
            self._play_name = name
            self._play_sid = sid
            threads.deferToThread(plutoRequest.buildVodStreamURL, url, self.country).addCallback(self._playVODCallback)

    def _playVODCallback(self, url):
        if url and self._play_name:
            string = f"4097:0:0:0:0:0:0:0:0:0:{quote(url)}:{quote(self._play_name)}"
            reference = eServiceReference(string)
            if "m3u8" in url.lower() or "127.0.0.1" in url:
                self.session.open(Pluto_Player, service=reference, sid=self._play_sid)

    def green(self):
        self.session.openWithCallback(self.endupdateLive, PlutoDownload)

    def endupdateLive(self, _ret=None):
        self.session.openWithCallback(self.updatebutton, MessageBox, _("The Pluto TV bouquets in your channel list have been updated.\n\nThey will now be rebuilt automatically every 5 hours."), type=MessageBox.TYPE_INFO, timeout=10)

    def updatebutton(self, _ret=None):
        with open("/etc/enigma2/bouquets.tv", "r", encoding="utf-8") as f:
            bouquets = f.read()
        if fileExists(TIMER_FILE) and all(((BOUQUET_FILE % cc) in bouquets) for cc in [x for x in getselectedcountries() if x]):
            with open(TIMER_FILE, "r", encoding="utf-8") as f:
                last = float(f.read().replace("\n", "").replace("\r", ""))
            updated = strftime(" %x %H:%M", localtime(int(last)))
            self["key_green"].text = _("Update LiveTV Bouquet")
            self["updated"].text = _("LiveTV Bouquet last updated:") + updated
        elif "pluto_tv" in bouquets:
            self["key_green"].text = _("Update LiveTV Bouquet")
            self["updated"].text = _("LiveTV Bouquet needs updating. Press GREEN.")
        else:
            self["key_green"].text = _("Create LiveTV Bouquet")
            self["updated"].text = ""

    def exit(self, *_args, **_kwargs):
        if self.history:
            self.back()
        else:
            self.close()

    def MDB(self):
        if not (selection := self.getSelection()):
            return
        _index, name, __type, _id = selection
        if __type in {"movie", "series"} and self.mdb:
            if self.mdb == "tmdb":
                from Plugins.Extensions.tmdb.tmdb import tmdbScreen
                self.session.open(tmdbScreen, name, 2)
            else:
                from Plugins.Extensions.IMDb.plugin import IMDB
                self.session.open(IMDB, name, False)

    def loadSetup(self):
        def loadSetupCallback(_result=None):
            if config.plugins.plutotv.country.value != self.country:
                self.country = config.plugins.plutotv.country.value
                self.initialise()
                self.getCategories()
        self.session.openWithCallback(loadSetupCallback, PlutoSetup)

    def switchCountry(self):
        def switchCountryCallback(result=None):
            if result and result[1] != self.country:
                self.country = result[1]
                self.initialise()
                self.getCategories()
        self.session.openWithCallback(
            switchCountryCallback,
            ChoiceBox,
            title=_("Temporarily switch the VoD list to another country"),
            list=list(zip(config.plugins.plutotv.country.description, config.plugins.plutotv.country.choices)),
            selection=config.plugins.plutotv.country.choices.index(self.country),
            keys=[]
        )

    def addColor(self, text, i=1):
        if i < len(self.colors):
            text = Hex2strColor(self.colors[i]) + text + Hex2strColor(self.colors[0])
        return text

    def close(self, *_args, **_kwargs):
        if self.updatebutton in Silent.afterUpdate:
            Silent.afterUpdate.remove(self.updatebutton)
        Screen.close(self)


class PlutoSetup(Setup):
    def __init__(self, session):
        Setup.__init__(self, session, yellow_button={"function": self.yellow}, blue_button={"function": self.blue})
        self.updateYellowButton()
        self.updateBlueButton()
        self.setTitle(_("PlutoTV Setup"))

    def createSetup(self):
        configList = []
        configList.append((_("VoD country"), config.plugins.plutotv.country, _("Select the country that the VoD list will be created for.")))
        configList.append(("---",))
        for n in range(1, NUMBER_OF_LIVETV_BOUQUETS + 1):
            if n == 1 or getattr(config.plugins.plutotv, "live_tv_country" + str(n - 1)).value:
                configList.append((_("LiveTV bouquet %s") % n, getattr(config.plugins.plutotv, "live_tv_country" + str(n)), _("Country for which LiveTV bouquet %s will be created.") % n))
        configList.append(("---",))
        configList.append((_('Live TV mode'), config.plugins.plutotv.live_tv_mode, _('Select the stream provider. Stitcher uses the native Pluto server with JWT auth (resolved at playback). JMP2 uses the jmp2.uk proxy. i.mjh.nz uses Matt Huisman\'s community playlist. Requires bouquet update to take effect.')))
        configList.append((_("Picon type"), config.plugins.plutotv.picons, _("Using service name picons means they will continue to work even if the service reference changes. Also, they can be shared between channels of the same name that don't have the same service references.")))
        configList.append((_("Data location"), config.plugins.plutotv.datalocation, _("Used for storing video cover graphics, etc. A hard drive that goes into standby mode or a slow network mount are not good choices.")))
        self["config"].list = configList

    def updateYellowButton(self):
        if os.path.isdir(PiconFetcher().pluginPiconDir):
            self["key_yellow"].text = _("Remove picons")
        else:
            self["key_yellow"].text = ""

    def updateBlueButton(self):
        with open("/etc/enigma2/bouquets.tv", "r", encoding="utf-8") as f:
            bouquets = f.read()
        if "pluto_tv" in bouquets:
            self["key_blue"].text = _("Remove LiveTV Bouquet")
        else:
            self["key_blue"].text = ""

    def yellow(self):
        if self["key_yellow"].text:
            PiconFetcher().removeall()
            self.updateYellowButton()

    def blue(self):
        if self["key_blue"].text:
            Silent.stop()
            from enigma import eDVBDB
            eDVBDB.getInstance().removeBouquet(re.escape(BOUQUET_FILE) % ".*")
            self.updateBlueButton()


class Pluto_Player(MoviePlayer):

    ENABLE_RESUME_SUPPORT = False    # Don"t use Enigma2 resume support. We use self resume support

    def __init__(self, session, service, sid):
        self.session = session
        self.mpservice = service
        self.id = sid
        MoviePlayer.__init__(self, self.session, service, sid)
        self.skinName = ["MoviePlayer"]

        self.__event_tracker = ServiceEventTracker(  # pylint: disable=unused-private-member
            screen=self,
            eventmap={
                iPlayableService.evStart: self.__serviceStarted,
            }
        )

        self["actions"] = ActionMap(
            ["MoviePlayerActions", "OkActions"],
            {
                "leavePlayerOnExit": self.leavePlayer,
                "leavePlayer": self.leavePlayer,
                "ok": self.toggleShow,
            }, -3
        )
        self.session.nav.playService(self.mpservice)

    def up(self):
        pass

    def down(self):
        pass

    def doEofInternal(self, _playing):
        self.close()

    def __serviceStarted(self):
        service = self.session.nav.getCurrentService()
        seekable = service.seek()
        last, length = resumePointsInstance.getResumePoint(self.id)
        if last is None or seekable is None:
            return
        length = seekable.getLength() or (None, 0)
        # This implies we don't resume if the length is unknown...
        if (last > 900000) and (not length[1] or (last < length[1] - 900000)):
            self.last = last
            last /= 90000
            Notifications.AddNotificationWithCallback(self.playLastCB, MessageBox, _("Do you want to resume this playback?") + "\n" + (_("Resume position at %s") % f"{int(last / 3600)}:{int(last % 3600 / 60):02d}:{int(last % 60):02d}"), timeout=10, default="yes" in config.usage.on_movie_start.value)

    def playLastCB(self, answer):
        if answer is True and self.last:
            self.doSeek(self.last)
        self.hideAfterResume()

    def leavePlayer(self):
        self.is_closing = True
        resumePointsInstance.setResumePoint(self.session, self.id)
        self.close()

    def leavePlayerConfirmed(self, answer):
        pass


def sessionstart(reason, session, **kwargs):  # pylint: disable=unused-argument
    if hasattr(session.nav, "playServiceExtensions") and playServiceExtension not in session.nav.playServiceExtensions:
        session.nav.playServiceExtensions.append(playServiceExtension)
    if hasattr(session.nav, "recordServiceExtensions") and recordServiceExtension not in session.nav.recordServiceExtensions:
        session.nav.recordServiceExtensions.append(recordServiceExtension)
    Silent.init(session)
    from twisted.internet import reactor
    reactor.callLater(30, startProactiveRefresh)


def Download_PlutoTV(session, **_kwargs):
    session.open(PlutoDownload)


def system(session, **_kwargs):
    session.open(PlutoTV)


def Plugins(**_kwargs):
    return [
        PluginDescriptor(name=_("PlutoTV"), where=PluginDescriptor.WHERE_PLUGINMENU, icon=PLUGIN_ICON, description=_("View video on demand and download a bouquet of live tv channels"), fnc=system, needsRestart=True),
        PluginDescriptor(name=_("Download PlutoTV bouquet, picons and EPG"), where=PluginDescriptor.WHERE_EXTENSIONSMENU, fnc=Download_PlutoTV, needsRestart=True),
        PluginDescriptor(name=_("Silently download PlutoTV"), where=PluginDescriptor.WHERE_SESSIONSTART, fnc=sessionstart),
    ]
