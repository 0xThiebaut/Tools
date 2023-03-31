from argparse import ArgumentParser, RawDescriptionHelpFormatter
from datetime import datetime
from os import utime, environ
from pathlib import Path
from random import randint
from sys import stderr
from tempfile import NamedTemporaryFile
from time import time, mktime
from typing import Sequence
from urllib.parse import urlparse, unquote

try:
    from requests import get, HTTPError, ConnectionError
except ModuleNotFoundError:
    print("Did you install the requests module? See https://pypi.org/project/requests/", file=stderr)
    raise

try:
    from dateutil.parser import parse
except ModuleNotFoundError:
    print("Did you install the python-dateutil module? See https://pypi.org/project/python-dateutil/", file=stderr)
    raise


class DeepLink(object):

    def __init__(self, name: str, url: str, snippet: str):
        self.name = name
        self.url = url
        self.snippet = snippet


class Result(object):

    def __init__(self, identifier: str, name: str, url: str, thumbnail: str, is_family_friendly: bool, display_url: str,
                 snippet: str, last_crawled: datetime, language: str, is_navigational: bool,
                 deep_links: Sequence[DeepLink] = None):
        self.identifier = identifier
        self.name = name
        self.url = url
        self.thumbnail = thumbnail
        self.is_family_friendly = is_family_friendly
        self.display_url = display_url
        self.snippet = snippet
        self.last_crawled = last_crawled
        self.language = language
        self.is_navigational = is_navigational
        self.deep_links = deep_links


class Bing(object):

    def __init__(self, key: str, default_size: int = 10, endpoint="https://api.bing.microsoft.com/v7.0/search",
                 market='en-US'):
        self.key = key
        self.default_size = default_size
        self.endpoint = endpoint
        self.market = market

    def search(self, query: str, size: int = 10, offset: int = 0):
        while size is None or size > 0:
            params = {
                'q': query,
                'mkt': self.market,
                'count': 50 if size is None or size > 50 else size,
                'offset': offset,
                'responseFilter': 'Webpages'
            }
            headers = {'Ocp-Apim-Subscription-Key': self.key}
            response = get(self.endpoint, headers=headers, params=params)
            response.raise_for_status()
            results = response.json()

            entries = results.get('webPages', {}).get('value', [])
            estimated = results.get('webPages', {}).get('totalEstimatedMatches', 0)

            for entry in entries:
                yield Result(
                    identifier=entry.get('id'),
                    name=entry.get('name'),
                    url=entry.get('url'),
                    thumbnail=entry.get('thumbnailUrl'),
                    is_family_friendly=entry.get('is_family_friendly'),
                    display_url=entry.get('displayUrl'),
                    snippet=entry.get('snippet'),
                    last_crawled=parse(entry.get('dateLastCrawled')),
                    language=entry.get('language'),
                    is_navigational=entry.get('isNavigational'),
                    deep_links=[DeepLink(
                        name=deeplink.get('name'),
                        url=deeplink.get('url'),
                        snippet=deeplink.get('snippet')) for deeplink in entry.get('deepLinks', [])]
                )
                if size is not None:
                    size -= 1
                offset += 1

            if offset >= estimated or len(entries) == 0:
                break


def download(url: str, prefix: str = '', suffix: str = ''):
    # Download the file
    try:
        response = get(url, stream=True)
        response.raise_for_status()
    except (HTTPError, ConnectionError):
        return

    # Compute the file's date
    date = parse(response.headers.get('Last-Modified')) if 'Last-Modified' in response.headers else \
        datetime.fromtimestamp(randint(int(parse('2019-01-01').timestamp()), int(time())))

    name = unquote(Path(urlparse(url).path).name)
    prefix += f' {name[:-len(suffix)] if name.endswith(suffix) else name} '

    with NamedTemporaryFile(mode='wb', delete=False, dir='.\\',
                            prefix=prefix,
                            suffix=suffix) as file:
        name = file.name
        file.write(response.content)

    modified = mktime(date.timetuple())
    utime(name, (modified, modified))


# Press the green button in the gutter to run the script.
if __name__ == '__main__':
    parser = ArgumentParser(
        description='Binget is a simple wget for Bing intended to easily download search query matches '
                    '(e.g. to populate honeypot networks).',
        epilog='''\
For more information on:
    - the Bing Web Search API, see https://learn.microsoft.com/en-us/bing/search-apis/bing-web-search/overview
    - the advanced Bing query operators, see https://help.bing.microsoft.com/#apex/18/en-US/10001
            ''',
        formatter_class=RawDescriptionHelpFormatter
    )
    parser.add_argument('query', metavar='QUERY', type=str, help='the Bing query to download')
    parser.add_argument('--key', metavar='KEY', type=str, default=environ.get('BING_SEARCH_V7_SUBSCRIPTION_KEY'),
                        required='BING_SEARCH_V7_SUBSCRIPTION_KEY' not in environ,
                        help='a Bing Web Search API authorization key')
    parser.add_argument('--size', metavar='SIZE', type=int, default=10,
                        help='the number of results to download (0 for unlimited)')
    parser.add_argument('--type', metavar='FILE_TYPE', type=str,
                        help='the expected file type (e.g. "pdf"; typically used alongside the filetype query operator)')
    args = parser.parse_args()
    b = Bing(args.key)
    for entry in b.search(args.query, size=args.size if args.size > 0 else None):
        download(entry.url, suffix=f'.{args.type}' if args.type else None)
        print('.', end='', flush=True)
