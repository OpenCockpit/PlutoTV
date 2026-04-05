#!/bin/bash

PATTERN="*_all.ipk"
CURRENT=`pwd`
TEMP=$(mktemp -d)

rm -f $CURRENT/$PATTERN # remove old ipk if exists

cp -a $CURRENT/. $TEMP

cd $TEMP

cd po
./updateallpo-multiOS.sh
cd ..

git_revision=`git rev-list HEAD --count`
git_hash=`git rev-parse HEAD`
git_tag_raw=$(git tag 2>/dev/null | sort -V | tail -1)
git_tag=${git_tag_raw:-"0.0.0"}

cd meta

# update version in control file in ipk image file only
# format matches gittag.bbclass: <tag>-git<count>+<hash8>+<hash10>
version_updated="${git_tag}-git${git_revision}+${git_hash:0:8}+${git_hash:0:10}-r0"
version_new="Version: ${version_updated}"
version_orig=`grep Version ./control/control`
sed -i "s/\b${version_orig}/${version_new}/g" ./control/control

# extract package name from control
package=$(grep Package ./control/control|cut -d " " -f 2)
echo "Package: $package"
# extract plugin name from Version.py
plugin=$(grep PLUGIN ../src/Version.py|cut -d '"' -f 2)
echo "Plugin: $plugin"

mkdir -p usr/lib/enigma2/python/Plugins/Extensions/$plugin
cp -ra ../src/. ./usr/lib/enigma2/python/Plugins/Extensions/$plugin
cp ../LICENSE ./.
tar -cvzf data.tar.gz usr

cd control
tar -cvzf control.tar.gz ./*
cd ..
mv ./control/control.tar.gz .

ar -r ../${package}_${version_updated}_all.ipk debian-binary control.tar.gz data.tar.gz

cd $CURRENT

cp $TEMP/$PATTERN $CURRENT
cp $TEMP/po/*.po $CURRENT/po/.
cp $TEMP/po/*.pot $CURRENT/po/.

rm -rf $TEMP # clean up
