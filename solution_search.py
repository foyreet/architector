"""Public-source discovery. Requests only go to fixed search endpoints."""
from concurrent.futures import ThreadPoolExecutor
import json
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen
from xml.etree import ElementTree


def fetch(base, params):
    req = Request(base + '?' + urlencode(params), headers={'User-Agent': 'Architector/1.0 (public source search)'})
    with urlopen(req, timeout=12) as response:
        return response.read()


def public_url(value):
    if not isinstance(value, str):
        return False
    try:
        return urlsplit(value).scheme in ('https', 'http') and bool(urlsplit(value).hostname)
    except ValueError:
        return False


def web(query):
    raw = fetch('https://www.bing.com/search', {'format': 'rss', 'q': query, 'setlang': 'en'})
    channel = ElementTree.fromstring(raw).find('channel')
    if channel is None:
        raise ValueError('Search response has no channel')
    return [{'title': item.findtext('title', ''), 'url': item.findtext('link', ''),
             'summary': item.findtext('description', '')} for item in channel.findall('item')[:5]]


def arxiv(query):
    data = fetch('https://export.arxiv.org/api/query', {'search_query': ' AND '.join('all:' + w for w in query.split()), 'max_results': 4})
    ns = {'a': 'http://www.w3.org/2005/Atom'}
    return [{'title': e.findtext('a:title', '', ns), 'url': e.findtext('a:id', '', ns),
             'summary': e.findtext('a:summary', '', ns)} for e in ElementTree.fromstring(data).findall('a:entry', ns)]


def crossref(query):
    items = json.loads(fetch('https://api.crossref.org/works', {'query.bibliographic': query, 'rows': 4}))['message']['items']
    return [{'title': (i.get('title') or [''])[0], 'url': i.get('URL'), 'summary': i.get('abstract', '')} for i in items]


def github(query):
    items = json.loads(fetch('https://api.github.com/search/repositories', {'q': query, 'per_page': 4}))['items']
    return [{'title': i['full_name'], 'url': i['html_url'], 'summary': i.get('description') or ''} for i in items]


def search(business, query):
    searches = [('Интернет · внедрения', web, business + ' production deployment case study impact results'),
                ('Интернет · неудачи', web, query + ' deployment failure postmortem lessons learned'),
                ('Интернет · бизнес-риски', web, business + ' failure postmortem'),
                ('Интернет · технические аналоги', web, query + ' implementation case study'),
                ('arXiv', arxiv, query), ('Crossref', crossref, query), ('GitHub', github, query)]
    found, failed, seen = [], [], set()
    with ThreadPoolExecutor(max_workers=len(searches)) as pool:
        jobs = [(name, pool.submit(fn, q)) for name, fn, q in searches]
        for name, job in jobs:
            try:
                for record in job.result():
                    url = record['url']
                    if not public_url(url) or not record['title'].strip() or url in seen:
                        continue
                    seen.add(url)
                    found.append({**record, 'provider': name, 'id': len(found) + 1})
            except (OSError, ValueError, KeyError, TypeError, ElementTree.ParseError):
                failed.append(name)
    return found, failed
