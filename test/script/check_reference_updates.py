"""Snapshot public DOI metadata and registered update flags for one project.

This is a bounded registry check, not an assertion that no undisclosed retraction
exists. Publisher verification records and contextual relevance remain manual.
"""
import argparse
import concurrent.futures
import datetime
import json
import re
import urllib.parse
import urllib.request
from pathlib import Path


def fetch(doi):
    url = 'https://api.crossref.org/works/' + urllib.parse.quote(doi, safe='')
    row = {'doi': doi, 'source': url}
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'ResearchDraftVerification/2.0'})
        with urllib.request.urlopen(req, timeout=35) as response:
            m = json.load(response)['message']
        for key in ('title', 'author', 'published', 'published-print', 'published-online',
                    'container-title', 'volume', 'issue', 'page', 'article-number',
                    'update-to', 'updated-by', 'relation', 'URL', 'type'):
            row[key] = m.get(key)
        row['status'] = 'retrieved'
    except Exception as exc:
        row.update(status='unavailable', error=str(exc))
    return row


def main():
    p = argparse.ArgumentParser()
    p.add_argument('project', type=Path)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    manuscript = a.project/'论文_中文.md'
    source_path = manuscript if manuscript.is_file() else a.project/'文献核验.md'
    source = source_path.read_text(encoding='utf-8')
    dois = list(dict.fromkeys(x.rstrip('.,;。') for x in re.findall(r'10\.\d{4,9}/[^\s<>)]+', source)))
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        result = list(pool.map(fetch, dois))
    out = {'checked_at': datetime.datetime.now().astimezone().isoformat(),
           'scope': 'Crossref DOI metadata and deposited update-to/updated-by/relation fields only; absence is not proof of absence of a retraction.',
           'project': str(a.project.resolve()), 'references': result}
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text(json.dumps(out, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    for row in result:
        print(row['doi'], row['status'], row.get('title'), row.get('published'),
              'updates=', row.get('update-to'), row.get('updated-by'), row.get('relation'))


if __name__ == '__main__':
    main()
