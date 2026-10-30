"""Durable knowledge promotion journal with optimistic rollback and crash recovery."""
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import uuid

KB='550-derlenmis-bilgi-tabani'


class PromotionError(ValueError):pass


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def sync_directory(path):
    if os.name=='posix':
        fd=os.open(path,os.O_RDONLY)
        try:os.fsync(fd)
        finally:os.close(fd)


def atomic(path, raw, mode=0o600):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.NamedTemporaryFile('wb',dir=path.parent,delete=False) as f:
        f.write(raw);f.flush();os.fsync(f.fileno());temp=Path(f.name)
    temp.chmod(mode);os.replace(temp,path)
    sync_directory(path.parent)


def record(folder, data):atomic(folder/'manifest.json',json.dumps(data,sort_keys=True).encode())


def destination(root, relative):
    p=Path(relative)
    if p.is_absolute() or '..' in p.parts or p.as_posix()!=relative or not relative.startswith(KB+'/') or p.suffix!='.md':
        raise PromotionError('promotion-path-invalid')
    result=Path(root)/p
    if result.is_symlink() or not result.resolve().is_relative_to(Path(root).resolve()):
        raise PromotionError('promotion-path-escape')
    return result


def rollback(root, folder, data):
    # Validate the entire generation first; external edits must not be overwritten.
    for entry in data['entries']:
        path=destination(root,entry['path']);actual=sha(path) if path.exists() else None
        if actual not in (entry['old'],entry['new']):
            raise PromotionError('promotion-recovery-conflict:'+entry['path'])
        if entry['old'] is not None:
            backup=folder/entry['blob']
            if not backup.is_file() or sha(backup)!=entry['old']:
                raise PromotionError('promotion-backup-invalid')
    data['status']='rolling_back';record(folder,data)
    for entry in reversed(data['entries']):
        path=destination(root,entry['path']);actual=sha(path) if path.exists() else None
        if actual==entry['old']:continue
        if actual!=entry['new']:raise PromotionError('promotion-recovery-conflict:'+entry['path'])
        if entry['old'] is None:
            # Preserve a newly created output in the journal rather than deleting it.
            archive=folder/('reverted-'+entry['new']+'.md')
            os.replace(path,archive)
            sync_directory(path.parent);sync_directory(folder)
        else:
            atomic(path,(folder/entry['blob']).read_bytes(),entry.get('mode',0o644))
    data['status']='rolled_back';record(folder,data)


def recover(root):
    home=Path(root)/'.beyin/scripts/.state/promotions'
    recovered=[]
    if not home.exists():return recovered
    for folder in sorted(home.iterdir()):
        if not folder.is_dir() or folder.is_symlink():continue
        manifest=folder/'manifest.json'
        if not manifest.exists():continue  # No prepared journal means no live writes started.
        data=json.loads(manifest.read_text())
        if not isinstance(data,dict) or data.get('schema')!=1 or not isinstance(data.get('entries'),list) or data.get('status') not in ('prepared','applying','rolling_back','committed','rolled_back'):
            raise PromotionError('promotion-journal-invalid')
        if data['status'] in ('committed','rolled_back'):continue
        seen=set()
        for entry in data['entries']:
            if not isinstance(entry,dict) or not {'path','blob','old','new','mode'}<=entry.keys():
                raise PromotionError('promotion-entry-invalid')
            if not isinstance(entry['path'],str) or entry['path'] in seen:
                raise PromotionError('promotion-path-invalid')
            destination(root,entry['path']);seen.add(entry['path'])
            if type(entry['mode']) is not int or not 0<=entry['mode']<=0o777:
                raise PromotionError('promotion-mode-invalid')
            if not isinstance(entry['blob'],str):raise PromotionError('promotion-blob-invalid')
            if not re.fullmatch(r'[0-9a-f]{64}\.before',entry['blob']):raise PromotionError('promotion-blob-invalid')
            if not isinstance(entry['new'],str) or any(x is not None and (not isinstance(x,str) or not re.fullmatch(r'[0-9a-f]{64}',x)) for x in (entry['old'],entry['new'])):
                raise PromotionError('promotion-hash-invalid')
        rollback(root,folder,data);recovered.append(folder.name)
    return recovered


def promote(root, stage, changed, baseline, copy_file):
    recover(root)
    home=Path(root)/'.beyin/scripts/.state/promotions';home.mkdir(parents=True,exist_ok=True)
    folder=home/uuid.uuid4().hex;folder.mkdir(mode=0o700)
    sync_directory(home.parent);sync_directory(home)
    entries=[]
    for relative in changed:
        path=destination(root,relative);old=baseline[relative]
        if (sha(path) if path.exists() else None)!=old:raise PromotionError('promotion-live-changed:'+relative)
        blob=hashlib.sha256(relative.encode()).hexdigest()+'.before'
        if old is not None:atomic(folder/blob,path.read_bytes())
        entries.append({'path':relative,'old':old,'new':sha(Path(stage)/relative),'blob':blob,
                        'mode':path.stat().st_mode & 0o777 if path.exists() else 0o644})
    data={'schema':1,'status':'prepared','entries':entries}
    record(folder,data)
    try:
        data['status']='applying';record(folder,data)
        for entry in entries:
            path=destination(root,entry['path']);actual=sha(path) if path.exists() else None
            if actual!=entry['old']:raise PromotionError('promotion-live-changed:'+entry['path'])
            copy_file(Path(stage)/entry['path'],path)
            if sha(path)!=entry['new']:raise PromotionError('promotion-copy-invalid')
            sync_directory(path.parent)
        data['status']='committed';record(folder,data)
    except Exception:
        rollback(root,folder,data)
        raise
