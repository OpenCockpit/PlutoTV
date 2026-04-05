DESCRIPTION = "PlutoTV plugin for enigma2"
MAINTAINER = "xcentaurix"
LICENSE = "GPL-3.0-only"
LIC_FILES_CHKSUM = "file://LICENSE;md5=1ebbd3e34237af26da5dc08a4e440464"
HOMEPAGE = "https://github.com/OpenCockpit/PlutoTV"

RDEPENDS:${PN} = "python3-multiprocessing python3-requests python3-zoneinfo"

inherit gittag allarch python3native gettext

DEPENDS = "gettext-native"

PV = "git"
PKGV = "${GITPKGVTAG}"
SRCREV = "${AUTOREV}"
SRC_URI = "git://github.com/OpenCockpit/PlutoTV.git;protocol=https;branch=master"

pluginname = "PlutoTV"
pluginpath = "/usr/lib/enigma2/python/Plugins/Extensions/${pluginname}"

do_install:append() {
	install -d ${D}${pluginpath}
	cp -r ${S}/src/* ${D}${pluginpath}/
	cp $(S)/LICENSE $(D)/.
	python3 -m compileall -o2 -b ${D} -d /
	if command -v msgfmt > /dev/null 2>&1 ; then
		find ${S}/po/ -maxdepth 1 -type f -name '*.po' | while read po ; do
			## remove everything before and including the "/"
			filename=${po##*/}
			## remove everything after and including the "."
			cc=${filename%%.*}
			folder=${D}${pluginpath}/locale/${cc}/LC_MESSAGES
			mkdir -p ${folder}
			msgfmt -o ${folder}/${pluginname}.mo ${po}
		done
	fi
}

FILES:${PN} = "${configpath}/ ${pluginpath}/"

FILES:${PN}-src = "${pluginpath}/*.py"
