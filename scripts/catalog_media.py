"""Reproduce the supplied x4 exports from their lossless native cutouts.

Uses the same premultiplied Lanczos algorithm and WebP options as the accepted
extraction pipeline. Both input and output must match its recorded SHA-256.
The repository stores only native media; generated x4 exports belong in dist.
"""
from pathlib import Path
import hashlib, json, zipfile
from concurrent.futures import ThreadPoolExecutor
from PIL import Image

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def build_media(root, dist):
    units=json.loads((root/'content/catalog/catalog.json').read_text(encoding='utf-8'))['units']
    images={i['id']:i for u in units for i in u['figures']+[i for w in u.get('weapons',[]) for i in w['images']]}
    small={i['small']:i['small_sha256'] for i in images.values()}
    for archive in sorted((root/'content/catalog/media').glob('native-*.zip')):
        with zipfile.ZipFile(archive) as bundle:
            for entry in bundle.infolist():
                if entry.filename not in small:
                    raise ValueError('Unexpected media archive entry: '+entry.filename)
                data=bundle.read(entry)
                if hashlib.sha256(data).hexdigest()!=small[entry.filename]:
                    raise ValueError('Native image hash mismatch: '+entry.filename)
                target=dist/entry.filename
                target.parent.mkdir(parents=True,exist_ok=True)
                target.write_bytes(data)
    def reproduce(image):
        native=dist/image['small'];large=dist/image['large']
        assert native.is_file() and digest(native)==image['small_sha256'],native
        if large.is_file() and digest(large)==image['large_sha256']:
            return
        with Image.open(native) as source:
            result=source.convert('RGBa').resize((source.width*4,source.height*4),Image.Resampling.LANCZOS).convert('RGBA')
        result.paste((0,0,0,0),mask=result.getchannel('A').point(lambda a:255 if a==0 else 0))
        large.parent.mkdir(parents=True,exist_ok=True)
        result.save(large,lossless=True,exact=True,method=6)
        if digest(large)!=image['large_sha256']:
            raise ValueError('Reproduced image differs from accepted export: '+image['id'])
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(reproduce,images.values()))

def package_native(root):
    """Local source-preparation step; deterministic, bounded archives for GitHub."""
    units=json.loads((root/'content/catalog/catalog.json').read_text(encoding='utf-8'))['units']
    images={i['small']:i['small_sha256'] for u in units for i in u['figures']+[i for w in u.get('weapons',[]) for i in w['images']]}
    destination=root/'content/catalog/media';destination.mkdir(exist_ok=True)
    groups=[[]];size=0
    for name,expected in sorted(images.items()):
        data=(root/name).read_bytes();assert hashlib.sha256(data).hexdigest()==expected
        if size+len(data)>3*1024*1024 and groups[-1]:groups.append([]);size=0
        groups[-1].append((name,data));size+=len(data)
    for index,group in enumerate(groups,1):
        with zipfile.ZipFile(destination/f'native-{index:02}.zip','w',compression=zipfile.ZIP_STORED) as bundle:
            for name,data in group:
                info=zipfile.ZipInfo(name,date_time=(2026,11,12,0,0,0));info.external_attr=0o644<<16
                bundle.writestr(info,data)
    print(f'Packaged {len(images)} lossless native cutouts in {len(groups)} archives.')

if __name__=='__main__':
    package_native(Path(__file__).resolve().parents[1])
