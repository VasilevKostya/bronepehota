"""Fetch open font/icon source assets once; builds then work without network."""
from pathlib import Path
from urllib.request import urlopen
import json, tarfile, io
root=Path(__file__).resolve().parents[1]
fonts=root/'assets/fonts'; icons=root/'assets/icons'; licenses=root/'assets/licenses'
for p in (fonts,icons,licenses): p.mkdir(parents=True,exist_ok=True)
for family,files in {'ptsans':['PT_Sans-Web-Regular.ttf','PT_Sans-Web-Bold.ttf','PT_Sans-Web-Italic.ttf'], 'ptsansnarrow':['PT_Sans-Narrow-Web-Bold.ttf']}.items():
    for f in files:
        (fonts/f).write_bytes(urlopen(f'https://raw.githubusercontent.com/google/fonts/main/ofl/{family}/{f}').read())
    (licenses/f'{family}-OFL.txt').write_bytes(urlopen(f'https://raw.githubusercontent.com/google/fonts/main/ofl/{family}/OFL.txt').read())
metadata=json.load(urlopen('https://registry.npmjs.org/@phosphor-icons/core/latest'))
archive=tarfile.open(fileobj=io.BytesIO(urlopen(metadata['dist']['tarball']).read()),mode='r:gz')
for name in ['magnifying-glass','list','download-simple','arrow-left','arrow-right','caret-down','x','check-circle','warning','link','book-open','arrows-clockwise','wifi-slash']:
    member=archive.getmember(f'package/assets/regular/{name}.svg')
    (icons/f'{name}.svg').write_bytes(archive.extractfile(member).read())
license_member=next(x for x in archive.getmembers() if x.name.lower()=='package/license')
(licenses/'phosphor-LICENSE.txt').write_bytes(archive.extractfile(license_member).read())
print('Fonts and icons saved. Phosphor version:',metadata['version'])
