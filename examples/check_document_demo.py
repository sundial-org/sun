#!/usr/bin/env python3
"""Browser integration check with optional screenshots and a demo video.

Requires: pip install playwright; playwright install chromium ffmpeg
Run: python examples/check_document_demo.py --record /tmp/sun-document-demo
Use --channel chrome to use an existing Google Chrome installation.
"""
import argparse
from pathlib import Path
import threading

from demo_documents import prepare_demo, review_web


def main():
    from playwright.sync_api import sync_playwright, expect
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--record', type=Path)
    parser.add_argument('--channel')
    args = parser.parse_args()
    destination = args.record.resolve() if args.record else None
    if destination: destination.mkdir(parents=True, exist_ok=True)
    root, data = prepare_demo()
    server, url = review_web.create_server(data)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel=args.channel)
            context = browser.new_context(viewport={'width': 1500, 'height': 1000},
                **({'record_video_dir': str(destination), 'record_video_size': {'width': 1500, 'height': 1000}}
                   if destination else {}))
            page = context.new_page()
            errors, external = [], []
            page.on('pageerror', lambda e: errors.append(str(e)))
            page.on('request', lambda r: external.append(r.url) if not r.url.startswith(('http://127.0.0.1:', 'blob:', 'data:')) else None)
            page.goto(url)
            expect(page.get_by_role('table', name='Launch budget', exact=True)).to_be_visible()
            expect(page.get_by_role('cell', name='36000', exact=True)).to_be_visible()
            expect(page.locator('#diff h2, #diff caption')).to_have_count(0)
            expect(page.get_by_role('cell', name='=SUM(B2:B4)*1.1', exact=True)).to_be_visible()
            expect(page.locator('#layout')).to_be_disabled()
            expect(page.locator('#notice')).to_be_empty()
            if destination:
                page.screenshot(path=str(destination / 'spreadsheet.png'), full_page=True)
                page.wait_for_timeout(1800)
            page.get_by_role('button', name='launch.pptx', exact=True).click()
            picker = page.get_by_label('Slide to compare')
            expect(picker).to_be_visible()
            picker.select_option('1')
            expect(page.locator('#diff h2, .change-list')).to_have_count(0)
            expect(page.locator('.slide-preview')).to_have_count(2)
            expect(page.locator('.slide-preview').last.get_by_text('42 teams', exact=True)).to_be_visible()
            expect(page.locator('#notice')).to_be_empty()
            if destination:
                page.screenshot(path=str(destination / 'slides.png'), full_page=True)
                page.wait_for_timeout(2200)
            picker.select_option('2')
            expect(page.locator('.slide-panel').first.get_by_text('Slide not present', exact=True)).to_be_visible()
            expect(page.locator('.slide-preview')).to_have_count(1)
            if destination: page.wait_for_timeout(1400)
            picker.select_option('3')
            expect(page.locator('.slide-panel').last.get_by_text('Slide not present', exact=True)).to_be_visible()
            if destination: page.wait_for_timeout(1400)
            page.get_by_role('button', name='metrics.csv', exact=True).click()
            expect(page.get_by_role('table', name='Data', exact=True)).to_be_visible()
            if destination: page.wait_for_timeout(1400)
            page.get_by_role('button', name='keynote.key', exact=True).click()
            expect(page.get_by_role('status')).to_contain_text('Export both Keynote versions')
            page.get_by_role('button', name='notes.txt', exact=True).click()
            expect(page.locator('#layout')).to_be_enabled()
            expect(page.get_by_text('Budget updated.', exact=False)).to_be_visible()
            # Switching files while the async document request is pending must not overwrite the new view.
            page.get_by_role('button', name='launch.pptx', exact=True).click()
            page.get_by_role('button', name='metrics.csv', exact=True).click()
            expect(page.get_by_role('table', name='Data', exact=True)).to_be_visible()
            expect(page.get_by_label('Slide to compare')).to_have_count(0)
            page.set_viewport_size({'width': 390, 'height': 844})
            expect(page.get_by_role('table', name='Data', exact=True)).to_be_visible()
            assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth'), 'Mobile view overflows'
            assert not errors, errors
            assert not external, external
            video = page.video
            context.close()
            if destination:
                video.save_as(str(destination / 'demo.webm'))
                video.delete()
            browser.close()
        print(f'Browser checks passed. Demo repository: {root}')
        if destination: print(f'Screenshots and video: {destination}')
    finally:
        server.shutdown(); server.server_close(); thread.join()


if __name__ == '__main__': main()
