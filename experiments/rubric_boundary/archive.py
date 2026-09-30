"""Archive finished adapters without writing signed URLs to disk."""
import hashlib
import json
import logging
import os
import tarfile
from concurrent.futures import ThreadPoolExecutor
from run import RUN, BASE_URL, read, write

def main():
    import httpx
    import tinker
    logging.disable(logging.CRITICAL)
    service=tinker.ServiceClient(api_key=os.environ['TINKER_API_KEY'],base_url=BASE_URL)
    rest=service.create_rest_client()
    def archive(path):
        m=read(path)
        name=m['name']
        folder=RUN/'archives'; folder.mkdir(exist_ok=True)
        target=folder/f'{name}.tar'
        if target.exists() and target.with_suffix('.json').exists(): return read(target.with_suffix('.json'))
        url=rest.get_checkpoint_archive_url_from_tinker_path(m['sampling_path']).result().url
        assert url.startswith('https://')
        digest=hashlib.sha256()
        partial=target.with_suffix('.part')
        try:
            with httpx.stream('GET',url,timeout=120,follow_redirects=True) as response:
                response.raise_for_status()
                with partial.open('wb') as out:
                    for chunk in response.iter_bytes(1024*1024):
                        out.write(chunk); digest.update(chunk)
        except Exception as e: raise RuntimeError('Archive download failed: '+type(e).__name__) from None
        with tarfile.open(partial) as bundle: members=[x.name for x in bundle.getmembers() if x.isfile()]
        assert members
        partial.replace(target)
        result=dict(name=name,bytes=target.stat().st_size,sha256=digest.hexdigest(),members=members,sampling_path=m['sampling_path'])
        write(target.with_suffix('.json'),result)
        print(json.dumps(dict(archived=name,bytes=result['bytes'])),flush=True)
        return result
    with ThreadPoolExecutor(max_workers=3) as pool:
        result=list(pool.map(archive,sorted((RUN/'training').glob('*/checkpoint.json'))))
    write(RUN/'archives.json',result)

if __name__=='__main__': main()
