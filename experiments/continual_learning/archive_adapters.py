"""Download completed sampler checkpoints without persisting signed URLs."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import logging
import os
import re
import tarfile
from run import RUN, BASE_URL, write_json


def main():
    import httpx
    import tinker
    logging.disable(logging.CRITICAL)
    service=tinker.ServiceClient(api_key=os.environ['TINKER_API_KEY'],base_url=BASE_URL)
    rest=service.create_rest_client()
    folder=RUN/'checkpoint_archives'
    folder.mkdir(exist_ok=True)
    manifests=[json.loads(p.read_text()) for p in sorted((RUN/'training').glob('*/checkpoint.json'))]
    def archive(m):
        name=m['name']
        assert re.fullmatch(r'[A-Za-z0-9.-]+',name) and '..' not in name
        target=folder/(name+'.tar')
        receipt=folder/(name+'.json')
        if target.exists() and receipt.exists():
            result=json.loads(receipt.read_text())
            assert target.stat().st_size==result['bytes']
            return result
        signed=rest.get_checkpoint_archive_url_from_tinker_path(m['sampling_path']).result()
        assert signed.url.startswith('https://')
        partial=target.with_suffix('.part')
        digest=hashlib.sha256()
        try:
            with httpx.stream('GET',signed.url,timeout=120,follow_redirects=True) as r:
                r.raise_for_status()
                with partial.open('wb') as f:
                    for chunk in r.iter_bytes(1024*1024):
                        f.write(chunk)
                        digest.update(chunk)
        except Exception as e:
            raise RuntimeError('Archive download failed: '+type(e).__name__) from None
        with tarfile.open(partial) as bundle:
            members=[x.name for x in bundle.getmembers() if x.isfile()]
        assert members and partial.stat().st_size>0
        partial.replace(target)
        result=dict(name=name,archive=target.name,bytes=target.stat().st_size,
                    sha256=digest.hexdigest(),members=members,sampling_path=m['sampling_path'])
        write_json(receipt,result)
        print(json.dumps({'archived':name,'bytes':result['bytes']}),flush=True)
        return result
    with ThreadPoolExecutor(max_workers=3) as pool:
        receipts=list(pool.map(archive,manifests))
    write_json(RUN/'archive_manifest.json',dict(adapters=receipts,total_bytes=sum(r['bytes'] for r in receipts)))


if __name__=='__main__':
    main()
